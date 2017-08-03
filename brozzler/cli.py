#!/usr/bin/env python
'''
brozzler/cli.py - brozzler command line executables

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

import argparse
import brozzler
import brozzler.worker
import datetime
import json
import logging
import os
import re
import requests
import doublethink
import signal
import string
import sys
import threading
import time
import traceback
import warnings
import yaml
import shutil
import base64
import rethinkdb as r

def add_common_options(arg_parser, argv=None):
    argv = argv or sys.argv
    arg_parser.add_argument(
            '-q', '--quiet', dest='log_level', action='store_const',
            default=logging.INFO, const=logging.WARN, help=(
                'quiet logging, only warnings and errors'))
    arg_parser.add_argument(
            '-v', '--verbose', dest='log_level', action='store_const',
            default=logging.INFO, const=logging.DEBUG, help=(
                'verbose logging'))
    arg_parser.add_argument(
            '--trace', dest='log_level', action='store_const',
            default=logging.INFO, const=brozzler.TRACE, help=(
                'very verbose logging'))
    # arg_parser.add_argument(
    #         '-s', '--silent', dest='log_level', action='store_const',
    #         default=logging.INFO, const=logging.CRITICAL)
    arg_parser.add_argument(
            '--version', action='version',
            version='brozzler %s - %s' % (
                brozzler.__version__, os.path.basename(argv[0])))

def add_rethinkdb_options(arg_parser):
    arg_parser.add_argument(
            '--rethinkdb-servers', dest='rethinkdb_servers',
            default=os.environ.get('BROZZLER_RETHINKDB_SERVERS', 'localhost'),
            help=(
                'rethinkdb servers, e.g. '
                'db0.foo.org,db0.foo.org:38015,db1.foo.org (default is the '
                'value of environment variable BROZZLER_RETHINKDB_SERVERS)'))
    arg_parser.add_argument(
            '--rethinkdb-db', dest='rethinkdb_db',
            default=os.environ.get('BROZZLER_RETHINKDB_DB', 'brozzler'),
            help=(
                'rethinkdb database name (default is the value of environment '
                'variable BROZZLER_RETHINKDB_DB)'))

def rethinker(args):
    servers = args.rethinkdb_servers or 'localhost'
    db = args.rethinkdb_db or os.environ.get(
            'BROZZLER_RETHINKDB_DB') or 'brozzler'
    return doublethink.Rethinker(servers.split(','), db)

def configure_logging(args):
    logging.basicConfig(
            stream=sys.stderr, level=args.log_level, format=(
                '%(asctime)s %(process)d %(levelname)s %(threadName)s '
                '%(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s'))
    logging.getLogger('requests.packages.urllib3').setLevel(logging.WARN)
    warnings.simplefilter(
            'ignore', category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
    warnings.simplefilter(
            'ignore', category=requests.packages.urllib3.exceptions.InsecurePlatformWarning)

def suggest_default_chrome_exe():
    # mac os x application executable paths
    for path in [
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']:
        if os.path.exists(path):
            return path

    # "chromium-browser" is the executable on ubuntu trusty
    # https://github.com/internetarchive/brozzler/pull/6/files uses "chromium"
    # google chrome executable names taken from these packages:
    # http://www.ubuntuupdates.org/ppa/google_chrome
    for exe in [
            'chromium-browser', 'chromium', 'google-chrome',
            'google-chrome-stable', 'google-chrome-beta',
            'google-chrome-unstable']:
        if shutil.which(exe):
            return exe
    return 'chromium-browser'

class BetterArgumentDefaultsHelpFormatter(
        argparse.ArgumentDefaultsHelpFormatter):
    '''
    Like argparse.ArgumentDefaultsHelpFormatter but omits the default value
    for arguments with action='store_const'.
    '''
    def _get_help_string(self, action):
        if isinstance(action, argparse._StoreConstAction):
            return action.help
        else:
            return super()._get_help_string(action)

def brozzle_page(argv=None):
    '''
    Command line utility entry point for brozzling a single page. Opens url in
    a browser, running some javascript behaviors, and prints outlinks.
    '''
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            description='brozzle-page - brozzle a single page',
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument('url', metavar='URL', help='page url')
    arg_parser.add_argument(
            '-e', '--chrome-exe', dest='chrome_exe',
            default=suggest_default_chrome_exe(),
            help='executable to use to invoke chrome')
    arg_parser.add_argument(
            '--behavior-parameters', dest='behavior_parameters',
            default=None, help=(
                'json blob of parameters to populate the javascript behavior '
                'template, e.g. {"parameter_username":"x",'
                '"parameter_password":"y"}'))
    arg_parser.add_argument(
            '--username', dest='username', default=None,
            help='use this username to try to log in if a login form is found')
    arg_parser.add_argument(
            '--password', dest='password', default=None,
            help='use this password to try to log in if a login form is found')
    arg_parser.add_argument(
            '--proxy', dest='proxy', default=None, help='http proxy')
    arg_parser.add_argument(
            '--skip-extract-outlinks', dest='skip_extract_outlinks',
            action='store_true', help=argparse.SUPPRESS)
    arg_parser.add_argument(
            '--skip-visit-hashtags', dest='skip_visit_hashtags',
            action='store_true', help=argparse.SUPPRESS)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    behavior_parameters = {}
    if args.behavior_parameters:
        behavior_parameters = json.loads(args.behavior_parameters)
    site = brozzler.Site(None, {
        'id': -1, 'seed': args.url, 'behavior_parameters': behavior_parameters,
        'username': args.username, 'password': args.password})
    page = brozzler.Page(None, {'url': args.url, 'site_id': site.id})
    worker = brozzler.BrozzlerWorker(frontier=None, proxy=args.proxy,
        skip_extract_outlinks=args.skip_extract_outlinks,
        skip_visit_hashtags=args.skip_visit_hashtags)

    def on_screenshot(screenshot_png):
        OK_CHARS = (string.ascii_letters + string.digits)
        filename = '/tmp/{}-{:%Y%m%d%H%M%S}.png'.format(
                ''.join(ch if ch in OK_CHARS else '_' for ch in args.url),
                datetime.datetime.now())
        # logging.info('len(screenshot_png)=%s', len(screenshot_png))
        with open(filename, 'wb') as f:
            f.write(screenshot_png)
        logging.info('wrote screenshot to %s', filename)

    browser = brozzler.Browser(chrome_exe=args.chrome_exe)
    try:
        browser.start(proxy=args.proxy)
        worker.brozzle_page(browser, site, page, on_screenshot=on_screenshot)
    except brozzler.ReachedLimit as e:
        logging.error('reached limit %s', e)
    finally:
        browser.stop()

def brozzler_new_job(argv=None):
    '''
    Command line utility entry point for queuing a new brozzler job. Takes a
    yaml brozzler job configuration file, creates job, sites, and pages objects
    in rethinkdb, which brozzler-workers will look at and start crawling.
    '''
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            description='brozzler-new-job - queue new job with brozzler',
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument(
            'job_conf_file', metavar='JOB_CONF_FILE',
            help='brozzler job configuration file in yaml')
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)
    frontier = brozzler.RethinkDbFrontier(rr)
    try:
        brozzler.new_job_file(frontier, args.job_conf_file)
    except brozzler.InvalidJobConf as e:
        print('brozzler-new-job: invalid job file:', args.job_conf_file, file=sys.stderr)
        print('  ' + yaml.dump(e.errors).rstrip().replace('\n', '\n  '), file=sys.stderr)
        sys.exit(1)

def brozzler_new_site(argv=None):
    '''
    Command line utility entry point for queuing a new brozzler site.
    Takes a seed url and creates a site and page object in rethinkdb, which
    brozzler-workers will look at and start crawling.
    '''
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            description='brozzler-new-site - register site to brozzle',
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument('seed', metavar='SEED', help='seed url')
    add_rethinkdb_options(arg_parser)
    arg_parser.add_argument(
            '--time-limit', dest='time_limit', default=None,
            help='time limit in seconds for this site')
    arg_parser.add_argument(
            '--ignore-robots', dest='ignore_robots', action='store_true',
            help='ignore robots.txt for this site')
    arg_parser.add_argument(
            '--warcprox-meta', dest='warcprox_meta',
            help=(
                'Warcprox-Meta http request header to send with each request; '
                'must be a json blob, ignored unless warcprox features are '
                'enabled'))
    arg_parser.add_argument(
            '--behavior-parameters', dest='behavior_parameters',
            default=None, help=(
                'json blob of parameters to populate the javascript behavior '
                'template, e.g. {"parameter_username":"x",'
                '"parameter_password":"y"}'))
    arg_parser.add_argument(
            '--username', dest='username', default=None,
            help='use this username to try to log in if a login form is found')
    arg_parser.add_argument(
            '--password', dest='password', default=None,
            help='use this password to try to log in if a login form is found')
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)
    site = brozzler.Site(rr, {
        'seed': args.seed,
        'time_limit': int(args.time_limit) if args.time_limit else None,
        'ignore_robots': args.ignore_robots,
        'warcprox_meta': json.loads(
            args.warcprox_meta) if args.warcprox_meta else None,
        'behavior_parameters': json.loads(
            args.behavior_parameters) if args.behavior_parameters else None,
        'username': args.username,
        'password': args.password})

    frontier = brozzler.RethinkDbFrontier(rr)
    brozzler.new_site(frontier, site)

def brozzler_worker(argv=None):
    '''
    Main entry point for brozzler, gets sites and pages to brozzle from
    rethinkdb, brozzles them.
    '''
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    add_rethinkdb_options(arg_parser)
    arg_parser.add_argument(
            '-e', '--chrome-exe', dest='chrome_exe',
            default=suggest_default_chrome_exe(),
            help='executable to use to invoke chrome')
    arg_parser.add_argument(
            '-n', '--max-browsers', dest='max_browsers', default='1',
            help='max number of chrome instances simultaneously browsing pages')
    arg_parser.add_argument(
            '--proxy', dest='proxy', default=None, help='http proxy')
    arg_parser.add_argument(
            '--warcprox-auto', dest='warcprox_auto', action='store_true',
            help=(
                'when needed, choose an available instance of warcprox from '
                'the rethinkdb service registry'))
    arg_parser.add_argument(
            '--skip-extract-outlinks', dest='skip_extract_outlinks',
            action='store_true', help=argparse.SUPPRESS)
    arg_parser.add_argument(
            '--skip-visit-hashtags', dest='skip_visit_hashtags',
            action='store_true', help=argparse.SUPPRESS)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    def dump_state(signum, frame):
        signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        try:
            state_strs = []
            frames = sys._current_frames()
            threads = {th.ident: th for th in threading.enumerate()}
            for ident in frames:
                if threads[ident]:
                    state_strs.append(str(threads[ident]))
                else:
                    state_strs.append('<???:thread:ident=%s>' % ident)
                stack = traceback.format_stack(frames[ident])
                state_strs.append(''.join(stack))
            logging.info(
                    'dumping state (caught signal %s)\n%s' % (
                        signum, '\n'.join(state_strs)))
        except BaseException as e:
            logging.error('exception dumping state: %s' % e)
        finally:
            signal.signal(signal.SIGQUIT, dump_state)

    rr = rethinker(args)
    frontier = brozzler.RethinkDbFrontier(rr)
    service_registry = doublethink.ServiceRegistry(rr)
    worker = brozzler.worker.BrozzlerWorker(
            frontier, service_registry, max_browsers=int(args.max_browsers),
            chrome_exe=args.chrome_exe, proxy=args.proxy,
            warcprox_auto=args.warcprox_auto,
            skip_extract_outlinks=args.skip_extract_outlinks,
            skip_visit_hashtags=args.skip_visit_hashtags)

    signal.signal(signal.SIGQUIT, dump_state)
    signal.signal(signal.SIGTERM, lambda s,f: worker.stop())
    signal.signal(signal.SIGINT, lambda s,f: worker.stop())

    th = threading.Thread(target=worker.run, name='BrozzlerWorkerThread')
    th.start()
    th.join()
    logging.info('brozzler-worker is all done, exiting')

def brozzler_ensure_tables(argv=None):
    '''
    Creates rethinkdb tables if they don't already exist. Brozzler
    (brozzler-worker, brozzler-new-job, etc) normally creates the tables it
    needs on demand at startup, but if multiple instances are starting up at
    the same time, you can end up with duplicate broken tables. So it's a good
    idea to use this utility at an early step when spinning up a cluster.
    '''
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)

    # services table
    doublethink.ServiceRegistry(rr)

    # sites, pages, jobs tables
    brozzler.frontier.RethinkDbFrontier(rr)

class Jsonner(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        elif isinstance(o, bytes):
            return base64.b64encode(o).decode('ascii')
        else:
            return json.JSONEncoder.default(self, o)

def brozzler_list_jobs(argv=None):
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument(
            '--yaml', dest='yaml', action='store_true', help=(
                'yaml output (default is json)'))
    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
            '--active', dest='active', action='store_true', help=(
                'list active jobs'))
    group.add_argument(
            '--all', dest='all', action='store_true', help=(
                'list all jobs'))
    group.add_argument(
            '--job', dest='job', metavar='JOB_ID', help=(
                'list only the specified job'))
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)
    if args.job is not None:
        try:
            job_id = int(args.job)
        except ValueError:
            job_id = args.job
        reql = rr.table('jobs').get(job_id)
        logging.debug('querying rethinkdb: %s', reql)
        result = reql.run()
        if result:
            results = [reql.run()]
        else:
            logging.error('no such job with id %r', job_id)
            sys.exit(1)
    else:
        reql = rr.table('jobs').order_by('id')
        if args.active:
            reql = reql.filter({'status': 'ACTIVE'})
        logging.debug('querying rethinkdb: %s', reql)
        results = reql.run()
    if args.yaml:
        yaml.dump_all(
                results, stream=sys.stdout, explicit_start=True,
                default_flow_style=False)
    else:
        for result in results:
            print(json.dumps(result, cls=Jsonner, indent=2))

def brozzler_list_sites(argv=None):
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument(
            '--yaml', dest='yaml', action='store_true', help=(
                'yaml output (default is json)'))
    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
            '--active', dest='active', action='store_true', help=(
                'list all active sites'))
    group.add_argument(
            '--job', dest='job', metavar='JOB_ID', help=(
                'list sites for a particular job'))
    group.add_argument(
            '--jobless', dest='jobless', action='store_true', help=(
                'list all jobless sites'))
    group.add_argument(
            '--site', dest='site', metavar='SITE_ID', help=(
                'list only the specified site'))
    group.add_argument(
            '--all', dest='all', action='store_true', help=(
                'list all sites'))
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)

    reql = rr.table('sites')
    if args.job:
        try:
            job_id = int(args.job)
        except ValueError:
            job_id = args.job
        reql = reql.get_all(job_id, index='job_id')
    elif args.jobless:
        reql = reql.filter(~r.row.has_fields('job_id'))
    elif args.active:
        reql = reql.between(
                ['ACTIVE', r.minval], ['ACTIVE', r.maxval],
                index='sites_last_disclaimed')
    logging.debug('querying rethinkdb: %s', reql)
    results = reql.run()
    if args.yaml:
        yaml.dump_all(
                results, stream=sys.stdout, explicit_start=True,
                default_flow_style=False)
    else:
        for result in results:
            print(json.dumps(result, cls=Jsonner, indent=2))

def brozzler_list_pages(argv=None):
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument(
            '--yaml', dest='yaml', action='store_true', help=(
                'yaml output (default is json)'))
    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
            '--job', dest='job', metavar='JOB_ID', help=(
                'list pages for all sites of a particular job'))
    group.add_argument(
            '--site', dest='site', metavar='SITE_ID', help=(
                'list pages for the specified site'))
    # group.add_argument(
    #         '--page', dest='page', metavar='PAGE_ID', help=(
    #             'list only the specified page'))
    group = arg_parser.add_mutually_exclusive_group()
    group.add_argument(
            '--queued', dest='queued', action='store_true', help=(
                'limit to queued pages'))
    group.add_argument(
            '--brozzled', dest='brozzled', action='store_true', help=(
                'limit to pages that have already been brozzled'))
    group.add_argument(
            '--claimed', dest='claimed', action='store_true', help=(
                'limit to pages that are currently claimed by a brozzler '
                'worker'))
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)
    if args.job:
        try:
            job_id = int(args.job)
        except ValueError:
            job_id = args.job
        reql = rr.table('sites').get_all(job_id, index='job_id')['id']
        logging.debug('querying rethinkb: %s', reql)
        site_ids = reql.run()
    elif args.site:
        try:
            site_ids = [int(args.site)]
        except ValueError:
            site_ids = [args.site]

    for site_id in site_ids:
        reql = rr.table('pages')
        if args.queued:
            reql = reql.between(
                    [site_id, 0, r.minval], [site_id, 0, r.maxval],
                    index='least_hops')
        elif args.brozzled:
            reql = reql.between(
                    [site_id, 1, r.minval], [site_id, r.maxval, r.maxval],
                    index='least_hops')
        else:
            reql = reql.between(
                    [site_id, 0, r.minval], [site_id, r.maxval, r.maxval],
                    index='least_hops')
        reql = reql.order_by(index="least_hops")
        if args.claimed:
            reql = reql.filter({'claimed': True})
        logging.debug('querying rethinkb: %s', reql)
        results = reql.run()
        if args.yaml:
            yaml.dump_all(
                    results, stream=sys.stdout, explicit_start=True,
                    default_flow_style=False)
        else:
            for result in results:
                print(json.dumps(result, cls=Jsonner, indent=2))

def brozzler_list_captures(argv=None):
    '''
    Handy utility for looking up entries in the rethinkdb "captures" table by
    url or sha1.
    '''
    import urlcanon

    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    arg_parser.add_argument(
            '-p', '--prefix', dest='prefix', action='store_true', help=(
                'use prefix match for url (n.b. may not work as expected if '
                'searching key has query string because canonicalization can '
                'reorder query parameters)'))
    arg_parser.add_argument(
            '--yaml', dest='yaml', action='store_true', help=(
                'yaml output (default is json)'))
    add_rethinkdb_options(arg_parser)
    add_common_options(arg_parser, argv)
    arg_parser.add_argument(
            'url_or_sha1', metavar='URL_or_SHA1',
            help='url or sha1 to look up in captures table')

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)

    if args.url_or_sha1[:5] == 'sha1:':
        if args.prefix:
            logging.warn(
                    'ignoring supplied --prefix option which does not apply '
                    'to lookup by sha1')
        # assumes it's already base32 (XXX could detect if hex and convert)
        sha1base32 = args.url_or_sha1[5:].upper()
        reql = rr.table('captures').between(
                [sha1base32, r.minval, r.minval],
                [sha1base32, r.maxval, r.maxval],
                index='sha1_warc_type')
        logging.debug('querying rethinkdb: %s', reql)
        results = reql.run()
    else:
        key = urlcanon.semantic(args.url_or_sha1).surt().decode('ascii')
        abbr_start_key = key[:150]
        if args.prefix:
            # surt is necessarily ascii and \x7f is the last ascii character
            abbr_end_key = key[:150] + '\x7f'
            end_key = key + '\x7f'
        else:
            abbr_end_key = key[:150]
            end_key = key
        reql = rr.table('captures').between(
                [abbr_start_key, r.minval],
                [abbr_end_key, r.maxval],
                index='abbr_canon_surt_timestamp', right_bound='closed')
        reql = reql.order_by(index='abbr_canon_surt_timestamp')
        reql = reql.filter(
                lambda capture: (capture['canon_surt'] >= key)
                                 & (capture['canon_surt'] <= end_key))
        logging.debug('querying rethinkdb: %s', reql)
        results = reql.run()

    if args.yaml:
        yaml.dump_all(
                results, stream=sys.stdout, explicit_start=True,
                default_flow_style=False)
    else:
        for result in results:
            print(json.dumps(result, cls=Jsonner, indent=2))

def brozzler_stop_crawl(argv=None):
    argv = argv or sys.argv
    arg_parser = argparse.ArgumentParser(
            prog=os.path.basename(argv[0]),
            formatter_class=BetterArgumentDefaultsHelpFormatter)
    group = arg_parser.add_mutually_exclusive_group(required=True)
    add_rethinkdb_options(arg_parser)
    group.add_argument(
            '--job', dest='job_id', metavar='JOB_ID', help=(
                'request crawl stop for the specified job'))
    group.add_argument(
            '--site', dest='site_id', metavar='SITE_ID', help=(
                'request crawl stop for the specified site'))
    add_common_options(arg_parser, argv)

    args = arg_parser.parse_args(args=argv[1:])
    configure_logging(args)

    rr = rethinker(args)
    if args.job_id:
        try:
            job_id = int(args.job_id)
        except ValueError:
            job_id = args.job_id
        job = brozzler.Job.load(rr, job_id)
        if not job:
            logging.fatal('job not found with id=%r', job_id)
            sys.exit(1)
        job.stop_requested = doublethink.utcnow()
        job.save()
    elif args.site_id:
        try:
            site_id = int(args.site_id)
        except ValueError:
            site_id = args.site_id
        site = brozzler.Site.load(rr, site_id)
        if not site:
            logging.fatal('site not found with id=%r', site_id)
            sys.exit(1)
        site.stop_requested = doublethink.utcnow()
        site.save()

