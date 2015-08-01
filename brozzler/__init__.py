import json as _json
from brozzler.browser import Browser, BrowserPool
from brozzler.site import Page, Site
from brozzler.hq import BrozzlerHQ
from brozzler.worker import BrozzlerWorker

def _read_version():
    import os
    version_txt = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['version.txt'])
    with open(version_txt, 'rb') as fin:
        version_bytes = fin.read()
        return version_bytes.strip().decode('utf-8')

version = _read_version()

class ShutdownRequested(Exception):
    pass

class ReachedLimit(Exception):
    def __init__(self, http_error):
        if "warcprox-meta" in http_error.headers:
            self.warcprox_meta = _json.loads(http_error.headers["warcprox-meta"])
        else:
            self.warcprox_meta = None
        self.http_payload = http_error.read()

    def __repr__(self):
        return "ReachedLimit(warcprox_meta={},http_payload={})".format(repr(self.warcprox_meta), repr(self.http_payload))

    def __str__(self):
        return self.__repr__()

# vim: set sw=4 et:
