'''
brozzler/models.py - model classes representing jobs, sites, and pages, with
related logic

Copyright (C) 2014-2017 Internet Archive

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

import brozzler
import cerberus
import datetime
import doublethink
import hashlib
import json
import logging
import os
import re
import time
import urlcanon
import urllib
import uuid
import yaml

def load_schema():
    schema_file = os.path.join(os.path.dirname(__file__), 'job_schema.yaml')
    with open(schema_file) as f:
        return yaml.load(f)

class JobValidator(cerberus.Validator):
    def _validate_type_url(self, value):
        url = urllib.parse.urlparse(value)
        return url.scheme in ('http', 'https', 'ftp')

class InvalidJobConf(Exception):
    def __init__(self, errors):
        self.errors = errors

def validate_conf(job_conf, schema=load_schema()):
    v = JobValidator(schema)
    if not v.validate(job_conf):
        raise InvalidJobConf(v.errors)

def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        merged = dict(a)
        b_tmp = dict(b)
        for k in a:
            merged[k] = merge(a[k], b_tmp.pop(k, None))
        merged.update(b_tmp)
        return merged
    elif isinstance(a, list) and isinstance(b, list):
        return a + b
    else:
        return a

def new_job_file(frontier, job_conf_file):
    '''Returns new Job.'''
    logging.info("loading %s", job_conf_file)
    with open(job_conf_file) as f:
        job_conf = yaml.load(f)
        return new_job(frontier, job_conf)

def new_job(frontier, job_conf):
    '''Returns new Job.'''
    validate_conf(job_conf)
    job = Job(frontier.rr, {
                "conf": job_conf, "status": "ACTIVE",
                "started": doublethink.utcnow()})
    if "id" in job_conf:
        job.id = job_conf["id"]
    job.save()

    sites = []
    for seed_conf in job_conf["seeds"]:
        merged_conf = merge(seed_conf, job_conf)
        merged_conf.pop("seeds")
        merged_conf["job_id"] = job.id
        merged_conf["seed"] = merged_conf.pop("url")
        site = brozzler.Site(frontier.rr, merged_conf)
        sites.append(site)

    for site in sites:
        new_site(frontier, site)

    return job

def new_site(frontier, site):
    site.id = str(uuid.uuid4())
    logging.info("new site {}".format(site))
    # insert the Page into the database before the Site, to avoid situation
    # where a brozzler worker immediately claims the site, finds no pages
    # to crawl, and decides the site is finished
    try:
        url = urlcanon.parse_url(site.seed)
        hashtag = (url.hash_sign + url.fragment).decode("utf-8")
        urlcanon.canon.remove_fragment(url)
        page = brozzler.Page(frontier.rr, {
            "url": str(url), "site_id": site.get("id"),
            "job_id": site.get("job_id"), "hops_from_seed": 0,
            "priority": 1000, "needs_robots_check": True})
        if hashtag:
            page.hashtags = [hashtag,]
        page.save()
        logging.info("queued page %s", page)
    finally:
        # finally block because we want to insert the Site no matter what
        site.save()

class ElapsedMixIn(object):
    def elapsed(self):
        '''Returns elapsed crawl time as a float in seconds.'''
        dt = 0
        for ss in self.starts_and_stops[:-1]:
            dt += (ss['stop'] - ss['start']).total_seconds()
        ss = self.starts_and_stops[-1]
        if ss['stop']:
            dt += (ss['stop'] - ss['start']).total_seconds()
        else: # crawl is active
            dt += (doublethink.utcnow() - ss['start']).total_seconds()
        return dt

class Job(doublethink.Document, ElapsedMixIn):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = "jobs"

    def populate_defaults(self):
        if not "status" in self:
            self.status = "ACTIVE"
        if not "starts_and_stops" in self:
            if self.get("started"):   # backward compatibility
                self.starts_and_stops = [{
                    "start": self.get("started"),
                    "stop": self.get("finished")}]
                del self["started"]
                if "finished" in self:
                    del self["finished"]
            else:
                self.starts_and_stops = [
                        {"start":doublethink.utcnow(),"stop":None}]

    def finish(self):
        if self.status == "FINISHED" or self.starts_and_stops[-1]["stop"]:
            self.logger.error(
                    "job is already finished status=%s "
                    "starts_and_stops[-1]['stop']=%s", self.status,
                    self.starts_and_stops[-1]["stop"])
        self.status = "FINISHED"
        self.starts_and_stops[-1]["stop"] = doublethink.utcnow()

class Site(doublethink.Document, ElapsedMixIn):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = 'sites'

    def populate_defaults(self):
        if not "status" in self:
            self.status = "ACTIVE"
        if not "claimed" in self:
            self.claimed = False
        if not "last_disclaimed" in self:
            self.last_disclaimed = brozzler.EPOCH_UTC
        if not "last_claimed" in self:
            self.last_claimed = brozzler.EPOCH_UTC
        if not "scope" in self:
            self.scope = {}
        if not "surt" in self.scope and self.seed:
            self.scope["surt"] = brozzler.site_surt_canon(
                    self.seed).surt().decode('ascii')

        if not "starts_and_stops" in self:
            if self.get("start_time"):   # backward compatibility
                self.starts_and_stops = [{
                    "start":self.get("start_time"),"stop":None}]
                if self.get("status") != "ACTIVE":
                    self.starts_and_stops[0]["stop"] = self.last_disclaimed
                del self["start_time"]
            else:
                self.starts_and_stops = [
                        {"start":doublethink.utcnow(),"stop":None}]

    def __str__(self):
        return 'Site({"id":"%s","seed":"%s",...})' % (self.id, self.seed)

    def note_seed_redirect(self, url):
        new_scope_surt = brozzler.site_surt_canon(url).surt().decode("ascii")
        if not new_scope_surt.startswith(self.scope["surt"]):
            self.logger.info("changing site scope surt from {} to {}".format(
                self.scope["surt"], new_scope_surt))
            self.scope["surt"] = new_scope_surt

    def extra_headers(self):
        hdrs = {}
        if self.warcprox_meta:
            hdrs["Warcprox-Meta"] = json.dumps(
                    self.warcprox_meta, separators=(',', ':'))
        return hdrs

    def is_in_scope(self, url, parent_page=None):
        if not isinstance(url, urlcanon.ParsedUrl):
            url = urlcanon.semantic(url)
        try_parent_urls = []
        if parent_page:
            try_parent_urls.append(urlcanon.semantic(parent_page.url))
            if parent_page.redirect_url:
                try_parent_urls.append(
                        urlcanon.semantic(parent_page.redirect_url))

        might_accept = False
        if not url.scheme in (b'http', b'https'):
            # XXX doesn't belong here maybe (where? worker ignores unknown
            # schemes?)
            return False
        elif (parent_page and "max_hops" in self.scope
                and parent_page.hops_from_seed >= self.scope["max_hops"]):
            pass
        elif url.surt().startswith(self.scope["surt"].encode("utf-8")):
            might_accept = True
        elif parent_page and parent_page.hops_off_surt < self.scope.get(
                "max_hops_off_surt", 0):
            might_accept = True
        elif "accepts" in self.scope:
            for accept_rule in self.scope["accepts"]:
                rule = urlcanon.MatchRule(**accept_rule)
                if try_parent_urls:
                    for parent_url in try_parent_urls:
                        if rule.applies(url, parent_url):
                           might_accept = True
                else:
                    if rule.applies(url):
                        might_accept = True

        if might_accept:
            if "blocks" in self.scope:
                for block_rule in self.scope["blocks"]:
                    rule = urlcanon.MatchRule(**block_rule)
                    if try_parent_urls:
                        for parent_url in try_parent_urls:
                            if rule.applies(url, parent_url):
                               return False
                    else:
                        if rule.applies(url):
                            return False
            return True
        else:
            return False

class Page(doublethink.Document):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = "pages"

    @staticmethod
    def compute_id(site_id, url):
        digest_this = "site_id:%s,url:%s" % (site_id, url)
        return hashlib.sha1(digest_this.encode("utf-8")).hexdigest()

    def populate_defaults(self):
        if not "hops_from_seed" in self:
            self.hops_from_seed = 0
        if not "brozzle_count" in self:
            self.brozzle_count = 0
        if not "claimed" in self:
            self.claimed = False
        if not "hops_off_surt" in self:
            self.hops_off_surt = 0
        if not "needs_robots_check" in self:
            self.needs_robots_check = False
        if not "priority" in self:
            self.priority = self._calc_priority()
        if not "id" in self:
            self.id = self.compute_id(self.site_id, self.url)

    def __str__(self):
        return 'Page({"id":"%s","url":"%s",...})' % (self.id, self.url)

    def note_redirect(self, url):
        self.redirect_url = url

    def _calc_priority(self):
        if not self.url:
            return None
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canon_url().count("/"))
        return priority

    def canon_url(self):
        if not self.url:
            return None
        if self._canon_hurl is None:
            self._canon_hurl = urlcanon.semantic(self.url)
        return str(self._canon_hurl)

