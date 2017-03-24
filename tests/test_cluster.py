#!/usr/bin/env python
'''
test_cluster.py - integration tests for a brozzler cluster, expects brozzler,
warcprox, pywb, rethinkdb and other dependencies to be running already

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
'''

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

def start_service(service):
    subprocess.check_call(['sudo', 'service', service, 'start'])

def stop_service(service):
    subprocess.check_call(['sudo', 'service', service, 'stop'])

@pytest.fixture(scope='module')
def httpd(request):
    class RequestHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/site5/redirect/':
                self.send_response(303, 'See other')
                self.send_header('Connection', 'close')
                self.send_header('Content-Length', 0)
                self.send_header('Location', '/site5/destination/')
                self.end_headers()
                self.wfile.write(b'')
            else:
                super().do_GET()

    # SimpleHTTPRequestHandler always uses CWD so we have to chdir
    os.chdir(os.path.join(os.path.dirname(__file__), 'htdocs'))

    httpd = http.server.HTTPServer(('localhost', 0), RequestHandler)
    httpd_thread = threading.Thread(name='httpd', target=httpd.serve_forever)
    httpd_thread.start()

    def fin():
        httpd.shutdown()
        httpd.server_close()
        httpd_thread.join()
    request.addfinalizer(fin)

    return httpd

def test_httpd(httpd):
    '''
    Tests that our http server is working as expected, and that two fetches
    of the same url return the same payload, proving it can be used to test
    deduplication.
    '''
    payload1 = content2 = None
    url = 'http://localhost:%s/site1/file1.txt' % httpd.server_port
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
    '''Check that the expected services are up and running.'''
    # check that rethinkdb is listening and looks sane
    rr = doublethink.Rethinker(db='rethinkdb')  # built-in db
    tbls = rr.table_list().run()
    assert len(tbls) > 10

    # check that warcprox is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8000))

    # check that pywb is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8880))

    # check that brozzler dashboard is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8881))

def test_brozzle_site(httpd):
    test_id = 'test_brozzle_site-%s' % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker('localhost', db='brozzler')
    site = brozzler.Site(rr, {
        'seed': 'http://localhost:%s/site1/' % httpd.server_port,
        'warcprox_meta': {'captures-table-extra-fields':{'test_id':test_id}}})

    # the two pages we expect to be crawled
    page1 = 'http://localhost:%s/site1/' % httpd.server_port
    page2 = 'http://localhost:%s/site1/file1.txt' % httpd.server_port
    robots = 'http://localhost:%s/robots.txt' % httpd.server_port

    # so we can examine rethinkdb before it does anything
    try:
        stop_service('brozzler-worker')

        assert site.id is None
        frontier = brozzler.RethinkDbFrontier(rr)
        brozzler.new_site(frontier, site)
        assert site.id is not None
        assert len(list(frontier.site_pages(site.id))) == 1
    finally:
        start_service('brozzler-worker')

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != 'FINISHED' and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == 'FINISHED'

    # check that we got the two pages we expected
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    assert {page.url for page in pages} == {
            'http://localhost:%s/site1/' % httpd.server_port,
            'http://localhost:%s/site1/file1.txt' % httpd.server_port}

    time.sleep(2)   # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table('captures').filter({'test_id':test_id}).run()
    captures_by_url = {
            c['url']: c for c in captures if c['http_method'] != 'HEAD'}
    assert robots in captures_by_url
    assert page1 in captures_by_url
    assert page2 in captures_by_url
    assert 'screenshot:%s' % page1 in captures_by_url
    assert 'thumbnail:%s' % page1 in captures_by_url
    # no screenshots of plaintext

    # check pywb
    t14 = captures_by_url[page2]['timestamp'].strftime('%Y%m%d%H%M%S')
    wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, page2)
    expected_payload = open(os.path.join(
        os.path.dirname(__file__), 'htdocs', 'site1', 'file1.txt'), 'rb').read()
    assert requests.get(wb_url).content == expected_payload

    url = 'screenshot:%s' % page1
    t14 = captures_by_url[url]['timestamp'].strftime('%Y%m%d%H%M%S')
    wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, url)
    response = requests.get(wb_url)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/jpeg'

    url = 'thumbnail:%s' % page1
    t14 = captures_by_url[url]['timestamp'].strftime('%Y%m%d%H%M%S')
    wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, url)
    response = requests.get(wb_url)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/jpeg'

def test_proxy_warcprox(httpd):
    '''Test --proxy with proxy that happens to be warcprox'''
    try:
        stop_service('brozzler-worker')
        _test_proxy_setting(
                httpd, proxy='localhost:8000', warcprox_auto=False,
                is_warcprox=True)
    finally:
        start_service('brozzler-worker')

def test_proxy_non_warcprox(httpd):
    '''Test --proxy with proxy that happens not to be warcprox'''
    class DumbProxyRequestHandler(http.server.SimpleHTTPRequestHandler):
        def do_HEAD(self):
            if not hasattr(self.server, 'requests'):
                self.server.requests = []
            logging.info('%s %s', self.command, self.path)
            self.server.requests.append('%s %s' % (self.command, self.path))
            response = urllib.request.urlopen(self.path)
            self.wfile.write(('HTTP/1.0 %s %s\r\n' % (
                response.code, response.reason)).encode('ascii'))
            for header in response.getheaders():
                self.wfile.write(('%s: %s\r\n' % (
                    header[0], header[1])).encode('ascii'))
            self.wfile.write(b'\r\n')
            return response
        def do_GET(self):
            response = self.do_HEAD()
            self.copyfile(response, self.wfile)
        def do_WARCPROX_WRITE_RECORD(self):
            if not hasattr(self.server, 'requests'):
                self.server.requests = []
            logging.info('%s %s', self.command, self.path)
            self.send_error(400)

    proxy = http.server.HTTPServer(('localhost', 0), DumbProxyRequestHandler)
    th = threading.Thread(name='dumb-proxy', target=proxy.serve_forever)
    th.start()

    try:
        stop_service('brozzler-worker')
        _test_proxy_setting(
                httpd, proxy='localhost:%s' % proxy.server_port,
                warcprox_auto=False, is_warcprox=False)
    finally:
        start_service('brozzler-worker')
    assert len(proxy.requests) <= 15
    assert proxy.requests.count('GET /status') == 1
    assert ('GET http://localhost:%s/site1/' % httpd.server_port) in proxy.requests
    assert ('GET http://localhost:%s/site1/file1.txt' % httpd.server_port) in proxy.requests
    assert [req for req in proxy.requests if req.startswith('WARCPROX_WRITE_RECORD')] == []

    proxy.shutdown()
    th.join()

def test_no_proxy(httpd):
    try:
        stop_service('brozzler-worker')
        _test_proxy_setting(
                httpd, proxy=None, warcprox_auto=False, is_warcprox=False)
    finally:
        start_service('brozzler-worker')
    # XXX how to check that no proxy was used?

def test_warcprox_auto(httpd):
    '''Test --warcprox-auto'''
    try:
        stop_service('brozzler-worker')
        _test_proxy_setting(
                httpd, proxy=None, warcprox_auto=True, is_warcprox=True)
    finally:
        start_service('brozzler-worker')

def test_proxy_conflict():
    with pytest.raises(AssertionError) as excinfo:
        worker = brozzler.worker.BrozzlerWorker(
                None, None, warcprox_auto=True, proxy='localhost:12345')

def _test_proxy_setting(
        httpd, proxy=None, warcprox_auto=False, is_warcprox=False):
    test_id = 'test_proxy=%s_warcprox_auto=%s_is_warcprox=%s-%s' % (
            proxy, warcprox_auto, is_warcprox,
            datetime.datetime.utcnow().isoformat())

    # the two pages we expect to be crawled
    page1 = 'http://localhost:%s/site1/' % httpd.server_port
    page2 = 'http://localhost:%s/site1/file1.txt' % httpd.server_port
    robots = 'http://localhost:%s/robots.txt' % httpd.server_port

    rr = doublethink.Rethinker('localhost', db='brozzler')
    service_registry = doublethink.ServiceRegistry(rr)
    site = brozzler.Site(rr, {
        'seed': 'http://localhost:%s/site1/' % httpd.server_port,
        'warcprox_meta': {'captures-table-extra-fields':{'test_id':test_id}}})
    assert site.id is None
    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id is not None
    assert len(list(frontier.site_pages(site.id))) == 1

    worker = brozzler.worker.BrozzlerWorker(
            frontier, service_registry, max_browsers=1,
            chrome_exe=brozzler.suggest_default_chrome_exe(),
            warcprox_auto=warcprox_auto, proxy=proxy)
    browser = worker._browser_pool.acquire()
    worker.brozzle_site(browser, site)
    worker._browser_pool.release(browser)

    # check proxy is set
    assert site.status == 'FINISHED'
    if warcprox_auto:
        assert site.proxy[-5:] == ':8000'
    else:
        assert not site.proxy
    site.refresh() # check that these things were persisted
    assert site.status == 'FINISHED'
    if warcprox_auto:
        assert site.proxy[-5:] == ':8000'
    else:
        assert not site.proxy

    # check that we got the two pages we expected
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    assert {page.url for page in pages} == {
            'http://localhost:%s/site1/' % httpd.server_port,
            'http://localhost:%s/site1/file1.txt' % httpd.server_port}

    time.sleep(2)   # in case warcprox hasn't finished processing urls
    # take a look at the captures table
    captures = rr.table('captures').filter({'test_id':test_id}).run()
    captures_by_url = {
            c['url']: c for c in captures if c['http_method'] != 'HEAD'}
    if is_warcprox:
        assert robots in captures_by_url
        assert page1 in captures_by_url
        assert page2 in captures_by_url
        assert 'screenshot:%s' % page1 in captures_by_url
        assert 'thumbnail:%s' % page1 in captures_by_url

        # check pywb
        t14 = captures_by_url[page2]['timestamp'].strftime('%Y%m%d%H%M%S')
        wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, page2)
        expected_payload = open(os.path.join(
            os.path.dirname(__file__), 'htdocs', 'site1', 'file1.txt'), 'rb').read()
        assert requests.get(wb_url).content == expected_payload
    else:
        assert captures_by_url == {}

def test_obey_robots(httpd):
    test_id = 'test_obey_robots-%s' % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker('localhost', db='brozzler')
    site = brozzler.Site(rr, {
        'seed': 'http://localhost:%s/site1/' % httpd.server_port,
        'user_agent': 'im a badbot',   # robots.txt blocks badbot
        'warcprox_meta': {'captures-table-extra-fields':{'test_id':test_id}}})

    # so we can examine rethinkdb before it does anything
    try:
        stop_service('brozzler-worker')

        assert site.id is None
        frontier = brozzler.RethinkDbFrontier(rr)
        brozzler.new_site(frontier, site)
        assert site.id is not None
        site_pages = list(frontier.site_pages(site.id))
        assert len(site_pages) == 1
        assert site_pages[0].url == site.seed
        assert site_pages[0].needs_robots_check
    finally:
        start_service('brozzler-worker')

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != 'FINISHED' and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == 'FINISHED'

    # check that only the one page is in rethinkdb
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 1
    page = pages[0]
    assert page.url == 'http://localhost:%s/site1/' % httpd.server_port
    assert page.blocked_by_robots

    # take a look at the captures table
    time.sleep(2)   # in case warcprox hasn't finished processing urls
    robots_url = 'http://localhost:%s/robots.txt' % httpd.server_port
    captures = list(rr.table('captures').filter({'test_id':test_id}).run())
    assert len(captures) == 1
    assert captures[0]['url'] == robots_url

    # check pywb
    t14 = captures[0]['timestamp'].strftime('%Y%m%d%H%M%S')
    wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, robots_url)
    expected_payload = open(os.path.join(
        os.path.dirname(__file__), 'htdocs', 'robots.txt'), 'rb').read()
    assert requests.get(
            wb_url, allow_redirects=False).content == expected_payload

def test_login(httpd):
    test_id = 'test_login-%s' % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker('localhost', db='brozzler')
    site = brozzler.Site(rr, {
        'seed': 'http://localhost:%s/site2/' % httpd.server_port,
        'warcprox_meta': {'captures-table-extra-fields':{'test_id':test_id}},
        'username': 'test_username', 'password': 'test_password'})

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != 'FINISHED' and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == 'FINISHED'

    # take a look at the captures table
    time.sleep(2)   # in case warcprox hasn't finished processing urls
    robots_url = 'http://localhost:%s/robots.txt' % httpd.server_port
    captures = list(rr.table('captures').filter(
                {'test_id':test_id}).order_by('timestamp').run())
    meth_url = ['%s %s' % (c['http_method'], c['url']) for c in captures]

    # there are several forms in in htdocs/site2/login.html but only one
    # that brozzler's heuristic should match and try to submit, and it has
    # action='00', so we can check for that here
    assert ('POST http://localhost:%s/site2/00' % httpd.server_port) in meth_url

    # sanity check the rest of the crawl
    assert ('GET http://localhost:%s/robots.txt' % httpd.server_port) in meth_url
    assert ('GET http://localhost:%s/site2/' % httpd.server_port) in meth_url
    assert ('WARCPROX_WRITE_RECORD screenshot:http://localhost:%s/site2/' % httpd.server_port) in meth_url
    assert ('WARCPROX_WRITE_RECORD thumbnail:http://localhost:%s/site2/' % httpd.server_port) in meth_url
    assert ('GET http://localhost:%s/site2/login.html' % httpd.server_port) in meth_url
    assert ('WARCPROX_WRITE_RECORD screenshot:http://localhost:%s/site2/login.html' % httpd.server_port) in meth_url
    assert ('WARCPROX_WRITE_RECORD thumbnail:http://localhost:%s/site2/login.html' % httpd.server_port) in meth_url

def test_seed_redirect(httpd):
    test_id = 'test_login-%s' % datetime.datetime.utcnow().isoformat()
    rr = doublethink.Rethinker('localhost', db='brozzler')
    seed_url = 'http://localhost:%s/site5/redirect/' % httpd.server_port
    site = brozzler.Site(rr, {
        'seed': 'http://localhost:%s/site5/redirect/' % httpd.server_port,
        'warcprox_meta': {'captures-table-extra-fields':{'test_id':test_id}}})
    assert site.scope['surt'] == 'http://(localhost:%s,)/site5/redirect/' % httpd.server_port

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)
    assert site.id

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != 'FINISHED' and time.time() - start < 300:
        time.sleep(0.5)
        site.refresh()
    assert site.status == 'FINISHED'

    # take a look at the pages table
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    pages.sort(key=lambda page: page.hops_from_seed)
    assert pages[0].hops_from_seed == 0
    assert pages[0].url == seed_url
    assert pages[0].redirect_url == 'http://localhost:%s/site5/destination/' % httpd.server_port
    assert pages[1].hops_from_seed == 1
    assert pages[1].url == 'http://localhost:%s/site5/destination/page2.html' % httpd.server_port

    # check that scope has been updated properly
    assert site.scope['surt'] == 'http://(localhost:%s,)/site5/destination/' % httpd.server_port
