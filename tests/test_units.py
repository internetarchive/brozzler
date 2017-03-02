#!/usr/bin/env python
'''
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
'''

import pytest
import http.server
import threading
import os
import brozzler
import brozzler.chrome
import socket
import logging
import yaml

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
    site = brozzler.Site(None, {'seed':url,'user_agent':'im/a/GoOdbot/yep'})
    assert brozzler.is_permitted_by_robots(site, url)

    site = brozzler.Site(None, {'seed':url,'user_agent':'im/a bAdBOt/uh huh'})
    assert not brozzler.is_permitted_by_robots(site, url)

def test_scoping():
    test_scope = yaml.load('''
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
- bad_thing: bad rule should be ignored
''')

    site = brozzler.Site(None, {
        'id': 1, 'seed': 'http://example.com/foo/bar?baz=quux#monkey',
        'scope': test_scope})
    page = brozzler.Page(None, {
        'url': 'http://example.com/foo/bar?baz=quux#monkey',
        'site_id': site.id})

    assert site.is_in_scope('http://example.com/foo/bar', page)
    assert not site.is_in_scope('http://example.com/foo/baz', page)

    assert not site.is_in_scope('http://foo.com/some.mp3', page)
    assert site.is_in_scope('http://foo.com/blah/audio_file/some.mp3', page)

    assert site.is_in_scope('http://a.b.vimeocdn.com/blahblah', page)
    assert not site.is_in_scope('https://a.b.vimeocdn.com/blahblah', page)

    assert site.is_in_scope('https://twitter.com/twit', page)
    assert site.is_in_scope('https://twitter.com/twit?lang=en', page)
    assert not site.is_in_scope('https://twitter.com/twit?lang=es', page)

    assert site.is_in_scope('https://www.facebook.com/whatevz', page)

    assert not site.is_in_scope(
            'https://www.youtube.com/watch?v=dUIn5OAPS5s', page)
    yt_user_page = brozzler.Page(None, {
        'url': 'https://www.youtube.com/user/SonoraSantaneraVEVO',
        'site_id': site.id, 'hops_from_seed': 10})
    assert site.is_in_scope(
            'https://www.youtube.com/watch?v=dUIn5OAPS5s', yt_user_page)

