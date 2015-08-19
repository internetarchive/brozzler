# vim: set sw=4 et:

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
        if site.extra_headers:
            req_sesh.headers.update(site.extra_headers)
        _robots_caches[site.id] = reppy.cache.RobotsCache(session=req_sesh)

    return _robots_caches[site.id]

def is_permitted_by_robots(site, url):
    if site.ignore_robots:
        return True
    try:
        result = _robots_cache(site).allowed(url, "brozzler")
        return result
    except BaseException as e:
        if isinstance(e, reppy.exceptions.ServerError) and isinstance(e.args[0], brozzler.ReachedLimit):
            raise e.args[0]
        else:
            logging.error("problem with robots.txt for %s: %s", url, repr(e), exc_info=True)
            return False

