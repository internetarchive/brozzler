'''
brozzler/pywb.py - pywb customizations for brozzler including rethinkdb index,
loading from warcs still being written to, and canonicalization rules matching
brozzler conventions

Copyright (C) 2016 Internet Archive

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

import sys
import logging
try:
    import pywb.apps.cli
    import pywb.cdx.cdxdomainspecific
    import pywb.cdx.cdxobject
    import pywb.cdx.cdxserver
    import pywb.webapp.query_handler
except ImportError as e:
    logging.critical(
            '%s: %s\n\nYou might need to run "pip install '
            'brozzler[easy]".\nSee README.rst for more information.',
            type(e).__name__, e)
    sys.exit(1)
import rethinkstuff
import rethinkdb
import surt
import json
import brozzler

class RethinkCDXSource(pywb.cdx.cdxsource.CDXSource):
    def __init__(self, servers, db, table):
        self.servers = servers
        self.db = db
        self.table = table

    @property
    def r(self):
        try:
            return self._r
        except AttributeError:
            self._r = rethinkstuff.Rethinker(self.servers, self.db)
            return self._r

    def load_cdx(self, cdx_query):
        # logging.debug('vars(cdx_query)=%s', vars(cdx_query))
        rethink_results = self._query_rethinkdb(cdx_query)
        return self._gen_cdx_lines(rethink_results)

    def _gen_cdx_lines(self, rethink_results):
        for record in rethink_results:
            # XXX inefficient, it gets parsed later, figure out how to
            # short-circuit this step and create the CDXObject directly
            blob = {
                'url': record['url'],
                'mime': record['content_type'],
                'status': str(record['response_code']),
                'digest': record['sha1base32'],
                'length': str(record['length']), # XXX is this the right length?
                'offset': str(record['offset']),
                'filename': record['filename'],
            }
            # b'org,archive)/ 20160427215530 {"url": "https://archive.org/", "mime": "text/html", "status": "200", "digest": "VILUFXZD232SLUA6XROZQIMEVUPW6EIE", "length": "16001", "offset": "90144", "filename": "ARCHIVEIT-261-ONE_TIME-JOB209607-20160427215508135-00000.warc.gz"}'
            cdx_line = '{} {:%Y%m%d%H%M%S} {}'.format(
                    record['canon_surt'], record['timestamp'],
                    json.dumps(blob))
            yield cdx_line.encode('utf-8')

    def _query_rethinkdb(self, cdx_query):
        start_key = cdx_query.key.decode('utf-8')
        end_key = cdx_query.end_key.decode('utf-8')
        reql = self.r.table(self.table).between(
                [start_key[:150], rethinkdb.minval],
                [end_key[:150]+'!', rethinkdb.maxval],
                index='abbr_canon_surt_timestamp')
        reql = reql.order_by(index='abbr_canon_surt_timestamp')

        # filters have to come after order_by apparently

        # TODO support for POST, etc
        # http_method='WARCPROX_WRITE_RECORD' for screenshots, thumbnails
        reql = reql.filter(
                lambda capture: rethinkdb.expr(
                    ['WARCPROX_WRITE_RECORD','GET']).contains(
                        capture['http_method']))
        reql = reql.filter(
                lambda capture: (capture['canon_surt'] >= start_key)
                                 & (capture['canon_surt'] < end_key))

        if cdx_query.limit:
            reql = reql.limit(cdx_query.limit)

        logging.debug('rethinkdb query: %s', reql)
        results = reql.run()
        return results

class TheGoodUrlCanonicalizer(object):
    '''
    Replacement for pywb.utils.canonicalize.UrlCanonicalizer that produces
    surts with scheme and with trailing comma, and does not "massage"
    www.foo.org into foo.org.
    '''
    def __init__(self, surt_ordered=True):
        '''We are always surt ordered (surt_ordered param is ignored)'''
        self.surt_ordered = True

    def __call__(self, url):
        try:
            key = surt.surt(
                    url, trailing_comma=True, host_massage=False,
                    with_scheme=True)
            # logging.debug('%s -> %s', url, key)
            return key
        except Exception as e:
            raise pywb.utils.canonicalize.UrlCanonicalizeException(
                    'Invalid Url: ' + url)

    def replace_default_canonicalizer():
        '''Replace parent class of CustomUrlCanonicalizer with this class.'''
        pywb.cdx.cdxdomainspecific.CustomUrlCanonicalizer.__bases__ = (
                TheGoodUrlCanonicalizer,)

    def good_surts_from_default(default_surt):
        '''
        Takes a standard surt without scheme and without trailing comma, and
        returns a list of "good" surts that together match the same set of
        urls. For example:

             good_surts_from_default('com,example)/path')

        returns

            ['http://(com,example,)/path',
             'https://(com,example,)/path',
             'http://(com,example,www,)/path',
             'https://(com,example,www,)/path']

        '''
        if default_surt == '':
            return ['']

        parts = default_surt.split(')', 1)
        if len(parts) == 2:
            orig_host_part, path_part = parts
            good_surts = [
                'http://(%s,)%s' % (orig_host_part, path_part),
                'https://(%s,)%s' % (orig_host_part, path_part),
                'http://(%s,www,)%s' % (orig_host_part, path_part),
                'https://(%s,www,)%s' % (orig_host_part, path_part),
            ]
        else: # no path part
            host_part = parts[0]
            good_surts = [
                'http://(%s' % host_part,
                'https://(%s' % host_part,
            ]
        return good_surts

    def monkey_patch_dsrules_init():
        orig_init = pywb.cdx.cdxdomainspecific.CDXDomainSpecificRule.__init__
        def cdx_dsrule_init(self, url_prefix, rules):
            orig_init(self, url_prefix, rules)
            good_surts = []
            for url_prefix in self.url_prefix:
                good_surts.extend(
                        TheGoodUrlCanonicalizer.good_surts_from_default(
                                url_prefix))
            self.url_prefix = good_surts
        pywb.cdx.cdxdomainspecific.CDXDomainSpecificRule.__init__ = cdx_dsrule_init

def support_in_progress_warcs():
    '''
    Monkey-patch pywb.warc.pathresolvers.PrefixResolver to include warcs still
    being written to (warcs having ".open" suffix). This way if a cdx entry
    references foo.warc.gz, pywb will try both foo.warc.gz and
    foo.warc.gz.open.
    '''
    _orig_prefix_resolver_call = pywb.warc.pathresolvers.PrefixResolver.__call__
    def _prefix_resolver_call(self, filename, cdx=None):
        raw_results = _orig_prefix_resolver_call(self, filename, cdx)
        results = []
        for warc_path in raw_results:
            results.append(warc_path)
            results.append('%s.open' % warc_path)
        return results
    pywb.warc.pathresolvers.PrefixResolver.__call__ = _prefix_resolver_call

def main(argv=sys.argv):
    brozzler.pywb.TheGoodUrlCanonicalizer.replace_default_canonicalizer()
    brozzler.pywb.TheGoodUrlCanonicalizer.monkey_patch_dsrules_init()
    brozzler.pywb.support_in_progress_warcs()
    wayback_cli = pywb.apps.cli.WaybackCli(
            args=argv[1:], default_port=8880,
            desc=('brozzler-wayback - pywb wayback (monkey-patched for use '
                  'with brozzler)'))
    wayback_cli.run()
