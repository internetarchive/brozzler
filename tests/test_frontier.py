#!/usr/bin/env python
"""
test_frontier.py - fairly narrow tests of frontier management, requires
rethinkdb running on localhost

Copyright (C) 2017-2018 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import datetime
import logging
import time

import doublethink
import pytest

import brozzler

args = argparse.Namespace()
args.log_level = logging.INFO
brozzler.cli.configure_logging(args)


def test_rethinkdb_up():
    """Checks that rethinkdb is listening and looks sane."""
    rr = doublethink.Rethinker(db="rethinkdb")  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10


def test_basics():
    rr = doublethink.Rethinker(db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)
    job_conf = {
        "seeds": [{"url": "http://example.com"}, {"url": "https://example.org/"}]
    }
    job = brozzler.new_job(frontier, job_conf)
    assert job.id
    assert job.starts_and_stops
    assert job.starts_and_stops[0]["start"]
    assert job == {
        "id": job.id,
        "conf": {
            "seeds": [{"url": "http://example.com"}, {"url": "https://example.org/"}]
        },
        "status": "ACTIVE",
        "starts_and_stops": [{"start": job.starts_and_stops[0]["start"], "stop": None}],
    }

    sites = sorted(list(frontier.job_sites(job.id)), key=lambda x: x.seed)
    assert len(sites) == 2
    assert sites[0].starts_and_stops[0]["start"]
    assert sites[1].starts_and_stops[0]["start"]
    assert sites[0] == {
        "claimed": False,
        "id": sites[0].id,
        "job_id": job.id,
        "last_claimed": brozzler.EPOCH_UTC,
        "last_disclaimed": brozzler.EPOCH_UTC,
        "scope": {"accepts": [{"ssurt": "com,example,//http:/"}]},
        "seed": "http://example.com",
        "starts_and_stops": [
            {"start": sites[0].starts_and_stops[0]["start"], "stop": None}
        ],
        "status": "ACTIVE",
    }
    assert sites[1] == {
        "claimed": False,
        "id": sites[1].id,
        "job_id": job.id,
        "last_claimed": brozzler.EPOCH_UTC,
        "last_disclaimed": brozzler.EPOCH_UTC,
        "scope": {"accepts": [{"ssurt": "org,example,//https:/"}]},
        "seed": "https://example.org/",
        "starts_and_stops": [
            {
                "start": sites[1].starts_and_stops[0]["start"],
                "stop": None,
            },
        ],
        "status": "ACTIVE",
    }

    pages = list(frontier.site_pages(sites[0].id))
    assert len(pages) == 1
    assert pages[0] == {
        "brozzle_count": 0,
        "claimed": False,
        "hops_from_seed": 0,
        "hops_off": 0,
        "id": brozzler.Page.compute_id(sites[0].id, "http://example.com"),
        "job_id": job.id,
        "needs_robots_check": True,
        "priority": 1000,
        "site_id": sites[0].id,
        "url": "http://example.com",
    }
    pages = list(frontier.site_pages(sites[1].id))
    assert len(pages) == 1
    assert pages[0] == {
        "brozzle_count": 0,
        "claimed": False,
        "hops_from_seed": 0,
        "hops_off": 0,
        "id": brozzler.Page.compute_id(sites[1].id, "https://example.org/"),
        "job_id": job.id,
        "needs_robots_check": True,
        "priority": 1000,
        "site_id": sites[1].id,
        "url": "https://example.org/",
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
    """
    Tests that the right stuff gets twiddled in rethinkdb when we "start" and
    "finish" crawling a job. Doesn't actually crawl anything.
    """
    # vagrant brozzler-worker isn't configured to look at the "ignoreme" db
    rr = doublethink.Rethinker(db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)
    job_conf = {"seeds": [{"url": "http://example.com/"}]}
    job = brozzler.new_job(frontier, job_conf)
    assert len(list(frontier.job_sites(job.id))) == 1
    site = list(frontier.job_sites(job.id))[0]

    assert job.status == "ACTIVE"
    assert len(job.starts_and_stops) == 1
    assert job.starts_and_stops[0]["start"]
    assert job.starts_and_stops[0]["stop"] is None
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"]
    assert site.starts_and_stops[0]["stop"] is None

    frontier.finished(site, "FINISHED")
    job.refresh()

    assert job.status == "FINISHED"
    assert len(job.starts_and_stops) == 1
    assert job.starts_and_stops[0]["start"]
    assert job.starts_and_stops[0]["stop"]
    assert job.starts_and_stops[0]["stop"] > job.starts_and_stops[0]["start"]
    assert site.status == "FINISHED"
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"]
    assert site.starts_and_stops[0]["stop"]
    assert site.starts_and_stops[0]["stop"] > site.starts_and_stops[0]["start"]

    frontier.resume_site(site)
    job.refresh()

    assert job.status == "ACTIVE"
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]["start"]
    assert job.starts_and_stops[1]["stop"] is None
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]["start"]
    assert site.starts_and_stops[1]["stop"] is None

    frontier.finished(site, "FINISHED")
    job.refresh()

    assert job.status == "FINISHED"
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]["start"]
    assert job.starts_and_stops[1]["stop"]
    assert job.starts_and_stops[1]["stop"] > job.starts_and_stops[1]["start"]
    assert site.status == "FINISHED"
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]["start"]
    assert site.starts_and_stops[1]["stop"]
    assert site.starts_and_stops[1]["stop"] > site.starts_and_stops[1]["start"]

    # resuming a job == resuming all of its sites
    frontier.resume_job(job)
    site = list(frontier.job_sites(job.id))[0]

    assert job.status == "ACTIVE"
    assert len(job.starts_and_stops) == 3
    assert job.starts_and_stops[2]["start"]
    assert job.starts_and_stops[2]["stop"] is None
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 3
    assert site.starts_and_stops[2]["start"]
    assert site.starts_and_stops[2]["stop"] is None

    frontier.finished(site, "FINISHED")
    job.refresh()

    assert job.status == "FINISHED"
    assert len(job.starts_and_stops) == 3
    assert job.starts_and_stops[2]["start"]
    assert job.starts_and_stops[2]["stop"]
    assert job.starts_and_stops[2]["stop"] > job.starts_and_stops[2]["start"]
    assert site.status == "FINISHED"
    assert len(site.starts_and_stops) == 3
    assert site.starts_and_stops[2]["start"]
    assert site.starts_and_stops[2]["stop"]
    assert site.starts_and_stops[2]["stop"] > site.starts_and_stops[2]["start"]

    frontier.resume_job(job)
    site = list(frontier.job_sites(job.id))[0]

    assert job.status == "ACTIVE"
    assert len(job.starts_and_stops) == 4
    assert job.starts_and_stops[3]["start"]
    assert job.starts_and_stops[3]["stop"] is None
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 4
    assert site.starts_and_stops[3]["start"]
    assert site.starts_and_stops[3]["stop"] is None

    # simulate a job stop request
    job_conf = {
        "seeds": [{"url": "http://example.com/"}, {"url": "http://example_2.com/"}]
    }
    job = brozzler.new_job(frontier, job_conf)
    assert len(list(frontier.job_sites(job.id))) == 2
    site1 = list(frontier.job_sites(job.id))[0]
    site2 = list(frontier.job_sites(job.id))[1]

    job.stop_requested = datetime.datetime.utcnow().replace(tzinfo=doublethink.UTC)
    job.save()

    # should raise a CrawlStopped
    with pytest.raises(brozzler.CrawlStopped):
        frontier.honor_stop_request(site1)

    frontier.finished(site1, "FINISHED_STOP_REQUESTED")
    frontier.finished(site2, "FINISHED_STOP_REQUESTED")
    job.refresh()

    assert job.status == "FINISHED"
    assert job.stop_requested
    assert len(job.starts_and_stops) == 1
    assert job.starts_and_stops[0]["start"]
    assert job.starts_and_stops[0]["stop"]
    assert job.starts_and_stops[0]["stop"] > job.starts_and_stops[0]["start"]
    assert site1.status == "FINISHED_STOP_REQUESTED"
    assert site2.status == "FINISHED_STOP_REQUESTED"
    assert len(site1.starts_and_stops) == 1
    assert len(site2.starts_and_stops) == 1
    assert site1.starts_and_stops[0]["start"]
    assert site1.starts_and_stops[0]["stop"]
    assert site1.starts_and_stops[0]["stop"] > site.starts_and_stops[0]["start"]
    assert site2.starts_and_stops[0]["start"]
    assert site2.starts_and_stops[0]["stop"]
    assert site2.starts_and_stops[0]["stop"] > site.starts_and_stops[0]["start"]

    # simulate job resume after a stop request
    frontier.resume_job(job)
    site1 = list(frontier.job_sites(job.id))[0]
    site2 = list(frontier.job_sites(job.id))[1]

    assert job.status == "ACTIVE"
    assert job.stop_requested is None
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]["start"]
    assert job.starts_and_stops[1]["stop"] is None
    assert site1.status == "ACTIVE"
    assert len(site1.starts_and_stops) == 2
    assert site1.starts_and_stops[1]["start"]
    assert site1.starts_and_stops[1]["stop"] is None
    assert site2.status == "ACTIVE"
    assert len(site2.starts_and_stops) == 2
    assert site2.starts_and_stops[1]["start"]
    assert site2.starts_and_stops[1]["stop"] is None

    # simulate a site stop request
    site1.stop_requested = datetime.datetime.utcnow().replace(tzinfo=doublethink.UTC)
    site1.save()

    # should not raise a CrawlStopped
    frontier.honor_stop_request(site2)

    frontier.finished(site1, "FINISHED_STOP_REQUESTED")
    job.refresh()

    assert job.status == "ACTIVE"
    assert job.stop_requested is None
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]["start"]
    assert job.starts_and_stops[1]["stop"] is None
    assert site1.status == "FINISHED_STOP_REQUESTED"
    assert len(site1.starts_and_stops) == 2
    assert site1.starts_and_stops[1]["start"]
    assert site1.starts_and_stops[1]["stop"]
    assert site1.starts_and_stops[1]["stop"] > site.starts_and_stops[1]["start"]
    assert site2.status == "ACTIVE"
    assert len(site2.starts_and_stops) == 2
    assert site2.starts_and_stops[1]["start"]
    assert site2.starts_and_stops[1]["stop"] is None

    # simulate site resume after a stop request
    frontier.resume_site(site1)
    site1 = list(frontier.job_sites(job.id))[0]
    site2 = list(frontier.job_sites(job.id))[1]

    assert job.status == "ACTIVE"
    assert job.stop_requested is None
    assert len(job.starts_and_stops) == 2
    assert job.starts_and_stops[1]["start"]
    assert job.starts_and_stops[1]["stop"] is None
    assert site1.status == "ACTIVE"
    assert site1.stop_requested is None
    assert len(site1.starts_and_stops) == 3
    assert site1.starts_and_stops[2]["start"]
    assert site1.starts_and_stops[2]["stop"] is None
    assert site2.status == "ACTIVE"
    assert len(site2.starts_and_stops) == 2
    assert site2.starts_and_stops[1]["start"]
    assert site2.starts_and_stops[1]["stop"] is None


def test_time_limit():
    # XXX test not thoroughly adapted to change in time accounting, since
    # starts_and_stops is no longer used to enforce time limits

    # vagrant brozzler-worker isn't configured to look at the "ignoreme" db
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(rr, {"seed": "http://example.com/", "time_limit": 99999})
    brozzler.new_site(frontier, site)

    site.refresh()  # get it back from the db
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"]
    assert site.starts_and_stops[0]["stop"] is None

    frontier.finished(site, "FINISHED")

    assert site.status == "FINISHED"
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"]
    assert site.starts_and_stops[0]["stop"]
    assert site.starts_and_stops[0]["stop"] > site.starts_and_stops[0]["start"]

    frontier.resume_site(site)

    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]["start"]
    assert site.starts_and_stops[1]["stop"] is None

    # no time limit set
    frontier.enforce_time_limit(site)

    site.time_limit = 10
    site.claimed = True
    site.save()

    # time limit not reached yet
    frontier.enforce_time_limit(site)
    assert site.status == "ACTIVE"
    assert len(site.starts_and_stops) == 2
    assert site.starts_and_stops[1]["start"]
    assert site.starts_and_stops[1]["stop"] is None

    site.time_limit = 0.1
    time.sleep(0.1)

    with pytest.raises(brozzler.ReachedTimeLimit):
        frontier.enforce_time_limit(site)


def test_field_defaults():
    rr = doublethink.Rethinker("localhost", db="ignoreme")

    # page
    brozzler.Page.table_ensure(rr)
    page = brozzler.Page(rr, {"hops_from_seed": 3})
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
    site = brozzler.Site(rr, {"seed": "http://example.com/"})
    assert site.id is None
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/"}]}
    site.save()
    assert site.id
    assert site.scope

    tite = brozzler.Site.load(rr, site.id)
    assert tite.id == site.id
    assert tite.scope == site.scope
    tite.save()
    assert tite.id == site.id
    assert tite.scope == site.scope
    tite.refresh()
    assert tite.id == site.id
    assert tite.scope == site.scope

    # job
    brozzler.Job.table_ensure(rr)
    job = brozzler.Job(rr, {"status": "WHUUUT"})
    assert job.status == "WHUUUT"
    assert job.id is None
    assert job.starts_and_stops
    job.save()
    assert job.status == "WHUUUT"
    assert job.id
    assert job.starts_and_stops

    kob = brozzler.Job.load(rr, job.id)
    assert kob.status == "WHUUUT"
    assert kob.id
    assert kob.starts_and_stops
    kob.save()
    assert kob.status == "WHUUUT"
    assert kob.id
    assert kob.starts_and_stops
    kob.refresh()
    assert kob.status == "WHUUUT"
    assert kob.id
    assert kob.starts_and_stops


def test_scope_and_schedule_outlinks():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(rr, {"seed": "http://example.com/"})
    parent_page = brozzler.Page(
        rr, {"hops_from_seed": 1, "url": "http://example.com/whatever"}
    )
    outlinks = [
        "https://example.com/",
        "https://example.com/foo",
        "http://example.com/bar",
        "HTtp://exAMPle.COm/bar",
        "HTtp://exAMPle.COm/BAr",
        "HTtp://exAMPle.COm/BAZZZZ",
    ]
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots

    assert sorted(parent_page.outlinks["rejected"]) == [
        "https://example.com/",
        "https://example.com/foo",
    ]
    assert sorted(parent_page.outlinks["accepted"]) == [
        "http://example.com/BAZZZZ",
        "http://example.com/BAr",
        "http://example.com/bar",
    ]
    assert parent_page.outlinks["blocked"] == []

    pp = brozzler.Page.load(rr, parent_page.id)
    assert pp == parent_page

    for url in parent_page.outlinks["rejected"]:
        id = brozzler.Page.compute_id(site.id, url)
        assert brozzler.Page.load(rr, id) is None
    for url in parent_page.outlinks["accepted"]:
        id = brozzler.Page.compute_id(site.id, url)
        assert brozzler.Page.load(rr, id)


def test_parent_url_scoping():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    # scope rules that look at parent page url should consider both the
    # original url and the redirect url, if any, of the parent page
    site = brozzler.Site(
        rr,
        {
            "seed": "http://example.com/foo/",
            "scope": {
                "accepts": [{"parent_url_regex": "^http://example.com/acceptme/.*$"}],
                "blocks": [{"parent_url_regex": "^http://example.com/blockme/.*$"}],
            },
            "remember_outlinks": True,
        },
    )
    site.save()

    # an outlink that would not otherwise be in scope
    outlinks = ["https://some-random-url.com/"]

    # parent page does not match any parent_url_regex
    parent_page = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/foo/spluh"}
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == outlinks
    assert parent_page.outlinks["accepted"] == []

    # parent page url matches accept parent_url_regex
    parent_page = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/acceptme/futz"}
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == []
    assert parent_page.outlinks["accepted"] == outlinks

    # parent page redirect_url matches accept parent_url_regex
    parent_page_c = brozzler.Page(
        rr,
        {
            "site_id": site.id,
            "url": "http://example.com/toot/blah",
            "redirect_url": "http://example.com/acceptme/futz",
        },
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == []
    assert parent_page.outlinks["accepted"] == outlinks

    # an outlink that would normally be in scope
    outlinks = ["http://example.com/foo/whatever/"]

    # parent page does not match any parent_url_regex
    parent_page = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/foo/spluh"}
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == []
    assert parent_page.outlinks["accepted"] == outlinks

    # parent page url matches block parent_url_regex
    parent_page = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/blockme/futz"}
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == outlinks
    assert parent_page.outlinks["accepted"] == []

    # parent page redirect_url matches block parent_url_regex
    parent_page_c = brozzler.Page(
        rr,
        {
            "site_id": site.id,
            "url": "http://example.com/toot/blah",
            "redirect_url": "http://example.com/blockme/futz",
        },
    )
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert parent_page.outlinks["rejected"] == outlinks
    assert parent_page.outlinks["accepted"] == []


def test_completed_page():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    # redirect that changes scope surt
    site = brozzler.Site(rr, {"seed": "http://example.com/a/"})
    site.save()
    page = brozzler.Page(
        rr,
        {
            "site_id": site.id,
            "url": "http://example.com/a/",
            "claimed": True,
            "brozzle_count": 0,
            "hops_from_seed": 0,
            "redirect_url": "http://example.com/b/",
        },
    )
    page.save()
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    frontier.completed_page(site, page)
    assert site.scope == {
        "accepts": [
            {"ssurt": "com,example,//http:/a/"},
            {"ssurt": "com,example,//http:/b/"},
        ]
    }
    site.refresh()
    assert site.scope == {
        "accepts": [
            {"ssurt": "com,example,//http:/a/"},
            {"ssurt": "com,example,//http:/b/"},
        ]
    }
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False

    # redirect that doesn't change scope surt because destination is covered by
    # the original surt
    site = brozzler.Site(rr, {"seed": "http://example.com/a/"})
    site.save()
    page = brozzler.Page(
        rr,
        {
            "site_id": site.id,
            "url": "http://example.com/a/",
            "claimed": True,
            "brozzle_count": 0,
            "hops_from_seed": 0,
            "redirect_url": "http://example.com/a/x/",
        },
    )
    page.save()
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    frontier.completed_page(site, page)
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    site.refresh()
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False

    # redirect that doesn't change scope surt because page is not the seed page
    site = brozzler.Site(rr, {"seed": "http://example.com/a/"})
    site.save()
    page = brozzler.Page(
        rr,
        {
            "site_id": site.id,
            "url": "http://example.com/c/",
            "claimed": True,
            "brozzle_count": 0,
            "hops_from_seed": 1,
            "redirect_url": "http://example.com/d/",
        },
    )
    page.save()
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    frontier.completed_page(site, page)
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    site.refresh()
    assert site.scope == {"accepts": [{"ssurt": "com,example,//http:/a/"}]}
    assert page.brozzle_count == 1
    assert page.claimed == False
    page.refresh()
    assert page.brozzle_count == 1
    assert page.claimed == False


def test_seed_page():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    site = brozzler.Site(rr, {"seed": "http://example.com/a/"})
    site.save()

    assert frontier.seed_page(site.id) is None

    page1 = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/a/b/", "hops_from_seed": 1}
    )
    page1.save()

    assert frontier.seed_page(site.id) is None

    page0 = brozzler.Page(
        rr, {"site_id": site.id, "url": "http://example.com/a/", "hops_from_seed": 0}
    )
    page0.save()

    assert frontier.seed_page(site.id) == page0


def test_hashtag_seed():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    # no hash tag
    site = brozzler.Site(rr, {"seed": "http://example.org/"})
    brozzler.new_site(frontier, site)

    assert site.scope == {"accepts": [{"ssurt": "org,example,//http:/"}]}

    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 1
    assert pages[0].url == "http://example.org/"
    assert not pages[0].hashtags

    # yes hash tag
    site = brozzler.Site(rr, {"seed": "http://example.org/#hash"})
    brozzler.new_site(frontier, site)

    assert site.scope == {"accepts": [{"ssurt": "org,example,//http:/"}]}

    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 1
    assert pages[0].url == "http://example.org/"
    assert pages[0].hashtags == [
        "#hash",
    ]


def test_hashtag_links():
    rr = doublethink.Rethinker("localhost", db="test_hashtag_links")
    frontier = brozzler.RethinkDbFrontier(rr)

    site = brozzler.Site(rr, {"seed": "http://example.org/"})
    brozzler.new_site(frontier, site)
    parent_page = frontier.seed_page(site.id)
    assert not parent_page.hashtags
    outlinks = [
        "http://example.org/#foo",
        "http://example.org/bar",
        "http://example.org/bar#baz",
        "http://example.org/bar#quux",
        "http://example.org/zuh#buh",
    ]
    frontier.scope_and_schedule_outlinks(site, parent_page, outlinks)

    pages = sorted(list(frontier.site_pages(site.id)), key=lambda p: p.url)
    assert len(pages) == 3
    assert pages[0].url == "http://example.org/"
    assert sorted(pages[0].outlinks["accepted"]) == [
        "http://example.org/",
        "http://example.org/bar",
        "http://example.org/zuh",
    ]
    assert not pages[0].outlinks["blocked"]
    assert not pages[0].outlinks["rejected"]
    assert pages[0].hashtags == [
        "#foo",
    ]
    assert pages[0].hops_from_seed == 0

    assert pages[1].url == "http://example.org/bar"
    assert sorted(pages[1].hashtags) == ["#baz", "#quux"]
    assert pages[1].priority == 36
    assert pages[1].hops_from_seed == 1

    assert pages[2].url == "http://example.org/zuh"
    assert pages[2].hashtags == ["#buh"]
    assert pages[2].priority == 12


def test_honor_stop_request():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    # 1. test stop request on job
    job_conf = {"seeds": [{"url": "http://example.com"}]}
    job = brozzler.new_job(frontier, job_conf)
    assert job.id
    sites = list(frontier.job_sites(job.id))
    assert len(sites) == 1
    site = sites[0]
    assert site.job_id == job.id

    # does not raise exception
    frontier.honor_stop_request(site)

    # set job.stop_requested
    job.stop_requested = datetime.datetime.utcnow().replace(tzinfo=doublethink.UTC)
    job.save()
    with pytest.raises(brozzler.CrawlStopped):
        frontier.honor_stop_request(site)

    # 2. test stop request on site
    job_conf = {"seeds": [{"url": "http://example.com"}]}
    job = brozzler.new_job(frontier, job_conf)
    assert job.id
    sites = list(frontier.job_sites(job.id))
    assert len(sites) == 1
    site = sites[0]
    assert site.job_id == job.id

    # does not raise exception
    frontier.honor_stop_request(site)

    # set site.stop_requested
    site.stop_requested = doublethink.utcnow()
    site.save()
    with pytest.raises(brozzler.CrawlStopped):
        frontier.honor_stop_request(site)


def test_claim_site():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    rr.table("sites").delete().run()  # clean slate

    with pytest.raises(brozzler.NothingToClaim):
        claimed_site = frontier.claim_sites()

    site = brozzler.Site(rr, {"seed": "http://example.org/"})
    brozzler.new_site(frontier, site)

    claimed_sites = frontier.claim_sites()
    assert len(claimed_sites) == 1
    claimed_site = claimed_sites[0]
    assert claimed_site.id == site.id
    assert claimed_site.claimed
    assert claimed_site.last_claimed >= doublethink.utcnow() - datetime.timedelta(
        minutes=1
    )
    with pytest.raises(brozzler.NothingToClaim):
        claimed_site = frontier.claim_sites()

    # site last_claimed less than 1 hour ago still not to be reclaimed
    claimed_site.last_claimed = doublethink.utcnow() - datetime.timedelta(minutes=55)
    claimed_site.save()
    with pytest.raises(brozzler.NothingToClaim):
        claimed_site = frontier.claim_sites()

    # site last_claimed more than 1 hour ago can be reclaimed
    site = claimed_site
    claimed_site = None
    site.last_claimed = doublethink.utcnow() - datetime.timedelta(minutes=65)
    site.save()
    claimed_sites = frontier.claim_sites()
    assert len(claimed_sites) == 1
    claimed_site = claimed_sites[0]
    assert claimed_site.id == site.id

    # clean up
    rr.table("sites").get(claimed_site.id).delete().run()


def test_max_claimed_sites():
    # max_claimed_sites is a brozzler job setting that puts a cap on the number
    # of the job's sites that can be brozzled simultaneously across the cluster
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)

    # clean slate
    rr.table("jobs").delete().run()
    rr.table("sites").delete().run()

    job_conf = {
        "seeds": [
            {"url": "http://example.com/1"},
            {"url": "http://example.com/2"},
            {"url": "http://example.com/3"},
            {"url": "http://example.com/4"},
            {"url": "http://example.com/5"},
        ],
        "max_claimed_sites": 3,
    }

    job = brozzler.new_job(frontier, job_conf)

    assert job.id
    assert job.max_claimed_sites == 3

    sites = list(frontier.job_sites(job.id))
    assert len(sites) == 5

    claimed_sites = frontier.claim_sites(1)
    assert len(claimed_sites) == 1
    claimed_sites = frontier.claim_sites(3)
    assert len(claimed_sites) == 2
    with pytest.raises(brozzler.NothingToClaim):
        claimed_site = frontier.claim_sites(3)

    # clean slate for the next one
    rr.table("jobs").delete().run()
    rr.table("sites").delete().run()


def test_choose_warcprox():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    svcreg = doublethink.ServiceRegistry(rr)
    frontier = brozzler.RethinkDbFrontier(rr)

    # avoid this error: https://travis-ci.org/internetarchive/brozzler/jobs/330991786#L1021
    rr.table("sites").wait().run()
    rr.table("services").wait().run()
    rr.table("sites").index_wait().run()
    rr.table("services").index_wait().run()

    # clean slate
    rr.table("sites").delete().run()
    rr.table("services").delete().run()
    worker = brozzler.BrozzlerWorker(frontier, svcreg)
    assert worker._choose_warcprox() is None

    rr.table("services").insert(
        {
            "role": "warcprox",
            "first_heartbeat": doublethink.utcnow(),
            "last_heartbeat": doublethink.utcnow(),
            "host": "host1",
            "port": 8000,
            "load": 0,
            "ttl": 60,
        }
    ).run()
    rr.table("services").insert(
        {
            "role": "warcprox",
            "first_heartbeat": doublethink.utcnow(),
            "last_heartbeat": doublethink.utcnow(),
            "host": "host2",
            "port": 8000,
            "load": 0,
            "ttl": 60,
        }
    ).run()
    rr.table("services").insert(
        {
            "role": "warcprox",
            "first_heartbeat": doublethink.utcnow(),
            "last_heartbeat": doublethink.utcnow(),
            "host": "host2",
            "port": 8001,
            "load": 0,
            "ttl": 60,
        }
    ).run()
    rr.table("services").insert(
        {
            "role": "warcprox",
            "first_heartbeat": doublethink.utcnow(),
            "last_heartbeat": doublethink.utcnow(),
            "host": "host3",
            "port": 8000,
            "load": 0,
            "ttl": 60,
        }
    ).run()
    rr.table("services").insert(
        {
            "role": "warcprox",
            "first_heartbeat": doublethink.utcnow(),
            "last_heartbeat": doublethink.utcnow(),
            "host": "host4",
            "port": 8000,
            "load": 1,
            "ttl": 60,
        }
    ).run()

    rr.table("sites").insert(
        {
            "proxy": "host1:8000",
            "status": "ACTIVE",
            "last_disclaimed": doublethink.utcnow(),
        }
    ).run()
    rr.table("sites").insert(
        {
            "proxy": "host1:8000",
            "status": "ACTIVE",
            "last_disclaimed": doublethink.utcnow(),
        }
    ).run()
    rr.table("sites").insert(
        {
            "proxy": "host2:8000",
            "status": "ACTIVE",
            "last_disclaimed": doublethink.utcnow(),
        }
    ).run()
    rr.table("sites").insert(
        {
            "proxy": "host2:8001",
            "status": "ACTIVE",
            "last_disclaimed": doublethink.utcnow(),
        }
    ).run()

    instance = worker._choose_warcprox()
    assert instance["host"] == "host3"
    assert instance["port"] == 8000
    rr.table("sites").insert(
        {
            "proxy": "host3:8000",
            "status": "ACTIVE",
            "last_disclaimed": doublethink.utcnow(),
        }
    ).run()

    instance = worker._choose_warcprox()
    assert instance["host"] == "host4"
    assert instance["port"] == 8000

    # clean up
    rr.table("sites").delete().run()
    rr.table("services").delete().run()


def test_max_hops_off():
    rr = doublethink.Rethinker("localhost", db="ignoreme")
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(
        rr,
        {
            "seed": "http://example.com/",
            "scope": {"max_hops_off_surt": 1, "blocks": [{"ssurt": "domain,bad,"}]},
        },
    )
    brozzler.new_site(frontier, site)
    site.refresh()  # get it back from the db

    # renamed this param
    assert not "max_hops_off_surt" in site.scope
    assert site.scope["max_hops_off"] == 1

    seed_page = frontier.seed_page(site.id)

    assert site.accept_reject_or_neither("http://foo.org/", seed_page) is None
    assert site.accept_reject_or_neither("https://example.com/toot", seed_page) is None
    assert site.accept_reject_or_neither("http://example.com/toot", seed_page) is True
    assert (
        site.accept_reject_or_neither("https://some.bad.domain/something", seed_page)
        is False
    )

    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        # two of these are in scope because of max_hops_off
        frontier.scope_and_schedule_outlinks(
            site,
            seed_page,
            [
                "http://foo.org/",
                "https://example.com/toot",
                "http://example.com/toot",
                "https://some.bad.domain/something",
            ],
        )
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots

    pages = sorted(list(frontier.site_pages(site.id)), key=lambda p: p.url)

    assert len(pages) == 4
    assert pages[0].url == "http://example.com/"
    assert pages[0].hops_off == 0
    assert not "hops_off_surt" in pages[0]
    assert set(pages[0].outlinks["accepted"]) == {
        "https://example.com/toot",
        "http://foo.org/",
        "http://example.com/toot",
    }
    assert pages[0].outlinks["blocked"] == []
    assert pages[0].outlinks["rejected"] == ["https://some.bad.domain/something"]
    assert {
        "brozzle_count": 0,
        "claimed": False,
        "hashtags": [],
        "hops_from_seed": 1,
        "hops_off": 0,
        "id": brozzler.Page.compute_id(site.id, "http://example.com/toot"),
        "job_id": None,
        "needs_robots_check": False,
        "priority": 12,
        "site_id": site.id,
        "url": "http://example.com/toot",
        "via_page_id": seed_page.id,
    } in pages
    assert {
        "brozzle_count": 0,
        "claimed": False,
        "hashtags": [],
        "hops_from_seed": 1,
        "hops_off": 1,
        "id": brozzler.Page.compute_id(site.id, "http://foo.org/"),
        "job_id": None,
        "needs_robots_check": False,
        "priority": 12,
        "site_id": site.id,
        "url": "http://foo.org/",
        "via_page_id": seed_page.id,
    } in pages
    assert {
        "brozzle_count": 0,
        "claimed": False,
        "hashtags": [],
        "hops_from_seed": 1,
        "hops_off": 1,
        "id": brozzler.Page.compute_id(site.id, "https://example.com/toot"),
        "job_id": None,
        "needs_robots_check": False,
        "priority": 12,
        "site_id": site.id,
        "url": "https://example.com/toot",
        "via_page_id": seed_page.id,
    } in pages

    # next hop is past max_hops_off, but normal in scope url is in scope
    foo_page = [pg for pg in pages if pg.url == "http://foo.org/"][0]
    orig_is_permitted_by_robots = brozzler.is_permitted_by_robots
    brozzler.is_permitted_by_robots = lambda *args: True
    try:
        frontier.scope_and_schedule_outlinks(
            site, foo_page, ["http://foo.org/bar", "http://example.com/blah"]
        )
    finally:
        brozzler.is_permitted_by_robots = orig_is_permitted_by_robots
    assert foo_page == {
        "brozzle_count": 0,
        "claimed": False,
        "hashtags": [],
        "hops_from_seed": 1,
        "hops_off": 1,
        "id": brozzler.Page.compute_id(site.id, "http://foo.org/"),
        "job_id": None,
        "needs_robots_check": False,
        "priority": 12,
        "site_id": site.id,
        "url": "http://foo.org/",
        "via_page_id": seed_page.id,
        "outlinks": {
            "accepted": ["http://example.com/blah"],
            "blocked": [],
            "rejected": ["http://foo.org/bar"],
        },
    }
    pages = sorted(list(frontier.site_pages(site.id)), key=lambda p: p.url)
    assert len(pages) == 5
    assert {
        "brozzle_count": 0,
        "claimed": False,
        "hashtags": [],
        "hops_from_seed": 2,
        "hops_off": 0,
        "id": brozzler.Page.compute_id(site.id, "http://example.com/blah"),
        "job_id": None,
        "needs_robots_check": False,
        "priority": 11,
        "site_id": site.id,
        "url": "http://example.com/blah",
        "via_page_id": foo_page.id,
    } in pages
