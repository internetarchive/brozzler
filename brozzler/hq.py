# vim: set sw=4 et:

import surt
import kombu
import json
import logging
import urllib.robotparser

# robots_url : RobotsFileParser
_robots_cache = {}
def robots(robots_url):
    if not robots_url in _robots_cache:
        robots_txt = urllib.robotparser.RobotFileParser(robots_url)
        logging.info("fetching {}".format(robots_url))
        try:
            robots_txt.read() # XXX should fetch through proxy
            _robots_cache[robots_url] = robots_txt
        except BaseException as e:
            logger.error("problem fetching {}".format(robots_url))

    return _robots_cache[robots_url]

def robots_url(url):
    hurl = surt.handyurl.parse(url)
    hurl.path = "/robots.txt"
    hurl.query = None
    hurl.hash = None
    return hurl.geturl()

class Site:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None):
        self.seed = seed
        self.id = id
        self.scope_surt = surt.surt(seed, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)

    def is_permitted_by_robots(self, url):
        return robots(robots_url(url)).can_fetch("*", url)

    def is_in_scope(self, url):
        try:
            surtt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
            return surtt.startswith(self.scope_surt)
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url))
            return False

    def to_dict(self):
        return dict(id=self.id, seed=self.seed)

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

