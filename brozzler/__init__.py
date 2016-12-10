"""
brozzler/__init__.py - __init__.py for brozzler package, contains some common
code

Copyright (C) 2014-2016 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from pkg_resources import get_distribution as _get_distribution
__version__ = _get_distribution('brozzler').version

class ShutdownRequested(Exception):
    pass

class NothingToClaim(Exception):
    pass

class CrawlJobStopped(Exception):
    pass

class ReachedLimit(Exception):
    def __init__(self, http_error=None, warcprox_meta=None, http_payload=None):
        import json
        if http_error:
            if "warcprox-meta" in http_error.headers:
                self.warcprox_meta = json.loads(
                        http_error.headers["warcprox-meta"])
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

class BaseDictable:
    def to_dict(self):
        d = dict(vars(self))
        for k in vars(self):
            if k.startswith("_") or d[k] is None:
                del d[k]
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), separators=(',', ':'))

    def __repr__(self):
        return "{}(**{})".format(self.__class__.__name__, self.to_dict())

def fixup(url):
    '''
    Does rudimentary canonicalization, such as converting IDN to punycode.
    '''
    import surt
    hurl = _surt.handyurl.parse(url)
    # handyurl.parse() already lowercases the scheme via urlsplit
    if hurl.host:
        hurl.host = hurl.host.encode('idna').decode('ascii').lower()
    return hurl.getURLString()

# logging level more fine-grained than logging.DEBUG==10
TRACE = 5

_behaviors = None
def behaviors():
    import os, yaml, string
    global _behaviors
    if _behaviors is None:
        behaviors_yaml = os.path.join(
                os.path.dirname(__file__), 'behaviors.yaml')
        with open(behaviors_yaml) as fin:
            conf = yaml.load(fin)
        _behaviors = conf['behaviors']

        for behavior in _behaviors:
            if 'behavior_js' in behavior:
                behavior_js = os.path.join(
                        os.path.dirname(__file__), 'behaviors.d',
                        behavior['behavior_js'])
                with open(behavior_js, encoding='utf-8') as fin:
                    behavior['script'] = fin.read()
            elif 'behavior_js_template' in behavior:
                behavior_js_template = os.path.join(
                        os.path.dirname(__file__), 'behaviors.d',
                        behavior['behavior_js_template'])
                with open(behavior_js_template, encoding='utf-8') as fin:
                    behavior['template'] = string.Template(fin.read())

    return _behaviors

def behavior_script(url, template_parameters=None):
    '''
    Returns the javascript behavior string populated with template_parameters.
    '''
    import re, logging
    for behavior in behaviors():
        if re.match(behavior['url_regex'], url):
            if 'behavior_js' in behavior:
                logging.info(
                        'using behavior %s for %s',
                        behavior['behavior_js'], url)
            elif 'behavior_js_template' in behavior:
                parameters = dict()
                if 'default_parameters' in behavior:
                    parameters.update(behavior['default_parameters'])
                if template_parameters:
                    parameters.update(template_parameters)
                javascript = behavior['template'].safe_substitute(parameters)

                logging.info(
                        'using template=%s populated with parameters=%s for %s',
                        repr(behavior['behavior_js_template']), parameters, url)

            return behavior['script']

    return None

from brozzler.site import Page, Site
from brozzler.worker import BrozzlerWorker
from brozzler.robots import is_permitted_by_robots
from brozzler.frontier import RethinkDbFrontier
from brozzler.browser import Browser, BrowserPool
from brozzler.job import new_job, new_site, Job

