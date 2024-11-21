"""
brozzler/chrome.py - manages the chrome/chromium browser for brozzler

Copyright (C) 2014-2023 Internet Archive

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
import json
import tempfile
import sys


def check_version(chrome_exe):
    """
    Raises SystemExit if `chrome_exe` is not a supported browser version.

    Must run in the main thread to have the desired effect.
    """
    # mac$ /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
    # Google Chrome 64.0.3282.140
    # mac$ /Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary --version
    # Google Chrome 66.0.3341.0 canary
    # linux$ chromium-browser --version
    # Using PPAPI flash.
    #  --ppapi-flash-path=/usr/lib/adobe-flashplugin/libpepflashplayer.so --ppapi-flash-version=
    # Chromium 61.0.3163.100 Built on Ubuntu , running on Ubuntu 16.04
    cmd = [chrome_exe, "--version"]
    out = subprocess.check_output(cmd, timeout=60)
    m = re.search(rb"(Chromium|Google Chrome) ([\d.]+)", out)
    if not m:
        sys.exit(
            "unable to parse browser version from output of "
            "%r: %r" % (subprocess.list2cmdline(cmd), out)
        )
    version_str = m.group(2).decode()
    major_version = int(version_str.split(".")[0])
    if major_version < 64:
        sys.exit(
            "brozzler requires chrome/chromium version 64 or "
            "later but %s reports version %s" % (chrome_exe, version_str)
        )
    return major_version


class Chrome:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, chrome_exe, port=9222, ignore_cert_errors=False):
        """
        Initializes instance of this class.

        Doesn't start the browser, start() does that.

        Args:
            chrome_exe: filesystem path to chrome/chromium executable
            port: chrome debugging protocol port (default 9222)
            ignore_cert_errors: configure chrome to accept all certs (default
                False)
        """
        self.port = port
        self.chrome_exe = chrome_exe
        self.ignore_cert_errors = ignore_cert_errors
        self._shutdown = threading.Event()
        self.chrome_process = None

    def __enter__(self):
        """
        Returns websocket url to chrome window with about:blank loaded.
        """
        return self.start()

    def __exit__(self, *args):
        self.stop()

    def _init_cookie_db(self, cookie_db):
        cookie_dir = os.path.join(self._chrome_user_data_dir, "Default")
        cookie_location = os.path.join(cookie_dir, "Cookies")
        self.logger.debug("cookie DB provided, writing to %s", cookie_location)
        os.makedirs(cookie_dir, exist_ok=True)

        try:
            with open(cookie_location, "wb") as cookie_file:
                cookie_file.write(cookie_db)
        except OSError:
            self.logger.error(
                "exception writing cookie file at %s", cookie_location, exc_info=True
            )

    def persist_and_read_cookie_db(self):
        cookie_location = os.path.join(self._chrome_user_data_dir, "Default", "Cookies")
        self.logger.debug(
            "marking cookies persistent then reading file into memory: %s",
            cookie_location,
        )
        try:
            with sqlite3.connect(cookie_location) as conn:
                cur = conn.cursor()
                cur.execute("UPDATE cookies SET is_persistent = 1")
        except sqlite3.Error:
            try:
                # db schema changed around version 66, this is the old schema
                with sqlite3.connect(cookie_location) as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE cookies SET persistent = 1")
            except sqlite3.Error:
                self.logger.error(
                    "exception updating cookie DB %s", cookie_location, exc_info=True
                )

        cookie_db = None
        try:
            with open(cookie_location, "rb") as cookie_file:
                cookie_db = cookie_file.read()
        except OSError:
            self.logger.error(
                "exception reading from cookie DB file %s",
                cookie_location,
                exc_info=True,
            )
        return cookie_db

    def start(
        self,
        proxy=None,
        cookie_db=None,
        disk_cache_dir=None,
        disk_cache_size=None,
        websocket_timeout=60,
        window_height=900,
        window_width=1400,
    ):
        """
        Starts chrome/chromium process.

        Args:
            proxy: http proxy 'host:port' (default None)
            cookie_db: raw bytes of chrome/chromium sqlite3 cookies database,
                which, if supplied, will be written to
                {chrome_user_data_dir}/Default/Cookies before running the
                browser (default None)
            disk_cache_dir: use directory for disk cache. The default location
                is inside `self._home_tmpdir` (default None).
            disk_cache_size: Forces the maximum disk space to be used by the disk
                cache, in bytes. (default None)
            websocket_timeout: websocket timeout, in seconds
            window_height, window_width: window height and width, in pixels
        Returns:
            websocket url to chrome window with about:blank loaded
        """
        # these can raise exceptions
        self._home_tmpdir = tempfile.TemporaryDirectory()
        self._chrome_user_data_dir = os.path.join(
            self._home_tmpdir.name, "chrome-user-data"
        )
        if cookie_db:
            self._init_cookie_db(cookie_db)
        self._shutdown.clear()

        new_env = os.environ.copy()
        new_env["HOME"] = self._home_tmpdir.name
        chrome_args = [
            self.chrome_exe,
            "-v",
            "--remote-debugging-port=%s" % self.port,
            "--remote-allow-origins=http://localhost:%s" % self.port,
            "--use-mock-keychain",  # mac thing
            "--user-data-dir=%s" % self._chrome_user_data_dir,
            "--disable-background-networking",
            "--disable-breakpad",
            "--disable-renderer-backgrounding",
            "--disable-hang-monitor",
            "--disable-background-timer-throttling",
            "--mute-audio",
            "--disable-web-sockets",
            f"--window-size={window_width},{window_height}",
            "--no-default-browser-check",
            "--disable-first-run-ui",
            "--no-first-run",
            "--homepage=about:blank",
            "--disable-features=HttpsUpgrades",
            "--disable-direct-npapi-requests",
            "--disable-web-security",
            "--disable-notifications",
            "--disable-extensions",
            "--disable-save-password-bubble",
            "--disable-sync",
        ]
        major_version = check_version(self.chrome_exe)
        if major_version >= 109:
            chrome_args.append("--headless=new")
        elif 96 <= major_version <= 108:
            chrome_args.append("--headless=chrome")
        else:
            chrome_args.append("--headless")

        extra_chrome_args = os.environ.get("BROZZLER_EXTRA_CHROME_ARGS")
        if extra_chrome_args:
            chrome_args.extend(extra_chrome_args.split())
        if disk_cache_dir:
            chrome_args.append("--disk-cache-dir=%s" % disk_cache_dir)
        if disk_cache_size:
            chrome_args.append("--disk-cache-size=%s" % disk_cache_size)
        if self.ignore_cert_errors:
            chrome_args.append("--ignore-certificate-errors")
        if proxy:
            chrome_args.append("--proxy-server=%s" % proxy)
        chrome_args.append("about:blank")
        self.logger.info("running: %r", subprocess.list2cmdline(chrome_args))
        # start_new_session - new process group so we can kill the whole group
        self.chrome_process = subprocess.Popen(
            chrome_args,
            env=new_env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._out_reader_thread = threading.Thread(
            target=self._read_stderr_stdout,
            name="ChromeOutReaderThread:%s" % self.port,
            daemon=True,
        )
        self._out_reader_thread.start()
        self.logger.info("chrome running, pid %s" % self.chrome_process.pid)

        return self._websocket_url(timeout_sec=websocket_timeout)

    def _websocket_url(self, timeout_sec=60):
        json_url = "http://localhost:%s/json" % self.port
        # make this a member variable so that kill -QUIT reports it
        self._start = time.time()
        self._last_warning = self._start
        while True:
            try:
                raw_json = urllib.request.urlopen(json_url, timeout=30).read()
                all_debug_info = json.loads(raw_json.decode("utf-8"))
                debug_info = [x for x in all_debug_info if x["url"] == "about:blank"]

                if debug_info and "webSocketDebuggerUrl" in debug_info[0]:
                    self.logger.debug("%s returned %s", json_url, raw_json)
                    url = debug_info[0]["webSocketDebuggerUrl"]
                    self.logger.info(
                        "got chrome window websocket debug url %s from %s",
                        url,
                        json_url,
                    )
                    return url
            except brozzler.ShutdownRequested:
                raise
            except Exception as e:
                if time.time() - self._last_warning > 30:
                    self.logger.warning(
                        "problem with %s (will keep trying until timeout "
                        "of %d seconds): %s",
                        json_url,
                        timeout_sec,
                        e,
                    )
                    self._last_warning = time.time()
            finally:
                e = None
                if self.chrome_process:
                    if time.time() - self._start > timeout_sec:
                        e = Exception(
                            "killing chrome, failed to retrieve %s after "
                            "%s seconds" % (json_url, time.time() - self._start)
                        )
                    elif self.chrome_process.poll() is not None:
                        e = Exception(
                            "chrome process died with status %s"
                            % self.chrome_process.poll()
                        )
                    else:
                        time.sleep(0.5)
                else:
                    e = Exception("??? self.chrome_process is not set ???")
                if e:
                    self.stop()
                    raise e

    def _read_stderr_stdout(self):
        # XXX select doesn't work on windows
        def readline_nonblock(f):
            buf = b""
            try:
                while (
                    not self._shutdown.is_set()
                    and (len(buf) == 0 or buf[-1] != 0xA)
                    and select.select([f], [], [], 0.5)[0]
                ):
                    buf += f.read(1)
            except (ValueError, OSError):
                # When the chrome process crashes, stdout & stderr are closed
                # and trying to read from them raises these exceptions. We just
                # stop reading and return current `buf`.
                pass
            return buf

        try:
            while not self._shutdown.is_set():
                buf = readline_nonblock(self.chrome_process.stdout)
                if buf:
                    self.logger.trace(
                        "chrome pid %s STDOUT %s", self.chrome_process.pid, buf
                    )

                buf = readline_nonblock(self.chrome_process.stderr)
                if buf:
                    self.logger.trace(
                        "chrome pid %s STDERR %s", self.chrome_process.pid, buf
                    )
        except:
            self.logger.error("unexpected exception", exc_info=True)

    def stop(self):
        if not self.chrome_process or self._shutdown.is_set():
            return
        self._shutdown.set()

        timeout_sec = 300
        if self.chrome_process.poll() is None:
            self.logger.info("terminating chrome pgid %s", self.chrome_process.pid)

            os.killpg(self.chrome_process.pid, signal.SIGTERM)
        t0 = time.time()

        try:
            while time.time() - t0 < timeout_sec:
                status = self.chrome_process.poll()
                if status is not None:
                    if status == 0:
                        self.logger.info(
                            "chrome pid %s exited normally", self.chrome_process.pid
                        )
                    else:
                        self.logger.warning(
                            "chrome pid %s exited with nonzero status %s",
                            self.chrome_process.pid,
                            status,
                        )

                    # XXX I would like to forcefully kill the process group
                    # here to guarantee no orphaned chromium subprocesses hang
                    # around, but there's a chance I suppose that some other
                    # process could have started with the same pgid
                    return
                time.sleep(0.5)

            self.logger.warning(
                "chrome pid %s still alive %.1f seconds after sending "
                "SIGTERM, sending SIGKILL",
                self.chrome_process.pid,
                time.time() - t0,
            )
            os.killpg(self.chrome_process.pid, signal.SIGKILL)
            status = self.chrome_process.wait()
            self.logger.warning(
                "chrome pid %s reaped (status=%s) after killing with " "SIGKILL",
                self.chrome_process.pid,
                status,
            )

        finally:
            self.chrome_process.stdout.close()
            self.chrome_process.stderr.close()
            try:
                self._home_tmpdir.cleanup()
            except:
                self.logger.error(
                    "exception deleting %s", self._home_tmpdir, exc_info=True
                )
            self._out_reader_thread.join()
            self.chrome_process = None
