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

import surt
import json
import logging
import brozzler
import hashlib
import time
import rethinkstuff
import datetime
import re
import ipaddress

_EPOCH_UTC = datetime.datetime.utcfromtimestamp(0.0).replace(
        tzinfo=rethinkstuff.UTC)

class Url:
    def __init__(self, url):
        self.url = url
        self._surt = None
        self._host = None

    @property
    def surt(self):
        if not self._surt:
            try:
                hurl = surt.handyurl.parse(self.url)
                surt.GoogleURLCanonicalizer.canonicalize(hurl)
                hurl.query = None
                hurl.hash = None
                # XXX chop off path after last slash??
                self._surt = hurl.getURLString(surt=True, trailing_comma=True)
            except Exception as e:
                logging.warn('problem surting %s - %s', repr(self.url), e)
        return self._surt

    @property
    def host(self):
        if not self._host:
            self._host = surt.handyurl.parse(self.url).host
        return self._host

    def matches_ip_or_domain(self, ip_or_domain):
        """
        Returns true if
         - ip_or_domain is an ip address and self.host is the same ip address
         - ip_or_domain is a domain and self.host is the same domain
         - ip_or_domain is a domain and self.host is a subdomain of it
        """
        if not self.host:
            return False

        if ip_or_domain == self.host:
            return True

        # if either ip_or_domain or self.host are ip addresses, and they're not
        # identical (previous check), not a match
        try:
            ipaddress.ip_address(ip_or_domain)
            return False
        except:
            pass
        try:
            ipaddress.ip_address(self.host)
            return False
        except:
            pass

        # if we get here, we're looking at two hostnames
        domain_parts = ip_or_domain.encode("idna").decode("ascii").lower().split(".")
        host_parts = self.host.encode("idna").decode("ascii").lower().split(".")

        return host_parts[-len(domain_parts):] == domain_parts

class Site(brozzler.BaseDictable):
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(
            self, seed, id=None, job_id=None, scope=None, proxy=None,
            ignore_robots=False, time_limit=None, warcprox_meta=None,
            enable_warcprox_features=False, reached_limit=None,
            status="ACTIVE", claimed=False, start_time=None,
            last_disclaimed=_EPOCH_UTC, last_claimed_by=None,
            last_claimed=_EPOCH_UTC, metadata={}, remember_outlinks=None,
            cookie_db=None, user_agent=None, behavior_parameters=None,
            username=None, password=None, starts_and_stops=None):

        self.seed = seed
        self.id = id
        self.job_id = job_id
        self.proxy = proxy
        self.ignore_robots = ignore_robots
        self.enable_warcprox_features = bool(enable_warcprox_features)
        self.warcprox_meta = warcprox_meta
        self.time_limit = time_limit
        self.reached_limit = reached_limit
        self.status = status
        self.claimed = bool(claimed)
        self.last_claimed_by = last_claimed_by
        self.last_disclaimed = last_disclaimed
        self.last_claimed = last_claimed
        self.metadata = metadata
        self.remember_outlinks = remember_outlinks
        self.cookie_db = cookie_db
        self.user_agent = user_agent
        self.behavior_parameters = behavior_parameters
        self.username = username
        self.password = password
        self.starts_and_stops = starts_and_stops
        if not self.starts_and_stops:
            if start_time:   # backward compatibility
                self.starts_and_stops = [{"start":start_time,"stop":None}]
                if self.status != "ACTIVE":
                    self.starts_and_stops[0]["stop"] = self.last_disclaimed
            else:
                self.starts_and_stops = [
                        {"start":rethinkstuff.utcnow(),"stop":None}]

        self.scope = scope or {}
        if not "surt" in self.scope:
            self.scope["surt"] = Url(seed).surt

    def elapsed(self):
        '''Returns elapsed crawl time as a float in seconds.'''
        dt = 0
        for ss in self.starts_and_stops[:-1]:
            dt += (ss['stop'] - ss['start']).total_seconds()
        ss = self.starts_and_stops[-1]
        if ss['stop']:
            dt += (ss['stop'] - ss['start']).total_seconds()
        else: # crawl is active
            dt += (rethinkstuff.utcnow() - ss['start']).total_seconds()
        return dt

    def __str__(self):
        return "Site-%s-%s" % (self.id, self.seed)

    def note_seed_redirect(self, url):
        new_scope_surt = Url(url).surt
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
        if not isinstance(url, Url):
            u = Url(url)
        else:
            u = url

        might_accept = False
        if not u.surt:
            return False
        elif not u.surt.startswith("http://") and not u.surt.startswith("https://"):
            # XXX doesn't belong here maybe (where? worker ignores unknown
            # schemes?)
            return False
        elif (parent_page and "max_hops" in self.scope
                and parent_page.hops_from_seed >= self.scope["max_hops"]):
            pass
        elif u.surt.startswith(self.scope["surt"]):
            might_accept = True
        elif parent_page and parent_page.hops_off_surt < self.scope.get(
                "max_hops_off_surt", 0):
            might_accept = True
        elif "accepts" in self.scope:
            for rule in self.scope["accepts"]:
                if self._scope_rule_applies(rule, u):
                    might_accept = True
                    break

        if might_accept:
            if "blocks" in self.scope:
                for rule in self.scope["blocks"]:
                    if self._scope_rule_applies(rule, u):
                        return False
            return True
        else:
            return False

    def _normalize_rule(self, rule):
        """
        Normalizes a scope rule.

        A scope rule is considered deprecated if it contains a `url_match` and
        `value`. This method converts such scope rules to the preferred style
        and returns the new rule. If `rule` is not a deprecated-style rule,
        returns  it unchanged.
        """
        if "url_match" in rule and "value" in rule:
            new_rule = dict(rule)
            url_match = new_rule.pop("url_match")
            if url_match == "REGEX_MATCH":
                new_rule["regex"] = new_rule.pop("value")
            elif url_match == "SURT_MATCH":
                new_rule["surt"] = new_rule.pop("value")
            elif url_match == "STRING_MATCH":
                new_rule["substring"] = new_rule.pop("value")
            else:
                raise Exception("invalid scope rule")
            return new_rule
        else:
            return rule

    def _scope_rule_applies(self, rule, url, parent_page=None):
        """
        Examples of valid rules expressed as yaml.

        - domain: bad.domain.com

        # preferred:
        - domain: monkey.org
          substring: bar

        # deprecated version of the same:
        - domain: monkey.org
          url_match: STRING_MATCH
          value: bar

        # preferred:
        - surt: http://(com,woop,)/fuh/

        # deprecated version of the same:
        - url_match: SURT_MATCH
          value: http://(com,woop,)/fuh/

        # preferred:
        - regex: ^https?://(www.)?youtube.com/watch?.*$
          parent_url_regex: ^https?://(www.)?youtube.com/user/.*$

        # deprecated version of the same:
        - url_match: REGEX_MATCH
          value: ^https?://(www.)?youtube.com/watch?.*$
          parent_url_regex: ^https?://(www.)?youtube.com/user/.*$
        """
        if not isinstance(url, Url):
            u = Url(url)
        else:
            u = url

        try:
            rewl = self._normalize_rule(rule)
        except Exception as e:
            self.logger.error(
                    "problem normalizing scope rule %s - %s", rule, e)
            return False

        invalid_keys = rewl.keys() - {
                "domain", "surt", "substring", "regex", "parent_url_regex"}
        if invalid_keys:
            self.logger.error(
                    "invalid keys %s in scope rule %s", invalid_keys, rule)
            return False

        if "domain" in rewl and not u.matches_ip_or_domain(rewl["domain"]):
            return False
        if "surt" in rewl and not u.surt.startswith(rewl["surt"]):
            return False
        if "substring" in rewl and not u.url.find(rewl["substring"]) >= 0:
            return False
        if "regex" in rewl:
            try:
                if not re.fullmatch(rewl["regex"], u.url):
                    return False
            except Exception as e:
                self.logger.error(
                        "caught exception matching against regex %s - %s",
                        rewl["regex"], e)
                return False
        if "parent_url_regex" in rewl:
            if not parent_page:
                return False
            pu = Url(parent_page.url)
            try:
                if not re.fullmatch(rule["parent_url_regex"], pu.url):
                    return False
            except Exception as e:
                self.logger.error(
                        "caught exception matching against regex %s - %s",
                        rule["parent_url_regex"], e)
                return False

        return True

class Page(brozzler.BaseDictable):
    def __init__(
            self, url, id=None, site_id=None, job_id=None, hops_from_seed=0,
            redirect_url=None, priority=None, claimed=False, brozzle_count=0,
            via_page_id=None, last_claimed_by=None, hops_off_surt=0,
            outlinks=None, needs_robots_check=False, blocked_by_robots=None):
        self.site_id = site_id
        self.job_id = job_id
        self.url = url
        self.hops_from_seed = hops_from_seed
        self.redirect_url = redirect_url
        self.claimed = bool(claimed)
        self.last_claimed_by = last_claimed_by
        self.brozzle_count = brozzle_count
        self.via_page_id = via_page_id
        self.hops_off_surt = hops_off_surt
        self.outlinks = outlinks
        self.needs_robots_check = needs_robots_check
        self.blocked_by_robots = blocked_by_robots
        self._canon_hurl = None

        if priority is not None:
            self.priority = priority
        else:
            self.priority = self._calc_priority()

        if id is not None:
            self.id = id
        else:
            digest_this = "site_id:{},url:{}".format(self.site_id, self.url)
            self.id = hashlib.sha1(digest_this.encode("utf-8")).hexdigest()

    def __repr__(self):
        return """Page(url={},job_id={},site_id={},hops_from_seed={})""".format(
                repr(self.url), self.job_id, self.site_id, self.hops_from_seed)

    def note_redirect(self, url):
        self.redirect_url = url

    def _calc_priority(self):
        priority = 0
        priority += max(0, 10 - self.hops_from_seed)
        priority += max(0, 6 - self.canon_url().count("/"))
        return priority

    def canon_url(self):
        if self._canon_hurl is None:
            self._canon_hurl = surt.handyurl.parse(self.url)
            surt.GoogleURLCanonicalizer.canonicalize(self._canon_hurl)
        return self._canon_hurl.geturl()

