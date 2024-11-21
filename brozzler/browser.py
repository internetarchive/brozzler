"""
brozzler/browser.py - manages the browsers for brozzler

Copyright (C) 2014-2024 Internet Archive

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
import time
import brozzler
import itertools
import json
import websocket
import time
import threading
import brozzler
from requests.structures import CaseInsensitiveDict
import datetime
import base64
from ipaddress import AddressValueError
from brozzler.chrome import Chrome
import socket
import urlcanon


class BrowsingException(Exception):
    pass


class NoBrowsersAvailable(Exception):
    pass


class BrowsingTimeout(BrowsingException):
    pass


class BrowserPool:
    """
    Manages pool of browsers. Automatically chooses available port for the
    debugging protocol.
    """

    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, size=3, **kwargs):
        """
        Initializes the pool.

        Args:
            size: size of pool (default 3)
            **kwargs: arguments for Browser(...)
        """
        self.size = size
        self.kwargs = kwargs
        self._in_use = set()
        self._lock = threading.Lock()

    def _fresh_browser(self):
        # choose available port
        sock = socket.socket()
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        sock.close()

        browser = Browser(port=port, **self.kwargs)
        return browser

    def acquire_multi(self, n=1):
        """
        Returns a list of up to `n` browsers.

        Raises:
            NoBrowsersAvailable if none available
        """
        browsers = []
        with self._lock:
            if len(self._in_use) >= self.size:
                raise NoBrowsersAvailable
            while len(self._in_use) < self.size and len(browsers) < n:
                browser = self._fresh_browser()
                browsers.append(browser)
                self._in_use.add(browser)
        return browsers

    def acquire(self):
        """
        Returns an available instance.

        Returns:
            browser from pool, if available

        Raises:
            NoBrowsersAvailable if none available
        """
        with self._lock:
            if len(self._in_use) >= self.size:
                raise NoBrowsersAvailable
            browser = self._fresh_browser()
            self._in_use.add(browser)
            return browser

    def release(self, browser):
        browser.stop()  # make sure
        with self._lock:
            self._in_use.remove(browser)

    def release_all(self, browsers):
        for browser in browsers:
            browser.stop()  # make sure
        with self._lock:
            for browser in browsers:
                self._in_use.remove(browser)

    def shutdown_now(self):
        self.logger.info(
            "shutting down browser pool (%s browsers in use)", len(self._in_use)
        )
        with self._lock:
            for browser in self._in_use:
                browser.stop()

    def num_available(self):
        return self.size - len(self._in_use)

    def num_in_use(self):
        return len(self._in_use)


# uncomment the next line for LOTS of debugging logging
# websocket.enableTrace(True)


class WebsockReceiverThread(threading.Thread):
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, websock, name=None, daemon=True):
        super().__init__(name=name, daemon=daemon)

        self.websock = websock

        self.calling_thread = threading.current_thread()

        self.websock.on_open = self._on_open
        self.websock.on_message = self._on_message
        self.websock.on_error = self._on_error
        self.websock.on_close = self._on_close

        self.is_open = False
        self.got_page_load_event = None
        self.page_status = None  # Loaded page HTTP status code
        self.reached_limit = None

        self.on_request = None
        self.on_response = None
        self.on_service_worker_version_updated = None

        self._result_messages = {}

    def expect_result(self, msg_id):
        self._result_messages[msg_id] = None

    def received_result(self, msg_id):
        return bool(self._result_messages.get(msg_id))

    def pop_result(self, msg_id):
        return self._result_messages.pop(msg_id)

    def _on_close(self, websock, close_status_code, close_msg):
        pass
        # self.logger.info('GOODBYE GOODBYE WEBSOCKET')

    def _on_open(self, websock):
        self.is_open = True

    def _on_error(self, websock, e):
        """
        Raises BrowsingException in the thread that created this instance.
        """
        if isinstance(
            e, (websocket.WebSocketConnectionClosedException, ConnectionResetError)
        ):
            self.logger.error("websocket closed, did chrome die?")
        else:
            self.logger.error("exception from websocket receiver thread", exc_info=1)
        brozzler.thread_raise(self.calling_thread, BrowsingException)

    def run(self):
        # ping_timeout is used as the timeout for the call to select.select()
        # in addition to its documented purpose, and must have a value to avoid
        # hangs in certain situations
        #
        # skip_ut8_validation is a recommended performance improvement:
        # https://websocket-client.readthedocs.io/en/latest/faq.html#why-is-this-library-slow
        self.websock.run_forever(
            sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),),
            ping_timeout=0.5,
            skip_utf8_validation=True,
        )

    def _on_message(self, websock, message):
        try:
            self._handle_message(websock, message)
        except:
            self.logger.error(
                "uncaught exception in _handle_message message=%s",
                message,
                exc_info=True,
            )

    def _network_response_received(self, message):
        status = message["params"]["response"].get("status")
        if status == 420 and "Warcprox-Meta" in CaseInsensitiveDict(
            message["params"]["response"]["headers"]
        ):
            if not self.reached_limit:
                warcprox_meta = json.loads(
                    CaseInsensitiveDict(message["params"]["response"]["headers"])[
                        "Warcprox-Meta"
                    ]
                )
                self.reached_limit = brozzler.ReachedLimit(warcprox_meta=warcprox_meta)
                self.logger.info("reached limit %s", self.reached_limit)
                brozzler.thread_raise(self.calling_thread, brozzler.ReachedLimit)
            else:
                self.logger.info(
                    "reached limit but self.reached_limit is already set, "
                    "assuming the calling thread is already handling this"
                )
        if self.on_response:
            self.on_response(message)

        if status and self.page_status is None:
            self.page_status = status

    def _javascript_dialog_opening(self, message):
        self.logger.info("javascript dialog opened: %s", message)
        if message["params"]["type"] == "alert":
            accept = True
        else:
            accept = False
        self.websock.send(
            json.dumps(
                dict(
                    id=0,
                    method="Page.handleJavaScriptDialog",
                    params={"accept": accept},
                ),
                separators=",:",
            )
        )

    def _handle_message(self, websock, json_message):
        message = json.loads(json_message)
        if "method" in message:
            if message["method"] == "Page.loadEventFired":
                self.got_page_load_event = datetime.datetime.utcnow()
            elif message["method"] == "Network.responseReceived":
                self._network_response_received(message)
            elif message["method"] == "Network.requestWillBeSent":
                if self.on_request:
                    self.on_request(message)
            elif message["method"] == "Page.interstitialShown":
                # AITFIVE-1529: handle http auth
                # we should kill the browser when we receive Page.interstitialShown and
                # consider the page finished, until this is fixed:
                # https://bugs.chromium.org/p/chromium/issues/detail?id=764505
                self.logger.info(
                    "Page.interstialShown (likely unsupported http auth request)"
                )
                brozzler.thread_raise(
                    self.calling_thread, brozzler.PageInterstitialShown
                )
            elif message["method"] == "Inspector.targetCrashed":
                self.logger.error("""chrome tab went "aw snap" or "he's dead jim"!""")
                brozzler.thread_raise(self.calling_thread, BrowsingException)
            elif message["method"] == "Console.messageAdded":
                self.logger.debug(
                    "console.%s %s",
                    message["params"]["message"]["level"],
                    message["params"]["message"]["text"],
                )
            elif message["method"] == "Runtime.exceptionThrown":
                self.logger.debug("uncaught exception: %s", message)
            elif message["method"] == "Page.javascriptDialogOpening":
                self._javascript_dialog_opening(message)
            elif (
                message["method"] == "Network.loadingFailed"
                and "params" in message
                and "errorText" in message["params"]
                and message["params"]["errorText"] == "net::ERR_PROXY_CONNECTION_FAILED"
            ):
                brozzler.thread_raise(self.calling_thread, brozzler.ProxyError)
            elif message["method"] == "ServiceWorker.workerVersionUpdated":
                if self.on_service_worker_version_updated:
                    self.on_service_worker_version_updated(message)
            # else:
            #     self.logger.debug("%s %s", message["method"], json_message)
        elif "result" in message:
            if message["id"] in self._result_messages:
                self._result_messages[message["id"]] = message

    #      else:
    #          self.logger.debug("%s", json_message)
    #  else:
    #      self.logger.debug("%s", json_message)


class Browser:
    """
    Manages an instance of Chrome for browsing pages.
    """

    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, **kwargs):
        """
        Initializes the Browser.

        Args:
            **kwargs: arguments for Chrome(...)
        """
        self.chrome = Chrome(**kwargs)
        self.websock_url = None
        self.websock = None
        self.websock_thread = None
        self.is_browsing = False
        self._command_id = Counter()
        self._wait_interval = 0.5

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def _wait_for(self, callback, timeout=None):
        """
        Spins until callback() returns truthy.
        """
        start = time.time()
        while True:
            if callback():
                return
            elapsed = time.time() - start
            if timeout and elapsed > timeout:
                raise BrowsingTimeout(
                    "timed out after %.1fs waiting for: %s" % (elapsed, callback)
                )
            brozzler.sleep(self._wait_interval)

    def send_to_chrome(self, suppress_logging=False, **kwargs):
        msg_id = next(self._command_id)
        kwargs["id"] = msg_id
        msg = json.dumps(kwargs, separators=",:")
        logging.log(
            logging.TRACE if suppress_logging else logging.DEBUG,
            "sending message to %s: %s",
            self.websock,
            msg,
        )
        self.websock.send(msg)
        return msg_id

    def start(self, **kwargs):
        """
        Starts chrome if it's not running.

        Args:
            **kwargs: arguments for self.chrome.start(...)
        """
        if not self.is_running():
            self.websock_url = self.chrome.start(**kwargs)
            self.websock = websocket.WebSocketApp(self.websock_url)
            self.websock_thread = WebsockReceiverThread(
                self.websock, name="WebsockThread:%s" % self.chrome.port
            )
            self.websock_thread.start()

            self._wait_for(lambda: self.websock_thread.is_open, timeout=30)

            # tell browser to send us messages we're interested in
            self.send_to_chrome(method="Network.enable")
            self.send_to_chrome(method="Page.enable")
            # Enable Console & Runtime output only when debugging.
            # After all, we just print these events with debug(), we don't use
            # them in Brozzler logic.
            if self.logger.isEnabledFor(logging.DEBUG):
                self.send_to_chrome(method="Console.enable")
                self.send_to_chrome(method="Runtime.enable")
            self.send_to_chrome(method="ServiceWorker.enable")
            self.send_to_chrome(method="ServiceWorker.setForceUpdateOnPageLoad")

            # disable google analytics and amp analytics
            self.send_to_chrome(
                method="Network.setBlockedURLs",
                params={
                    "urls": [
                        "*google-analytics.com/analytics.js*",
                        "*google-analytics.com/ga.js*",
                        "*google-analytics.com/ga_exp.js*",
                        "*google-analytics.com/urchin.js*",
                        "*google-analytics.com/collect*",
                        "*google-analytics.com/r/collect*",
                        "*google-analytics.com/__utm.gif*",
                        "*google-analytics.com/gtm/js?*",
                        "*google-analytics.com/cx/api.js*",
                        "*cdn.ampproject.org/*/amp-analytics*.js",
                    ]
                },
            )

    def stop(self):
        """
        Stops chrome if it's running.
        """
        try:
            if self.websock and self.websock.sock and self.websock.sock.connected:
                self.logger.info("shutting down websocket connection")
                try:
                    self.websock.close()
                except BaseException as e:
                    self.logger.error(
                        "exception closing websocket %s - %s", self.websock, e
                    )

            self.chrome.stop()

            if self.websock_thread and (
                self.websock_thread != threading.current_thread()
            ):
                self.websock_thread.join(timeout=30)
                if self.websock_thread.is_alive():
                    self.logger.error(
                        "%s still alive 30 seconds after closing %s, will "
                        "forcefully nudge it again",
                        self.websock_thread,
                        self.websock,
                    )
                    self.websock.keep_running = False
                    self.websock_thread.join(timeout=30)
                    if self.websock_thread.is_alive():
                        self.logger.critical(
                            "%s still alive 60 seconds after closing %s",
                            self.websock_thread,
                            self.websock,
                        )

            self.websock_url = None
        except:
            self.logger.error("problem stopping", exc_info=True)

    def is_running(self):
        return self.websock_url is not None

    def browse_page(
        self,
        page_url,
        extra_headers=None,
        user_agent=None,
        behavior_parameters=None,
        behaviors_dir=None,
        on_request=None,
        on_response=None,
        on_service_worker_version_updated=None,
        on_screenshot=None,
        username=None,
        password=None,
        hashtags=None,
        screenshot_full_page=False,
        skip_extract_outlinks=False,
        skip_visit_hashtags=False,
        skip_youtube_dl=False,
        simpler404=False,
        page_timeout=300,
        behavior_timeout=900,
        extract_outlinks_timeout=60,
        download_throughput=-1,
        stealth=False,
    ):
        """
        Browses page in browser.

        Browser should already be running, i.e. start() should have been
        called. Opens the page_url in the browser, runs behaviors, takes a
        screenshot, extracts outlinks.

        Args:
            page_url: url of the page to browse
            extra_headers: dict of extra http headers to configure the browser
                to send with every request (default None)
            user_agent: user agent string, replaces browser default if
                supplied (default None)
            behavior_parameters: dict of parameters for populating the
                javascript behavior template (default None)
            behaviors_dir: Directory containing behaviors.yaml and JS templates
                (default None loads Brozzler default JS behaviors)
            on_request: callback to invoke on every Network.requestWillBeSent
                event, takes one argument, the json-decoded message (default
                None)
            on_response: callback to invoke on every Network.responseReceived
                event, takes one argument, the json-decoded message (default
                None)
            on_service_worker_version_updated: callback to invoke on every
                ServiceWorker.workerVersionUpdated event, takes one argument,
                the json-decoded message (default None)
            on_screenshot: callback to invoke when screenshot is obtained,
                takes one argument, the the raw jpeg bytes (default None)
                # XXX takes two arguments, the url of the page at the time the
                # screenshot was taken, and the raw jpeg bytes (default None)
            username: username string to use to try logging in if a login form
                is found in the page (default None)
            password: password string to use to try logging in if a login form
                is found in the page (default None)
            ... (there are more)

        Returns:
            A tuple (final_page_url, outlinks).
            final_page_url: the url in the location bar at the end of the
                browse_page cycle, which could be different from the original
                page url if the page redirects, javascript has changed the url
                in the location bar, etc
            outlinks: a list of navigational links extracted from the page

        Raises:
            brozzler.ProxyError: in case of proxy connection error
            BrowsingException: if browsing the page fails in some other way
        """
        if not self.is_running():
            raise BrowsingException("browser has not been started")
        if self.is_browsing:
            raise BrowsingException("browser is already busy browsing a page")
        self.is_browsing = True
        if on_request:
            self.websock_thread.on_request = on_request
        if on_response:
            self.websock_thread.on_response = on_response
        if on_service_worker_version_updated:
            self.websock_thread.on_service_worker_version_updated = (
                on_service_worker_version_updated
            )
        try:
            with brozzler.thread_accept_exceptions():
                self.configure_browser(
                    extra_headers=extra_headers,
                    user_agent=user_agent,
                    download_throughput=download_throughput,
                    stealth=stealth,
                )
                self.navigate_to_page(page_url, timeout=page_timeout)
                if password:
                    self.try_login(username, password, timeout=page_timeout)
                    # if login redirected us, return to page_url
                    if page_url != self.url().split("#")[0]:
                        self.logger.debug(
                            "login navigated away from %s; returning!", page_url
                        )
                        self.navigate_to_page(page_url, timeout=page_timeout)
                # If the target page HTTP status is 4xx/5xx, there is no point
                # in running behaviors, screenshot, outlink and hashtag
                # extraction as we didn't get a valid page.
                # This is only enabled with option `simpler404`.
                run_behaviors = True
                if simpler404 and (
                    self.websock_thread.page_status is None
                    or self.websock_thread.page_status >= 400
                ):
                    run_behaviors = False

                if run_behaviors and behavior_timeout > 0:
                    behavior_script = brozzler.behavior_script(
                        page_url, behavior_parameters, behaviors_dir=behaviors_dir
                    )
                    self.run_behavior(behavior_script, timeout=behavior_timeout)
                final_page_url = self.url()
                if on_screenshot:
                    if simpler404:
                        if (
                            self.websock_thread.page_status
                            and self.websock_thread.page_status < 400
                        ):
                            self._try_screenshot(on_screenshot, screenshot_full_page)
                    else:
                        self._try_screenshot(on_screenshot, screenshot_full_page)

                if not run_behaviors or skip_extract_outlinks:
                    outlinks = []
                else:
                    outlinks = self.extract_outlinks(timeout=extract_outlinks_timeout)
                if run_behaviors and not skip_visit_hashtags:
                    self.visit_hashtags(final_page_url, hashtags, outlinks)
                return final_page_url, outlinks
        except brozzler.ReachedLimit:
            # websock_thread has stashed the ReachedLimit exception with
            # more information, raise that one
            raise self.websock_thread.reached_limit
        except websocket.WebSocketConnectionClosedException as e:
            self.logger.error("websocket closed, did chrome die?")
            raise BrowsingException(e)
        finally:
            self.is_browsing = False
            self.websock_thread.on_request = None
            self.websock_thread.on_response = None

    def _try_screenshot(self, on_screenshot, full_page=False):
        """The browser instance must be scrolled to the top of the page before
        trying to get a screenshot.
        """
        self.send_to_chrome(
            method="Runtime.evaluate",
            suppress_logging=True,
            params={"expression": "window.scroll(0,0)"},
        )
        for i in range(3):
            try:
                jpeg_bytes = self.screenshot(full_page)
                on_screenshot(jpeg_bytes)
                return
            except BrowsingTimeout as e:
                logging.error("attempt %s/3: %s", i + 1, e)

    def visit_hashtags(self, page_url, hashtags, outlinks):
        _hashtags = set(hashtags or [])
        for outlink in outlinks:
            url = urlcanon.whatwg(outlink)
            hashtag = (url.hash_sign + url.fragment).decode("utf-8")
            urlcanon.canon.remove_fragment(url)
            if hashtag and str(url) == page_url:
                _hashtags.add(hashtag)
        # could inject a script that listens for HashChangeEvent to figure
        # out which hashtags were visited already and skip those
        for hashtag in _hashtags:
            # navigate_to_hashtag (nothing to wait for so no timeout?)
            self.logger.debug("navigating to hashtag %s", hashtag)
            url = urlcanon.whatwg(page_url)
            url.hash_sign = b"#"
            url.fragment = hashtag[1:].encode("utf-8")
            self.send_to_chrome(method="Page.navigate", params={"url": str(url)})
            time.sleep(5)  # um.. wait for idleness or something?
            # take another screenshot?
            # run behavior again with short timeout?
            # retrieve outlinks again and append to list?

    def configure_browser(
        self, extra_headers=None, user_agent=None, download_throughput=-1, stealth=False
    ):
        headers = extra_headers or {}
        headers["Accept-Encoding"] = "gzip"  # avoid encodings br, sdch
        self.websock_thread.expect_result(self._command_id.peek())
        msg_id = self.send_to_chrome(
            method="Network.setExtraHTTPHeaders", params={"headers": headers}
        )
        self._wait_for(lambda: self.websock_thread.received_result(msg_id), timeout=10)
        if user_agent:
            msg_id = self.send_to_chrome(
                method="Network.setUserAgentOverride", params={"userAgent": user_agent}
            )
        if download_throughput > -1:
            # traffic shaping already used by SPN2 to aid warcprox resilience
            # parameter value as bytes/second, or -1 to disable (default)
            msg_id = self.send_to_chrome(
                method="Network.emulateNetworkConditions",
                params={"downloadThroughput": download_throughput},
            )
        if stealth:
            self.websock_thread.expect_result(self._command_id.peek())
            js = brozzler.jinja2_environment().get_template("stealth.js").render()
            msg_id = self.send_to_chrome(
                method="Page.addScriptToEvaluateOnNewDocument", params={"source": js}
            )
            self._wait_for(
                lambda: self.websock_thread.received_result(msg_id), timeout=10
            )

    def navigate_to_page(self, page_url, timeout=300):
        self.logger.info("navigating to page %s", page_url)
        self.websock_thread.got_page_load_event = None
        self.websock_thread.page_status = None
        self.send_to_chrome(method="Page.navigate", params={"url": page_url})
        self._wait_for(lambda: self.websock_thread.got_page_load_event, timeout=timeout)

    def extract_outlinks(self, timeout=60):
        self.logger.info("extracting outlinks")
        self.websock_thread.expect_result(self._command_id.peek())
        js = brozzler.jinja2_environment().get_template("extract-outlinks.js").render()
        msg_id = self.send_to_chrome(
            method="Runtime.evaluate", params={"expression": js}
        )
        self._wait_for(
            lambda: self.websock_thread.received_result(msg_id), timeout=timeout
        )
        message = self.websock_thread.pop_result(msg_id)
        if (
            "result" in message
            and "result" in message["result"]
            and "value" in message["result"]["result"]
        ):
            if message["result"]["result"]["value"]:
                out = []
                for link in message["result"]["result"]["value"].split("\n"):
                    try:
                        out.append(str(urlcanon.whatwg(link)))
                    except AddressValueError:
                        self.logger.warning("skip invalid outlink: %s", link)
                return frozenset(out)
            else:
                # no links found
                return frozenset()
        else:
            self.logger.error(
                "problem extracting outlinks, result message: %s", message
            )
            return frozenset()

    def screenshot(self, full_page=False, timeout=45):
        """Optionally capture full page screenshot using puppeteer as an
        inspiration:
        https://github.com/GoogleChrome/puppeteer/blob/master/lib/Page.js#L898
        """
        self.logger.info("taking screenshot")
        if full_page:
            self.websock_thread.expect_result(self._command_id.peek())
            msg_id = self.send_to_chrome(method="Page.getLayoutMetrics")
            self._wait_for(
                lambda: self.websock_thread.received_result(msg_id), timeout=timeout
            )
            message = self.websock_thread.pop_result(msg_id)
            width = message["result"]["contentSize"]["width"]
            height = message["result"]["contentSize"]["height"]
            clip = dict(x=0, y=0, width=width, height=height, scale=1)
            deviceScaleFactor = 1
            screenOrientation = {"angle": 0, "type": "portraitPrimary"}
            self.send_to_chrome(
                method="Emulation.setDeviceMetricsOverride",
                params=dict(
                    mobile=False,
                    width=width,
                    height=height,
                    deviceScaleFactor=deviceScaleFactor,
                    screenOrientation=screenOrientation,
                ),
            )
            capture_params = {"format": "jpeg", "quality": 95, "clip": clip}
        else:
            capture_params = {"format": "jpeg", "quality": 95}
        self.websock_thread.expect_result(self._command_id.peek())
        msg_id = self.send_to_chrome(
            method="Page.captureScreenshot", params=capture_params
        )
        self._wait_for(
            lambda: self.websock_thread.received_result(msg_id), timeout=timeout
        )
        message = self.websock_thread.pop_result(msg_id)
        jpeg_bytes = base64.b64decode(message["result"]["data"])
        return jpeg_bytes

    def url(self, timeout=30):
        """
        Returns value of document.URL from the browser.
        """
        self.websock_thread.expect_result(self._command_id.peek())
        msg_id = self.send_to_chrome(
            method="Runtime.evaluate", params={"expression": "document.URL"}
        )
        self._wait_for(
            lambda: self.websock_thread.received_result(msg_id), timeout=timeout
        )
        message = self.websock_thread.pop_result(msg_id)
        return message["result"]["result"]["value"]

    def run_behavior(self, behavior_script, timeout=900):
        self.send_to_chrome(
            method="Runtime.evaluate",
            suppress_logging=True,
            params={"expression": behavior_script},
        )

        check_interval = min(timeout, 7)
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                logging.info("behavior reached hard timeout after %.1fs", elapsed)
                return

            brozzler.sleep(check_interval)

            self.websock_thread.expect_result(self._command_id.peek())
            msg_id = self.send_to_chrome(
                method="Runtime.evaluate",
                suppress_logging=True,
                params={"expression": "umbraBehaviorFinished()"},
            )
            try:
                self._wait_for(
                    lambda: self.websock_thread.received_result(msg_id), timeout=5
                )
                msg = self.websock_thread.pop_result(msg_id)
                if (
                    msg
                    and "result" in msg
                    and not ("exceptionDetails" in msg["result"])
                    and not (
                        "wasThrown" in msg["result"] and msg["result"]["wasThrown"]
                    )
                    and "result" in msg["result"]
                    and type(msg["result"]["result"]["value"]) == bool
                    and msg["result"]["result"]["value"]
                ):
                    self.logger.info("behavior decided it has finished")
                    return
            except BrowsingTimeout:
                pass

    def try_login(self, username, password, timeout=300):
        try_login_js = (
            brozzler.jinja2_environment()
            .get_template("try-login.js.j2")
            .render(username=username, password=password)
        )

        self.websock_thread.got_page_load_event = None
        self.send_to_chrome(
            method="Runtime.evaluate",
            suppress_logging=True,
            params={"expression": try_login_js},
        )

        # wait for tryLogin to finish trying (should be very very quick)
        start = time.time()
        while True:
            self.websock_thread.expect_result(self._command_id.peek())
            msg_id = self.send_to_chrome(
                method="Runtime.evaluate",
                params={
                    "expression": 'try { __brzl_tryLoginState } catch (e) { "maybe-submitted-form" }'
                },
            )
            try:
                self._wait_for(
                    lambda: self.websock_thread.received_result(msg_id), timeout=5
                )
                msg = self.websock_thread.pop_result(msg_id)
                if msg and "result" in msg and "result" in msg["result"]:
                    result = msg["result"]["result"]["value"]
                    if result == "login-form-not-found":
                        # we're done
                        return
                    elif result in ("submitted-form", "maybe-submitted-form"):
                        # wait for page load event below
                        self.logger.info(
                            "submitted a login form, waiting for another "
                            "page load event"
                        )
                        break
                    # else try again to get __brzl_tryLoginState

            except BrowsingTimeout:
                pass

            if time.time() - start > 30:
                raise BrowsingException(
                    "timed out trying to check if tryLogin finished"
                )

        # if we get here, we submitted a form, now we wait for another page
        # load event
        self._wait_for(lambda: self.websock_thread.got_page_load_event, timeout=timeout)


class Counter:
    def __init__(self):
        self.next_value = 0

    def __next__(self):
        try:
            return self.next_value
        finally:
            self.next_value += 1

    def peek(self):
        return self.next_value
