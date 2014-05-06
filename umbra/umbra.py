#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import sys

# logging.basicConfig(stream=sys.stdout, level=logging.INFO,
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
        format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')

import os
import argparse
import json
import urllib.request, urllib.error, urllib.parse
import itertools
import websocket
import time
import uuid
import threading
import subprocess
import signal
import kombu
import tempfile
from umbra.behaviors import Behavior

class UmbraWorker:
    """Runs chrome/chromium to synchronously browse one page at a time using
    worker.browse_page(). Currently the implementation starts up a new instance
    of chrome for each page browsed, always on the same debug port. (In the
    future, it may keep the browser running indefinitely.)"""
    logger = logging.getLogger('umbra.UmbraWorker')

    HARD_TIMEOUT_SECONDS = 20 * 60

    def __init__(self, umbra, chrome_port=9222, chrome_exe='chromium-browser', chrome_wait=10, client_id='request'):
        self.command_id = itertools.count(1)
        self.lock = threading.Lock()
        self.umbra = umbra
        self.chrome_port = chrome_port
        self.chrome_exe = chrome_exe
        self.chrome_wait = chrome_wait
        self.client_id = client_id
        self._behavior = None
        self.websock = None

    def browse_page(self, url, url_metadata):
        """Synchronously browse a page and run behaviors."""
        with self.lock:
            self.url = url
            self.url_metadata = url_metadata
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
                        elif time.time() - start > UmbraWorker.HARD_TIMEOUT_SECONDS:
                            self.logger.info("finished browsing page, reached hard timeout of {} seconds url={}".format(UmbraWorker.HARD_TIMEOUT_SECONDS, self.url))
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

    # XXX should this class know anything about amqp? or should it
    # delegate this back up to the Umbra class?
    def _send_request_to_amqp(self, chrome_msg):
        payload = chrome_msg['params']['request']
        payload['parentUrl'] = self.url
        payload['parentUrlMetadata'] = self.url_metadata
        self.logger.debug('sending to amqp exchange={} routing_key={} payload={}'.format(self.umbra.umbra_exchange.name, self.client_id, payload))
        with self.umbra.producer_lock:
            self.umbra.producer.publish(payload,
                    exchange=self.umbra.umbra_exchange,
                    routing_key=self.client_id)

    def _handle_message(self, websock, message):
        # self.logger.debug("message from {} - {}".format(websock.url, message[:95]))
        # self.logger.debug("message from {} - {}".format(websock.url, message))
        message = json.loads(message)
        if "method" in message and message["method"] == "Network.requestWillBeSent":
            if self._behavior:
                self._behavior.notify_of_activity()
            if not message["params"]["request"]["url"].lower().startswith("data:"):
                self._send_request_to_amqp(message)
            else:
                self.logger.debug("ignoring data url {}".format(message["params"]["request"]["url"][:80]))
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


class Umbra:
    """Consumes amqp messages representing requests to browse urls, from the
    amqp queue "urls" on exchange "umbra". Incoming amqp message is a json
    object with 3 attributes:
      {
        "clientId": "umbra.client.123",
        "url": "http://example.com/my_fancy_page",
        "metadata": {"arbitrary":"fields", "etc":4}
      }

    "url" is the url to browse.

    "clientId" uniquely idenfities the client of
    umbra. Umbra uses the clientId to direct information via amqp back to the
    client. It sends this information on that same "umbra" exchange, and uses
    the clientId as the amqp routing key.

    Each url requested in the browser is published to amqp this way. The
    outgoing amqp message is a json object:

      {
        'url': 'http://example.com/images/embedded_thing.jpg',
        'method': 'GET',
        'headers': {'User-Agent': '...', 'Accept': '...'}
        'parentUrl': 'http://example.com/my_fancy_page',
        'parentUrlMetadata': {"arbitrary":"fields", "etc":4},
      }

    POST requests have an additional field, postData.
    """

    logger = logging.getLogger('umbra.Umbra')

    def __init__(self, amqp_url, chrome_exe, browser_wait):
        self.amqp_url = amqp_url
        self.chrome_exe = chrome_exe
        self.browser_wait = browser_wait
        self.producer = None
        self.producer_lock = None
        self.workers = {}
        self.workers_lock = threading.Lock()
        self.amqp_thread = threading.Thread(target=self._consume_amqp)
        self.amqp_stop = threading.Event()
        self.amqp_thread.start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self.amqp_stop.set()
        self.amqp_thread.join()

    def _consume_amqp(self):
        while not self.amqp_stop.is_set():
            try:
                self.umbra_exchange = kombu.Exchange(name='umbra', type='direct', durable=True)
                url_queue = kombu.Queue('urls', routing_key='url', exchange=self.umbra_exchange)
                self.logger.info("connecting to amqp exchange={} at {}".format(self.umbra_exchange.name, self.amqp_url))
                with kombu.Connection(self.amqp_url) as conn:
                    if self.producer_lock is None:
                        self.producer_lock = threading.Lock()
                    with self.producer_lock:
                        self.producer = conn.Producer(serializer='json')
                    with conn.Consumer(url_queue, callbacks=[self._browse_page_requested]) as consumer:
                        import socket
                        while not self.amqp_stop.is_set():
                            try:
                                conn.drain_events(timeout=0.5)
                            except socket.timeout:
                                pass
            except BaseException as e:
                self.logger.error("amqp exception {}".format(e))
                self.logger.error("attempting to reopen amqp connection")

    def _browse_page_requested(self, body, message):
        """First waits for the UmbraWorker for the client body['clientId'] to
        become available, or creates a new worker if this clientId has not been
        served before. Starts a worker browsing the page asynchronously, then
        acknowledges the amqp message, which lets the server know it can be
        removed from the queue."""
        client_id = body['clientId']
        with self.workers_lock:
            if not client_id in self.workers:
                port = 9222 + len(self.workers)
                t = UmbraWorker(umbra=self, chrome_port=port,
                        chrome_exe=self.chrome_exe,
                        chrome_wait=self.browser_wait,
                        client_id=client_id)
                self.workers[client_id] = t

        def browse_page_async():
            self.logger.info('client_id={} body={}'.format(client_id, body))
            self.workers[client_id].browse_page(body['url'], body['metadata'])

        threading.Thread(target=browse_page_async).start()

        message.ack()


class Chrome:
    logger = logging.getLogger('umbra.Chrome')

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
                "--remote-debugging-port=%s" % self.port,
                "--disable-web-sockets", "--disable-cache",
                "--window-size=1100,900", "--enable-logging",
                "--no-default-browser-check", "--disable-first-run-ui", "--no-first-run",
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

def main():
    import faulthandler
    faulthandler.register(signal.SIGQUIT)

    arg_parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]),
            description='umbra - Browser automation tool',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    arg_parser.add_argument('-w', '--browser-wait', dest='browser_wait', default='10',
            help='Seconds to wait for browser initialization')
    arg_parser.add_argument('-e', '--executable', dest='executable', default='chromium-browser',
            help='Executable to use to invoke chrome')
    arg_parser.add_argument('-u', '--url', dest='amqp_url', default='amqp://guest:guest@localhost:5672/%2f',
            help='URL identifying the amqp server to talk to')
    args = arg_parser.parse_args(args=sys.argv[1:])

    umbra = Umbra(args.amqp_url, args.executable, args.browser_wait)
    try:
        while True:
            time.sleep(0.5)
    except:
        pass
    finally:
        umbra.shutdown()


if __name__ == "__main__":
    main()

