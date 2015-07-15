# vim: set sw=4 et:

import surt
import json
import logging
import urllib.robotparser
import brozzler
import sqlite3
import time
import kombu
import kombu.simple

## XXX move into Site class
# robots_url : RobotsFileParser
_robots_cache = {}
def robots(robots_url):
    if not robots_url in _robots_cache:
        robots_txt = urllib.robotparser.RobotFileParser(robots_url)
        logging.info("fetching {}".format(robots_url))
        try:
            robots_txt.read() # XXX should fetch through proxy
            _robots_cache[robots_url] = robots_txt
        except BaseException as e:
            logger.error("problem fetching {}".format(robots_url))

    return _robots_cache[robots_url]

def robots_url(url):
    hurl = surt.handyurl.parse(url)
    hurl.path = "/robots.txt"
    hurl.query = None
    hurl.hash = None
    return hurl.geturl()

class Site:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None):
        self.seed = seed
        self.id = id
        self.scope_surt = surt.surt(seed, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)

    def is_permitted_by_robots(self, url):
        return robots(robots_url(url)).can_fetch("*", url)

    def is_in_scope(self, url):
        try:
            surtt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
            return surtt.startswith(self.scope_surt)
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url))
            return False

    def to_dict(self):
        return dict(id=self.id, seed=self.seed)

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

class BrozzlerHQDb:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, db_file="./brozzler-hq-0.db"):
        self._conn = sqlite3.connect(db_file)
        self._create_tables()

    def _create_tables(self):
        cursor = self._conn.cursor()
        cursor.executescript("""
            create table if not exists brozzler_sites (
                id integer primary key,
                site_json text
            );

            create table if not exists brozzler_urls (
                id integer primary key,
                site_id integer,
                priority integer,
                in_progress boolean,
                canon_url varchar(4000),
                crawl_url_json text
            );
            create index if not exists brozzler_urls_priority on brozzler_urls (priority desc);
            create index if not exists brozzler_urls_site_id on brozzler_urls (site_id);
        """)
        self._conn.commit()

    def pop_url(self, site_id):
        cursor = self._conn.cursor()
        cursor.execute("select id, priority, crawl_url_json from brozzler_urls where site_id = ? and not in_progress order by priority desc limit 1", (site_id,))
        row = cursor.fetchone()
        if row:
            (id, priority, crawl_url_json) = row
            new_priority = priority - 2000
            cursor.execute("update brozzler_urls set priority=?, in_progress=1 where id=?", (new_priority, id))
            self._conn.commit()

            d = json.loads(crawl_url_json)
            d["id"] = id
            return d
        else:
            return None

    def completed(self, crawl_url):
        cursor = self._conn.cursor()
        cursor.execute("update brozzler_urls set in_progress=0 where id=?", (crawl_url.id,))
        self._conn.commit()

    def new_site(self, site):
        cursor = self._conn.cursor()
        cursor.execute("insert into brozzler_sites (site_json) values (?)", (site.to_json(),))
        self._conn.commit()
        return cursor.lastrowid

    def schedule_url(self, crawl_url, priority=0):
        cursor = self._conn.cursor()
        cursor.execute("insert into brozzler_urls (site_id, priority, canon_url, crawl_url_json, in_progress) values (?, ?, ?, ?, 0)",
                (crawl_url.site_id, priority, crawl_url.canonical(), crawl_url.to_json()))
        self._conn.commit()

    def sites(self):
        cursor = self._conn.cursor()
        cursor.execute("select id, site_json from brozzler_sites")
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            site_dict = json.loads(row[1])
            site_dict["id"] = row[0]
            yield brozzler.hq.Site(**site_dict)

    def update_crawl_url(self, crawl_url):
        cursor = self._conn.cursor()
        # CREATE TABLE brozzler_urls ( id integer primary key, site_id integer, priority integer, in_progress boolean, canon_url varchar(4000), crawl_url_json text 
        cursor.execute("select id, priority, crawl_url_json from brozzler_urls where site_id=? and canon_url=?", (crawl_url.site_id, crawl_url.canonical()))
        row = cursor.fetchone()
        if row:
            # (id, priority, existing_crawl_url) = row
            new_priority = crawl_url.calc_priority() + row[1]
            existing_crawl_url = brozzler.CrawlUrl(**json.loads(row[2]))
            existing_crawl_url.hops_from_seed = min(crawl_url.hops_from_seed, existing_crawl_url.hops_from_seed)

            cursor.execute("update brozzler_urls set priority=?, crawl_url_json=? where id=?", (new_priority, existing_crawl_url.to_json(), row[0]))
            self._conn.commit()
        else:
            raise KeyError("crawl url not in brozzler_urls site_id={} url={}".format(crawl_url.site_id, crawl_url.canonical()))

class BrozzlerHQ:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, amqp_url="amqp://guest:guest@localhost:5672/%2f", db=None):
        self.amqp_url = amqp_url
        self._conn = kombu.Connection(amqp_url)
        self._new_sites_q = self._conn.SimpleQueue("brozzler.sites.new")
        self._unclaimed_sites_q = self._conn.SimpleQueue("brozzler.sites.unclaimed")
        if db != None:
            self._db = db
        else:
            self._db = BrozzlerHQDb()

    def run(self):
        try:
            while True:
                self._new_site()
                self._consume_completed_url()
                self._feed_crawl_urls()
                time.sleep(0.5)
        finally:
            self._conn.close()

    def _new_site(self):
        try:
            msg = self._new_sites_q.get(block=False)
            new_site = brozzler.hq.Site(**msg.payload)
            msg.ack()

            self.logger.info("new site {}".format(new_site))
            site_id = self._db.new_site(new_site)
            new_site.id = site_id

            if new_site.is_permitted_by_robots(new_site.seed):
                crawl_url = brozzler.CrawlUrl(new_site.seed, site_id=new_site.id, hops_from_seed=0)
                self._db.schedule_url(crawl_url, priority=1000)
                self._unclaimed_sites_q.put(new_site.to_dict())
            else:
                self.logger.warn("seed url {} is blocked by robots.txt".format(new_site.seed))
        except kombu.simple.Empty:
            pass

    def _feed_crawl_urls(self):
        for site in self._db.sites():
            q = self._conn.SimpleQueue("brozzler.sites.{}.crawl_urls".format(site.id))
            if len(q) == 0:
                url = self._db.pop_url(site.id)
                if url:
                    self.logger.info("feeding {} to {}".format(url, q.queue.name))
                    q.put(url)

    def _scope_and_schedule_outlinks(self, site, parent_url):
        counts = {"added":0,"updated":0,"rejected":0,"blocked":0}
        if parent_url.outlinks:
            for url in parent_url.outlinks:
                if site.is_in_scope(url):
                    if site.is_permitted_by_robots(url):
                        crawl_url = brozzler.CrawlUrl(url, site_id=site.id, hops_from_seed=parent_url.hops_from_seed+1)
                        try:
                            self._db.update_crawl_url(crawl_url)
                            counts["updated"] += 1
                        except KeyError:
                            self._db.schedule_url(crawl_url, priority=crawl_url.calc_priority())
                            counts["added"] += 1
                    else:
                        counts["blocked"] += 1
                else:
                    counts["rejected"] += 1

        self.logger.info("{} new links added, {} existing links updated, {} links rejected, {} links blocked by robots from {}".format(
            counts["added"], counts["updated"], counts["rejected"], counts["blocked"], parent_url))

    def _consume_completed_url(self):
        for site in self._db.sites():
            q = self._conn.SimpleQueue("brozzler.sites.{}.completed_urls".format(site.id))
            try:
                msg = q.get(block=False)
                completed_url = brozzler.CrawlUrl(**msg.payload)
                msg.ack()
                self._db.completed(completed_url)
                self._scope_and_schedule_outlinks(site, completed_url)
            except kombu.simple.Empty:
                pass

