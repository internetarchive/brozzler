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
from brozzler.chrome import Chrome
import surt

class BrowsingException(Exception):
    pass

class NoBrowsersAvailable(Exception):
    pass

class BrowsingTimeout(BrowsingException):
    pass

class BrowserPool:
    logger = logging.getLogger(__module__ + '.' + __qualname__)

    BASE_PORT = 9200

    def __init__(self, size=3, **kwargs):
        '''
        Initializes the pool.

        Args:
            size: size of pool (default 3)
            **kwargs: arguments for Browser(...)
        '''
        self.size = size
        self._available = set()
        self._in_use = set()

        for i in range(0, size):
            browser = Browser(port=BrowserPool.BASE_PORT + i, **kwargs)
            self._available.add(browser)

        self._lock = threading.Lock()

    def acquire(self):
        '''
        Returns an available instance.

        Returns:
            browser from pool, if available

        Raises:
            NoBrowsersAvailable if none available
        '''
        with self._lock:
            try:
                browser = self._available.pop()
            except KeyError:
                raise NoBrowsersAvailable
            self._in_use.add(browser)
            return browser

    def release(self, browser):
        with self._lock:
            self._available.add(browser)
            self._in_use.remove(browser)

    def shutdown_now(self):
        self.logger.info(
                'shutting down browser pool (%s browsers in use)',
                len(self._in_use))
        with self._lock:
            for browser in self._available:
                browser.stop()
            for browser in self._in_use:
                browser.stop()

    def num_available(self):
        return len(self._available)

    def num_in_use(self):
        return len(self._in_use)

class Browser:
    '''
    Manages an instance of Chrome for browsing pages.
    '''
    logger = logging.getLogger(__module__ + '.' + __qualname__)

    def __init__(self, **kwargs):
        '''
        Initializes the Browser.

        Args:
            **kwargs: arguments for Chrome(...)
        '''
        self.chrome = Chrome(**kwargs)
        self.websocket_url = None
        self.is_browsing = False
        self._browser_controller = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self, **kwargs):
        '''
        Starts chrome if it's not running.

        Args:
            **kwargs: arguments for self.chrome.start(...)
        '''
        if not self.is_running():
            self.websocket_url = self.chrome.start(**kwargs)
            self._browser_controller = BrowserController(self.websocket_url)
            self._browser_controller.start()

    def stop(self):
        '''
        Stops chrome if it's running.
        '''
        try:
            if self._browser_controller:
                self._browser_controller.stop()
            self.websocket_url = None
            self.chrome.stop()
        except:
            self.logger.error('problem stopping', exc_info=True)

    def is_running(self):
        return self.websocket_url is not None

    def browse_page(
            self, page_url, ignore_cert_errors=False, extra_headers=None,
            user_agent=None, behavior_parameters=None,
            on_request=None, on_response=None, on_screenshot=None):
        '''
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
            on_request: callback to invoke on every Network.requestWillBeSent
                event, takes one argument, the json-decoded message (default
                None)
            on_response: callback to invoke on every Network.responseReceived
                event, takes one argument, the json-decoded message (default
                None)
            on_screenshot: callback to invoke when screenshot is obtained,
                takes one argument, the the raw jpeg bytes (default None)
                # XXX takes two arguments, the url of the page at the time the
                # screenshot was taken, and the raw jpeg bytes (default None)

        Returns:
            A tuple (final_page_url, outlinks).
            final_page_url: the url in the location bar at the end of the
                browse_page cycle, which could be different from the original
                page url if the page redirects, javascript has changed the url
                in the location bar, etc
            outlinks: a list of navigational links extracted from the page

        Raises:
            BrowsingException: if browsing the page fails
        '''
        if not self.is_running():
            raise BrowsingException('browser has not been started')
        if self.is_browsing:
            raise BrowsingException('browser is already busy browsing a page')
        self.is_browsing = True
        try:
            self._browser_controller.navigate_to_page(page_url, timeout=300)
            ## if login_credentials:
            ##     self._browser_controller.try_login(login_credentials) (5 min?)
            behavior_script = brozzler.behavior_script(
                    page_url, behavior_parameters)
            self._browser_controller.run_behavior(behavior_script, timeout=900)
            if on_screenshot:
                self._browser_controller.scroll_to_top()
                jpeg_bytes = self._browser_controller.screenshot()
                on_screenshot(jpeg_bytes)
            outlinks = self._browser_controller.extract_outlinks()
            ## for each hashtag not already visited:
            ##     navigate_to_hashtag (nothing to wait for so no timeout?)
            ##     if on_screenshot;
            ##         take screenshot (30 sec)
            ##     run behavior (3 min)
            ##     outlinks += retrieve_outlinks (60 sec)
            final_page_url = self._browser_controller.url()
            return final_page_url, outlinks
        except websocket.WebSocketConnectionClosedException as e:
            self.logger.error('websocket closed, did chrome die?')
            raise BrowsingException(e)
        finally:
            self.is_browsing = False

class Counter:
    def __init__(self):
        self.next_value = 0
    def __next__(self):
        try:
            return self.next_value
        finally:
            self.next_value += 1
    def peek_next(self):
        return self.next_value

class BrowserController:
    '''
    '''

    logger = logging.getLogger(__module__ + '.' + __qualname__)

    def __init__(self, websocket_url):
        self.websocket_url = websocket_url
        self._command_id = Counter()
        self._websock_thread = None
        self._websock_open = None
        self._result_messages = {}

    def _wait_for(self, callback, timeout=None):
        '''
        Spins until callback() returns truthy.
        '''
        start = time.time()
        while True:
            brozzler.sleep(0.5)
            if callback():
                return
            elapsed = time.time() - start
            if timeout and elapsed > timeout:
                raise BrowsingTimeout(
                        'timed out after %.1fs waiting for: %s' % (
                            elapsed, callback))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        if not self._websock_thread:
            calling_thread = threading.current_thread()

            def on_open(websock):
                self._websock_open = datetime.datetime.utcnow()
            def on_error(websock, e):
                '''
                Raises BrowsingException in the thread that called start()
                '''
                if isinstance(e, websocket.WebSocketConnectionClosedException):
                    self.logger.error('websocket closed, did chrome die?')
                else:
                    self.logger.error(
                            'exception from websocket receiver thread',
                            exc_info=1)
                brozzler.thread_raise(calling_thread, BrowsingException)

            # open websocket, start thread that receives messages
            self._websock = websocket.WebSocketApp(
                    self.websocket_url, on_open=on_open,
                    on_message=self._on_message, on_error=on_error)
            thread_name = 'WebsockThread:{}-{:%Y%m%d%H%M%S}'.format(
                    surt.handyurl.parse(self.websocket_url).port,
                    datetime.datetime.utcnow())
            self._websock_thread = threading.Thread(
                    target=self._websock.run_forever, name=thread_name,
                    daemon=True)
            self._websock_thread.start()
            self._wait_for(lambda: self._websock_open, timeout=10)

            # tell browser to send messages we're interested in
            self.send_to_chrome(method='Network.enable')
            self.send_to_chrome(method='Page.enable')
            self.send_to_chrome(method='Console.enable')
            self.send_to_chrome(method='Debugger.enable')
            self.send_to_chrome(method='Runtime.enable')

            # disable google analytics, see _handle_message() where breakpoint
            # is caught Debugger.paused
            self.send_to_chrome(
                    method='Debugger.setBreakpointByUrl',
                    params={
                        'lineNumber': 1,
                        'urlRegex': 'https?://www.google-analytics.com/analytics.js'})

    def stop(self, *args):
        if self._websock_thread:
            if (self._websock and self._websock.sock
                    and self._websock.sock.connected):
                self.logger.info('shutting down websocket connection')
                try:
                    self._websock.close()
                except BaseException as e:
                    self.logger.error(
                            'exception closing websocket %s - %s',
                            self._websock, e)

            if self._websock_thread != threading.current_thread():
                self._websock_thread.join(timeout=30)
                if self._websock_thread.is_alive():
                    self.logger.error(
                            '%s still alive 30 seconds after closing %s, will '
                            'forcefully nudge it again', self._websock_thread,
                            self._websock)
                    self._websock.keep_running = False
                    self._websock_thread.join(timeout=30)
                    if self._websock_thread.is_alive():
                        self.logger.critical(
                                '%s still alive 60 seconds after closing %s',
                                    self._websock_thread, self._websock)

    def _on_message(self, websock, message):
        try:
            self._handle_message(websock, message)
        except:
            self.logger.error(
                    'uncaught exception in _handle_message message=%s',
                    message, exc_info=True)

    def _handle_message(self, websock, json_message):
        message = json.loads(json_message)
        if 'method' in message:
            if message['method'] == 'Page.loadEventFired':
                self._got_page_load_event = datetime.datetime.utcnow()
            elif message['method'] == 'Debugger.paused':
                self._debugger_paused(message)
            elif message['method'] == 'Console.messageAdded':
                self.logger.debug(
                        '%s console.%s %s', self._websock.url,
                        message['params']['message']['level'],
                        message['params']['message']['text'])
        #     else:
        #         self.logger.debug("%s %s", message["method"], json_message)
        elif 'result' in message:
            if message['id'] in self._result_messages:
                self._result_messages[message['id']] = message
        #     else:
        #         self.logger.debug("%s", json_message)
        # else:
        #     self.logger.debug("%s", json_message)

    def _debugger_paused(self, message):
        # we hit the breakpoint set in start(), get rid of google analytics
        self.logger.debug('debugger paused! message=%s', message)
        scriptId = message['params']['callFrames'][0]['location']['scriptId']

        # replace script
        self.send_to_chrome(
                method='Debugger.setScriptSource',
                params={'scriptId': scriptId,
                    'scriptSource': 'console.log("google analytics is no more!");'})

        # resume execution
        self.send_to_chrome(method='Debugger.resume')

    def send_to_chrome(self, suppress_logging=False, **kwargs):
        msg_id = next(self._command_id)
        kwargs['id'] = msg_id
        msg = json.dumps(kwargs)
        if not suppress_logging:
            self.logger.debug('sending message to %s: %s', self._websock, msg)
        self._websock.send(msg)
        return msg_id

    def navigate_to_page(
            self, page_url, extra_headers=None, user_agent=None, timeout=300):
        '''
        '''
        headers = extra_headers or {}
        headers['Accept-Encoding'] = 'identity'
        self.send_to_chrome(
                method='Network.setExtraHTTPHeaders',
                params={'headers': headers})

        if user_agent:
            self.send_to_chrome(
                    method='Network.setUserAgentOverride',
                    params={'userAgent': user_agent})

        # navigate to the page!
        self.logger.info('navigating to page %s', page_url)
        self._got_page_load_event = None
        self.send_to_chrome(method='Page.navigate', params={'url': page_url})
        self._wait_for(lambda: self._got_page_load_event, timeout=timeout)

    OUTLINKS_JS = r'''
var __brzl_framesDone = new Set();
var __brzl_compileOutlinks = function(frame) {
    __brzl_framesDone.add(frame);
    if (frame && frame.document) {
        var outlinks = Array.prototype.slice.call(
                frame.document.querySelectorAll('a[href]'));
        for (var i = 0; i < frame.frames.length; i++) {
            if (frame.frames[i] && !__brzl_framesDone.has(frame.frames[i])) {
                outlinks = outlinks.concat(
                            __brzl_compileOutlinks(frame.frames[i]));
            }
        }
    }
    return outlinks;
}
__brzl_compileOutlinks(window).join('\n');
'''
    def extract_outlinks(self, timeout=60):
        self.logger.info('extracting outlinks')
        self._result_messages[self._command_id.peek_next()] = None
        msg_id = self.send_to_chrome(
                method='Runtime.evaluate',
                params={'expression': self.OUTLINKS_JS})
        self._wait_for(
                lambda: self._result_messages.get(msg_id), timeout=timeout)
        message = self._result_messages.pop(msg_id)
        if message['result']['result']['value']:
            return frozenset(message['result']['result']['value'].split('\n'))
        else:
            self._outlinks = frozenset()

    def screenshot(self, timeout=30):
        self.logger.info('taking screenshot')
        self._result_messages[self._command_id.peek_next()] = None
        msg_id = self.send_to_chrome(method='Page.captureScreenshot')
        self._wait_for(
                lambda: self._result_messages.get(msg_id), timeout=timeout)
        message = self._result_messages.pop(msg_id)
        jpeg_bytes = base64.b64decode(message['result']['data'])
        return jpeg_bytes

    def scroll_to_top(self, timeout=30):
        self.logger.info('scrolling to top')
        self._result_messages[self._command_id.peek_next()] = None
        msg_id = self.send_to_chrome(
                    method='Runtime.evaluate',
                    params={'expression': 'window.scrollTo(0, 0);'})
        self._wait_for(
                lambda: self._result_messages.get(msg_id), timeout=timeout)
        self._result_messages.pop(msg_id)

    def url(self, timeout=30):
        '''
        Returns value of document.URL from the browser.
        '''
        self._result_messages[self._command_id.peek_next()] = None
        msg_id = self.send_to_chrome(
                method='Runtime.evaluate',
                params={'expression': 'document.URL'})
        self._wait_for(
                lambda: self._result_messages.get(msg_id), timeout=timeout)
        message = self._result_messages.pop(msg_id)
        return message['result']['result']['value']

    def run_behavior(self, behavior_script, timeout=900):
        self.send_to_chrome(
                method='Runtime.evaluate', suppress_logging=True,
                params={'expression': behavior_script})

        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                logging.info(
                        'behavior reached hard timeout after %.1fs', elapsed)
                return

            brozzler.sleep(7)

            self._result_messages[self._command_id.peek_next()] = None
            msg_id = self.send_to_chrome(
                     method='Runtime.evaluate', suppress_logging=True,
                     params={'expression': 'umbraBehaviorFinished()'})
            try:
                self._wait_for(
                        lambda: self._result_messages.get(msg_id), timeout=5)
                msg = self._result_messages.get(msg_id)
                if (msg and 'result' in msg
                        and not ('wasThrown' in msg['result']
                            and msg['result']['wasThrown'])
                        and 'result' in msg['result']
                        and type(msg['result']['result']['value']) == bool
                        and msg['result']['result']['value']):
                    self.logger.info('behavior decided it has finished')
                    return
            except BrowsingTimeout:
                pass


