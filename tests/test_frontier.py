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
import doublethink
import time

args = argparse.Namespace()
args.log_level = logging.INFO
brozzler.cli.configure_logging(args)

def test_rethinkdb_up():
    '''Checks that rethinkdb is listening and looks sane.'''
    rr = doublethink.Rethinker(db='rethinkdb')  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10

def test_resume_job():
    '''
    Tests that the right stuff gets twiddled in rethinkdb when we "start" and
    "finish" crawling a job. Doesn't actually crawl anything.
    '''
    # vagrant brozzler-worker isn't configured to look at the "ignoreme" db
    rr = doublethink.Rethinker(db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)
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
    job.refresh()

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
    job.refresh()

    assert job.status == 'ACTIVE'
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]['start']
    assert job.starts_and_stops[1]['stop'] is None
    assert site.status == 'ACTIVE'
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop'] is None

    frontier.finished(site, 'FINISHED')
    job.refresh()

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
    job.refresh()

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
    rr = doublethink.Rethinker('localhost', db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(rr, {'seed':'http://example.com/', 'time_limit':99999})
    brozzler.new_site(frontier, site)

    site.refresh()  # get it back from the db
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
    site.save()

    time.sleep(0.1)
    frontier._enforce_time_limit(site)

    assert site.status == 'FINISHED_TIME_LIMIT'
    assert not site.claimed
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]['start']
    assert site.starts_and_stops[1]['stop']
    assert site.starts_and_stops[1]['stop'] > site.starts_and_stops[0]['start']

def test_field_defaults():
    rr = doublethink.Rethinker('localhost', db='ignoreme')

    # page
    brozzler.Page.table_ensure(rr)
    page = brozzler.Page(rr, {'hops_from_seed': 3})
    assert page.hops_from_seed == 3
    assert page.id
    assert page.brozzle_count == 0
    page.save()
    assert page.hops_from_seed == 3
    assert page.id
    assert page.brozzle_count == 0

    qage = brozzler.Page.load(rr, page.id)
    assert qage.hops_from_seed == 3
    assert qage.id == page.id
    assert qage.brozzle_count == 0
    qage.save()
    assert qage.hops_from_seed == 3
    assert qage.id == page.id
    assert qage.brozzle_count == 0
    qage.refresh()
    assert qage.hops_from_seed == 3
    assert qage.id == page.id
    assert qage.brozzle_count == 0

    # site
    brozzler.Site.table_ensure(rr)
    site = brozzler.Site(rr, {'enable_warcprox_features': True})
    assert site.enable_warcprox_features is True
    assert site.id is None
    assert site.scope
    site.save()
    assert site.id
    assert site.scope

    tite = brozzler.Site.load(rr, site.id)
    assert tite.enable_warcprox_features is True
    assert tite.id == site.id
    assert tite.scope == site.scope
    tite.save()
    assert tite.enable_warcprox_features is True
    assert tite.id == site.id
    assert tite.scope == site.scope
    tite.refresh()
    assert tite.enable_warcprox_features is True
    assert tite.id == site.id
    assert tite.scope == site.scope

    # job
    brozzler.Job.table_ensure(rr)
    job = brozzler.Job(rr, {'status': 'WHUUUT'})
    assert job.status == 'WHUUUT'
    assert job.id is None
    assert job.starts_and_stops
    job.save()
    assert job.status == 'WHUUUT'
    assert job.id
    assert job.starts_and_stops

    kob = brozzler.Job.load(rr, job.id)
    assert kob.status == 'WHUUUT'
    assert kob.id
    assert kob.starts_and_stops
    kob.save()
    assert kob.status == 'WHUUUT'
    assert kob.id
    assert kob.starts_and_stops
    kob.refresh()
    assert kob.status == 'WHUUUT'
    assert kob.id
    assert kob.starts_and_stops

