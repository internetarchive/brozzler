'''
brozzler/job.py - Job class representing a brozzler crawl job, and functions
for setting up a job with supplied configuration

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

import logging
import brozzler
import yaml
import json
import datetime
import uuid
import rethinkstuff
import os
import cerberus
import urllib

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
    job = Job(frontier.r, {
                "conf": job_conf,
                "status": "ACTIVE", "started": rethinkstuff.utcnow()})
    if "id" in job_conf:
        job.id = job_conf["id"]
    job.save()

    sites = []
    for seed_conf in job_conf["seeds"]:
        merged_conf = merge(seed_conf, job_conf)
        site = brozzler.Site(frontier.r, {
            "job_id": job.id,
            "seed": merged_conf["url"],
            "scope": merged_conf.get("scope"),
            "time_limit": merged_conf.get("time_limit"),
            "proxy": merged_conf.get("proxy"),
            "ignore_robots": merged_conf.get("ignore_robots"),
            "enable_warcprox_features": merged_conf.get(
                "enable_warcprox_features"),
            "warcprox_meta": merged_conf.get("warcprox_meta"),
            "metadata": merged_conf.get("metadata"),
            "remember_outlinks": merged_conf.get("remember_outlinks"),
            "user_agent": merged_conf.get("user_agent"),
            "behavior_parameters": merged_conf.get("behavior_parameters"),
            "username": merged_conf.get("username"),
            "password": merged_conf.get("password")})
        sites.append(site)

    for site in sites:
        new_site(frontier, site)

    return job

def new_site(frontier, site):
    site.id = str(uuid.uuid4())
    logging.info("new site {}".format(site))
    try:
        # insert the Page into the database before the Site, to avoid situation
        # where a brozzler worker immediately claims the site, finds no pages
        # to crawl, and decides the site is finished
        try:
            page = brozzler.Page(frontier.r, {
                "url": site.seed, "site_id": site.get("id"),
                "job_id": site.get("job_id"), "hops_from_seed": 0,
                "priority": 1000, "needs_robots_check": True})
            page.save()
            logging.info("queued page %s", page)
        finally:
            # finally block because we want to insert the Site no matter what
            site.save()
    except brozzler.ReachedLimit as e:
        frontier.reached_limit(site, e)

class Job(rethinkstuff.Document):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = "jobs"

    def __init__(self, rethinker, d={}):
        rethinkstuff.Document.__init__(self, rethinker, d)
        self.status = self.get("status", "ACTIVE")
        if not "starts_and_stops" in self:
            if self.get("started"):   # backward compatibility
                self.starts_and_stops = [{
                    "start": self.get("started"),
                    "stop": self.get("finished")}]
                del self["started"]
            else:
                self.starts_and_stops = [
                        {"start":rethinkstuff.utcnow(),"stop":None}]

    def finish(self):
        if self.status == "FINISHED" or self.starts_and_stops[-1]["stop"]:
            self.logger.error(
                    "job is already finished status=%s "
                    "starts_and_stops[-1]['stop']=%s", self.status,
                    self.starts_and_stops[-1]["stop"])
        self.status = "FINISHED"
        self.starts_and_stops[-1]["stop"] = rethinkstuff.utcnow()

