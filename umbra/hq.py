# vim: set sw=4 et:

import surt
import kombu
import json
import logging

class Site:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, seed, id=None):
        self.seed = seed
        self.id = id
        self.scope_surt = surt.surt(seed, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)

    def is_in_scope(self, url):
        try:
            surtt = surt.surt(url, canonicalizer=surt.GoogleURLCanonicalizer, trailing_comma=True)
            return surtt.startswith(self.scope_surt)
        except:
            self.logger.warn("""problem parsing url "{}" """.format(url), exc_info=True)
            return False

    def to_dict(self):
        return dict(id=self.id, seed=self.seed)

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))
        
