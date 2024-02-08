#!/usr/bin/env python
"""
test_brozzling.py - XXX explain

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
import brozzler
import logging
import os
import http.server
import threading
import argparse
import urllib
import json
import threading
import socket

args = argparse.Namespace()
args.log_level = logging.INFO
brozzler.cli.configure_logging(args)

WARCPROX_META_420 = {
    "stats": {
        "test_limits_bucket": {
            "total": {"urls": 0, "wire_bytes": 0},
            "new": {"urls": 0, "wire_bytes": 0},
            "revisit": {"urls": 0, "wire_bytes": 0},
            "bucket": "test_limits_bucket",
        }
    },
    "reached-limit": {"test_limits_bucket/total/urls": 0},
}


@pytest.fixture(scope="module")
def httpd(request):
    class RequestHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.extensions_map[".mpd"] = "video/vnd.mpeg.dash.mpd"
            http.server.SimpleHTTPRequestHandler.__init__(self, *args, **kwargs)

        def do_GET(self):
            if self.path == "/420":
                self.send_response(420, "Reached limit")
                self.send_header("Connection", "close")
                self.send_header("Warcprox-Meta", json.dumps(WARCPROX_META_420))
                payload = b"request rejected by warcprox: reached limit test_limits_bucket/total/urls=0\n"
                self.send_header("Content-Type", "text/plain;charset=utf-8")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/401":
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Test"')
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(self.headers.get("Authorization", b""))
                self.wfile.write(b"not authenticated")
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/login-action":
                self.send_response(200)
                payload = b"login successful\n"
                self.send_header("Content-Type", "text/plain;charset=utf-8")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)
            else:
                super().do_POST()

    # SimpleHTTPRequestHandler always uses CWD so we have to chdir
    os.chdir(os.path.join(os.path.dirname(__file__), "htdocs"))

    httpd = http.server.HTTPServer(("localhost", 0), RequestHandler)
    httpd_thread = threading.Thread(name="httpd", target=httpd.serve_forever)
    httpd_thread.start()

    def fin():
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()

    request.addfinalizer(fin)

    return httpd


def test_httpd(httpd):
    """
    Tests that our http server is working as expected, and that two fetches
    of the same url return the same payload, proving it can be used to test
    deduplication.
    """
    payload1 = content2 = None
    url = "http://localhost:%s/site1/file1.txt" % httpd.server_port
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        payload1 = response.read()
        assert payload1

    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        payload2 = response.read()
        assert payload2

    assert payload1 == payload2

    url = "http://localhost:%s/420" % httpd.server_port
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(url)
    assert excinfo.value.getcode() == 420


def test_aw_snap_hes_dead_jim():
    chrome_exe = brozzler.suggest_default_chrome_exe()
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        with pytest.raises(brozzler.BrowsingException):
            browser.browse_page("chrome://crash")


# chromium's 401 handling changed???
@pytest.mark.xfail
def test_page_interstitial_exception(httpd):
    chrome_exe = brozzler.suggest_default_chrome_exe()
    url = "http://localhost:%s/401" % httpd.server_port
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        with pytest.raises(brozzler.PageInterstitialShown):
            browser.browse_page(url)


def test_on_response(httpd):
    response_urls = []

    def on_response(msg):
        response_urls.append(msg["params"]["response"]["url"])

    chrome_exe = brozzler.suggest_default_chrome_exe()
    url = "http://localhost:%s/site3/page.html" % httpd.server_port
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        browser.browse_page(url, on_response=on_response)
    assert response_urls[0] == "http://localhost:%s/site3/page.html" % httpd.server_port
    assert (
        response_urls[1] == "http://localhost:%s/site3/brozzler.svg" % httpd.server_port
    )
    assert response_urls[2] == "http://localhost:%s/favicon.ico" % httpd.server_port


def test_420(httpd):
    chrome_exe = brozzler.suggest_default_chrome_exe()
    url = "http://localhost:%s/420" % httpd.server_port
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        with pytest.raises(brozzler.ReachedLimit) as excinfo:
            browser.browse_page(url)
        assert excinfo.value.warcprox_meta == WARCPROX_META_420


def test_js_dialogs(httpd):
    chrome_exe = brozzler.suggest_default_chrome_exe()
    url = "http://localhost:%s/site4/alert.html" % httpd.server_port
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        # before commit d2ed6b97a24 these would hang and eventually raise
        # brozzler.browser.BrowsingTimeout, which would cause this test to fail
        browser.browse_page("http://localhost:%s/site4/alert.html" % httpd.server_port)
        browser.browse_page(
            "http://localhost:%s/site4/confirm.html" % httpd.server_port
        )
        browser.browse_page("http://localhost:%s/site4/prompt.html" % httpd.server_port)
        # XXX print dialog unresolved
        # browser.browse_page(
        #         'http://localhost:%s/site4/print.html' % httpd.server_port)


def test_page_videos(httpd):
    # test depends on behavior of youtube-dl and chromium, could fail and need
    # to be adjusted on youtube-dl or chromium updates
    chrome_exe = brozzler.suggest_default_chrome_exe()
    worker = brozzler.BrozzlerWorker(None)
    site = brozzler.Site(None, {})
    page = brozzler.Page(
        None, {"url": "http://localhost:%s/site6/" % httpd.server_port}
    )
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        worker.brozzle_page(browser, site, page)
    assert page.videos
    assert len(page.videos) == 4
    assert page.videos[0] == {
        "blame": "youtube-dl",
        "response_code": 200,
        "content-length": 383631,
        "content-type": "video/mp4",
        "url": "http://localhost:%s/site6/small.mp4" % httpd.server_port,
    }
    assert page.videos[1] == {
        "blame": "youtube-dl",
        "content-length": 92728,
        "content-type": "video/webm",
        "response_code": 200,
        "url": "http://localhost:%s/site6/small-video_280x160_100k.webm"
        % httpd.server_port,
    }
    assert page.videos[2] == {
        "blame": "youtube-dl",
        "content-length": 101114,
        "content-type": "video/webm",
        "response_code": 200,
        "url": "http://localhost:%s/site6/small-audio.webm" % httpd.server_port,
    }
    assert page.videos[3] == {
        "blame": "browser",
        # 'response_code': 206,
        # 'content-range': 'bytes 0-229454/229455',
        "response_code": 200,
        "content-length": 229455,
        "content-type": "video/webm",
        "url": "http://localhost:%s/site6/small.webm" % httpd.server_port,
    }


def test_extract_outlinks(httpd):
    chrome_exe = brozzler.suggest_default_chrome_exe()
    worker = brozzler.BrozzlerWorker(None)
    site = brozzler.Site(None, {})
    page = brozzler.Page(
        None, {"url": "http://localhost:%s/site8/" % httpd.server_port}
    )
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        outlinks = worker.brozzle_page(browser, site, page)
    assert outlinks == {
        "http://example.com/offsite",
        "http://localhost:%s/site8/baz/zuh" % httpd.server_port,
        "http://localhost:%s/site8/fdjisapofdjisap#1" % httpd.server_port,
        "http://localhost:%s/site8/fdjisapofdjisap#2" % httpd.server_port,
    }


def test_proxy_down():
    """
    Test that browsing raises `brozzler.ProxyError` when proxy is down.

    See also `test_proxy_down` in test_units.py.

    Tests two different kinds of connection error:
    - nothing listening the port (nobody listens on on port 4 :))
    - port bound but not accepting connections
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    for not_listening_proxy in ("127.0.0.1:4", "127.0.0.1:%s" % sock.getsockname()[1]):
        site = brozzler.Site(None, {"seed": "http://example.com/"})
        page = brozzler.Page(None, {"url": "http://example.com/"})

        worker = brozzler.BrozzlerWorker(frontier=None, proxy=not_listening_proxy)
        chrome_exe = brozzler.suggest_default_chrome_exe()

        with brozzler.Browser(chrome_exe=chrome_exe) as browser:
            with pytest.raises(brozzler.ProxyError):
                worker.brozzle_page(browser, site, page)


def test_try_login(httpd):
    """Test try_login behavior."""
    response_urls = []

    def on_response(msg):
        response_urls.append(msg["params"]["response"]["url"])

    chrome_exe = brozzler.suggest_default_chrome_exe()
    form_url = "http://localhost:%s/site11/form1.html" % httpd.server_port
    form_url_other = "http://localhost:%s/site11/form2.html" % httpd.server_port
    favicon_url = "http://localhost:%s/favicon.ico" % httpd.server_port
    login_url = "http://localhost:%s/login-action" % httpd.server_port
    # When username and password are defined and initial page has login form,
    # detect login form, submit login, and then return to the initial page.
    username = "user1"
    password = "pass1"
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        browser.browse_page(
            form_url, username=username, password=password, on_response=on_response
        )
    assert len(response_urls) == 4
    assert response_urls[0] == form_url
    assert response_urls[1] == favicon_url
    assert response_urls[2] == login_url
    assert response_urls[3] == form_url

    # We are now supporting a different type of form, we'll test that here.
    response_urls = []
    username = "user1"
    password = "pass1"
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        browser.browse_page(
            form_url_other,
            username=username,
            password=password,
            on_response=on_response,
        )
    assert len(response_urls) == 4
    assert response_urls[0] == form_url_other
    assert response_urls[1] == favicon_url
    assert response_urls[2] == login_url
    assert response_urls[3] == form_url_other

    # When username and password are not defined, just load the initial page.
    response_urls = []
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        browser.browse_page(form_url, on_response=on_response)
    assert len(response_urls) == 2
    assert response_urls[0] == form_url
    assert response_urls[1] == favicon_url

    # when the page doesn't have a form with username/password, don't submit it
    response_urls = []
    form_without_login_url = (
        "http://localhost:%s/site11/form-no-login.html" % httpd.server_port
    )
    with brozzler.Browser(chrome_exe=chrome_exe) as browser:
        browser.browse_page(
            form_without_login_url,
            username=username,
            password=password,
            on_response=on_response,
        )
    assert len(response_urls) == 2
    assert response_urls[0] == form_without_login_url
    assert response_urls[1] == favicon_url
