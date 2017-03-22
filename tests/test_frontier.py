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
import datetime

args = argparse.Namespace()
args.log_level = logging.INFO
brozzler.cli.configure_logging(args)

def test_rethinkdb_up():
    '''Checks that rethinkdb is listening and looks sane.'''
    rr = doublethink.Rethinker(db='rethinkdb')  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10

def test_basics():
    rr = doublethink.Rethinker(db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)
    job_conf = {'seeds': [
        {'url': 'http://example.com'}, {'url': 'https://example.org/'}]}
    job = brozzler.new_job(frontier, job_conf)
    assert job.id
    assert job.starts_and_stops
    assert job.starts_and_stops[0]['start']
    assert job == {
        'id': job.id,
        'conf': {
            'seeds': [
                {'url': 'http://example.com'},
                {'url': 'https://example.org/'}
            ]
        },
        'status': 'ACTIVE',
        'starts_and_stops': [
            {
                'start': job.starts_and_stops[0]['start'],
                'stop': None
            }
        ]
    }

    sites = sorted(list(frontier.job_sites(job.id)), key=lambda x: x.seed)
    assert len(sites) == 2
    assert sites[0].starts_and_stops[0]['start']
    assert sites[1].starts_and_stops[0]['start']
    assert sites[0] == {
        'claimed': False,
        'id': sites[0].id,
        'job_id': job.id,
        'last_claimed': brozzler.EPOCH_UTC,
        'last_disclaimed': brozzler.EPOCH_UTC,
        'scope': {
            'surt': 'http://(com,example,)/'
        },
        'seed': 'http://example.com',
        'starts_and_stops': [
            {
                'start': sites[0].starts_and_stops[0]['start'],
                'stop': None
           }
        ],
        'status': 'ACTIVE'
    }
    assert sites[1] == {
        'claimed': False,
        'id': sites[1].id,
        'job_id': job.id,
        'last_claimed': brozzler.EPOCH_UTC,
        'last_disclaimed': brozzler.EPOCH_UTC,
        'scope': {
            'surt': 'https://(org,example,)/',
        },
        'seed': 'https://example.org/',
        'starts_and_stops': [
            {
                'start': sites[1].starts_and_stops[0]['start'],
                'stop': None,
           },
        ],
        'status': 'ACTIVE',
    }

    pages = list(frontier.site_pages(sites[0].id))
    assert len(pages) == 1
    assert pages[0] == {
        'brozzle_count': 0,
        'claimed': False,
        'hops_from_seed': 0,
        'hops_off_surt': 0,
        'id': brozzler.Page.compute_id(sites[0].id, 'http://example.com'),
        'job_id': job.id,
        'needs_robots_check': True,
        'priority': 1000,
        'site_id': sites[0].id,
        'url': 'http://example.com',
    }
    pages = list(frontier.site_pages(sites[1].id))
    assert len(pages) == 1
    assert pages[0] == {
        'brozzle_count': 0,
        'claimed': False,
        'hops_from_seed': 0,
        'hops_off_surt': 0,
        'id': brozzler.Page.compute_id(sites[1].id, 'https://example.org/'),
        'job_id': job.id,
        'needs_robots_check': True,
        'priority': 1000,
        'site_id': sites[1].id,
        'url': 'https://example.org/',
    }

    # test "brozzled" parameter of frontier.site_pages
    assert len(list(frontier.site_pages(sites[1].id))) == 1
    assert len(list(frontier.site_pages(sites[1].id, brozzled=True))) == 0
    assert len(list(frontier.site_pages(sites[1].id, brozzled=False))) == 1
    pages[0].brozzle_count = 1
    pages[0].save()
    assert len(list(frontier.site_pages(sites[1].id))) == 1
    assert len(list(frontier.site_pages(sites[1].id, brozzled=True))) == 1
    assert len(list(frontier.site_pages(sites[1].id, brozzled=False))) == 0
    pages[0].brozzle_count = 32819
    pages[0].save()
    assert len(list(frontier.site_pages(sites[1].id))) == 1
    assert len(list(frontier.site_pages(sites[1].id, brozzled=True))) == 1
    assert len(list(frontier.site_pages(sites[1].id, brozzled=False))) == 0

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
    site = brozzler.Site(rr, {
        'seed': 'http://example.com/', 'enable_warcprox_features': True})
    assert site.enable_warcprox_features is True
    assert site.id is None
    assert site.scope
    assert site.scope['surt'] == 'http://(com,example,)/'
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

def test_scope_and_schedule_outlinks():
    rr = doublethink.Rethinker('localhost', db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(rr, {'seed':'http://example.com/'})
    parent_page = brozzler.Page(rr, {
        'hops_from_seed': 1, 'url': 'http://example.com/whatever'})
    outlinks = [
        'https://example.com/',
        'https://example.com/foo',
        'http://example.com/bar',
        'HTtp://exAMPle.COm/bar',
        'HTtp://exAMPle.COm/BAr',
        'HTtp://exAMPle.COm/BAZZZZ',]
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots

    assert sorted(parent_page.outlinks['rejected']) == [
            'https://example.com/', 'https://example.com/foo']
    assert sorted(parent_page.outlinks['accepted']) == [
                'http://example.com/BAZZZZ', 'http://example.com/BAr',
                'http://example.com/bar']
    assert parent_page.outlinks['blocked'] == []

    pp = brozzler.Page.load(rr, parent_page.id)
    assert pp == parent_page

    for url in parent_page.outlinks['rejected']:
        id = brozzler.Page.compute_id(site.id, url)
        assert brozzler.Page.load(rr, id) is None
    for url in parent_page.outlinks['accepted']:
        id = brozzler.Page.compute_id(site.id, url)
        assert brozzler.Page.load(rr, id)

def test_parent_url_scoping():
    rr = doublethink.Rethinker('localhost', db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)

    # scope rules that look at parent page url should consider both the
    # original url and the redirect url, if any, of the parent page
    site = brozzler.Site(rr, {
        'seed': 'http://example.com/foo/',
        'scope': {
            'accepts': [{
                'parent_url_regex': '^http://example.com/acceptme/.*$'}],
            'blocks': [{
                'parent_url_regex': '^http://example.com/blockme/.*$'}],
            },
        'remember_outlinks': True})
    site.save()

    # an outlink that would not otherwise be in scope
    outlinks = ['https://some-random-url.com/']

    # parent page does not match any parent_url_regex
    parent_page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/foo/spluh'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == outlinks
    assert parent_page.outlinks['accepted'] == []

    # parent page url matches accept parent_url_regex
    parent_page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/acceptme/futz'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == []
    assert parent_page.outlinks['accepted'] == outlinks

    # parent page redirect_url matches accept parent_url_regex
    parent_page_c = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/toot/blah',
        'redirect_url':'http://example.com/acceptme/futz'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == []
    assert parent_page.outlinks['accepted'] == outlinks

    # an outlink that would normally be in scope
    outlinks = ['http://example.com/foo/whatever/']

    # parent page does not match any parent_url_regex
    parent_page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/foo/spluh'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == []
    assert parent_page.outlinks['accepted'] == outlinks

    # parent page url matches block parent_url_regex
    parent_page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/blockme/futz'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == outlinks
    assert parent_page.outlinks['accepted'] == []

    # parent page redirect_url matches block parent_url_regex
    parent_page_c = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/toot/blah',
        'redirect_url':'http://example.com/blockme/futz'})
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks['rejected'] == outlinks
    assert parent_page.outlinks['accepted'] == []

def test_completed_page():
    rr = doublethink.Rethinker('localhost', db='ignoreme')
    frontier = brozzler.RethinkDbFrontier(rr)

    # redirect that changes scope surt
    site = brozzler.Site(rr, {'seed':'http://example.com/a/'})
    site.save()
    page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/a/',
        'claimed': True,
        'brozzle_count': 0,
        'hops_from_seed': 0,
        'redirect_url':'http://example.com/b/', })
    page.save()
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    frontier.completed_page(site, page)
    assert site.scope == {'surt': 'http://(com,example,)/b/'}
    site.refresh()
    assert site.scope == {'surt': 'http://(com,example,)/b/'}
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False

    # redirect that doesn't change scope surt because destination is covered by
    # the original surt
    site = brozzler.Site(rr, {'seed':'http://example.com/a/'})
    site.save()
    page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/a/',
        'claimed': True,
        'brozzle_count': 0,
        'hops_from_seed': 0,
        'redirect_url':'http://example.com/a/x/', })
    page.save()
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    frontier.completed_page(site, page)
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    site.refresh()
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False

    # redirect that doesn't change scope surt because page is not the seed page
    site = brozzler.Site(rr, {'seed':'http://example.com/a/'})
    site.save()
    page = brozzler.Page(rr, {
        'site_id': site.id,
        'url': 'http://example.com/c/',
        'claimed': True,
        'brozzle_count': 0,
        'hops_from_seed': 1,
        'redirect_url':'http://example.com/d/', })
    page.save()
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    frontier.completed_page(site, page)
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    site.refresh()
    assert site.scope == {'surt': 'http://(com,example,)/a/'}
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False

