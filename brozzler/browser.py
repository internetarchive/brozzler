'''
brozzler/browser.py - manages the browsers for brozzler

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
import json
import itertools
import websocket
import time
import threading
import os
import random
import brozzler
from brozzler.chrome import Chrome
from brozzler.behaviors import Behavior
from requests.structures import CaseInsensitiveDict
import base64
import sqlite3
import datetime

__all__ = ["BrowserPool", "Browser"]

class BrowserPool:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    BASE_PORT = 9200

    def __init__(self, size=3, **kwargs):
        """kwargs are passed on to Browser.__init__"""
        self.size = size
        self._available = set()
        self._in_use = set()

        for i in range(0, size):
            browser = Browser(BrowserPool.BASE_PORT + i, **kwargs)
            self._available.add(browser)

        self._lock = threading.Lock()

    def acquire(self):
        """
        Returns browser from pool if available, raises NoBrowsersAvailable
        otherwise.
        """
        with self._lock:
            try:
                browser = self._available.pop()
            except KeyError:
                raise NoBrowsersAvailable()
            self._in_use.add(browser)
            return browser

    def release(self, browser):
        with self._lock:
            self._available.add(browser)
            self._in_use.remove(browser)

    def shutdown_now(self):
        for browser in self._in_use:
            browser.abort_browse_page()

    def num_available(self):
        return len(self._available)

    def num_in_use(self):
        return len(self._in_use)

class NoBrowsersAvailable(Exception):
    pass

class BrowsingException(Exception):
    pass

class BrowsingAborted(BrowsingException):
    pass

class ResultMessageTimeout(BrowsingException):
    pass

class Browser:
    """
    Runs chrome/chromium to synchronously browse one page at a time using
    worker.browse_page(). Should not be accessed from multiple threads.
    """

    logger = logging.getLogger(__module__ + "." + __qualname__)

    HARD_TIMEOUT_SECONDS = 20 * 60

    def __init__(
            self, chrome_port=9222, chrome_exe='chromium-browser', proxy=None,
            ignore_cert_errors=False):
        self.command_id = itertools.count(1)
        self.chrome_port = chrome_port
        self.chrome_exe = chrome_exe
        self.proxy = proxy
        self.ignore_cert_errors = ignore_cert_errors
        self._behavior = None
        self._websock = None
        self._abort_browse_page = False
        self._chrome_instance = None
        self._aw_snap_hes_dead_jim = None
        self._work_dir = None
        self._websocket_url = None

    def __repr__(self):
        return "{}.{}:{}".format(Browser.__module__, Browser.__qualname__, self.chrome_port)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self, proxy=None, cookie_db=None):
        if not self._chrome_instance:
            self._chrome_instance = Chrome(
                    port=self.chrome_port, executable=self.chrome_exe,
                    ignore_cert_errors=self.ignore_cert_errors,
                    proxy=proxy or self.proxy, cookie_db=None)
            try:
                self._websocket_url = self._chrome_instance.start()
            except:
                self._chrome_instance = None
                raise

    def stop(self):
        try:
            if self.is_running():
                self._chrome_instance.stop()
                self._chrome_instance = None
                self._websocket_url = None
        except:
            self.logger.error("problem stopping", exc_info=True)

    def is_running(self):
        return bool(self._websocket_url)

    def abort_browse_page(self):
        self._abort_browse_page = True

    def persist_and_read_cookie_db(self):
        if self._chrome_instance:
            return self._chrome_instance.persist_and_read_cookie_db()
        else:
            return None

    def browse_page(
            self, url, extra_headers=None, behavior_parameters=None,
            user_agent=None,
            on_request=None, on_response=None, on_screenshot=None,
            on_url_change=None):
        """
        Synchronously loads a page, runs behaviors, and takes a screenshot.

        Raises BrowsingException if browsing the page fails in a non-critical
        way.

        Returns extracted outlinks.
        """
        if not self.is_running():
            raise BrowsingException("browser has not been started")
        self.url = url
        self.extra_headers = extra_headers
        self.user_agent = user_agent
        self.on_request = on_request
        self.on_screenshot = on_screenshot
        self.on_url_change = on_url_change
        self.on_response = on_response
        self.behavior_parameters = behavior_parameters

        self._outlinks = None
        self._reached_limit = None
        self._aw_snap_hes_dead_jim = None
        self._abort_browse_page = False
        self._has_screenshot = False
        self._waiting_on_result_messages = {}
        self._result_message_timeout = None

        self._websock = websocket.WebSocketApp(
                self._websocket_url, on_open=self._visit_page,
                on_message=self._wrap_handle_message)

        thread_name = "WebsockThread:{}-{:%Y%m%d%H%M%S}".format(
                self.chrome_port, datetime.datetime.utcnow())
        websock_thread = threading.Thread(
                target=self._websock.run_forever, name=thread_name,
                kwargs={'ping_timeout':0.5})
        websock_thread.start()
        self._start = time.time()
        aborted = False

        try:
            while True:
                time.sleep(0.5)
                if self._browse_interval_func():
                    return self._outlinks
        finally:
            if (self._websock and self._websock.sock
                    and self._websock.sock.connected):
                try:
                    self._websock.close()
                except BaseException as e:
                    self.logger.error(
                            "exception closing websocket %s - %s" % (
                                self._websock, e))

            websock_thread.join(timeout=30)
            if websock_thread.is_alive():
                self.logger.error(
                        "%s still alive 30 seconds after closing %s, will "
                        "forcefully nudge it again" % (
                            websock_thread, self._websock))
                self._websock.keep_running = False
                websock_thread.join(timeout=30)
                if websock_thread.is_alive():
                    self.logger.critical(
                            "%s still alive 60 seconds after closing %s" % (
                                websock_thread, self._websock))

            self._behavior = None

    OUTLINKS_JS = r"""
var __brzl_framesDone = new Set();
var __brzl_compileOutlinks = function(frame) {
    __brzl_framesDone.add(frame);
    if (frame && frame.document) {
        var outlinks = Array.prototype.slice.call(
                frame.document.querySelectorAll('a[href]'));
        for (var i = 0; i < frame.frames.length; i++) {
            if (frame.frames[i] && !__brzl_framesDone.has(frame.frames[i])) {
                outlinks = outlinks.concat(__brzl_compileOutlinks(frame.frames[i]));
            }
        }
    }
    return outlinks;
}
__brzl_compileOutlinks(window).join('\n');
"""

    def _chain_chrome_messages(self, chain):
        """
        Sends a series of messages to chrome/chromium on the debugging protocol
        websocket. Waits for a reply from each one before sending the next.
        Enforces a timeout waiting for each reply. If the timeout is hit, sets
        self._result_message_timeout with a ResultMessageTimeout (an exception
        class). Takes an array of dicts, each of which should look like this:

            {
                "info": "human readable description",
                "chrome_msg": { ... },   # message to send to chrome, as a dict
                "timeout": 30,           # timeout in seconds
                "callback": my_callback, # takes one arg, the result message
            }

        The code is rather convoluted because of the asynchronous nature of the
        whole thing. See how it's used in _start_postbehavior_chain.
        """
        timer = None

        def callback(message):
            if timer:
                timer.cancel()
            if "callback" in chain[0]:
                chain[0]["callback"](message)
            self._chain_chrome_messages(chain[1:])

        def timeout():
            self._result_message_timeout = ResultMessageTimeout(
                    "timed out after %.1fs waiting for result message "
                    "for %s", chain[0]["timeout"], chain[0]["chrome_msg"])

        if chain:
            msg_id = self.send_to_chrome(**chain[0]["chrome_msg"])
            self._waiting_on_result_messages[msg_id] = callback
            self.logger.info(
                    "msg_id=%s for message %s", msg_id, chain[0]["chrome_msg"])
            timer = threading.Timer(chain[0]["timeout"], timeout)
            timer.daemon = True
            timer.start()
        else:
            self.logger.info("finished chrome message chain")

    def _start_postbehavior_chain(self):
        if self.on_screenshot:
            chain = [{
                "info": "scrolling to top",
                "chrome_msg": {
                    "method": "Runtime.evaluate",
                    "params": {"expression": "window.scrollTo(0, 0);"},
                },
                "timeout": 30,
                "callback": lambda message: None,
            }, {
                "info": "requesting screenshot",
                "chrome_msg": {"method": "Page.captureScreenshot"},
                "timeout": 30,
                "callback": lambda message: (
                        self.on_screenshot and self.on_screenshot(
                            base64.b64decode(message["result"]["data"]))),
            }]
        else:
            chain = []

        def set_outlinks(message):
            if message["result"]["result"]["value"]:
                self._outlinks = frozenset(
                        message["result"]["result"]["value"].split("\n"))
            else:
                self._outlinks = frozenset()

        chain.append({
            "info": "retrieving outlinks",
            "chrome_msg": {
                "method": "Runtime.evaluate",
                "params": {"expression": self.OUTLINKS_JS},
            },
            "timeout": 60,
            "callback": set_outlinks,
        })

        self._chain_chrome_messages(chain)

    def _browse_interval_func(self):
        """Called periodically while page is being browsed. Returns True when
        finished browsing."""
        if (not self._websock or not self._websock.sock
                or not self._websock.sock.connected):
            raise BrowsingException(
                    "websocket closed, did chrome die? {}".format(
                        self._websocket_url))
        elif self._result_message_timeout:
            raise self._result_message_timeout
        elif self._aw_snap_hes_dead_jim:
            raise BrowsingException(
                    """chrome tab went "aw snap" or "he's dead jim"!""")
        elif self._outlinks is not None:
            # setting self._outlinks is the last thing that happens in the
            # post-behavior chain
            return True
        elif (self._behavior != None and self._behavior.is_finished()
                or time.time() - self._start > Browser.HARD_TIMEOUT_SECONDS):
            if self._behavior and self._behavior.is_finished():
                self.logger.info(
                        "behavior decided it's finished with %s", self.url)
            else:
                self.logger.info(
                        "reached hard timeout of %s seconds url=%s",
                        Browser.HARD_TIMEOUT_SECONDS, self.url)
            self._behavior = None
            self._start_postbehavior_chain()
            return False
        elif self._reached_limit:
            raise self._reached_limit
        elif self._abort_browse_page:
            raise BrowsingAborted("browsing page aborted")
        else:
            return False

    def send_to_chrome(self, suppress_logging=False, **kwargs):
        msg_id = next(self.command_id)
        kwargs["id"] = msg_id
        msg = json.dumps(kwargs)
        if not suppress_logging:
            self.logger.debug("sending message to %s: %s", self._websock, msg)
        self._websock.send(msg)
        return msg_id

    def _visit_page(self, websock):
        # navigate to about:blank here to avoid situation where we navigate to
        # the same page that we're currently on, perhaps with a different
        # #fragment, which prevents Page.loadEventFired from happening
        self.send_to_chrome(method="Page.navigate", params={"url": "about:blank"})

        self.send_to_chrome(method="Network.enable")
        self.send_to_chrome(method="Page.enable")
        self.send_to_chrome(method="Console.enable")
        self.send_to_chrome(method="Debugger.enable")
        self.send_to_chrome(method="Runtime.enable")

        headers = self.extra_headers or {}
        headers['Accept-Encoding'] = 'identity'
        self.send_to_chrome(
                method="Network.setExtraHTTPHeaders",
                params={"headers":headers})

        if self.user_agent:
            self.send_to_chrome(method="Network.setUserAgentOverride", params={"userAgent": self.user_agent})

        # disable google analytics, see _handle_message() where breakpoint is caught "Debugger.paused"
        self.send_to_chrome(method="Debugger.setBreakpointByUrl", params={"lineNumber": 1, "urlRegex":"https?://www.google-analytics.com/analytics.js"})

        # navigate to the page!
        self.send_to_chrome(method="Page.navigate", params={"url": self.url})

    def _wrap_handle_message(self, websock, message):
        try:
            self._handle_message(websock, message)
        except:
            self.logger.error(
                    "uncaught exception in _handle_message message=%s",
                    message, exc_info=True)
            self.abort_browse_page()

    def _network_request_will_be_sent(self, message):
        if self._behavior:
            self._behavior.notify_of_activity()
        if message["params"]["request"]["url"].lower().startswith("data:"):
            self.logger.debug("ignoring data url {}".format(message["params"]["request"]["url"][:80]))
        elif self.on_request:
            self.on_request(message)

    def _network_response_received(self, message):
        if (not self._reached_limit
                and message["params"]["response"]["status"] == 420
                and "Warcprox-Meta" in CaseInsensitiveDict(
                    message["params"]["response"]["headers"])):
            warcprox_meta = json.loads(CaseInsensitiveDict(
                message["params"]["response"]["headers"])["Warcprox-Meta"])
            self._reached_limit = brozzler.ReachedLimit(
                    warcprox_meta=warcprox_meta)
            self.logger.info("reached limit %s", self._reached_limit)
        if self.on_response:
            self.on_response(message)

    def _page_load_event_fired(self, message):
        def page_url_after_load_event(message):
            if message["result"]["result"]["value"] != self.url:
                if self.on_url_change:
                    self.on_url_change(message["result"]["result"]["value"])
        msg_id = self.send_to_chrome(
                method="Runtime.evaluate",
                params={"expression":"document.URL"})
        self._waiting_on_result_messages[msg_id] = page_url_after_load_event

        self.logger.info("Page.loadEventFired, moving on to starting behaviors url={}".format(self.url))
        self._behavior = Behavior(self.url, self)
        self._behavior.start(self.behavior_parameters)

    def _console_message_added(self, message):
        self.logger.debug("%s console.%s %s", self._websock.url,
                message["params"]["message"]["level"],
                message["params"]["message"]["text"])

    def _debugger_paused(self, message):
        # We hit the breakpoint set in visit_page. Get rid of google
        # analytics script!
        self.logger.debug("debugger paused! message={}".format(message))
        scriptId = message['params']['callFrames'][0]['location']['scriptId']

        # replace script
        self.send_to_chrome(method="Debugger.setScriptSource", params={"scriptId": scriptId, "scriptSource":"console.log('google analytics is no more!');"})

        # resume execution
        self.send_to_chrome(method="Debugger.resume")

    def _handle_message(self, websock, json_message):
        message = json.loads(json_message)
        if "method" in message:
            if message["method"] == "Network.requestWillBeSent":
                self._network_request_will_be_sent(message)
            elif message["method"] == "Network.responseReceived":
                self._network_response_received(message)
            elif message["method"] == "Page.loadEventFired":
                self._page_load_event_fired(message)
            elif message["method"] == "Console.messageAdded":
                self._console_message_added(message)
            elif message["method"] == "Debugger.paused":
                self._debugger_paused(message)
            elif message["method"] == "Inspector.targetCrashed":
                self._aw_snap_hes_dead_jim = message
            # elif message["method"] in (
            #         "Network.dataReceived", "Network.responseReceived",
            #         "Network.loadingFinished"):
            #     pass
            # else:
            #     self.logger.debug("%s %s", message["method"], json_message)
        elif "result" in message:
            if message["id"] in self._waiting_on_result_messages:
                callback = self._waiting_on_result_messages[message["id"]]
                del self._waiting_on_result_messages[message["id"]]
                self.logger.debug(
                        "received result for message id=%s, calling %s",
                        message["id"], callback)
                callback(message)
            elif self._behavior and self._behavior.is_waiting_on_result(
                    message["id"]):
                self._behavior.notify_of_result(message)
            # else:
            #     self.logger.debug("%s", json_message)
        # else:
        #     self.logger.debug("%s", json_message)

