# vim: set sw=4 et:

import json
import logging
import brozzler
import sqlite3
import time
import kombu
import kombu.simple

class BrozzlerHQDb:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, db_file="./brozzler-hq.db"):
        self._conn = sqlite3.connect(db_file)
        self._create_tables()

    def _create_tables(self):
        cursor = self._conn.cursor()
        cursor.executescript("""
            create table if not exists brozzler_sites (
                id integer primary key,
                status varchar(100) default 'ACTIVE',
                site_json text
            );

            create table if not exists brozzler_pages (
                id integer primary key,
                site_id integer,
                priority integer,
                brozzle_count integer default 0,
                in_progress boolean,
                canon_url varchar(4000),
                page_json text
            );
            create index if not exists brozzler_pages_priority on brozzler_pages (priority desc);
            create index if not exists brozzler_pages_site_id on brozzler_pages (site_id);
        """)
        self._conn.commit()

    def pop_page(self, site_id):
        cursor = self._conn.cursor()
        cursor.execute("select id, priority, page_json from brozzler_pages where site_id=? and not in_progress and brozzle_count=0 order by priority desc limit 1", (site_id,))
        row = cursor.fetchone()
        if row:
            (id, priority, page_json) = row
            new_priority = priority - 2000
            cursor.execute("update brozzler_pages set priority=?, in_progress=1 where id=?", (new_priority, id))
            self._conn.commit()

            d = json.loads(page_json)
            d["id"] = id
            return d
        else:
            return None

    def completed(self, page):
        cursor = self._conn.cursor()
        cursor.execute("update brozzler_pages set in_progress=0, brozzle_count=brozzle_count+1 where id=?", (page.id,))
        self._conn.commit()

    def new_site(self, site):
        cursor = self._conn.cursor()
        cursor.execute("insert into brozzler_sites (site_json) values (?)", (site.to_json(),))
        self._conn.commit()
        return cursor.lastrowid

    def update_site(self, site):
        cursor = self._conn.cursor()
        cursor.execute("update brozzler_sites set site_json=? where id=?", (site.to_json(), site.id))
        self._conn.commit()

    def schedule_page(self, page, priority=0):
        cursor = self._conn.cursor()
        cursor.execute("insert into brozzler_pages (site_id, priority, canon_url, page_json, in_progress) values (?, ?, ?, ?, 0)",
                (page.site_id, priority, page.canon_url(), page.to_json()))
        self._conn.commit()

    def sites(self):
        cursor = self._conn.cursor()
        cursor.execute("select id, site_json from brozzler_sites where status != 'FINISHED'")
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            site_dict = json.loads(row[1])
            site_dict["id"] = row[0]
            yield brozzler.Site(**site_dict)

    def update_page(self, page):
        cursor = self._conn.cursor()
        # CREATE TABLE brozzler_pages ( id integer primary key, site_id integer, priority integer, in_progress boolean, canon_url varchar(4000), page_json text
        cursor.execute("select id, priority, page_json from brozzler_pages where site_id=? and canon_url=?", (page.site_id, page.canon_url()))
        row = cursor.fetchone()
        if row:
            # (id, priority, existing_page) = row
            new_priority = page.calc_priority() + row[1]
            existing_page = brozzler.Page(**json.loads(row[2]))
            existing_page.hops_from_seed = min(page.hops_from_seed, existing_page.hops_from_seed)

            cursor.execute("update brozzler_pages set priority=?, page_json=? where id=?", (new_priority, existing_page.to_json(), row[0]))
            self._conn.commit()
        else:
            raise KeyError("page not in brozzler_pages site_id={} canon_url={}".format(page.site_id, page.canon_url()))

    def in_progress_pages(self, site):
        cursor = self._conn.cursor()
        cursor.execute("select id, page_json from brozzler_pages where site_id = ? and in_progress", (site.id,))

        pages = []
        for row in cursor.fetchall():
            (id, page_json) = row
            page = brozzler.Page(**json.loads(page_json))
            page.id = id
            pages.append(page)

        if len(pages) > 1:
            self.logger.error("more than one page in progress for site?! shouldn't happen, violates politeness policy... site={}: pages={}".format(site, pages))

        return pages

    def set_status(self, site, status):
        cursor = self._conn.cursor()
        cursor.execute("update brozzler_sites set status=? where id=?", (status, site.id,))
        self._conn.commit()

    def get_status(self, site):
        cursor = self._conn.cursor()
        cursor.execute("select status from brozzler_sites where id=?", (site.id,))
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            raise KeyError("site not in brozzler_sites id={}".format(site.id,))

class BrozzlerHQ:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, amqp_url="amqp://guest:guest@localhost:5672/%2f", db=None):
        self.amqp_url = amqp_url
        self._conn = kombu.Connection(amqp_url)
        self._new_sites_q = self._conn.SimpleQueue("brozzler.sites.new")
        self._unclaimed_sites_q = self._conn.SimpleQueue("brozzler.sites.unclaimed")
        self._disclaimed_sites_q = self._conn.SimpleQueue("brozzler.sites.disclaimed")
        if db != None:
            self._db = db
        else:
            self._db = BrozzlerHQDb()

    def run(self):
        try:
            while True:
                self._new_site()
                self._consume_completed_page()
                self._feed_pages()
                self._disclaimed_site()
                time.sleep(0.5)
        finally:
            self._conn.close()

    def _disclaimed_site(self):
        try:
            msg = self._disclaimed_sites_q.get(block=False)
            site = brozzler.Site(**msg.payload)
            msg.ack()
            self.logger.info("received disclaimed site {}".format(site))

            status = self._db.get_status(site)
            if status != "FINISHED":
                self.logger.info("feeding disclaimed site {} back to {}".format(site, self._unclaimed_sites_q.queue.name))
                self._unclaimed_sites_q.put(site.to_dict())
            else:
                self.logger.info("disclaimed site is FINISHED {}".format(site))
        except kombu.simple.Empty:
            pass

    def _new_site(self):
        try:
            msg = self._new_sites_q.get(block=False)
            new_site = brozzler.Site(**msg.payload)
            msg.ack()

            self.logger.info("new site {}".format(new_site))
            site_id = self._db.new_site(new_site)
            new_site.id = site_id

            if new_site.is_permitted_by_robots(new_site.seed):
                page = brozzler.Page(new_site.seed, site_id=new_site.id, hops_from_seed=0)
                self._db.schedule_page(page, priority=1000)
                self._unclaimed_sites_q.put(new_site.to_dict())
            else:
                self.logger.warn("seed url {} is blocked by robots.txt".format(new_site.seed))
        except kombu.simple.Empty:
            pass

    def _finished(self, site):
        self.logger.info("site FINISHED! {}".format(site))
        self._db.set_status(site, "FINISHED")

    def _feed_pages(self):
        for site in self._db.sites():
            q = self._conn.SimpleQueue("brozzler.sites.{}.pages".format(site.id))
            if len(q) == 0:
                page = self._db.pop_page(site.id)
                if page:
                    self.logger.info("feeding {} to {}".format(page, q.queue.name))
                    q.put(page)
                elif not self._db.in_progress_pages(site):
                    self._finished(site)

    def _scope_and_schedule_outlinks(self, site, parent_page):
        counts = {"added":0,"updated":0,"rejected":0,"blocked":0}
        if parent_page.outlinks:
            for url in parent_page.outlinks:
                if site.is_in_scope(url):
                    if site.is_permitted_by_robots(url):
                        child_page = brozzler.Page(url, site_id=site.id, hops_from_seed=parent_page.hops_from_seed+1)
                        try:
                            self._db.update_page(child_page)
                            counts["updated"] += 1
                        except KeyError:
                            self._db.schedule_page(child_page, priority=child_page.calc_priority())
                            counts["added"] += 1
                    else:
                        counts["blocked"] += 1
                else:
                    counts["rejected"] += 1

        self.logger.info("{} new links added, {} existing links updated, {} links rejected, {} links blocked by robots from {}".format(
            counts["added"], counts["updated"], counts["rejected"], counts["blocked"], parent_page))

    def _consume_completed_page(self):
        for site in self._db.sites():
            q = self._conn.SimpleQueue("brozzler.sites.{}.completed_pages".format(site.id))
            try:
                msg = q.get(block=False)
                completed_page = brozzler.Page(**msg.payload)
                msg.ack()
                self._db.completed(completed_page)
                if completed_page.redirect_url and completed_page.hops_from_seed == 0:
                    site.note_seed_redirect(completed_page.redirect_url)
                    self._db.update_site(site)
                self._scope_and_schedule_outlinks(site, completed_page)
            except kombu.simple.Empty:
                pass

