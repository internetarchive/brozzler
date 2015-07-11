# vim: set sw=4 et:

import surt
import json

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

