#!/usr/bin/env python
'''
test_frontier.py - fairly narrow tests of frontier management, requires
rethinkdb running on localhost

Copyright (C) 2017 Internet Archive

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
import logging
import argparse
import rethinkstuff
import time

args = argparse.Namespace()
args.log_level = logging.INFO
brozzler.cli.configure_logging(args)

def test_rethinkdb_up():
    '''Checks that rethinkdb is listening and looks sane.'''
    r = rethinkstuff.Rethinker(db='rethinkdb')  # built-in db
    tbls = r.table_list().run()
    assert len(tbls) > 10

def test_resume_job():
    '''
    Tests that the right stuff gets twiddled in rethinkdb when we "start" and
    "finish" crawling a job. Doesn't actually crawl anything.
    '''
    # vagrant brozzler-worker isn't configured to look at the "ignoreme" db
    r = rethinkstuff.Rethinker(db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(r)
    job_conf = {'seeds': [{'url': 'http://example.com/'}]}
    job = brozzler.new_job(frontier, job_conf)
    assert len(list(frontier.job_sites(job.id))) == 1
    site = list(frontier.job_sites(job.id))[0]

    assert job.status == 'ACTIVE'
    assert len(job.starts_and_stops) == 1
    assert job.starts_and_stops[0]['start']
    assert job.starts_and_stops[0]['stop'] is None
    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]['start']
    assert site.starts_and_stops[0]['stop'] is None

    frontier.finished(site, 'FINISHED')
    job = frontier.job(job.id)

    assert job.status == 'FINISHED'
    assert len(job.starts_and_stops) == 1
    assert job.starts_and_stops[0]['start']
    assert job.starts_and_stops[0]['stop']
    assert job.starts_and_stops[0]['stop'] > job.starts_and_stops[0]['start']
    assert site.status == 'FINISHED'
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]['start']
    assert site.starts_and_stops[0]['stop']
    assert site.starts_and_stops[0]['stop'] > site.starts_and_stops[0]['start']

    frontier.resume_site(site)
    job = frontier.job(job.id)

    assert job.status == 'ACTIVE'
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]['start']
    assert job.starts_and_stops[1]['stop'] is None
    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop'] is None

    frontier.finished(site, 'FINISHED')
    job = frontier.job(job.id)

    assert job.status == 'FINISHED'
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]['start']
    assert job.starts_and_stops[1]['stop']
    assert job.starts_and_stops[1]['stop'] > job.starts_and_stops[0]['start']
    assert site.status == 'FINISHED'
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop']
    assert site.starts_and_stops[1]['stop'] > site.starts_and_stops[0]['start']

    # resuming a job == resuming all of its sites
    frontier.resume_job(job)
    site = list(frontier.job_sites(job.id))[0]

    assert job.status == 'ACTIVE'
    assert len(job.starts_and_stops) == 3
    assert job.starts_and_stops[2]['start']
    assert job.starts_and_stops[2]['stop'] is None
    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 3
    assert site.starts_and_stops[2]['start']
    assert site.starts_and_stops[2]['stop'] is None

    frontier.finished(site, 'FINISHED')
    job = frontier.job(job.id)

    assert job.status == 'FINISHED'
    assert len(job.starts_and_stops) == 3
    assert job.starts_and_stops[2]['start']
    assert job.starts_and_stops[2]['stop']
    assert job.starts_and_stops[2]['stop'] > job.starts_and_stops[0]['start']
    assert site.status == 'FINISHED'
    assert len(site.starts_and_stops) == 3
    assert site.starts_and_stops[2]['start']
    assert site.starts_and_stops[2]['stop']
    assert site.starts_and_stops[2]['stop'] > site.starts_and_stops[0]['start']

def test_time_limit():
    # vagrant brozzler-worker isn't configured to look at the "ignoreme" db
    r = rethinkstuff.Rethinker('localhost', db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(r)
    site = brozzler.Site(seed='http://example.com/', time_limit=99999)
    brozzler.new_site(frontier, site)

    site = frontier.site(site.id)  # get it back from the db
    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]['start']
    assert site.starts_and_stops[0]['stop'] is None

    frontier.finished(site, 'FINISHED')

    assert site.status == 'FINISHED'
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]['start']
    assert site.starts_and_stops[0]['stop']
    assert site.starts_and_stops[0]['stop'] > site.starts_and_stops[0]['start']

    frontier.resume_site(site)

    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop'] is None

    # time limit not reached yet
    frontier._enforce_time_limit(site)

    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop'] is None

    site.time_limit = 0.1
    site.claimed = True
    frontier.update_site(site)

    time.sleep(0.1)
    frontier._enforce_time_limit(site)

    assert site.status == 'FINISHED_TIME_LIMIT'
    assert not site.claimed
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop']
    assert site.starts_and_stops[1]['stop'] > site.starts_and_stops[0]['start']
