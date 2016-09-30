#!/usr/bin/env python
'''
cluster-integration-tests.py - integration tests for a brozzler cluster,
expects brozzler, warcprox, pywb, rethinkdb and other dependencies to be
running already

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
            'http://localhost:%s/' % httpd.server_port) as response:
        assert response.status == 200
        payload1 = response.read()
        assert payload1

    with urllib.request.urlopen(
            'http://localhost:%s/' % httpd.server_port) as response:
        assert response.status == 200
        payload2 = response.read()
        assert payload2

    assert payload1 == payload2

def test_services_up():
    '''Check that the expected services are up and running.'''
    # check that warcprox is listening
    with socket.socket() as s:
        # if the connect fails an exception is raised and the test fails
        s.connect(('localhost', 8000))

    ### # check that pywb is listening
    ### with socket.socket() as s:
    ###     # if the connect fails an exception is raised and the test fails
    ###     s.connect(('localhost', 8880))

    # check that rethinkdb is listening and looks sane
    r = rethinkstuff.Rethinker(db='rethinkdb')  # built-in db
    tbls = r.table_list().run()
    assert len(tbls) > 10

def test_brozzle_site(httpd):
    pass

