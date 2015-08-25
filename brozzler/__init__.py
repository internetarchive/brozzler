import json as _json
import logging as _logging
from brozzler.site import Page, Site
from brozzler.worker import BrozzlerWorker
from brozzler.robots import is_permitted_by_robots
from brozzler.frontier import RethinkDbFrontier
from brozzler.browser import Browser, BrowserPool
from brozzler.job import new_job, new_site

def _read_version():
    import os
    version_txt = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['version.txt'])
    with open(version_txt, 'rb') as fin:
        version_bytes = fin.read()
        return version_bytes.strip().decode('utf-8')

version = _read_version()

# XXX don't know if these should be restricted; right now, only needed for
# rethinkdb "between" query
MAX_PRIORITY = 1000000000
MIN_PRIORITY = -1000000000

class ShutdownRequested(Exception):
    pass

class NothingToClaim(Exception):
    pass

class ReachedLimit(Exception):
    def __init__(self, http_error=None, warcprox_meta=None, http_payload=None):
        if http_error:
            if "warcprox-meta" in http_error.headers:
                self.warcprox_meta = _json.loads(http_error.headers["warcprox-meta"])
            else:
                self.warcprox_meta = None
            self.http_payload = http_error.read()
        elif warcprox_meta:
            self.warcprox_meta = warcprox_meta
            self.http_payload = http_payload

    def __repr__(self):
        return "ReachedLimit(warcprox_meta={},http_payload={})".format(repr(self.warcprox_meta), repr(self.http_payload))

    def __str__(self):
        return self.__repr__()

# vim: set sw=4 et:
