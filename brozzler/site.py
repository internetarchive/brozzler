# vim: set sw=4 et:

import surt
import json
import logging
import urllib.robotparser
import urllib.request

def robots_url(url):
    hurl = surt.handyurl.parse(url)
    hurl.path = "/robots.txt"
    hurl.query = None
    hurl.hash = None
    return hurl.geturl()

class RobotFileParser(urllib.robotparser.RobotFileParser):
    logger = logging.getLogger(__module__ + "." + __qualname__)

    """Adds support  for fetching robots.txt through a proxy to
    urllib.robotparser.RobotFileParser."""
    def __init__(self, url="", proxy=None):
        super(RobotFileParser, self).__init__(url)
        self.proxy = proxy

    def read(self):
        """Reads the robots.txt URL and feeds it to the parser."""
        try:
            request = urllib.request.Request(self.url)
            if self.proxy:
                request.set_proxy(self.proxy, request.type)
            f = urllib.request.urlopen(request)
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                self.logger.info("{} returned {}, disallowing all".format(self.url, err.code))
                self.disallow_all = True
            elif err.code >= 400:
                self.logger.info("{} returned {}, allowing all".format(self.url, err.code))
                self.allow_all = True
        except BaseException as err:
            self.logger.error("problem fetching {}, disallowing all".format(self.url), exc_info=True)
            self.disallow_all = True
        else:
            raw = f.read()
            self.parse(raw.decode("utf-8").splitlines())

class Site:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None, scope_surt=None, proxy=None, ignore_robots=False):
        self.seed = seed
        self.id = id
        self.proxy = proxy
        self.ignore_robots = ignore_robots

        if scope_surt:
            self.scope_surt = scope_surt
        else:
            self.scope_surt = surt.surt(seed, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)

        self._robots_cache = {}  # {robots_url:RobotFileParser,...}

    def is_permitted_by_robots(self, url):
        return self.ignore_robots or self._robots(robots_url(url)).can_fetch("*", url)

    def is_in_scope(self, url):
        try:
            surtt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
            return surtt.startswith(self.scope_surt)
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url))
            return False

    def to_dict(self):
        return dict(id=self.id, seed=self.seed, scope_surt=self.scope_surt)

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

    def _robots(self, robots_url):
        if not robots_url in self._robots_cache:
            robots_txt = RobotFileParser(robots_url, self.proxy)
            self.logger.info("fetching {}".format(robots_url))
            robots_txt.read()
            self._robots_cache[robots_url] = robots_txt

        return self._robots_cache[robots_url]

class CrawlUrl:
    def __init__(self, url, id=None, site_id=None, hops_from_seed=0, outlinks=None):
        self.id = id
        self.site_id = site_id
        self.url = url
        self.hops_from_seed = hops_from_seed
        self._canon_hurl = None
        self.outlinks = outlinks

    def __repr__(self):
        return """CrawlUrl(url="{}",site_id={},hops_from_seed={})""".format(
                self.url, self.site_id, self.hops_from_seed)

    def calc_priority(self):
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canonical().count("/"))
        return priority

    def canonical(self):
        if self._canon_hurl is None:
            self._canon_hurl = surt.handyurl.parse(self.url)
            surt.GoogleURLCanonicalizer.canonicalize(self._canon_hurl)
        return self._canon_hurl.geturl()

    def to_dict(self):
        if self.outlinks is not None and not isinstance(self.outlinks, list):
            outlinks = []
            outlinks.extend(self.outlinks)
        else:
            outlinks = self.outlinks

        return dict(id=self.id, site_id=self.site_id, url=self.url,
                hops_from_seed=self.hops_from_seed, outlinks=outlinks)

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

