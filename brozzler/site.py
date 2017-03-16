'''
brozzler/site.py - classes representing sites and pages

Copyright (C) 2014-2017 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

import urlcanon
import json
import logging
import brozzler
import hashlib
import time
import doublethink
import datetime
import re

_EPOCH_UTC = datetime.datetime.utcfromtimestamp(0.0).replace(
        tzinfo=doublethink.UTC)

class Site(doublethink.Document):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = 'sites'

    def populate_defaults(self):
        if not "status" in self:
            self.status = "ACTIVE"
        if not "enable_warcprox_features" in self:
            self.enable_warcprox_features = False
        if not "claimed" in self:
            self.claimed = False
        if not "last_disclaimed" in self:
            self.last_disclaimed = _EPOCH_UTC
        if not "last_claimed" in self:
            self.last_claimed = _EPOCH_UTC
        if not "scope" in self:
            self.scope = {}
        if not "surt" in self.scope and self.seed:
            self.scope["surt"] = brozzler.site_surt_canon(
                    self.seed).surt().decode('ascii')

        if not "starts_and_stops" in self:
            if self.get("start_time"):   # backward compatibility
                self.starts_and_stops = [{
                    "start":self.get("start_time"),"stop":None}]
                if self.get("status") != "ACTIVE":
                    self.starts_and_stops[0]["stop"] = self.last_disclaimed
                del self["start_time"]
            else:
                self.starts_and_stops = [
                        {"start":doublethink.utcnow(),"stop":None}]

    def __str__(self):
        return 'Site({"id":"%s","seed":"%s",...})' % (self.id, self.seed)

    def elapsed(self):
        '''Returns elapsed crawl time as a float in seconds.'''
        dt = 0
        for ss in self.starts_and_stops[:-1]:
            dt += (ss['stop'] - ss['start']).total_seconds()
        ss = self.starts_and_stops[-1]
        if ss['stop']:
            dt += (ss['stop'] - ss['start']).total_seconds()
        else: # crawl is active
            dt += (doublethink.utcnow() - ss['start']).total_seconds()
        return dt

    def note_seed_redirect(self, url):
        new_scope_surt = brozzler.site_surt_canon(url).surt().decode("ascii")
        if not new_scope_surt.startswith(self.scope["surt"]):
            self.logger.info("changing site scope surt from {} to {}".format(
                self.scope["surt"], new_scope_surt))
            self.scope["surt"] = new_scope_surt

    def extra_headers(self):
        hdrs = {}
        if self.enable_warcprox_features and self.warcprox_meta:
            hdrs["Warcprox-Meta"] = json.dumps(
                    self.warcprox_meta, separators=(',', ':'))
        return hdrs

    def is_in_scope(self, url, parent_page=None):
        if not isinstance(url, urlcanon.ParsedUrl):
            url = urlcanon.semantic(url)
        try_parent_urls = []
        if parent_page:
            try_parent_urls.append(urlcanon.semantic(parent_page.url))
            if parent_page.redirect_url:
                try_parent_urls.append(
                        urlcanon.semantic(parent_page.redirect_url))

        might_accept = False
        if not url.scheme in (b'http', b'https'):
            # XXX doesn't belong here maybe (where? worker ignores unknown
            # schemes?)
            return False
        elif (parent_page and "max_hops" in self.scope
                and parent_page.hops_from_seed >= self.scope["max_hops"]):
            pass
        elif url.surt().startswith(self.scope["surt"].encode("utf-8")):
            might_accept = True
        elif parent_page and parent_page.hops_off_surt < self.scope.get(
                "max_hops_off_surt", 0):
            might_accept = True
        elif "accepts" in self.scope:
            for accept_rule in self.scope["accepts"]:
                rule = urlcanon.MatchRule(**accept_rule)
                if try_parent_urls:
                    for parent_url in try_parent_urls:
                        if rule.applies(url, parent_url):
                           might_accept = True
                else:
                    if rule.applies(url):
                        might_accept = True

        if might_accept:
            if "blocks" in self.scope:
                for block_rule in self.scope["blocks"]:
                    rule = urlcanon.MatchRule(**block_rule)
                    if try_parent_urls:
                        for parent_url in try_parent_urls:
                            if rule.applies(url, parent_url):
                               return False
                    else:
                        if rule.applies(url):
                            return False
            return True
        else:
            return False

class Page(doublethink.Document):
    logger = logging.getLogger(__module__ + "." + __qualname__)
    table = "pages"

    @staticmethod
    def compute_id(site_id, url):
        digest_this = "site_id:%s,url:%s" % (site_id, url)
        return hashlib.sha1(digest_this.encode("utf-8")).hexdigest()

    def populate_defaults(self):
        if not "hops_from_seed" in self:
            self.hops_from_seed = 0
        if not "brozzle_count" in self:
            self.brozzle_count = 0
        if not "claimed" in self:
            self.claimed = False
        if not "hops_off_surt" in self:
            self.hops_off_surt = 0
        if not "needs_robots_check" in self:
            self.needs_robots_check = False
        if not "priority" in self:
            self.priority = self._calc_priority()
        if not "id" in self:
            self.id = self.compute_id(self.site_id, self.url)

    def __str__(self):
        return 'Page({"id":"%s","url":"%s",...})' % (self.id, self.url)

    def note_redirect(self, url):
        self.redirect_url = url

    def _calc_priority(self):
        if not self.url:
            return None
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canon_url().count("/"))
        return priority

    def canon_url(self):
        if not self.url:
            return None
        if self._canon_hurl is None:
            self._canon_hurl = urlcanon.semantic(self.url)
        return str(self._canon_hurl)

