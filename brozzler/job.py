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
import doublethink
import os
import cerberus
import urllib
import urlcanon

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

class Job(doublethink.Document):
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

