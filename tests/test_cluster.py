#!/usr/bin/env python
"""
test_cluster.py - integration tests for a brozzler cluster, expects brozzler,
warcprox, pywb, rethinkdb and other dependencies to be running already

Copyright (C) 2016-2018 Internet Archive

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

import pytest
import http.server
import threading
import urllib.request
import os
import socket
import doublethink
import time
import brozzler
import datetime
import requests
import subprocess
import http.server
import logging
import sys
import warcprox


# https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
def _local_address():
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # ip doesn't need to be reachable
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()


local_address = _local_address()


def start_service(service):
    subprocess.check_call(["sudo", "svc", "-u", "/etc/service/" + service])


def stop_service(service):
    subprocess.check_call(["sudo", "svc", "-d", "/etc/service/" + service])
    while True:
        status = subprocess.check_output(["sudo", "svstat", "/etc/service/" + service])
        if b" down " in status:
            break
        time.sleep(0.5)


@pytest.fixture(scope="module")
def httpd(request):
    class RequestHandler(http.server.SimpleHTTPRequestHandler):
        def do_POST(self):
            logging.info("\n%s\n%s", self.requestline, self.headers)
            self.do_GET()

        def do_GET(self):
            logging.info("\n%s\n%s", self.requestline, self.headers)
            if self.path == "/site5/redirect/":
                self.send_response(303, "See other")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", 0)
                self.send_header("Location", "/site5/destination/")
                self.end_headers()
                self.wfile.write(b"")
            elif self.path == "/site9/redirect.html":
                self.send_response(303, "See other")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", 0)
                self.send_header("Location", "/site9/destination.html")
                self.end_headers()
                self.wfile.write(b"")
            elif self.path.startswith("/infinite/"):
                payload = b"""
<html>
 <head>
  <title>infinite site</title>
 </head>
 <body>
  <a href='a/'>a/</a> <a href='b/'>b/</a> <a href='c/'>c/</a>
  <a href='d/'>d/</a> <a href='e/'>e/</a> <a href='f/'>f/</a>
  <a href='g/'>g/</a> <a href='h/'>h/</a> <a href='i/'>i/</a>
 </body>
</html>
"""
                self.send_response(200, "OK")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)
            else:
                super().do_GET()

    # SimpleHTTPRequestHandler always uses CWD so we have to chdir
    os.chdir(os.path.join(os.path.dirname(__file__), "htdocs"))

    httpd = http.server.HTTPServer((local_address, 0), RequestHandler)
    httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
    httpd_thread.start()

    def fin():
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()

    request.addfinalizer(fin)

    return httpd


def make_url(httpd, rel_url):
    return "http://%s:%s%s" % (local_address, httpd.server_port, rel_url)


def test_httpd(httpd):
    """
    Tests that our http server is working as expected, and that two fetches
    of the same url return the same payload, proving it can be used to test
    deduplication.
    """
    payload1 = content2 = None
    url = make_url(httpd, "/site1/file1.txt")
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        payload1 = response.read()
        assert payload1

    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        payload2 = response.read()
        assert payload2

    assert payload1 == payload2


def test_services_up():
    """Check that the expected services are up and running."""
    # check that rethinkdb is listening and looks sane
    rr = doublethink.Rethinker(db="rethinkdb")  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10

    # check that warcprox is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(("localhost", 8000))

    # check that pywb is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(("localhost", 8880))

    # check that brozzler dashboard is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(("localhost", 8881))


def test_brozzle_site(httpd):
    test_id = "test_brozzle_site-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site1/"),
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )

    # the two pages we expect to be crawled
    page1 = make_url(httpd, "/site1/")
    page2 = make_url(httpd, "/site1/file1.txt")
    robots = make_url(httpd, "/robots.txt")

    # so we can examine rethinkdb before it does anything
    try:
        stop_service("brozzler-worker")

        assert site.id is None
        frontier = brozzler.RethinkDbFrontier(rr)
        brozzler.new_site(frontier, site)
        assert site.id is not None
        assert len(list(frontier.site_pages(site.id))) == 1
    finally:
        start_service("brozzler-worker")

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # check that we got the two pages we expected
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    assert {page.url for page in pages} == {
        make_url(httpd, "/site1/"),
        make_url(httpd, "/site1/file1.txt"),
    }

    time.sleep(2)  # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table("captures").filter({"test_id": test_id}).run()
    captures_by_url = {c["url"]: c for c in captures if c["http_method"] != "HEAD"}
    assert robots in captures_by_url
    assert page1 in captures_by_url
    assert page2 in captures_by_url
    assert "screenshot:%s" % page1 in captures_by_url
    assert "thumbnail:%s" % page1 in captures_by_url
    # no screenshots of plaintext

    # check pywb
    t14 = captures_by_url[page2]["timestamp"].strftime("%Y%m%d%H%M%S")
    wb_url = "http://localhost:8880/brozzler/%s/%s" % (t14, page2)
    expected_payload = open(
        os.path.join(os.path.dirname(__file__), "htdocs", "site1", "file1.txt"), "rb"
    ).read()
    assert requests.get(wb_url).content == expected_payload

    url = "screenshot:%s" % page1
    t14 = captures_by_url[url]["timestamp"].strftime("%Y%m%d%H%M%S")
    wb_url = "http://localhost:8880/brozzler/%s/%s" % (t14, url)
    response = requests.get(wb_url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"

    url = "thumbnail:%s" % page1
    t14 = captures_by_url[url]["timestamp"].strftime("%Y%m%d%H%M%S")
    wb_url = "http://localhost:8880/brozzler/%s/%s" % (t14, url)
    response = requests.get(wb_url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_proxy_warcprox(httpd):
    """Test --proxy with proxy that happens to be warcprox"""
    try:
        stop_service("brozzler-worker")
        _test_proxy_setting(
            httpd, proxy="localhost:8000", warcprox_auto=False, is_warcprox=True
        )
    finally:
        start_service("brozzler-worker")


def test_proxy_non_warcprox(httpd):
    """Test --proxy with proxy that happens not to be warcprox"""

    class DumbProxyRequestHandler(http.server.SimpleHTTPRequestHandler):
        def do_HEAD(self):
            if not hasattr(self.server, "requests"):
                self.server.requests = []
            logging.info("%s %s", self.command, self.path)
            self.server.requests.append("%s %s" % (self.command, self.path))
            response = urllib.request.urlopen(self.path)
            self.wfile.write(
                ("HTTP/1.0 %s %s\r\n" % (response.code, response.reason)).encode(
                    "ascii"
                )
            )
            for header in response.getheaders():
                self.wfile.write(
                    ("%s: %s\r\n" % (header[0], header[1])).encode("ascii")
                )
            self.wfile.write(b"\r\n")
            return response

        def do_GET(self):
            response = self.do_HEAD()
            self.copyfile(response, self.wfile)

        def do_WARCPROX_WRITE_RECORD(self):
            if not hasattr(self.server, "requests"):
                self.server.requests = []
            logging.info("%s %s", self.command, self.path)
            self.send_error(400)

    proxy = http.server.HTTPServer(("localhost", 0), DumbProxyRequestHandler)
    th = threading.Thread(name="dumb-proxy", target=proxy.serve_forever)
    th.start()

    try:
        stop_service("brozzler-worker")
        _test_proxy_setting(
            httpd,
            proxy="localhost:%s" % proxy.server_port,
            warcprox_auto=False,
            is_warcprox=False,
        )
    finally:
        start_service("brozzler-worker")
    assert len(proxy.requests) <= 15
    assert proxy.requests.count("GET /status") == 1
    assert ("GET %s" % make_url(httpd, "/site1/")) in proxy.requests
    assert ("GET %s" % make_url(httpd, "/site1/file1.txt")) in proxy.requests
    assert [
        req for req in proxy.requests if req.startswith("WARCPROX_WRITE_RECORD")
    ] == []

    proxy.shutdown()
    th.join()


def test_no_proxy(httpd):
    try:
        stop_service("brozzler-worker")
        _test_proxy_setting(httpd, proxy=None, warcprox_auto=False, is_warcprox=False)
    finally:
        start_service("brozzler-worker")
    # XXX how to check that no proxy was used?


def test_warcprox_auto(httpd):
    """Test --warcprox-auto"""
    try:
        stop_service("brozzler-worker")
        _test_proxy_setting(httpd, proxy=None, warcprox_auto=True, is_warcprox=True)
    finally:
        start_service("brozzler-worker")


def test_proxy_conflict():
    with pytest.raises(AssertionError) as excinfo:
        worker = brozzler.worker.BrozzlerWorker(
            None, None, warcprox_auto=True, proxy="localhost:12345"
        )


def _test_proxy_setting(httpd, proxy=None, warcprox_auto=False, is_warcprox=False):
    test_id = "test_proxy=%s_warcprox_auto=%s_is_warcprox=%s-%s" % (
        proxy,
        warcprox_auto,
        is_warcprox,
        datetime.datetime.utcnow().isoformat(),
    )

    # the two pages we expect to be crawled
    page1 = make_url(httpd, "/site1/")
    page2 = make_url(httpd, "/site1/file1.txt")
    robots = make_url(httpd, "/robots.txt")

    rr = doublethink.Rethinker("localhost", db="brozzler")
    service_registry = doublethink.ServiceRegistry(rr)
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site1/"),
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )
    assert site.id is None
    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id is not None
    assert len(list(frontier.site_pages(site.id))) == 1

    worker = brozzler.worker.BrozzlerWorker(
        frontier,
        service_registry,
        max_browsers=1,
        chrome_exe=brozzler.suggest_default_chrome_exe(),
        warcprox_auto=warcprox_auto,
        proxy=proxy,
    )
    browser = worker._browser_pool.acquire()
    worker.brozzle_site(browser, site)
    worker._browser_pool.release(browser)

    # check proxy is set
    assert site.status == "FINISHED"
    if warcprox_auto:
        assert site.proxy[-5:] == ":8000"
    else:
        assert not site.proxy
    site.refresh()  # check that these things were persisted
    assert site.status == "FINISHED"
    if warcprox_auto:
        assert site.proxy[-5:] == ":8000"
    else:
        assert not site.proxy

    # check that we got the two pages we expected
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    assert {page.url for page in pages} == {
        make_url(httpd, "/site1/"),
        make_url(httpd, "/site1/file1.txt"),
    }

    time.sleep(2)  # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table("captures").filter({"test_id": test_id}).run()
    captures_by_url = {c["url"]: c for c in captures if c["http_method"] != "HEAD"}
    if is_warcprox:
        assert robots in captures_by_url
        assert page1 in captures_by_url
        assert page2 in captures_by_url
        assert "screenshot:%s" % page1 in captures_by_url
        assert "thumbnail:%s" % page1 in captures_by_url

        # check pywb
        t14 = captures_by_url[page2]["timestamp"].strftime("%Y%m%d%H%M%S")
        wb_url = "http://localhost:8880/brozzler/%s/%s" % (t14, page2)
        expected_payload = open(
            os.path.join(os.path.dirname(__file__), "htdocs", "site1", "file1.txt"),
            "rb",
        ).read()
        assert requests.get(wb_url).content == expected_payload
    else:
        assert captures_by_url == {}


def test_obey_robots(httpd):
    test_id = "test_obey_robots-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site1/"),
            "user_agent": "im a badbot",  # robots.txt blocks badbot
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )

    # so we can examine rethinkdb before it does anything
    try:
        stop_service("brozzler-worker")

        assert site.id is None
        frontier = brozzler.RethinkDbFrontier(rr)
        brozzler.new_site(frontier, site)
        assert site.id is not None
        site_pages = list(frontier.site_pages(site.id))
        assert len(site_pages) == 1
        assert site_pages[0].url == site.seed
        assert site_pages[0].needs_robots_check
    finally:
        start_service("brozzler-worker")

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # check that only the one page is in rethinkdb
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 1
    page = pages[0]
    assert page.url == make_url(httpd, "/site1/")
    assert page.blocked_by_robots

    # take a look at the captures table
    time.sleep(2)  # in case warcprox hasn't finished processing urls
    robots_url = make_url(httpd, "/robots.txt")
    captures = list(rr.table("captures").filter({"test_id": test_id}).run())
    assert len(captures) == 1
    assert captures[0]["url"] == robots_url

    # check pywb
    t14 = captures[0]["timestamp"].strftime("%Y%m%d%H%M%S")
    wb_url = "http://localhost:8880/brozzler/%s/%s" % (t14, robots_url)
    expected_payload = open(
        os.path.join(os.path.dirname(__file__), "htdocs", "robots.txt"), "rb"
    ).read()
    assert requests.get(wb_url, allow_redirects=False).content == expected_payload


def test_login(httpd):
    test_id = "test_login-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site2/"),
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
            "username": "test_username",
            "password": "test_password",
        },
    )

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # take a look at the captures table
    time.sleep(2)  # in case warcprox hasn't finished processing urls
    robots_url = make_url(httpd, "/robots.txt")
    captures = list(
        rr.table("captures").filter({"test_id": test_id}).order_by("timestamp").run()
    )
    meth_url = ["%s %s" % (c["http_method"], c["url"]) for c in captures]

    # there are several forms in in htdocs/site2/login.html but only one
    # that brozzler's heuristic should match and try to submit, and it has
    # action='00', so we can check for that here
    assert ("POST %s" % make_url(httpd, "/site2/00")) in meth_url

    # sanity check the rest of the crawl
    assert ("GET %s" % make_url(httpd, "/robots.txt")) in meth_url
    assert ("GET %s" % make_url(httpd, "/site2/")) in meth_url
    assert (
        "WARCPROX_WRITE_RECORD screenshot:%s" % make_url(httpd, "/site2/")
    ) in meth_url
    assert (
        "WARCPROX_WRITE_RECORD thumbnail:%s" % make_url(httpd, "/site2/")
    ) in meth_url
    assert ("GET %s" % make_url(httpd, "/site2/login.html")) in meth_url
    assert (
        "WARCPROX_WRITE_RECORD screenshot:%s" % make_url(httpd, "/site2/login.html")
    ) in meth_url
    assert (
        "WARCPROX_WRITE_RECORD thumbnail:%s" % make_url(httpd, "/site2/login.html")
    ) in meth_url


def test_seed_redirect(httpd):
    test_id = "test_seed_redirect-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    seed_url = make_url(httpd, "/site5/redirect/")
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site5/redirect/"),
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )
    assert site.scope == {
        "accepts": [
            {
                "ssurt": "%s//%s:http:/site5/redirect/"
                % (local_address, httpd.server_port)
            }
        ]
    }

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # take a look at the pages table
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    pages.sort(key=lambda page: page.hops_from_seed)
    assert pages[0].hops_from_seed == 0
    assert pages[0].url == seed_url
    assert pages[0].redirect_url == make_url(httpd, "/site5/destination/")
    assert pages[1].hops_from_seed == 1
    assert pages[1].url == make_url(httpd, "/site5/destination/page2.html")

    # check that scope has been updated properly
    assert site.scope == {
        "accepts": [
            {
                "ssurt": "%s//%s:http:/site5/redirect/"
                % (local_address, httpd.server_port)
            },
            {
                "ssurt": "%s//%s:http:/site5/destination/"
                % (local_address, httpd.server_port)
            },
        ]
    }


def test_hashtags(httpd):
    test_id = "test_hashtags-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    seed_url = make_url(httpd, "/site7/")
    site = brozzler.Site(
        rr,
        {
            "seed": seed_url,
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # check that we the page we expected
    pages = sorted(list(frontier.site_pages(site.id)), key=lambda p: p.url)
    assert len(pages) == 2
    assert pages[0].url == seed_url
    assert pages[0].hops_from_seed == 0
    assert pages[0].brozzle_count == 1
    assert pages[0].outlinks["accepted"] == [make_url(httpd, "/site7/foo.html")]
    assert not pages[0].hashtags
    assert pages[1].url == make_url(httpd, "/site7/foo.html")
    assert pages[1].hops_from_seed == 1
    assert pages[1].brozzle_count == 1
    assert sorted(pages[1].hashtags) == [
        "#boosh",
        "#ignored",
        "#whee",
    ]

    time.sleep(2)  # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table("captures").filter({"test_id": test_id}).run()
    captures_by_url = {c["url"]: c for c in captures if c["http_method"] != "HEAD"}
    assert seed_url in captures_by_url
    assert make_url(httpd, "/site7/foo.html") in captures_by_url
    assert make_url(httpd, "/site7/whee.txt") in captures_by_url
    assert make_url(httpd, "/site7/boosh.txt") in captures_by_url
    assert "screenshot:%s" % seed_url in captures_by_url
    assert "thumbnail:%s" % seed_url in captures_by_url
    assert "screenshot:%s" % make_url(httpd, "/site7/foo.html") in captures_by_url
    assert "thumbnail:%s" % make_url(httpd, "/site7/foo.html") in captures_by_url


def test_redirect_hashtags(httpd):
    test_id = "test_hashtags-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    seed_url = make_url(httpd, "/site9/")
    site = brozzler.Site(
        rr,
        {
            "seed": seed_url,
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # check that we the page we expected
    pages = sorted(list(frontier.site_pages(site.id)), key=lambda p: p.url)
    assert len(pages) == 2
    assert pages[0].url == seed_url
    assert pages[0].hops_from_seed == 0
    assert pages[0].brozzle_count == 1
    assert pages[0].outlinks["accepted"] == [make_url(httpd, "/site9/redirect.html")]
    assert not pages[0].hashtags
    assert pages[1].url == make_url(httpd, "/site9/redirect.html")
    assert pages[1].hops_from_seed == 1
    assert pages[1].brozzle_count == 1
    assert sorted(pages[1].hashtags) == [
        "#hash1",
        "#hash2",
    ]

    time.sleep(2)  # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table("captures").filter({"test_id": test_id}).run()
    redirect_captures = [
        c
        for c in captures
        if c["url"] == make_url(httpd, "/site9/redirect.html")
        and c["http_method"] == "GET"
    ]
    assert len(redirect_captures) == 2  # youtube-dl + browser, no hashtags

    # === expected captures ===
    #  1. GET http://localhost:41243/favicon.ico
    #  2. GET http://localhost:41243/robots.txt
    #  3. GET http://localhost:41243/site9/
    #  4. GET http://localhost:41243/site9/
    #  5. GET http://localhost:41243/site9/destination.html
    #  6. GET http://localhost:41243/site9/destination.html
    #  7. GET http://localhost:41243/site9/redirect.html
    #  8. GET http://localhost:41243/site9/redirect.html
    #  9. HEAD http://localhost:41243/site9/
    # 10. HEAD http://localhost:41243/site9/redirect.html
    # 11. WARCPROX_WRITE_RECORD screenshot:http://localhost:41243/site9/
    # 12. WARCPROX_WRITE_RECORD screenshot:http://localhost:41243/site9/redirect.html
    # 13. WARCPROX_WRITE_RECORD thumbnail:http://localhost:41243/site9/
    # 14. WARCPROX_WRITE_RECORD thumbnail:http://localhost:41243/site9/redirect.html


def test_stop_crawl(httpd):
    test_id = "test_stop_crawl_job-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    frontier = brozzler.RethinkDbFrontier(rr)

    # create a new job with three sites that could be crawled forever
    job_conf = {
        "seeds": [
            {"url": make_url(httpd, "/infinite/foo/")},
            {"url": make_url(httpd, "/infinite/bar/")},
            {"url": make_url(httpd, "/infinite/baz/")},
        ]
    }
    job = brozzler.new_job(frontier, job_conf)
    assert job.id

    sites = list(frontier.job_sites(job.id))
    assert not sites[0].stop_requested
    assert not sites[1].stop_requested

    # request crawl stop for one site using the command line entrypoint
    brozzler.cli.brozzler_stop_crawl(["brozzler-stop-crawl", "--site=%s" % sites[0].id])
    sites[0].refresh()
    assert sites[0].stop_requested

    # stop request should be honored quickly
    start = time.time()
    while not sites[0].status.startswith("FINISHED") and time.time() - start < 120:
        time.sleep(0.5)
        sites[0].refresh()
    assert sites[0].status == "FINISHED_STOP_REQUESTED"

    # but the other sites and the job as a whole should still be crawling
    sites[1].refresh()
    assert sites[1].status == "ACTIVE"
    sites[2].refresh()
    assert sites[2].status == "ACTIVE"
    job.refresh()
    assert job.status == "ACTIVE"

    # request crawl stop for the job using the command line entrypoint
    brozzler.cli.brozzler_stop_crawl(["brozzler-stop-crawl", "--job=%s" % job.id])
    job.refresh()
    assert job.stop_requested

    # stop request should be honored quickly
    start = time.time()
    while not job.status.startswith("FINISHED") and time.time() - start < 120:
        time.sleep(0.5)
        job.refresh()
    assert job.status == "FINISHED"

    # the other sites should also be FINISHED_STOP_REQUESTED
    sites[0].refresh()
    assert sites[0].status == "FINISHED_STOP_REQUESTED"
    sites[1].refresh()
    assert sites[1].status == "FINISHED_STOP_REQUESTED"
    sites[2].refresh()
    assert sites[2].status == "FINISHED_STOP_REQUESTED"


def test_warcprox_outage_resiliency(httpd):
    """
    Tests resiliency to warcprox outage.

    If no instances of warcprox are healthy when starting to crawl a site,
    brozzler-worker should sit there and wait until a healthy instance appears.

    If an instance goes down, sites assigned to that instance should bounce
    over to a healthy instance.

    If all instances of warcprox go down, brozzler-worker should sit and wait.
    """
    rr = doublethink.Rethinker("localhost", db="brozzler")
    frontier = brozzler.RethinkDbFrontier(rr)
    svcreg = doublethink.ServiceRegistry(rr)

    # run two instances of warcprox
    opts = warcprox.Options()
    opts.address = "0.0.0.0"
    opts.port = 0
    opts.rethinkdb_services_url = "rethinkdb://localhost/brozzler/services"

    warcprox1 = warcprox.controller.WarcproxController(opts)
    warcprox2 = warcprox.controller.WarcproxController(opts)
    warcprox1_thread = threading.Thread(
        target=warcprox1.run_until_shutdown, name="warcprox1"
    )
    warcprox2_thread = threading.Thread(
        target=warcprox2.run_until_shutdown, name="warcprox2"
    )

    # put together a site to crawl
    test_id = "test_warcprox_death-%s" % datetime.datetime.utcnow().isoformat()
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/infinite/"),
            "warcprox_meta": {"captures-table-extra-fields": {"test_id": test_id}},
        },
    )

    try:
        # we manage warcprox instances ourselves, so stop the one running on
        # the system, if any
        try:
            stop_service("warcprox")
        except Exception as e:
            logging.warning("problem stopping warcprox service: %s", e)

        # queue the site for brozzling
        brozzler.new_site(frontier, site)

        # check that nothing happens
        # XXX tail brozzler-worker.log or something?
        time.sleep(30)
        site.refresh()
        assert site.status == "ACTIVE"
        assert not site.proxy
        assert len(list(frontier.site_pages(site.id))) == 1

        # start one instance of warcprox
        warcprox1_thread.start()

        # check that it started using that instance
        start = time.time()
        while not site.proxy and time.time() - start < 30:
            time.sleep(0.5)
            site.refresh()
        assert site.proxy.endswith(":%s" % warcprox1.proxy.server_port)

        # check that the site accumulates pages in the frontier, confirming
        # that crawling is really happening
        start = time.time()
        while len(list(frontier.site_pages(site.id))) <= 1 and time.time() - start < 60:
            time.sleep(0.5)
            site.refresh()
        assert len(list(frontier.site_pages(site.id))) > 1

        # stop warcprox #1, start warcprox #2
        warcprox2_thread.start()
        warcprox1.stop.set()
        warcprox1_thread.join()

        # check that it switched over to warcprox #2
        start = time.time()
        while (
            not site.proxy
            or not site.proxy.endswith(":%s" % warcprox2.proxy.server_port)
        ) and time.time() - start < 30:
            time.sleep(0.5)
            site.refresh()
        assert site.proxy.endswith(":%s" % warcprox2.proxy.server_port)

        # stop warcprox #2
        warcprox2.stop.set()
        warcprox2_thread.join()

        page_count = len(list(frontier.site_pages(site.id)))
        assert page_count > 1

        # check that it is waiting for a warcprox to appear
        time.sleep(30)
        site.refresh()
        assert site.status == "ACTIVE"
        assert not site.proxy
        assert len(list(frontier.site_pages(site.id))) == page_count

        # stop crawling the site, else it can pollute subsequent test runs
        brozzler.cli.brozzler_stop_crawl(["brozzler-stop-crawl", "--site=%s" % site.id])
        site.refresh()
        assert site.stop_requested

        # stop request should be honored quickly
        start = time.time()
        while not site.status.startswith("FINISHED") and time.time() - start < 120:
            time.sleep(0.5)
            site.refresh()
        assert site.status == "FINISHED_STOP_REQUESTED"
    finally:
        warcprox1.stop.set()
        warcprox2.stop.set()
        warcprox1_thread.join()
        warcprox2_thread.join()
        start_service("warcprox")


def test_time_limit(httpd):
    test_id = "test_time_limit-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    frontier = brozzler.RethinkDbFrontier(rr)

    # create a new job with one seed that could be crawled forever
    job_conf = {"seeds": [{"url": make_url(httpd, "/infinite/foo/"), "time_limit": 20}]}
    job = brozzler.new_job(frontier, job_conf)
    assert job.id

    sites = list(frontier.job_sites(job.id))
    assert len(sites) == 1
    site = sites[0]

    # time limit should be enforced pretty soon
    start = time.time()
    while not sites[0].status.startswith("FINISHED") and time.time() - start < 120:
        time.sleep(0.5)
        sites[0].refresh()
    assert sites[0].status == "FINISHED_TIME_LIMIT"

    # all sites finished so job should be finished too
    start = time.time()
    job.refresh()
    while not job.status == "FINISHED" and time.time() - start < 10:
        time.sleep(0.5)
        job.refresh()
    assert job.status == "FINISHED"


def test_ydl_stitching(httpd):
    test_id = "test_ydl_stitching-%s" % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker("localhost", db="brozzler")
    frontier = brozzler.RethinkDbFrontier(rr)
    site = brozzler.Site(
        rr,
        {
            "seed": make_url(httpd, "/site10/"),
            "warcprox_meta": {
                "warc-prefix": "test_ydl_stitching",
                "captures-table-extra-fields": {"test_id": test_id},
            },
        },
    )
    brozzler.new_site(frontier, site)

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != "FINISHED" and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == "FINISHED"

    # check page.videos
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 1
    page = pages[0]
    assert len(page.videos) == 6
    stitched_url = "youtube-dl:00001:%s" % make_url(httpd, "/site10/")
    assert {
        "blame": "youtube-dl",
        "content-length": 267900,
        "content-type": "video/mp4",
        "response_code": 204,
        "url": stitched_url,
    } in page.videos

    time.sleep(2)  # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = list(rr.table("captures").filter({"test_id": test_id}).run())
    l = [c for c in captures if c["url"] == stitched_url]
    assert len(l) == 1
    c = l[0]
    assert c["filename"].startswith("test_ydl_stitching")
    assert c["content_type"] == "video/mp4"
    assert c["http_method"] == "WARCPROX_WRITE_RECORD"
