#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import sys
import urllib.parse
import sortedcontainers

class CrawlUrl:
    def __init__(self, url, priority=1):
        self.url = url
        self.set_priority(priority)
        self._netloc = None

    def set_priority(self, priority):
        # priority_key is both a sortable priority (higher value is higher
        # priority) and a unique hash key
        self.priority_key = (priority << 32) | (hash(self.url) & (2**32 - 1))

    def get_priority(self):
        return self.priority >> 32

    @property
    def host(self):
        if self._netloc is None:
            self._netloc = urllib.parse.urlsplit(self.url)[1]
        return self._netloc

class Frontier:
    def __init__(self):
        # {url:CrawlUrl}
        self.urls = {} 
        
        # {host:SortedDict{priority_key:CrawlUrl}}
        self.queues_by_host = {}

    def schedule(self, crawl_url):
        try:
            old_priority_key = self.urls.pop(crawl_url.url).priority_key
            old_crawl_url = self.queues_by_host[crawl_url.host].pop(old_priority_key)

            # XXX very dumb calculation of new priority, probably doesn't belong here
            crawl_url.set_priority(crawl_url.get_priority() + old_crawl_url.get_priority())
        except KeyError:
            pass

        self.urls[crawl_url.url] = crawl_url
        if crawl_url.host not in self.queues_by_host:
            self.queues_by_host[crawl_url.host] = sortedcontainers.SortedDict()
        self.queues_by_host[crawl_url.host][crawl_url.priority_key] = crawl_url

    def pop(self, host=None):
        if not host or host not in self.queues_by_host:
            # XXX should prioritize queues, this picks one at random
            for h in self.queues_by_host:
                host = h
                break

        result = self.queues_by_host[host].popitem(last=True)[1]
        if len(self.queues_by_host[host]) == 0:
            del self.queues_by_host[host]

        result2 = self.urls.pop(result.url)
        assert result2 is result

        return result

