#!/usr/bin/env python
'''
test_cluster.py - integration tests for a brozzler cluster, expects brozzler,
warcprox, pywb, rethinkdb and other dependencies to be running already

Copyright (C) 2016 Internet Archive

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
import rethinkstuff
import time
import brozzler
import datetime
import requests

@pytest.fixture(scope='module')
def httpd(request):
    # SimpleHTTPRequestHandler always uses CWD so we have to chdir
    os.chdir(os.path.join(os.path.dirname(__file__), 'htdocs'))

    httpd = http.server.HTTPServer(
            ('localhost', 0), http.server.SimpleHTTPRequestHandler)
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
    with urllib.request.urlopen(
            'http://localhost:%s/file1.txt' % httpd.server_port) as response:
        assert response.status == 200
        payload1 = response.read()
        assert payload1

    with urllib.request.urlopen(
            'http://localhost:%s/file1.txt' % httpd.server_port) as response:
        assert response.status == 200
        payload2 = response.read()
        assert payload2

    assert payload1 == payload2

def test_services_up():
    '''Check that the expected services are up and running.'''
    # check that rethinkdb is listening and looks sane
    r = rethinkstuff.Rethinker(db='rethinkdb')  # built-in db
    tbls = r.table_list().run()
    assert len(tbls) > 10

    # check that warcprox is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8000))

    # check that pywb is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8880))

    # check that brozzler webconsole is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8881))

def test_brozzle_site(httpd):
    test_id = 'test_brozzle_site-%s' % datetime.datetime.utcnow().isoformat()
    site = brozzler.Site(
            seed='http://localhost:%s/' % httpd.server_port,
            proxy='localhost:8000', enable_warcprox_features=True,
            warcprox_meta={'captures-table-extra-fields':{'test_id':test_id}})

    # the two pages we expect to be crawled
    page1 = 'http://localhost:%s/' % httpd.server_port
    page2 = 'http://localhost:%s/file1.txt' % httpd.server_port

    assert site.id is None
    r = rethinkstuff.Rethinker('localhost', db='brozzler')
    frontier = brozzler.RethinkDbFrontier(r)
    brozzler.new_site(frontier, site)
    assert site.id is not None
    assert len(list(frontier.site_pages(site.id))) == 1

    # the site should be brozzled fairly quickly
    start = time.time()
    while site.status != 'FINISHED' and time.time() - start < 120:
        time.sleep(0.5)
        site = frontier.site(site.id)
    assert site.status == 'FINISHED'

    # check that we got the two pages we expected
    pages = list(frontier.site_pages(site.id))
    assert len(pages) == 2
    assert {page.url for page in pages} == {
            'http://localhost:%s/' % httpd.server_port,
            'http://localhost:%s/file1.txt' % httpd.server_port }

    # take a look at the captures table
    captures = r.table('captures').filter({'test_id':test_id}).run()
    captures_by_url = {c['url']:c for c in captures if c['method'] != 'HEAD'}
    assert page1 in captures_by_url
    assert '%srobots.txt' % page1 in captures_by_url
    assert page2 in captures_by_url
    assert 'youtube-dl:%s' % page1 in captures_by_url
    assert 'youtube-dl:%s' % page2 in captures_by_url
    assert 'screenshot:%s' % page1 in captures_by_url
    assert 'screenshot:%s' % page2 in captures_by_url
    assert 'thumbnail:%s' % page1 in captures_by_url
    assert 'thumbnail:%s' % page2 in captures_by_url

    # check pywb
    t14 = captures_by_url[page2].timestamp.strftime('%Y%m%d%H%M%S')
    wb_url = 'http://localhost:8880/brozzler/%s/%s' % (t14, page2)
    expected_payload = open(os.path.join(
        os.path.dirname(__file__), 'htdocs', 'file1.txt'), 'rb').read()
    assert requests.get().content == expected_payload
