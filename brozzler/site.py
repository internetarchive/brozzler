# vim: set sw=4 et:

import surt
import json
import logging
import urllib.robotparser
import requests
import reppy.cache

class Site:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None, scope_surt=None, proxy=None,
        ignore_robots=False, time_limit=None, extra_headers=None,
        enable_warcprox_features=False):
        self.seed = seed
        self.id = id
        self.proxy = proxy
        self.ignore_robots = ignore_robots
        self.enable_warcprox_features = enable_warcprox_features
        self.time_limit = time_limit
        self.extra_headers = extra_headers

        if scope_surt:
            self.scope_surt = scope_surt
        else:
            self.scope_surt = surt.surt(seed, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)

        req_sesh = requests.Session()
        req_sesh.verify = False   # ignore cert errors
        if proxy:
            proxie = "http://{}".format(proxy)
            req_sesh.proxies = {"http":proxie,"https":proxie}
        if extra_headers:
            req_sesh.headers.update(extra_headers)
        self._robots_cache = reppy.cache.RobotsCache(session=req_sesh)

    def __repr__(self):
        return """Site(seed={},scope_surt={},proxy={},enable_warcprox_features={},ignore_robots={},extra_headers={})""".format(
                repr(self.seed), repr(self.scope_surt), repr(self.proxy), self.enable_warcprox_features, self.ignore_robots, self.extra_headers)

    def note_seed_redirect(self, url):
        new_scope_surt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
        if not new_scope_surt.startswith(self.scope_surt):
            self.logger.info("changing site scope surt from {} to {}".format(self.scope_surt, new_scope_surt))
            self.scope_surt = new_scope_surt

    def is_permitted_by_robots(self, url):
        return self.ignore_robots or self._robots_cache.allowed(url, "brozzler")

    def is_in_scope(self, url):
        try:
            surtt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
            return surtt.startswith(self.scope_surt)
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url))
            return False

    def to_dict(self):
        d = dict(vars(self))
        for k in vars(self):
            if k.startswith("_"):
                del d[k]
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

class Page:
    def __init__(self, url, id=None, site_id=None, hops_from_seed=0, outlinks=None, redirect_url=None):
        self.id = id
        self.site_id = site_id
        self.url = url
        self.hops_from_seed = hops_from_seed
        self._canon_hurl = None
        self.outlinks = outlinks
        self.redirect_url = redirect_url

    def __repr__(self):
        return """Page(url={},site_id={},hops_from_seed={})""".format(
                repr(self.url), self.site_id, self.hops_from_seed)

    def note_redirect(self, url):
        self.redirect_url = url

    def calc_priority(self):
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canon_url().count("/"))
        return priority

    def canon_url(self):
        if self._canon_hurl is None:
            self._canon_hurl = surt.handyurl.parse(self.url)
            surt.GoogleURLCanonicalizer.canonicalize(self._canon_hurl)
        return self._canon_hurl.geturl()

    def to_dict(self):
        d = dict(vars(self))

        for k in vars(self):
            if k.startswith("_"):
                del d[k]

        if self.outlinks is not None and not isinstance(self.outlinks, list):
            outlinks = []
            outlinks.extend(self.outlinks)
            d["outlinks"] = outlinks

        return d

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

