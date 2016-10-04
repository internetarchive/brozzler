#
# brozzler/robots.py - robots.txt support
#
# Copyright (C) 2014-2016 Internet Archive
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import json
import logging
import brozzler
import reppy.cache
import requests

__all__ = ["is_permitted_by_robots"]

_robots_caches = {}  # {site_id:reppy.cache.RobotsCache}
def _robots_cache(site):
    class SessionRaiseOn420(requests.Session):
        def get(self, url, *args, **kwargs):
            res = super().get(url, *args, **kwargs)
            if res.status_code == 420 and 'warcprox-meta' in res.headers:
                raise brozzler.ReachedLimit(warcprox_meta=json.loads(res.headers['warcprox-meta']), http_payload=res.text)
            else:
                return res

    if not site.id in _robots_caches:
        req_sesh = SessionRaiseOn420()
        req_sesh.verify = False   # ignore cert errors
        if site.proxy:
            proxie = "http://{}".format(site.proxy)
            req_sesh.proxies = {"http":proxie,"https":proxie}
        if site.extra_headers():
            req_sesh.headers.update(site.extra_headers())
        if site.user_agent:
            req_sesh.headers['User-Agent'] = site.user_agent
        _robots_caches[site.id] = reppy.cache.RobotsCache(session=req_sesh)

    return _robots_caches[site.id]

def is_permitted_by_robots(site, url):
    if site.ignore_robots:
        return True

    tries_left = 10
    while True:
        try:
            result = _robots_cache(site).allowed(url, "brozzler")
            return result
        except BaseException as e:
            if isinstance(e, reppy.exceptions.ServerError) and isinstance(e.args[0], brozzler.ReachedLimit):
                raise e.args[0]
            else:
                if tries_left > 0:
                    logging.warn("caught exception fetching robots.txt (%s tries left) for %s: %s", tries_left, url, repr(e))
                    tries_left -= 1
                else:
                    logging.error("caught exception fetching robots.txt (0 tries left) for %s: %s", url, repr(e), exc_info=True)
                    return False

