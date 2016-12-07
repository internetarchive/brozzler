#!/usr/bin/env python
'''
test_units.py - some unit tests for parts of brozzler amenable to that

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
import os
import brozzler
import brozzler.chrome
import socket
import logging

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

def test_robots(httpd):
    '''
    Basic test of robots.txt user-agent substring matching.
    '''
    url = 'http://localhost:%s/' % httpd.server_port
    site = brozzler.Site(seed=url, user_agent='im/a/GoOdbot/yep')
    assert brozzler.is_permitted_by_robots(site, url)

    site = brozzler.Site(seed=url, user_agent='im/a bAdBOt/uh huh')
    assert not brozzler.is_permitted_by_robots(site, url)

def test_find_available_port():
    try:
        psutil.net_connections(kind='tcp')
    except psutil.AccessDenied:
        logging.warn(
                'skipping _find_available_port() test because '
                'psutil.net_connections(kind="tcp") raised AccessDenied')
        return
    assert brozzler.chrome.Chrome._find_available_port(None, 9800) == 9800
    sock = socket.socket()
    sock.bind(('localhost', 9800))
    assert brozzler.chrome.Chrome._find_available_port(None, 9800) == 9999
    sock.close()
    assert brozzler.chrome.Chrome._find_available_port(None, 9800) == 9800

