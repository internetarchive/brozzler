#!/usr/bin/env python
"""
test_units.py - some unit tests for parts of brozzler amenable to that

Copyright (C) 2016-2017 Internet Archive

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
import os
import brozzler
import brozzler.chrome
import brozzler.ydl
import logging
import yaml
import datetime
import requests
import tempfile
import uuid
import socket
import time
import sys
import threading
from unittest import mock

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format=(
        "%(asctime)s %(process)d %(levelname)s %(threadName)s "
        "%(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s"
    ),
)


@pytest.fixture(scope="module")
def httpd(request):
    # SimpleHTTPRequestHandler always uses CWD so we have to chdir
    os.chdir(os.path.join(os.path.dirname(__file__), "htdocs"))

    httpd = http.server.HTTPServer(
        ("localhost", 0), http.server.SimpleHTTPRequestHandler
    )
    httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
    httpd_thread.start()

    def fin():
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()

    request.addfinalizer(fin)

    return httpd


def test_robots(httpd):
    """
    Basic test of robots.txt user-agent substring matching.
    """
    url = "http://localhost:%s/" % httpd.server_port
    site = brozzler.Site(None, {"seed": url, "user_agent": "im/a/GoOdbot/yep"})
    assert brozzler.is_permitted_by_robots(site, url)

    site = brozzler.Site(None, {"seed": url, "user_agent": "im/a bAdBOt/uh huh"})
    assert not brozzler.is_permitted_by_robots(site, url)


def test_robots_http_statuses():
    for status in (
        200,
        204,
        400,
        401,
        402,
        403,
        404,
        405,
        500,
        501,
        502,
        503,
        504,
        505,
    ):

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                response = (
                    (
                        "HTTP/1.1 %s Meaningless message\r\n"
                        + "Content-length: 0\r\n"
                        + "\r\n"
                    )
                    % status
                ).encode("utf-8")
                self.connection.sendall(response)
                # self.send_response(status)
                # self.end_headers()

        httpd = http.server.HTTPServer(("localhost", 0), Handler)
        httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
        httpd_thread.start()

        try:
            url = "http://localhost:%s/" % httpd.server_port
            site = brozzler.Site(None, {"seed": url})
            assert brozzler.is_permitted_by_robots(site, url)
        finally:
            httpd.shutdown()
            httpd.server_close()
            httpd_thread.join()


def test_robots_empty_response():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()

    httpd = http.server.HTTPServer(("localhost", 0), Handler)
    httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
    httpd_thread.start()

    try:
        url = "http://localhost:%s/" % httpd.server_port
        site = brozzler.Site(None, {"seed": url})
        assert brozzler.is_permitted_by_robots(site, url)
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()


def test_robots_socket_timeout():
    stop_hanging = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            stop_hanging.wait(60)
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-length: 0\r\n\r\n")

    orig_timeout = brozzler.robots._SessionRaiseOn420.timeout

    httpd = http.server.HTTPServer(("localhost", 0), Handler)
    httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
    httpd_thread.start()

    try:
        url = "http://localhost:%s/" % httpd.server_port
        site = brozzler.Site(None, {"seed": url})
        brozzler.robots._SessionRaiseOn420.timeout = 2
        assert brozzler.is_permitted_by_robots(site, url)
    finally:
        brozzler.robots._SessionRaiseOn420.timeout = orig_timeout
        stop_hanging.set()
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()


def test_robots_dns_failure():
    # .invalid. is guaranteed nonexistent per rfc 6761
    url = "http://whatever.invalid./"
    site = brozzler.Site(None, {"seed": url})
    assert brozzler.is_permitted_by_robots(site, url)


def test_robots_connection_failure():
    # .invalid. is guaranteed nonexistent per rfc 6761
    url = "http://localhost:4/"  # nobody listens on port 4
    site = brozzler.Site(None, {"seed": url})
    assert brozzler.is_permitted_by_robots(site, url)


def test_scoping():
    test_scope = yaml.safe_load(
        """
max_hops: 100
accepts:
- url_match: REGEX_MATCH
  value: ^.*/audio_file/.*\.mp3$
- url_match: SURT_MATCH
  value: http://(com,vimeocdn,
- url_match: STRING_MATCH
  value: ec-media.soundcloud.com
- regex: ^https?://twitter\.com.*$
- substring: facebook.com
- regex: ^https?://(www.)?youtube.com/watch?.*$
  parent_url_regex: ^https?://(www.)?youtube.com/user/.*$
blocks:
- domain: twitter.com
  url_match: REGEX_MATCH
  value: ^.*lang=(?!en).*$
"""
    )

    site = brozzler.Site(
        None,
        {
            "id": 1,
            "seed": "http://example.com/foo/bar?baz=quux#monkey",
            "scope": test_scope,
        },
    )
    page = brozzler.Page(
        None, {"url": "http://example.com/foo/bar?baz=quux#monkey", "site_id": site.id}
    )

    assert site.accept_reject_or_neither("http://example.com/foo/bar", page) is True
    assert site.accept_reject_or_neither("http://example.com/foo/baz", page) is None

    assert site.accept_reject_or_neither("http://foo.com/some.mp3", page) is None
    assert (
        site.accept_reject_or_neither("http://foo.com/blah/audio_file/some.mp3", page)
        is True
    )

    assert (
        site.accept_reject_or_neither("http://a.b.vimeocdn.com/blahblah", page) is True
    )
    assert (
        site.accept_reject_or_neither("https://a.b.vimeocdn.com/blahblah", page) is None
    )

    assert site.accept_reject_or_neither("https://twitter.com/twit", page) is True
    assert (
        site.accept_reject_or_neither("https://twitter.com/twit?lang=en", page) is True
    )
    assert (
        site.accept_reject_or_neither("https://twitter.com/twit?lang=es", page) is False
    )

    assert (
        site.accept_reject_or_neither("https://www.facebook.com/whatevz", page) is True
    )

    assert (
        site.accept_reject_or_neither(
            "https://www.youtube.com/watch?v=dUIn5OAPS5s", page
        )
        is None
    )
    yt_user_page = brozzler.Page(
        None,
        {
            "url": "https://www.youtube.com/user/SonoraSantaneraVEVO",
            "site_id": site.id,
            "hops_from_seed": 10,
        },
    )
    assert (
        site.accept_reject_or_neither(
            "https://www.youtube.com/watch?v=dUIn5OAPS5s", yt_user_page
        )
        is True
    )


def test_proxy_down():
    """
    Test all fetching scenarios raise `brozzler.ProxyError` when proxy is down.

    This test needs to cover every possible fetch through the proxy other than
    fetches from the browser. For that, see test_brozzling.py.

    Tests two different kinds of connection error:
    - nothing listening the port (nobody listens on on port 4 :))
    - port bound but not accepting connections
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    for not_listening_proxy in ("127.0.0.1:4", "127.0.0.1:%s" % sock.getsockname()[1]):
        worker = brozzler.BrozzlerWorker(frontier=None, proxy=not_listening_proxy)
        site = brozzler.Site(
            None, {"id": str(uuid.uuid4()), "seed": "http://example.com/"}
        )
        page = brozzler.Page(None, {"url": "http://example.com/"})

        # robots.txt fetch
        with pytest.raises(brozzler.ProxyError):
            brozzler.is_permitted_by_robots(
                site, "http://example.com/", proxy=not_listening_proxy
            )

        # youtube-dl fetch
        with tempfile.TemporaryDirectory(prefix="brzl-ydl-") as tempdir:
            with pytest.raises(brozzler.ProxyError):
                brozzler.ydl.do_youtube_dl(worker, site, page)

        # raw fetch
        with pytest.raises(brozzler.ProxyError):
            worker._fetch_url(site, page=page)

        # WARCPROX_WRITE_RECORD
        with pytest.raises(brozzler.ProxyError):
            worker._warcprox_write_record(
                warcprox_address=not_listening_proxy,
                url="test://proxy_down/warcprox_write_record",
                warc_type="metadata",
                content_type="text/plain",
                payload=b"""payload doesn't matter here""",
            )


def test_start_stop_backwards_compat():
    site = brozzler.Site(None, {"seed": "http://example.com/"})
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"]
    assert site.starts_and_stops[0]["stop"] is None
    assert not "start_time" in site

    site = brozzler.Site(
        None,
        {"seed": "http://example.com/", "start_time": datetime.datetime(2017, 1, 1)},
    )
    assert len(site.starts_and_stops) == 1
    assert site.starts_and_stops[0]["start"] == datetime.datetime(2017, 1, 1)
    assert site.starts_and_stops[0]["stop"] is None
    assert not "start_time" in site

    job = brozzler.Job(None, {"seeds": [{"url": "https://example.com/"}]})
    assert job.starts_and_stops[0]["start"]
    assert job.starts_and_stops[0]["stop"] is None
    assert not "started" in job
    assert not "finished" in job

    job = brozzler.Job(
        None,
        {
            "seeds": [{"url": "https://example.com/"}],
            "started": datetime.datetime(2017, 1, 1),
            "finished": datetime.datetime(2017, 1, 2),
        },
    )
    assert job.starts_and_stops[0]["start"] == datetime.datetime(2017, 1, 1)
    assert job.starts_and_stops[0]["stop"] == datetime.datetime(2017, 1, 2)
    assert not "started" in job
    assert not "finished" in job


class Exception1(Exception):
    pass


class Exception2(Exception):
    pass


def test_thread_raise_not_accept():
    def never_accept():
        try:
            brozzler.sleep(2)
        except Exception as e:
            nonlocal thread_caught_exception
            thread_caught_exception = e

    # test that thread_raise does not raise exception in a thread that has no
    # `with thread_exception_gate()` block
    thread_caught_exception = None
    th = threading.Thread(target=never_accept)
    th.start()
    brozzler.thread_raise(th, Exception1)
    th.join()
    assert thread_caught_exception is None


def test_thread_raise_immediate():
    def accept_immediately():
        try:
            with brozzler.thread_accept_exceptions():
                brozzler.sleep(2)
        except Exception as e:
            nonlocal thread_caught_exception
            thread_caught_exception = e

    # test immediate exception raise
    thread_caught_exception = None
    th = threading.Thread(target=accept_immediately)
    th.start()
    brozzler.thread_raise(th, Exception1)
    start = time.time()
    th.join()
    assert thread_caught_exception
    assert isinstance(thread_caught_exception, Exception1)
    assert time.time() - start < 1.0


def test_thread_raise_safe_exit():
    def delay_context_exit():
        gate = brozzler.thread_accept_exceptions()
        orig_exit = type(gate).__exit__
        try:
            type(gate).__exit__ = lambda self, et, ev, t: (
                brozzler.sleep(2),
                orig_exit(self, et, ev, t),
                False,
            )[-1]
            with brozzler.thread_accept_exceptions() as gate:
                brozzler.sleep(2)
        except Exception as e:
            nonlocal thread_caught_exception
            thread_caught_exception = e
        finally:
            type(gate).__exit__ = orig_exit

    # test that a second thread_raise() doesn't result in an exception in
    # ThreadExceptionGate.__exit__
    thread_caught_exception = None
    th = threading.Thread(target=delay_context_exit)
    th.start()
    time.sleep(0.2)
    brozzler.thread_raise(th, Exception1)
    time.sleep(0.2)
    brozzler.thread_raise(th, Exception2)
    th.join()
    assert thread_caught_exception
    assert isinstance(thread_caught_exception, Exception1)


def test_thread_raise_pending_exception():
    def accept_eventually():
        try:
            brozzler.sleep(2)
            with brozzler.thread_accept_exceptions():
                pass
        except Exception as e:
            nonlocal thread_caught_exception
            thread_caught_exception = e

    # test exception that has to wait for `with thread_exception_gate()` block
    thread_caught_exception = None
    th = threading.Thread(target=accept_eventually)
    th.start()
    brozzler.thread_raise(th, Exception1)
    start = time.time()
    th.join()
    assert isinstance(thread_caught_exception, Exception1)
    assert time.time() - start > 1.0


def test_thread_raise_second_with_block():
    def two_with_blocks():
        try:
            with brozzler.thread_accept_exceptions():
                time.sleep(2)
            return  # test fails
        except Exception1 as e:
            pass
        except:
            return  # fail test

        try:
            with brozzler.thread_accept_exceptions():
                brozzler.sleep(2)
        except Exception as e:
            nonlocal thread_caught_exception
            thread_caught_exception = e

    # test that second `with` block gets second exception raised during first
    # `with` block
    thread_caught_exception = None
    th = threading.Thread(target=two_with_blocks)
    th.start()
    brozzler.thread_raise(th, Exception1)
    brozzler.thread_raise(th, Exception2)
    th.join()
    assert isinstance(thread_caught_exception, Exception2)


def test_needs_browsing():
    # only one test case here right now, which exposed a bug

    class ConvenientHeaders(http.client.HTTPMessage):
        def __init__(self, headers):
            http.client.HTTPMessage.__init__(self)
            for k, v in headers.items():
                self.add_header(k, v)

    page = brozzler.Page(None, {"url": "http://example.com/a"})

    spy = brozzler.ydl.YoutubeDLSpy()
    spy.fetches.append(
        {
            "url": "http://example.com/a",
            "method": "HEAD",
            "response_code": 301,
            "response_headers": ConvenientHeaders({"Location": "/b"}),
        }
    )
    spy.fetches.append(
        {
            "url": "http://example.com/b",
            "method": "GET",
            "response_code": 200,
            "response_headers": ConvenientHeaders({"Content-Type": "application/pdf"}),
        }
    )

    assert not brozzler.worker.BrozzlerWorker._needs_browsing(None, page, spy.fetches)


def test_seed_redirect():
    site = brozzler.Site(None, {"seed": "http://foo.com/"})
    site.note_seed_redirect("https://foo.com/a/b/c")
    assert site.scope == {
        "accepts": [
            {
                "ssurt": "com,foo,//http:/",
            },
            {
                "ssurt": "com,foo,//https:/",
            },
        ]
    }

    site = brozzler.Site(None, {"seed": "https://foo.com/"})
    site.note_seed_redirect("http://foo.com/a/b/c")
    assert site.scope == {
        "accepts": [
            {
                "ssurt": "com,foo,//https:/",
            },
            {
                "ssurt": "com,foo,//http:/",
            },
        ]
    }

    site = brozzler.Site(None, {"seed": "http://foo.com/"})
    site.note_seed_redirect("https://bar.com/a/b/c")
    assert site.scope == {
        "accepts": [
            {
                "ssurt": "com,foo,//http:/",
            },
            {
                "ssurt": "com,bar,//https:/a/b/c",
            },
        ]
    }


def test_limit_failures():
    page = mock.Mock()
    page.failed_attempts = None
    page.brozzle_count = 0

    site = mock.Mock()
    site.status = "ACTIVE"
    site.active_brozzling_time = 0
    site.starts_and_stops = [{"start": datetime.datetime.utcnow()}]

    rr = mock.Mock()
    rr.servers = [mock.Mock()]
    rethink_query = mock.Mock(run=mock.Mock(return_value=[]))
    rr.db_list = mock.Mock(return_value=rethink_query)
    rr.table_list = mock.Mock(return_value=rethink_query)
    rr.table = mock.Mock(
        return_value=mock.Mock(
            between=mock.Mock(
                return_value=mock.Mock(limit=mock.Mock(return_value=rethink_query))
            )
        )
    )
    assert rr.table().between().limit().run() == []
    frontier = brozzler.RethinkDbFrontier(rr)
    frontier.enforce_time_limit = mock.Mock()
    frontier.honor_stop_request = mock.Mock()
    frontier.claim_page = mock.Mock(return_value=page)
    frontier._maybe_finish_job = mock.Mock()

    browser = mock.Mock()

    worker = brozzler.BrozzlerWorker(frontier)
    worker.brozzle_page = mock.Mock(side_effect=Exception)

    assert page.failed_attempts is None
    assert page.brozzle_count == 0
    assert site.status == "ACTIVE"

    worker.brozzle_site(browser, site)
    assert page.failed_attempts == 1
    assert page.brozzle_count == 0
    assert site.status == "ACTIVE"

    worker.brozzle_site(browser, site)
    assert page.failed_attempts == 2
    assert page.brozzle_count == 0
    assert site.status == "ACTIVE"

    worker.brozzle_site(browser, site)
    assert page.failed_attempts == 3
    assert page.brozzle_count == 1
    assert site.status == "FINISHED"
