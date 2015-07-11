# vim: set sw=4 et:

import surt
import json

class CrawlUrl:
    def __init__(self, url, id=None, site_id=None, hops_from_seed=0):
        self.id = id
        self.site_id = site_id
        self.url = url
        self.hops_from_seed = hops_from_seed
        self._canon_hurl = None

    def __repr__(self):
        return """CrawlUrl(url="{}",site_id={},hops_from_seed={})""".format(
                self.url, self.site_id, self.hops_from_seed)

    def canonical(self):
        if self._canon_hurl is None:
            self._canon_hurl = surt.handyurl.parse(self.url)
            surt.GoogleURLCanonicalizer.canonicalize(self._canon_hurl)
        return self._canon_hurl.geturl()

    def to_json(self):
        d = dict(id=self.id, site_id=self.site_id, url=self.url, hops_from_seed=self.hops_from_seed)
        return json.dumps(d, separators=(',', ':'))

