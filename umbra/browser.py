#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import json
import urllib.request
import itertools
import websocket
import time
import threading
import subprocess
import signal
import tempfile
import os
from umbra.behaviors import Behavior

class Browser:
    """Runs chrome/chromium to synchronously browse one page at a time using
    worker.browse_page(). Currently the implementation starts up a new instance
    of chrome for each page browsed, always on the same debug port. (In the
    future, it may keep the browser running indefinitely.)"""

    logger = logging.getLogger(__module__ + "." + __qualname__)

    HARD_TIMEOUT_SECONDS = 20 * 60

    def __init__(self, chrome_port=9222, chrome_exe='chromium-browser', chrome_wait=60, client_id='request'):
        self.command_id = itertools.count(1)
        self._lock = threading.Lock()
        self.chrome_port = chrome_port
        self.chrome_exe = chrome_exe
        self.chrome_wait = chrome_wait
        self.client_id = client_id
        self._behavior = None
        self.websock = None

    def browse_page(self, url, on_request=None):
        """Synchronously browses a page and runs behaviors. First blocks to
        acquire lock to ensure we only browse one page at a time."""
        with self._lock:
            self.url = url
            self.on_request = on_request
            with tempfile.TemporaryDirectory() as user_data_dir:
                with Chrome(self.chrome_port, self.chrome_exe, self.chrome_wait, user_data_dir) as websocket_url:
                    self.websock = websocket.WebSocketApp(websocket_url,
                            on_open=self._visit_page,
                            on_message=self._handle_message)
                    websock_thread = threading.Thread(target=self.websock.run_forever, kwargs={'ping_timeout':0.5})
                    websock_thread.start()
                    start = time.time()

                    while True:
                        time.sleep(0.5)
                        if not self.websock or not self.websock.sock or not self.websock.sock.connected:
                            self.logger.error("websocket closed, did chrome die??? {}".format(self.websock))
                            break
                        elif time.time() - start > Browser.HARD_TIMEOUT_SECONDS:
                            self.logger.info("finished browsing page, reached hard timeout of {} seconds url={}".format(Browser.HARD_TIMEOUT_SECONDS, self.url))
                            break
                        elif self._behavior != None and self._behavior.is_finished():
                            self.logger.info("finished browsing page according to behavior url={}".format(self.url))
                            break

                    try:
                        self.websock.close()
                    except BaseException as e:
                        self.logger.error("exception closing websocket {} - {}".format(self.websock, e))

                    websock_thread.join()
                    self._behavior = None

    def send_to_chrome(self, **kwargs):
        msg_id = next(self.command_id)
        kwargs['id'] = msg_id
        msg = json.dumps(kwargs)
        self.logger.debug('sending message to {}: {}'.format(self.websock, msg))
        self.websock.send(msg)
        return msg_id

    def _visit_page(self, websock):
        self.send_to_chrome(method="Network.enable")
        self.send_to_chrome(method="Page.enable")
        self.send_to_chrome(method="Console.enable")
        self.send_to_chrome(method="Debugger.enable")
        self.send_to_chrome(method="Runtime.enable")

        # disable google analytics, see _handle_message() where breakpoint is caught "Debugger.paused"
        self.send_to_chrome(method="Debugger.setBreakpointByUrl", params={"lineNumber": 1, "urlRegex":"https?://www.google-analytics.com/analytics.js"})

        # navigate to the page!
        self.send_to_chrome(method="Page.navigate", params={"url": self.url})

    def _handle_message(self, websock, message):
        # self.logger.debug("message from {} - {}".format(websock.url, message[:95]))
        # self.logger.debug("message from {} - {}".format(websock.url, message))
        message = json.loads(message)
        if "method" in message and message["method"] == "Network.requestWillBeSent":
            if self._behavior:
                self._behavior.notify_of_activity()
            if message["params"]["request"]["url"].lower().startswith("data:"):
                self.logger.debug("ignoring data url {}".format(message["params"]["request"]["url"][:80]))
            else:
                self.on_request(message)
        elif "method" in message and message["method"] == "Page.loadEventFired":
            if self._behavior is None:
                self.logger.info("Page.loadEventFired, starting behaviors url={} message={}".format(self.url, message))
                self._behavior = Behavior(self.url, self)
                self._behavior.start()
            else:
                self.logger.warn("Page.loadEventFired but behaviors already running url={} message={}".format(self.url, message))
        elif "method" in message and message["method"] == "Console.messageAdded":
            self.logger.debug("{} console.{} {}".format(websock.url,
                message["params"]["message"]["level"],
                message["params"]["message"]["text"]))
        elif "method" in message and message["method"] == "Debugger.paused":
            # We hit the breakpoint set in visit_page. Get rid of google
            # analytics script!

            self.logger.debug("debugger paused! message={}".format(message))
            scriptId = message['params']['callFrames'][0]['location']['scriptId']

            # replace script
            self.send_to_chrome(method="Debugger.setScriptSource", params={"scriptId": scriptId, "scriptSource":"console.log('google analytics is no more!');"})

            # resume execution
            self.send_to_chrome(method="Debugger.resume")
        elif "result" in message:
            if self._behavior and self._behavior.is_waiting_on_result(message['id']):
                self._behavior.notify_of_result(message)
        # elif "method" in message and message["method"] in ("Network.dataReceived", "Network.responseReceived", "Network.loadingFinished"):
        #     pass
        # elif "method" in message:
        #     self.logger.debug("{} {}".format(message["method"], message))
        # else:
        #     self.logger.debug("[no-method] {}".format(message))


class Chrome:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, port, executable, browser_wait, user_data_dir):
        self.port = port
        self.executable = executable
        self.browser_wait = browser_wait
        self.user_data_dir = user_data_dir

    def fetch_debugging_json():
        raw_json = urllib.request.urlopen("http://localhost:%s/json" % self.port).read()
        json = raw_json.decode('utf-8')
        return json.loads(json)

    # returns websocket url to chrome window with about:blank loaded
    def __enter__(self):
        chrome_args = [self.executable,
                "--user-data-dir={}".format(self.user_data_dir),
                "--remote-debugging-port={}".format(self.port),
                "--disable-web-sockets", "--disable-cache",
                "--window-size=1100,900", "--no-default-browser-check",
                "--disable-first-run-ui", "--no-first-run",
                "--homepage=about:blank", "about:blank"]
        self.logger.info("running {}".format(chrome_args))
        self.chrome_process = subprocess.Popen(chrome_args, start_new_session=True)
        self.logger.info("chrome running, pid {}".format(self.chrome_process.pid))
        start = time.time()

        json_url = "http://localhost:%s/json" % self.port

        while True:
            try:
                raw_json = urllib.request.urlopen(json_url).read()
                all_debug_info = json.loads(raw_json.decode('utf-8'))
                debug_info = [x for x in all_debug_info if x['url'] == 'about:blank']

                if debug_info and 'webSocketDebuggerUrl' in debug_info[0]:
                    self.logger.debug("{} returned {}".format(json_url, raw_json))
                    url = debug_info[0]['webSocketDebuggerUrl']
                    self.logger.info('got chrome window websocket debug url {} from {}'.format(url, json_url))
                    return url
            except:
                pass
            finally:
                if time.time() - start > float(self.browser_wait):
                    raise Exception("failed to retrieve {} after {} seconds".format(json_url, time.time() - start))
                else:
                    time.sleep(0.5)

    def __exit__(self, *args):
        self.logger.info("killing chrome pid {}".format(self.chrome_process.pid))
        os.killpg(self.chrome_process.pid, signal.SIGINT)
        self.chrome_process.wait()

