#
# brozzler/job.py - Job class representing a brozzler crawl job, and functions
# for setting up a job with supplied configuration
#
# Copyright (C) 2014-2016 Internet Archive
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
import brozzler
import yaml
import json
import datetime
import uuid
import rethinkstuff

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
    logging.info("loading %s", job_conf_file)
    with open(job_conf_file) as f:
        job_conf = yaml.load(f)
        new_job(frontier, job_conf)

def new_job(frontier, job_conf):
    job = Job(
            id=job_conf.get("id"), conf=job_conf, status="ACTIVE",
            started=rethinkstuff.utcnow())

    sites = []
    for seed_conf in job_conf["seeds"]:
        merged_conf = merge(seed_conf, job_conf)
        # XXX check for unknown settings, invalid url, etc

        site = brozzler.Site(job_id=job.id,
                seed=merged_conf["url"],
                scope=merged_conf.get("scope"),
                time_limit=merged_conf.get("time_limit"),
                proxy=merged_conf.get("proxy"),
                ignore_robots=merged_conf.get("ignore_robots"),
                enable_warcprox_features=merged_conf.get(
                    "enable_warcprox_features"),
                warcprox_meta=merged_conf.get("warcprox_meta"),
                metadata=merged_conf.get("metadata"))
        sites.append(site)

    # insert all the sites into database before the job
    for site in sites:
        new_site(frontier, site)

    frontier.new_job(job)

def new_site(frontier, site):
    site.id = str(uuid.uuid4())
    logging.info("new site {}".format(site))
    try:
        # insert the Page into the database before the Site, to avoid situation
        # where a brozzler worker immediately claims the site, finds no pages
        # to crawl, and decides the site is finished
        try:
            if brozzler.is_permitted_by_robots(site, site.seed):
                page = brozzler.Page(site.seed, site_id=site.id,
                    job_id=site.job_id, hops_from_seed=0, priority=1000)
                frontier.new_page(page)
                logging.info("queued page %s", page)
            else:
                logging.warn("seed url {} is blocked by robots.txt".format(site.seed))
        finally:
            # finally block because we want to insert the Site no matter what
            frontier.new_site(site)
    except brozzler.ReachedLimit as e:
        frontier.reached_limit(site, e)

class Job(brozzler.BaseDictable):
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, id=None, conf=None, status="ACTIVE", started=None,
                 finished=None, stop_requested=None):
        self.id = id
        self.conf = conf
        self.status = status
        self.started = started
        self.finished = finished
        self.stop_requested = stop_requested

    def __str__(self):
        return 'Job(id=%s)' % self.id

