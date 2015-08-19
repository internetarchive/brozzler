# vim: set sw=4 et:

import surt
import json
import logging
import brozzler
import hashlib

__all__ = ["Site", "Page"]

class BaseDictable:
    def to_dict(self):
        d = dict(vars(self))
        for k in vars(self):
            if k.startswith("_") or d[k] is None:
                del d[k]
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

class Site(BaseDictable):
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None, scope=None, proxy=None,
        ignore_robots=False, time_limit=None, extra_headers=None,
        enable_warcprox_features=False, reached_limit=None, status="ACTIVE",
        claimed=False, last_disclaimed=0):
        self.seed = seed
        self.id = id
        self.proxy = proxy
        self.ignore_robots = ignore_robots
        self.enable_warcprox_features = bool(enable_warcprox_features)
        self.extra_headers = extra_headers
        self.time_limit = time_limit
        self.reached_limit = reached_limit
        self.status = status
        self.claimed = bool(claimed)
        self.last_disclaimed = last_disclaimed  # time as seconds since epoch

        self.scope = scope or {}
        if not "surt" in self.scope:
            self.scope["surt"] = surt.GoogleURLCanonicalizer.canonicalize(surt.handyurl.parse(seed)).getURLString(surt=True, trailing_comma=True)

    def __repr__(self):
        return """Site(id={},seed={},scope={},proxy={},enable_warcprox_features={},ignore_robots={},extra_headers={},reached_limit={})""".format(
                self.id, repr(self.seed), repr(self.scope),
                repr(self.proxy), self.enable_warcprox_features,
                self.ignore_robots, self.extra_headers, self.reached_limit)

    def note_seed_redirect(self, url):
        new_scope_surt = surt.GoogleURLCanonicalizer.canonicalize(surt.handyurl.parse(url)).getURLString(surt=True, trailing_comma=True)
        if not new_scope_surt.startswith(self.scope["surt"]):
            self.logger.info("changing site scope surt from {} to {}".format(self.scope["surt"], new_scope_surt))
            self.scope["surt"] = new_scope_surt

    def note_limit_reached(self, e):
        self.logger.info("reached_limit e=%s", e)
        assert isinstance(e, brozzler.ReachedLimit)
        if self.reached_limit and self.reached_limit != e.warcprox_meta["reached-limit"]:
            self.logger.warn("reached limit %s but site had already reached limit %s",
                    e.warcprox_meta["reached-limit"], self.reached_limit)
        else:
            self.reached_limit = e.warcprox_meta["reached-limit"]
            self.status = "FINISHED_REACHED_LIMIT"

    def is_in_scope(self, url, parent_page=None):
        if parent_page and "max_hops" in self.scope and parent_page.hops_from_seed >= self.scope["max_hops"]:
            return False

        try:
            hurl = surt.handyurl.parse(url)

            # XXX doesn't belong here probably (where? worker ignores unknown schemes?)
            if hurl.scheme != "http" and hurl.scheme != "https":
                return False

            surtt = surt.GoogleURLCanonicalizer.canonicalize(hurl).getURLString(surt=True, trailing_comma=True)
            return surtt.startswith(self.scope["surt"])
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url))
            return False

class Page(BaseDictable):
    def __init__(self, url, id=None, site_id=None, hops_from_seed=0, redirect_url=None, priority=None, claimed=False, brozzle_count=0):
        self.site_id = site_id
        self.url = url
        self.hops_from_seed = hops_from_seed
        self.redirect_url = redirect_url
        self.claimed = bool(claimed)
        self.brozzle_count = brozzle_count
        self._canon_hurl = None

        if priority is not None:
            self.priority = priority
        else:
            self.priority = self._calc_priority()

        if id is not None:
            self.id = id
        else:
            digest_this = "site_id:{},canon_url:{}".format(self.site_id, self.canon_url())
            self.id = hashlib.sha1(digest_this.encode("utf-8")).hexdigest()

    def __repr__(self):
        return """Page(url={},site_id={},hops_from_seed={})""".format(
                repr(self.url), self.site_id, self.hops_from_seed)

    def note_redirect(self, url):
        self.redirect_url = url

    def _calc_priority(self):
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canon_url().count("/"))
        priority = max(priority, brozzler.MIN_PRIORITY)
        priority = min(priority, brozzler.MAX_PRIORITY)
        return priority

    def canon_url(self):
        if self._canon_hurl is None:
            self._canon_hurl = surt.handyurl.parse(self.url)
            surt.GoogleURLCanonicalizer.canonicalize(self._canon_hurl)
        return self._canon_hurl.geturl()

