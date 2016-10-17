#!/usr/bin/env python
'''
brozzler-easy - brozzler-worker, warcprox, pywb, and brozzler-webconsole all
working together in a single process

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
    import warcprox
    import warcprox.main
    import pywb
    import brozzler.pywb
    import wsgiref.simple_server
    import wsgiref.handlers
    import brozzler.webconsole
except ImportError as e:
    logging.critical(
            '%s: %s\n\nYou might need to run "pip install '
            'brozzler[easy]".\nSee README.rst for more information.',
            type(e).__name__, e)
    sys.exit(1)
import argparse
import brozzler
import brozzler.cli
import os
import socket
import signal
import threading
import time
import rethinkstuff
import traceback
import socketserver

def _build_arg_parser(prog=os.path.basename(sys.argv[0])):
    arg_parser = argparse.ArgumentParser(
            prog=prog, formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description=(
                'brozzler-easy - easy deployment of brozzler, with '
                'brozzler-worker, warcprox, pywb, and brozzler-webconsole all '
                'running in a single process'))

    # common args
    arg_parser.add_argument(
            '--rethinkdb-servers', dest='rethinkdb_servers',
            default='localhost', help=(
                'rethinkdb servers, e.g. '
                'db0.foo.org,db0.foo.org:38015,db1.foo.org'))
    arg_parser.add_argument(
            '--rethinkdb-db', dest='rethinkdb_db', default='brozzler',
            help='rethinkdb database name')
    arg_parser.add_argument(
            '-d', '--warcs-dir', dest='warcs_dir', default='./warcs',
            help='where to write warcs')

    # warcprox args
    arg_parser.add_argument(
            '-c', '--cacert', dest='cacert',
            default='./%s-warcprox-ca.pem' % socket.gethostname(),
            help=(
                'warcprox CA certificate file; if file does not exist, it '
                'will be created'))
    arg_parser.add_argument(
            '--certs-dir', dest='certs_dir',
            default='./%s-warcprox-ca' % socket.gethostname(),
            help='where warcprox will store and load generated certificates')
    arg_parser.add_argument(
            '--onion-tor-socks-proxy', dest='onion_tor_socks_proxy',
            default=None, help=(
                'host:port of tor socks proxy, used only to connect to '
                '.onion sites'))

    # brozzler-worker args
    arg_parser.add_argument(
            '-e', '--chrome-exe', dest='chrome_exe',
            default=brozzler.cli.suggest_default_chrome_exe(),
            help='executable to use to invoke chrome')
    arg_parser.add_argument(
            '-n', '--max-browsers', dest='max_browsers',
            type=int, default=1, help=(
                'max number of chrome instances simultaneously '
                'browsing pages'))

    # pywb args
    arg_parser.add_argument(
            '--pywb-address', dest='pywb_address',
            default='0.0.0.0',
            help='pywb wayback address to listen on')
    arg_parser.add_argument(
            '--pywb-port', dest='pywb_port', type=int,
            default=8880, help='pywb wayback port')

    # webconsole args
    arg_parser.add_argument(
            '--webconsole-address', dest='webconsole_address',
            default='localhost',
            help='brozzler web console address to listen on')
    arg_parser.add_argument(
            '--webconsole-port', dest='webconsole_port',
            type=int, default=8881, help='brozzler web console port')

    # common at the bottom args
    arg_parser.add_argument(
            '-v', '--verbose', dest='verbose', action='store_true',
            help='verbose logging')
    arg_parser.add_argument(
            '-q', '--quiet', dest='quiet', action='store_true',
            help='quiet logging (warnings and errors only)')
    # arg_parser.add_argument(
    #         '-s', '--silent', dest='log_level', action='store_const',
    #         default=logging.INFO, const=logging.CRITICAL)
    arg_parser.add_argument(
            '--version', action='version',
            version='brozzler %s - %s' % (brozzler.__version__, prog))

    return arg_parser

class ThreadingWSGIServer(
        socketserver.ThreadingMixIn, wsgiref.simple_server.WSGIServer):
    pass

class BrozzlerEasyController:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, args):
        self.stop = threading.Event()
        self.args = args
        self.warcprox_controller = warcprox.main.init_controller(
                self._warcprox_args(args))
        self.brozzler_worker = self._init_brozzler_worker(args)
        self.pywb_httpd = self._init_pywb(args)
        self.webconsole_httpd = self._init_brozzler_webconsole(args)

    def _init_brozzler_webconsole(self, args):
        return wsgiref.simple_server.make_server(
                args.webconsole_address, args.webconsole_port,
                brozzler.webconsole.app, ThreadingWSGIServer)

    def _init_brozzler_worker(self, args):
        r = rethinkstuff.Rethinker(
                args.rethinkdb_servers.split(","), args.rethinkdb_db)
        frontier = brozzler.RethinkDbFrontier(r)
        service_registry = rethinkstuff.ServiceRegistry(r)
        worker = brozzler.worker.BrozzlerWorker(
                frontier, service_registry,
                max_browsers=args.max_browsers,
                chrome_exe=args.chrome_exe,
                proxy='%s:%s' % self.warcprox_controller.proxy.server_address,
                enable_warcprox_features=True)
        return worker

    def _init_pywb(self, args):
        brozzler.pywb.TheGoodUrlCanonicalizer.replace_default_canonicalizer()
        brozzler.pywb.TheGoodUrlCanonicalizer.monkey_patch_dsrules_init()
        brozzler.pywb.support_in_progress_warcs()

        if args.warcs_dir.endswith('/'):
            warcs_dir = args.warcs_dir
        else:
            warcs_dir = args.warcs_dir + '/'

        conf = {
            'collections': {
                'brozzler': {
                    'index_paths': brozzler.pywb.RethinkCDXSource(
                        servers=args.rethinkdb_servers.split(","),
                        db=args.rethinkdb_db, table='captures')
                },
            },
            # 'enable_http_proxy': True,
            # 'enable_memento': True,
            'archive_paths': warcs_dir,
            'enable_cdx_api': True,
            'framed_replay': True,
            'port': args.pywb_port,
            'enable_auto_colls': False,
        }
        wsgi_app = pywb.framework.wsgi_wrappers.init_app(
                pywb.webapp.pywb_init.create_wb_router, config=conf,
                load_yaml=False)

        # disable is_hop_by_hop restrictions
        wsgiref.handlers.is_hop_by_hop = lambda x: False
        return wsgiref.simple_server.make_server(
                args.pywb_address, args.pywb_port, wsgi_app,
                ThreadingWSGIServer)

    def start(self):
        self.logger.info('starting warcprox')
        self.warcprox_controller.start()

        # XXX wait til fully started?
        self.logger.info('starting brozzler-worker')
        self.brozzler_worker.start()

        self.logger.info(
                'starting pywb at %s:%s', *self.pywb_httpd.server_address)
        threading.Thread(target=self.pywb_httpd.serve_forever).start()

        self.logger.info(
                'starting brozzler-webconsole at %s:%s',
                *self.webconsole_httpd.server_address)
        threading.Thread(target=self.webconsole_httpd.serve_forever).start()

    def shutdown(self):
        self.logger.info('shutting down brozzler-webconsole')
        self.webconsole_httpd.shutdown()

        self.logger.info('shutting down brozzler-worker')
        self.brozzler_worker.shutdown_now()
        # brozzler-worker is fully shut down at this point

        self.logger.info('shutting down pywb')
        self.pywb_httpd.shutdown()

        self.logger.info('shutting down warcprox')
        self.warcprox_controller.shutdown()

    def wait_for_shutdown_request(self):
        try:
            while not self.stop.is_set():
                time.sleep(0.5)
        finally:
            self.shutdown()

    def _warcprox_args(self, args):
        '''
        Takes args as produced by the argument parser built by
        _build_arg_parser and builds warcprox arguments object suitable to pass
        to warcprox.main.init_controller. Copies some arguments, renames some,
        populates some with defaults appropriate for brozzler-easy, etc.
        '''
        warcprox_args = argparse.Namespace()
        warcprox_args.address = 'localhost'
        # let the OS choose an available port; discover it later using
        # sock.getsockname()[1]
        warcprox_args.port = 0
        warcprox_args.cacert = args.cacert
        warcprox_args.certs_dir = args.certs_dir
        warcprox_args.directory = args.warcs_dir
        warcprox_args.gzip = True
        warcprox_args.prefix = 'brozzler'
        warcprox_args.size = 1000 * 1000* 1000
        warcprox_args.rollover_idle_time = 3 * 60
        warcprox_args.digest_algorithm = 'sha1'
        warcprox_args.base32 = True
        warcprox_args.stats_db_file = None
        warcprox_args.playback_port = None
        warcprox_args.playback_index_db_file = None
        warcprox_args.rethinkdb_servers = args.rethinkdb_servers
        warcprox_args.rethinkdb_db = args.rethinkdb_db
        warcprox_args.rethinkdb_big_table = True
        warcprox_args.kafka_broker_list = None
        warcprox_args.kafka_capture_feed_topic = None
        warcprox_args.queue_size = 500
        warcprox_args.max_threads = None
        warcprox_args.profile = False
        warcprox_args.onion_tor_socks_proxy = args.onion_tor_socks_proxy
        return warcprox_args

    def dump_state(self, signum=None, frame=None):
        state_strs = []
        for th in threading.enumerate():
            state_strs.append(str(th))
            stack = traceback.format_stack(sys._current_frames()[th.ident])
            state_strs.append(''.join(stack))
        logging.warn('dumping state (caught signal {})\n{}'.format(
            signum, '\n'.join(state_strs)))

def main():
    arg_parser = _build_arg_parser()
    args = arg_parser.parse_args(args=sys.argv[1:])
    if args.verbose:
        loglevel = logging.DEBUG
    elif args.quiet:
        loglevel = logging.WARNING
    else:
        loglevel = logging.INFO

    logging.basicConfig(
            level=loglevel, stream=sys.stderr, format=(
                '%(asctime)s %(process)d %(levelname)s %(threadName)s '
                '%(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s'))

    controller = BrozzlerEasyController(args)
    signal.signal(signal.SIGTERM, lambda a,b: controller.stop.set())
    signal.signal(signal.SIGINT, lambda a,b: controller.stop.set())
    signal.signal(signal.SIGQUIT, controller.dump_state)
    controller.start()
    controller.wait_for_shutdown_request()
