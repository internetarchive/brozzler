'''
brozzler/browser.py - manages the browsers for brozzler

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
import socket
import urlcanon

class BrowsingException(Exception):
    pass

class NoBrowsersAvailable(Exception):
    pass

class BrowsingTimeout(BrowsingException):
    pass

class BrowserPool:
    '''
    Manages pool of browsers. Automatically chooses available port for the
    debugging protocol.
    '''
    logger = logging.getLogger(__module__ + '.' + __qualname__)

    def __init__(self, size=3, **kwargs):
        '''
        Initializes the pool.

        Args:
            size: size of pool (default 3)
            **kwargs: arguments for Browser(...)
        '''
        self.size = size
        self.kwargs = kwargs
        self._in_use = set()
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
            if len(self._in_use) >= self.size:
                raise NoBrowsersAvailable

            # choose available port
            sock = socket.socket()
            sock.bind(('0.0.0.0', 0))
            port = sock.getsockname()[1]
            sock.close()

            browser = Browser(port=port, **self.kwargs)
            self._in_use.add(browser)
            return browser

    def release(self, browser):
        browser.stop()  # make sure
        with self._lock:
            self._in_use.remove(browser)

    def shutdown_now(self):
        self.logger.info(
                'shutting down browser pool (%s browsers in use)',
                len(self._in_use))
        with self._lock:
            for browser in self._in_use:
                browser.stop()

    def num_available(self):
        return self.size - len(self._in_use)

    def num_in_use(self):
        return len(self._in_use)

class WebsockReceiverThread(threading.Thread):
    logger = logging.getLogger(__module__ + '.' + __qualname__)

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
        self.reached_limit = None

        self.on_request = None
        self.on_response = None

        self._result_messages = {}

    def expect_result(self, msg_id):
        self._result_messages[msg_id] = None

    def received_result(self, msg_id):
        return bool(self._result_messages.get(msg_id))

    def pop_result(self, msg_id):
        return self._result_messages.pop(msg_id)

    def _on_close(self, websock):
        pass
        # self.logger.info('GOODBYE GOODBYE WEBSOCKET')

    def _on_open(self, websock):
        self.is_open = True

    def _on_error(self, websock, e):
        '''
        Raises BrowsingException in the thread that created this instance.
        '''
        if isinstance(e, (
            websocket.WebSocketConnectionClosedException,
            ConnectionResetError)):
            self.logger.error('websocket closed, did chrome die?')
        else:
            self.logger.error(
                    'exception from websocket receiver thread',
                    exc_info=1)
        brozzler.thread_raise(self.calling_thread, BrowsingException)

    def run(self):
        # ping_timeout is used as the timeout for the call to select.select()
        # in addition to its documented purpose, and must have a value to avoid
        # hangs in certain situations
        self.websock.run_forever(ping_timeout=0.5)

    def _on_message(self, websock, message):
        try:
            self._handle_message(websock, message)
        except:
            self.logger.error(
                    'uncaught exception in _handle_message message=%s',
                    message, exc_info=True)

    def _debugger_paused(self, message):
        # we hit the breakpoint set in start(), get rid of google analytics
        self.logger.debug('debugger paused! message=%s', message)
        scriptId = message['params']['callFrames'][0]['location']['scriptId']

        # replace script
        self.websock.send(
                json.dumps(dict(
                    id=0, method='Debugger.setScriptSource',
                    params={'scriptId': scriptId,
                        'scriptSource': 'console.log("google analytics is no more!");'})))

        # resume execution
        self.websock.send(json.dumps(dict(id=0, method='Debugger.resume')))

    def _network_response_received(self, message):
        if (message['params']['response']['status'] == 420
                and 'Warcprox-Meta' in CaseInsensitiveDict(
                    message['params']['response']['headers'])):
            if not self.reached_limit:
                warcprox_meta = json.loads(CaseInsensitiveDict(
                    message['params']['response']['headers'])['Warcprox-Meta'])
                self.reached_limit = brozzler.ReachedLimit(
                        warcprox_meta=warcprox_meta)
                self.logger.info('reached limit %s', self.reached_limit)
                brozzler.thread_raise(
                        self.calling_thread, brozzler.ReachedLimit)
            else:
                self.logger.info(
                        'reached limit but self.reached_limit is already set, '
                        'assuming the calling thread is already handling this')
        if self.on_response:
            self.on_response(message)

    def _javascript_dialog_opening(self, message):
        self.logger.info('javascript dialog opened: %s', message)
        if message['params']['type'] == 'alert':
            accept = True
        else:
            accept = False
        self.websock.send(
                json.dumps(dict(
                    id=0, method='Page.handleJavaScriptDialog',
                    params={'accept': accept})))

    def _handle_message(self, websock, json_message):
        message = json.loads(json_message)
        if 'method' in message:
            if message['method'] == 'Page.loadEventFired':
                self.got_page_load_event = datetime.datetime.utcnow()
            elif message['method'] == 'Network.responseReceived':
                self._network_response_received(message)
            elif message['method'] == 'Network.requestWillBeSent':
                if self.on_request:
                    self.on_request(message)
            elif message['method'] == 'Debugger.paused':
                self._debugger_paused(message)
            elif message['method'] == 'Inspector.targetCrashed':
                self.logger.error(
                        '''chrome tab went "aw snap" or "he's dead jim"!''')
                brozzler.thread_raise(self.calling_thread, BrowsingException)
            elif message['method'] == 'Console.messageAdded':
                self.logger.debug(
                        'console.%s %s', message['params']['message']['level'],
                        message['params']['message']['text'])
            elif message['method'] == 'Page.javascriptDialogOpening':
                self._javascript_dialog_opening(message)
            elif (message['method'] == 'Network.loadingFailed'
                    and 'params' in message and 'errorText' in message['params']
                    and message['params']['errorText'] == 'net::ERR_PROXY_CONNECTION_FAILED'):
                brozzler.thread_raise(self.calling_thread, brozzler.ProxyError)
            # else:
            #     self.logger.debug("%s %s", message["method"], json_message)
        elif 'result' in message:
            if message['id'] in self._result_messages:
                self._result_messages[message['id']] = message
       #      else:
       #          self.logger.debug("%s", json_message)
       #  else:
       #      self.logger.debug("%s", json_message)

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
        self.websock_url = None
        self.websock = None
        self.websock_thread = None
        self.is_browsing = False
        self._command_id = Counter()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def _wait_for(self, callback, timeout=None):
        '''
        Spins until callback() returns truthy.
        '''
        start = time.time()
        while True:
            if callback():
                return
            elapsed = time.time() - start
            if timeout and elapsed > timeout:
                raise BrowsingTimeout(
                        'timed out after %.1fs waiting for: %s' % (
                            elapsed, callback))
            brozzler.sleep(0.5)

    def send_to_chrome(self, suppress_logging=False, **kwargs):
        msg_id = next(self._command_id)
        kwargs['id'] = msg_id
        msg = json.dumps(kwargs)
        logging.log(
                brozzler.TRACE if suppress_logging else logging.DEBUG,
                'sending message to %s: %s', self.websock, msg)
        self.websock.send(msg)
        return msg_id

    def start(self, **kwargs):
        '''
        Starts chrome if it's not running.

        Args:
            **kwargs: arguments for self.chrome.start(...)
        '''
        if not self.is_running():
            self.websock_url = self.chrome.start(**kwargs)
            self.websock = websocket.WebSocketApp(self.websock_url)
            self.websock_thread = WebsockReceiverThread(
                    self.websock, name='WebsockThread:%s' % self.chrome.port)
            self.websock_thread.start()

            self._wait_for(lambda: self.websock_thread.is_open, timeout=10)

            # tell browser to send us messages we're interested in
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

    def stop(self):
        '''
        Stops chrome if it's running.
        '''
        try:
            if (self.websock and self.websock.sock
                    and self.websock.sock.connected):
                self.logger.info('shutting down websocket connection')
                try:
                    self.websock.close()
                except BaseException as e:
                    self.logger.error(
                            'exception closing websocket %s - %s',
                            self.websock, e)

            self.chrome.stop()

            if self.websock_thread and (
                    self.websock_thread != threading.current_thread()):
                self.websock_thread.join(timeout=30)
                if self.websock_thread.is_alive():
                    self.logger.error(
                            '%s still alive 30 seconds after closing %s, will '
                            'forcefully nudge it again', self.websock_thread,
                            self.websock)
                    self.websock.keep_running = False
                    self.websock_thread.join(timeout=30)
                    if self.websock_thread.is_alive():
                        self.logger.critical(
                                '%s still alive 60 seconds after closing %s',
                                    self.websock_thread, self.websock)

            self.websock_url = None
        except:
            self.logger.error('problem stopping', exc_info=True)

    def is_running(self):
        return self.websock_url is not None

    def browse_page(
            self, page_url, ignore_cert_errors=False, extra_headers=None,
            user_agent=None, behavior_parameters=None,
            on_request=None, on_response=None, on_screenshot=None,
            username=None, password=None, hashtags=None):
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
            brozzler.ProxyError: in case of proxy connection error
            BrowsingException: if browsing the page fails in some other way
        '''
        if not self.is_running():
            raise BrowsingException('browser has not been started')
        if self.is_browsing:
            raise BrowsingException('browser is already busy browsing a page')
        self.is_browsing = True
        if on_request:
            self.websock_thread.on_request = on_request
        if on_response:
            self.websock_thread.on_response = on_response
        try:
            with brozzler.thread_accept_exceptions():
                self.configure_browser(
                        extra_headers=extra_headers,
                        user_agent=user_agent)
                self.navigate_to_page(page_url, timeout=300)
                if password:
                    self.try_login(username, password, timeout=300)
                    # if login redirected us, return to page_url
                    if page_url != self.url().split('#')[0]:
                        self.logger.debug(
                            'login navigated away from %s; returning!',
                            page_url)
                        self.navigate_to_page(page_url, timeout=300)
                if on_screenshot:
                    jpeg_bytes = self.screenshot()
                    on_screenshot(jpeg_bytes)
                behavior_script = brozzler.behavior_script(
                        page_url, behavior_parameters)
                self.run_behavior(behavior_script, timeout=900)
                outlinks = self.extract_outlinks()
                self.visit_hashtags(page_url, hashtags, outlinks)
                final_page_url = self.url()
                return final_page_url, outlinks
        except brozzler.ReachedLimit:
            # websock_thread has stashed the ReachedLimit exception with
            # more information, raise that one
            raise self.websock_thread.reached_limit
        except websocket.WebSocketConnectionClosedException as e:
            self.logger.error('websocket closed, did chrome die?')
            raise BrowsingException(e)
        finally:
            self.is_browsing = False
            self.websock_thread.on_request = None
            self.websock_thread.on_response = None

    def visit_hashtags(self, page_url, hashtags, outlinks):
        _hashtags = set(hashtags or [])
        for outlink in outlinks:
            url = urlcanon.whatwg(outlink)
            hashtag = (url.hash_sign + url.fragment).decode('utf-8')
            urlcanon.canon.remove_fragment(url)
            if hashtag and str(url) == page_url:
                _hashtags.add(hashtag)
        # could inject a script that listens for HashChangeEvent to figure
        # out which hashtags were visited already and skip those
        for hashtag in _hashtags:
            # navigate_to_hashtag (nothing to wait for so no timeout?)
            self.logger.debug('navigating to hashtag %s', hashtag)
            url = urlcanon.whatwg(page_url)
            url.hash_sign = b'#'
            url.fragment = hashtag[1:].encode('utf-8')
            self.send_to_chrome(
                    method='Page.navigate', params={'url': str(url)})
            time.sleep(5) # um.. wait for idleness or something?
            # take another screenshot?
            # run behavior again with short timeout?
            # retrieve outlinks again and append to list?

    def configure_browser(self, extra_headers=None, user_agent=None):
        headers = extra_headers or {}
        headers['Accept-Encoding'] = 'identity'
        self.send_to_chrome(
                method='Network.setExtraHTTPHeaders',
                params={'headers': headers})

        if user_agent:
            self.send_to_chrome(
                    method='Network.setUserAgentOverride',
                    params={'userAgent': user_agent})

    def navigate_to_page(self, page_url, timeout=300):
        self.logger.info('navigating to page %s', page_url)
        self.websock_thread.got_page_load_event = None
        self.send_to_chrome(method='Page.navigate', params={'url': page_url})
        self._wait_for(
                lambda: self.websock_thread.got_page_load_event,
                timeout=timeout)

    def extract_outlinks(self, timeout=60):
        self.logger.info('extracting outlinks')
        self.websock_thread.expect_result(self._command_id.peek())
        js = brozzler.jinja2_environment().get_template(
                'extract-outlinks.js').render()
        msg_id = self.send_to_chrome(
                method='Runtime.evaluate', params={'expression': js})
        self._wait_for(
                lambda: self.websock_thread.received_result(msg_id),
                timeout=timeout)
        message = self.websock_thread.pop_result(msg_id)
        if ('result' in message and 'result' in message['result']
                and 'value' in message['result']['result']):
            if message['result']['result']['value']:
                return frozenset(
                        message['result']['result']['value'].split('\n'))
            else:
                # no links found
                return frozenset()
        else:
            self.logger.error(
                    'problem extracting outlinks, result message: %s', message)
            return frozenset()

    def screenshot(self, timeout=30):
        self.logger.info('taking screenshot')
        self.websock_thread.expect_result(self._command_id.peek())
        msg_id = self.send_to_chrome(method='Page.captureScreenshot')
        self._wait_for(
                lambda: self.websock_thread.received_result(msg_id),
                timeout=timeout)
        message = self.websock_thread.pop_result(msg_id)
        jpeg_bytes = base64.b64decode(message['result']['data'])
        return jpeg_bytes

    def url(self, timeout=30):
        '''
        Returns value of document.URL from the browser.
        '''
        self.websock_thread.expect_result(self._command_id.peek())
        msg_id = self.send_to_chrome(
                method='Runtime.evaluate',
                params={'expression': 'document.URL'})
        self._wait_for(
                lambda: self.websock_thread.received_result(msg_id),
                timeout=timeout)
        message = self.websock_thread.pop_result(msg_id)
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

            self.websock_thread.expect_result(self._command_id.peek())
            msg_id = self.send_to_chrome(
                     method='Runtime.evaluate', suppress_logging=True,
                     params={'expression': 'umbraBehaviorFinished()'})
            try:
                self._wait_for(
                        lambda: self.websock_thread.received_result(msg_id),
                        timeout=5)
                msg = self.websock_thread.pop_result(msg_id)
                if (msg and 'result' in msg
                        and not ('exceptionDetails' in msg['result'])
                        and not ('wasThrown' in msg['result']
                            and msg['result']['wasThrown'])
                        and 'result' in msg['result']
                        and type(msg['result']['result']['value']) == bool
                        and msg['result']['result']['value']):
                    self.logger.info('behavior decided it has finished')
                    return
            except BrowsingTimeout:
                pass

    def try_login(self, username, password, timeout=300):
        try_login_js = brozzler.jinja2_environment().get_template(
                'try-login.js.j2').render(
                        username=username, password=password)

        self.websock_thread.got_page_load_event = None
        self.send_to_chrome(
                method='Runtime.evaluate', suppress_logging=True,
                params={'expression': try_login_js})

        # wait for tryLogin to finish trying (should be very very quick)
        start = time.time()
        while True:
            self.websock_thread.expect_result(self._command_id.peek())
            msg_id = self.send_to_chrome(
                method='Runtime.evaluate',
                params={'expression': 'try { __brzl_tryLoginState } catch (e) { "maybe-submitted-form" }'})
            try:
                self._wait_for(
                        lambda: self.websock_thread.received_result(msg_id),
                        timeout=5)
                msg = self.websock_thread.pop_result(msg_id)
                if (msg and 'result' in msg
                        and 'result' in msg['result']):
                    result = msg['result']['result']['value']
                    if result == 'login-form-not-found':
                        # we're done
                        return
                    elif result in ('submitted-form', 'maybe-submitted-form'):
                        # wait for page load event below
                        self.logger.info(
                                'submitted a login form, waiting for another '
                                'page load event')
                        break
                    # else try again to get __brzl_tryLoginState

            except BrowsingTimeout:
                pass

            if time.time() - start > 30:
                raise BrowsingException(
                        'timed out trying to check if tryLogin finished')

        # if we get here, we submitted a form, now we wait for another page
        # load event
        self._wait_for(
                lambda: self.websock_thread.got_page_load_event,
                timeout=timeout)

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


