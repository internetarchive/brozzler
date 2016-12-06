'''
brozzler/chrome.py - manages the chrome/chromium browser for brozzler

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
'''

import logging
import urllib.request
import time
import threading
import subprocess
import os
import brozzler
import select
import re
import signal
import sqlite3
import datetime
import json

class Chrome:
    logger = logging.getLogger(__module__ + '.' + __qualname__)

    def __init__(
            self, port, executable, user_home_dir, user_data_dir, proxy=None,
            ignore_cert_errors=False):
        self.port = port
        self.executable = executable
        self.user_home_dir = user_home_dir
        self.user_data_dir = user_data_dir
        self.proxy = proxy
        self.ignore_cert_errors = ignore_cert_errors
        self._shutdown = threading.Event()

    def __enter__(self):
        '''
        Returns websocket url to chrome window with about:blank loaded.
        '''
        return self.start()

    def __exit__(self, *args):
        self.stop()

    def start(self):
        '''
        Returns websocket url to chrome window with about:blank loaded.
        '''
        timeout_sec = 600
        new_env = os.environ.copy()
        new_env['HOME'] = self.user_home_dir
        chrome_args = [
                self.executable, '--use-mock-keychain', # mac thing
                '--user-data-dir=%s' % self.user_data_dir,
                '--remote-debugging-port=%s' % self.port,
                '--disable-web-sockets', '--disable-cache',
                '--window-size=1100,900', '--no-default-browser-check',
                '--disable-first-run-ui', '--no-first-run',
                '--homepage=about:blank', '--disable-direct-npapi-requests',
                '--disable-web-security', '--disable-notifications',
                '--disable-extensions', '--disable-save-password-bubble']
        if self.ignore_cert_errors:
            chrome_args.append('--ignore-certificate-errors')
        if self.proxy:
            chrome_args.append('--proxy-server=%s' % self.proxy)
        chrome_args.append('about:blank')
        self.logger.info(
                'running: %s' % repr(subprocess.list2cmdline(chrome_args)))
        # start_new_session - new process group so we can kill the whole group
        self.chrome_process = subprocess.Popen(
                chrome_args, env=new_env, start_new_session=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self._out_reader_thread = threading.Thread(
                target=self._read_stderr_stdout,
                name='ChromeOutReaderThread(pid=%s)' % self.chrome_process.pid)
        self._out_reader_thread.start()
        self.logger.info('chrome running, pid %s' % self.chrome_process.pid)
        # make this a member variable so that kill -QUIT reports it
        self._start = time.time()

        json_url = 'http://localhost:%s/json' % self.port

        while True:
            try:
                raw_json = urllib.request.urlopen(json_url, timeout=30).read()
                all_debug_info = json.loads(raw_json.decode('utf-8'))
                debug_info = [x for x in all_debug_info
                              if x['url'] == 'about:blank']

                if debug_info and 'webSocketDebuggerUrl' in debug_info[0]:
                    self.logger.debug('%s returned %s', json_url, raw_json)
                    url = debug_info[0]['webSocketDebuggerUrl']
                    self.logger.info(
                            'got chrome window websocket debug url %s from %s',
                            url, json_url)
                    return url
            except BaseException as e:
                if int(time.time() - self._start) % 10 == 5:
                    self.logger.warn(
                            'problem with %s (will keep trying until timeout '
                            'of %d seconds): %s', json_url, timeout_sec, e)
                pass
            finally:
                if time.time() - self._start > timeout_sec:
                    self.logger.error(
                            'killing chrome, failed to retrieve %s after %s '
                            'seconds', json_url, time.time() - self._start)
                    self.stop()
                    raise Exception(
                            'killed chrome, failed to retrieve %s after %s '
                            'seconds' % (json_url, time.time() - self._start))
                else:
                    time.sleep(0.5)

    def _read_stderr_stdout(self):
        # XXX select doesn't work on windows
        def readline_nonblock(f):
            buf = b''
            while not self._shutdown.is_set() and (
                    len(buf) == 0 or buf[-1] != 0xa) and select.select(
                            [f],[],[],0.5)[0]:
                buf += f.read(1)
            return buf

        try:
            while not self._shutdown.is_set():
                buf = readline_nonblock(self.chrome_process.stdout)
                if buf:
                    if re.search(
                            b'Xlib:  extension|'
                            b'CERT_PKIXVerifyCert for [^ ]* failed|'
                            b'^ALSA lib|ERROR:gl_surface_glx.cc|'
                            b'ERROR:gpu_child_thread.cc', buf):
                        logging.log(
                                brozzler.TRACE, 'chrome pid %s STDOUT %s',
                                self.chrome_process.pid, buf)
                    else:
                        logging.debug(
                                'chrome pid %s STDOUT %s',
                                self.chrome_process.pid, buf)

                buf = readline_nonblock(self.chrome_process.stderr)
                if buf:
                    if re.search(
                            b'Xlib:  extension|'
                            b'CERT_PKIXVerifyCert for [^ ]* failed|'
                            b'^ALSA lib|ERROR:gl_surface_glx.cc|'
                            b'ERROR:gpu_child_thread.cc', buf):
                        logging.log(
                                brozzler.TRACE, 'chrome pid %s STDOUT %s',
                                self.chrome_process.pid, buf)
                    else:
                        logging.debug(
                                'chrome pid %s STDERR %s',
                                self.chrome_process.pid, buf)
        except:
            logging.error('unexpected exception', exc_info=True)

    def stop(self):
        if not self.chrome_process or self._shutdown.is_set():
            return

        timeout_sec = 300
        self._shutdown.set()
        self.logger.info('terminating chrome pgid %s' % self.chrome_process.pid)

        os.killpg(self.chrome_process.pid, signal.SIGTERM)
        first_sigterm = time.time()

        try:
            while time.time() - first_sigterm < timeout_sec:
                time.sleep(0.5)

                status = self.chrome_process.poll()
                if status is not None:
                    if status == 0:
                        self.logger.info(
                                'chrome pid %s exited normally',
                                self.chrome_process.pid)
                    else:
                        self.logger.warn(
                                'chrome pid %s exited with nonzero status %s',
                                self.chrome_process.pid, status)

                    # XXX I would like to forcefully kill the process group
                    # here to guarantee no orphaned chromium subprocesses hang
                    # around, but there's a chance I suppose that some other
                    # process could have started with the same pgid
                    return

            self.logger.warn(
                    'chrome pid %s still alive %.1f seconds after sending '
                    'SIGTERM, sending SIGKILL', self.chrome_process.pid,
                    time.time() - first_sigterm)
            os.killpg(self.chrome_process.pid, signal.SIGKILL)
            status = self.chrome_process.wait()
            self.logger.warn(
                    'chrome pid %s reaped (status=%s) after killing with '
                    'SIGKILL', self.chrome_process.pid, status)
        finally:
            self._out_reader_thread.join()
            self.chrome_process = None
