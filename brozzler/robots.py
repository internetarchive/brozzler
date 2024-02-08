"""
brozzler/robots.py - robots.txt support

Uses the reppy library version 0.3.4. Monkey-patches reppy to support substring
user-agent matching. We're sticking with 0.3.4 because later versions don't
support supplying a custom requests.Session.

See also https://github.com/seomoz/reppy/issues/37

Copyright (C) 2014-2016 Internet Archive

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

import json
import logging
import brozzler
import reppy
import reppy.cache
import reppy.parser
import requests

__all__ = ["is_permitted_by_robots"]

# monkey-patch reppy to do substring user-agent matching, see top of file
reppy.Utility.short_user_agent = lambda strng: strng


def _reppy_rules_getitem(self, agent):
    """
    Find the user-agent token matching the supplied full user-agent, using
    a case-insensitive substring search.
    """
    lc_agent = agent.lower()
    for s in self.agents:
        if s in lc_agent:
            return self.agents[s]
    return self.agents.get("*")


reppy.parser.Rules.__getitem__ = _reppy_rules_getitem


class _SessionRaiseOn420(requests.Session):
    timeout = 60

    def get(self, url, *args, **kwargs):
        res = super().get(url, timeout=self.timeout, *args, **kwargs)
        if res.status_code == 420 and "warcprox-meta" in res.headers:
            raise brozzler.ReachedLimit(
                warcprox_meta=json.loads(res.headers["warcprox-meta"]),
                http_payload=res.text,
            )
        else:
            return res


_robots_caches = {}  # {site_id:reppy.cache.RobotsCache}


def _robots_cache(site, proxy=None):
    if not site.id in _robots_caches:
        req_sesh = _SessionRaiseOn420()
        req_sesh.verify = False  # ignore cert errors
        if proxy:
            proxie = "http://%s" % proxy
            req_sesh.proxies = {"http": proxie, "https": proxie}
        if site.extra_headers():
            req_sesh.headers.update(site.extra_headers())
        if site.user_agent:
            req_sesh.headers["User-Agent"] = site.user_agent
        _robots_caches[site.id] = reppy.cache.RobotsCache(
            session=req_sesh, disallow_forbidden=False
        )

    return _robots_caches[site.id]


def is_permitted_by_robots(site, url, proxy=None):
    """
    Checks if `url` is permitted by robots.txt.

    Treats any kind of error fetching robots.txt as "allow all". See
    http://builds.archive.org/javadoc/heritrix-3.x-snapshot/org/archive/modules/net/CrawlServer.html#updateRobots(org.archive.modules.CrawlURI)
    for some background on that policy.

    Returns:
        bool: `True` if `site.ignore_robots` is set, or if `url` is permitted
            by robots.txt, `False` otherwise

    Raises:
        brozzler.ReachedLimit: if warcprox responded with 420 Reached Limit
        requests.exceptions.ProxyError: if the proxy is down
    """
    if site.ignore_robots:
        return True

    try:
        result = _robots_cache(site, proxy).allowed(url, site.user_agent or "brozzler")
        return result
    except Exception as e:
        if isinstance(e, reppy.exceptions.ServerError) and isinstance(
            e.args[0], brozzler.ReachedLimit
        ):
            raise e.args[0]
        elif hasattr(e, "args") and isinstance(
            e.args[0], requests.exceptions.ProxyError
        ):
            # reppy has wrapped an exception that we want to bubble up
            raise brozzler.ProxyError(e)
        else:
            logging.warning(
                "returning true (permitted) after problem fetching "
                "robots.txt for %r: %r",
                url,
                e,
            )
            return True
