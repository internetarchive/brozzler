'''
brozzler/frontier.py - RethinkDbFrontier manages crawl jobs, sites and pages

Copyright (C) 2014-2016 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import logging
import brozzler
import random
import time
import datetime
import rethinkdb
import rethinkstuff

class UnexpectedDbResult(Exception):
    pass

class RethinkDbFrontier:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, r, shards=None, replicas=None):
        self.r = r
        self.shards = shards or len(r.servers)
        self.replicas = replicas or min(len(r.servers), 3)
        self._ensure_db()

    def _ensure_db(self):
        dbs = self.r.db_list().run()
        if not self.r.dbname in dbs:
            self.logger.info(
                    "creating rethinkdb database %s", repr(self.r.dbname))
            self.r.db_create(self.r.dbname).run()
        tables = self.r.table_list().run()
        if not "sites" in tables:
            self.logger.info(
                    "creating rethinkdb table 'sites' in database %s",
                    repr(self.r.dbname))
            self.r.table_create(
                    "sites", shards=self.shards, replicas=self.replicas).run()
            self.r.table("sites").index_create(
                    "sites_last_disclaimed", [
                        self.r.row["status"],
                        self.r.row["last_disclaimed"]]).run()
            self.r.table("sites").index_create("job_id").run()
        if not "pages" in tables:
            self.logger.info(
                    "creating rethinkdb table 'pages' in database %s",
                    repr(self.r.dbname))
            self.r.table_create(
                    "pages", shards=self.shards, replicas=self.replicas).run()
            self.r.table("pages").index_create(
                    "priority_by_site", [
                        self.r.row["site_id"], self.r.row["brozzle_count"],
                        self.r.row["claimed"], self.r.row["priority"]]).run()
            # this index is for displaying pages in a sensible order in the web
            # console
            self.r.table("pages").index_create(
                    "least_hops", [
                        self.r.row["site_id"], self.r.row["brozzle_count"],
                        self.r.row["hops_from_seed"]]).run()
        if not "jobs" in tables:
            self.logger.info(
                    "creating rethinkdb table 'jobs' in database %s",
                    repr(self.r.dbname))
            self.r.table_create(
                    "jobs", shards=self.shards, replicas=self.replicas).run()

    def _vet_result(self, result, **kwargs):
        # self.logger.debug("vetting expected=%s result=%s", kwargs, result)
        # {'replaced': 0, 'errors': 0, 'skipped': 0, 'inserted': 1, 'deleted': 0, 'generated_keys': ['292859c1-4926-4b27-9d87-b2c367667058'], 'unchanged': 0}
        for k in ["replaced", "errors", "skipped", "inserted", "deleted", "unchanged"]:
            if k in kwargs:
                expected = kwargs[k]
            else:
                expected = 0
            if isinstance(expected, list):
                if result.get(k) not in kwargs[k]:
                    raise UnexpectedDbResult("expected {} to be one of {} in {}".format(repr(k), expected, result))
            else:
                if result.get(k) != expected:
                    raise UnexpectedDbResult("expected {} to be {} in {}".format(repr(k), expected, result))

    def new_job(self, job):
        self.logger.info("inserting into 'jobs' table %s", repr(job))
        result = self.r.table("jobs").insert(job.to_dict()).run()
        self._vet_result(result, inserted=1)
        if not job.id:
            # only if "id" has not already been set
            job.id = result["generated_keys"][0]

    def new_site(self, site):
        self.logger.info("inserting into 'sites' table %s", site)
        result = self.r.table("sites").insert(site.to_dict()).run()
        self._vet_result(result, inserted=1)
        if not site.id:
            # only if "id" has not already been set
            site.id = result["generated_keys"][0]

    def update_job(self, job):
        self.logger.debug("updating 'jobs' table entry %s", job)
        result = self.r.table("jobs").get(job.id).replace(job.to_dict()).run()
        self._vet_result(result, replaced=[0,1], unchanged=[0,1])

    def update_site(self, site):
        self.logger.debug("updating 'sites' table entry %s", site)
        result = self.r.table("sites").get(site.id).replace(site.to_dict()).run()
        self._vet_result(result, replaced=[0,1], unchanged=[0,1])

    def update_page(self, page):
        self.logger.debug("updating 'pages' table entry %s", page)
        result = self.r.table("pages").get(page.id).replace(page.to_dict()).run()
        self._vet_result(result, replaced=[0,1], unchanged=[0,1])

    def new_page(self, page):
        self.logger.debug("inserting into 'pages' table %s", page)
        result = self.r.table("pages").insert(page.to_dict()).run()
        self._vet_result(result, inserted=1)

    def claim_site(self, worker_id):
        # XXX keep track of aggregate priority and prioritize sites accordingly?
        while True:
            result = (
                    self.r.table("sites", read_mode="majority")
                    .between(
                        ["ACTIVE",rethinkdb.minval],
                        ["ACTIVE",rethinkdb.maxval],
                        index="sites_last_disclaimed")
                    .order_by(index="sites_last_disclaimed")
                    .filter(
                        (rethinkdb.row["claimed"] != True) |
                        (rethinkdb.row["last_claimed"]
                            < rethinkdb.now() - 2*60*60))
                    .limit(1)
                    .update(
                        # try to avoid a race condition resulting in multiple
                        # brozzler-workers claiming the same site
                        # see https://github.com/rethinkdb/rethinkdb/issues/3235#issuecomment-60283038
                        rethinkdb.branch(
                            (rethinkdb.row["claimed"] != True) |
                            (rethinkdb.row["last_claimed"]
                                < rethinkdb.now() - 2*60*60), {
                                    "claimed": True,
                                    "last_claimed_by": worker_id,
                                    "last_claimed": rethinkstuff.utcnow()
                                }, {}), return_changes=True)).run()
            self._vet_result(result, replaced=[0,1], unchanged=[0,1])
            if result["replaced"] == 1:
                if result["changes"][0]["old_val"]["claimed"]:
                    self.logger.warn(
                            "re-claimed site that was still marked 'claimed' "
                            "because it was last claimed a long time ago "
                            "at %s, and presumably some error stopped it from "
                            "being disclaimed",
                            result["changes"][0]["old_val"]["last_claimed"])
                site = brozzler.Site(**result["changes"][0]["new_val"])
            else:
                raise brozzler.NothingToClaim
            # XXX This is the only place we enforce time limit for now. Worker
            # loop should probably check time limit. Maybe frontier needs a
            # housekeeping thread to ensure that time limits get enforced in a
            # timely fashion.
            if not self._enforce_time_limit(site):
                return site

    def _enforce_time_limit(self, site):
        if (site.time_limit and site.time_limit > 0
                and (rethinkstuff.utcnow() - site.start_time).total_seconds() > site.time_limit):
            self.logger.debug("site FINISHED_TIME_LIMIT! time_limit=%s start_time=%s elapsed=%s %s",
                    site.time_limit, site.start_time, rethinkstuff.utcnow() - site.start_time, site)
            self.finished(site, "FINISHED_TIME_LIMIT")
            return True
        else:
            return False

    def claim_page(self, site, worker_id):
        # ignores the "claimed" field of the page, because only one
        # brozzler-worker can be working on a site at a time, and that would
        # have to be the worker calling this method, so if something is claimed
        # already, it must have been left that way because of some error
        result = self.r.table("pages").between(
                [site.id, 0, self.r.minval, self.r.minval],
                [site.id, 0, self.r.maxval, self.r.maxval],
                index="priority_by_site").order_by(
                        index=rethinkdb.desc("priority_by_site")).limit(
                                1).update({
                                    "claimed":True,
                                    "last_claimed_by":worker_id},
                                    return_changes="always").run()
        self._vet_result(result, unchanged=[0,1], replaced=[0,1])
        if result["unchanged"] == 0 and result["replaced"] == 0:
            raise brozzler.NothingToClaim
        else:
            return brozzler.Page(**result["changes"][0]["new_val"])

    def has_outstanding_pages(self, site):
        results_iter = self.r.table("pages").between(
                [site.id, 0, self.r.minval, self.r.minval],
                [site.id, 0, self.r.maxval, self.r.maxval],
                index="priority_by_site").limit(1).run()
        return len(list(results_iter)) > 0

    def page(self, id):
        result = self.r.table("pages").get(id).run()
        if result:
            return brozzler.Page(**result)
        else:
            return None

    def completed_page(self, site, page):
        page.brozzle_count += 1
        page.claimed = False
        # XXX set priority?
        self.update_page(page)
        if page.redirect_url and page.hops_from_seed == 0:
            site.note_seed_redirect(page.redirect_url)
            self.update_site(site)

    def active_jobs(self):
        results = self.r.table("jobs").filter({"status":"ACTIVE"}).run()
        for result in results:
            yield brozzler.Job(**result)

    def job(self, id):
        if id is None:
            return None
        result = self.r.table("jobs").get(id).run()
        if result:
            return brozzler.Job(**result)
        else:
            return None

    def honor_stop_request(self, job_id):
        """Raises brozzler.CrawlJobStopped if stop has been requested."""
        job = self.job(job_id)
        if job and job.stop_requested:
            self.logger.info("stop requested for job %s", job_id)
            raise brozzler.CrawlJobStopped

    def _maybe_finish_job(self, job_id):
        """Returns True if job is finished."""
        job = self.job(job_id)
        if not job:
            return False
        if job.status.startswith("FINISH"):
            self.logger.warn("%s is already %s", job, job.status)
            return True

        results = self.r.table("sites").get_all(job_id, index="job_id").run()
        n = 0
        for result in results:
            site = brozzler.Site(**result)
            if not site.status.startswith("FINISH"):
                results.close()
                return False
            n += 1

        self.logger.info("all %s sites finished, job %s is FINISHED!", n, job.id)
        job.status = "FINISHED"
        job.finished = rethinkstuff.utcnow()
        self.update_job(job)
        return True

    def finished(self, site, status):
        self.logger.info("%s %s", status, site)
        site.status = status
        self.update_site(site)
        if site.job_id:
            self._maybe_finish_job(site.job_id)

    def disclaim_site(self, site, page=None):
        self.logger.info("disclaiming %s", site)
        site.claimed = False
        site.last_disclaimed = rethinkstuff.utcnow()
        if not page and not self.has_outstanding_pages(site):
            self.finished(site, "FINISHED")
        else:
            self.update_site(site)
        if page:
            page.claimed = False
            self.update_page(page)

    def scope_and_schedule_outlinks(self, site, parent_page, outlinks):
        if site.remember_outlinks:
            parent_page.outlinks = {"accepted":[],"blocked":[],"rejected":[]}
        counts = {"added":0,"updated":0,"rejected":0,"blocked":0}
        for url in outlinks or []:
            u = brozzler.site.Url(url)
            if site.is_in_scope(u, parent_page=parent_page):
                if brozzler.is_permitted_by_robots(site, url):
                    if not u.surt.startswith(site.scope["surt"]):
                        hops_off_surt = parent_page.hops_off_surt + 1
                    else:
                        hops_off_surt = 0
                    new_child_page = brozzler.Page(
                            url, site_id=site.id, job_id=site.job_id,
                            hops_from_seed=parent_page.hops_from_seed+1,
                            via_page_id=parent_page.id,
                            hops_off_surt=hops_off_surt)
                    existing_child_page = self.page(new_child_page.id)
                    if existing_child_page:
                        existing_child_page.priority += new_child_page.priority
                        self.update_page(existing_child_page)
                        counts["updated"] += 1
                    else:
                        self.new_page(new_child_page)
                        counts["added"] += 1
                    if site.remember_outlinks:
                        parent_page.outlinks["accepted"].append(url)
                else:
                    counts["blocked"] += 1
                    if site.remember_outlinks:
                        parent_page.outlinks["blocked"].append(url)
            else:
                counts["rejected"] += 1
                if site.remember_outlinks:
                    parent_page.outlinks["rejected"].append(url)

        if site.remember_outlinks:
            self.update_page(parent_page)

        self.logger.info(
                "%s new links added, %s existing links updated, %s links "
                "rejected, %s links blocked by robots from %s",
                counts["added"], counts["updated"], counts["rejected"],
                counts["blocked"], parent_page)

    def reached_limit(self, site, e):
        self.logger.info("reached_limit site=%s e=%s", site, e)
        assert isinstance(e, brozzler.ReachedLimit)
        if site.reached_limit and site.reached_limit != e.warcprox_meta["reached-limit"]:
            self.logger.warn("reached limit %s but site had already reached limit %s",
                    e.warcprox_meta["reached-limit"], self.reached_limit)
        else:
            site.reached_limit = e.warcprox_meta["reached-limit"]
            self.finished(site, "FINISHED_REACHED_LIMIT")

    def job_sites(self, job_id):
        results = self.r.table('sites').get_all(job_id, index="job_id").run()
        for result in results:
            yield brozzler.Site(**result)

    def seed_page(self, site_id):
        results = self.r.table("pages").between(
                [site_id, self.r.minval, self.r.minval, self.r.minval],
                [site_id, self.r.maxval, self.r.maxval, self.r.maxval],
                index="priority_by_site").filter({"hops_from_seed":0}).run()
        pages = list(results)
        if len(pages) > 1:
            self.logger.warn(
                    "more than one seed page for site_id %s ?", site_id)
        if len(pages) < 1:
            return None
        return brozzler.Page(**pages[0])

    def site_pages(self, site_id, unbrozzled_only=False):
        results = self.r.table("pages").between(
                [site_id, 0 if unbrozzled_only else self.r.minval,
                    self.r.minval, self.r.minval],
                [site_id, 0 if unbrozzled_only else self.r.maxval,
                    self.r.maxval, self.r.maxval],
                index="priority_by_site").run()
        for result in results:
            yield brozzler.Page(**result)

