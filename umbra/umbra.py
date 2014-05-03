#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import os, sys, argparse
# logging.basicConfig(stream=sys.stdout, level=logging.INFO,
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
        format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')

from json import dumps, loads
import urllib.request, urllib.error, urllib.parse
from itertools import count
import websocket
import time
import uuid
import threading
import subprocess
import signal
from kombu import Connection, Exchange, Queue
import tempfile
from umbra import behaviors

class UmbraWorker:
    logger = logging.getLogger('umbra.UmbraWorker')

    def __init__(self, umbra, chrome_port=9222, chrome_exe='chromium-browser', chrome_wait=10, client_id='request'):
        self.command_id = count(1)
        self.lock = threading.Lock()
        self.umbra = umbra
        self.chrome_port = chrome_port
        self.chrome_exe = chrome_exe
        self.chrome_wait = chrome_wait
        self.client_id = client_id
        self.page_done = threading.Event()
        self.idle_timer = None
        self.hard_stop_timer = None

    def browse_page(self, url, url_metadata):
        with self.lock:
            self.url = url
            self.url_metadata = url_metadata
            with tempfile.TemporaryDirectory() as user_data_dir:
                with Chrome(self.chrome_port, self.chrome_exe, self.chrome_wait, user_data_dir) as websocket_url:
                    websock = websocket.WebSocketApp(websocket_url,
                            on_open=self.visit_page, on_message=self.handle_message)
                    websock_thread = threading.Thread(target=websock.run_forever)
                    websock_thread.start()

                    self.page_done.clear()
                    self._reset_idle_timer()
                    while not self.page_done.is_set():
                        time.sleep(0.5)

                    websock.close()
                    self.idle_timer = None

    def _reset_idle_timer(self):
        def _idle_timeout():
            self.logger.debug('idle timeout')
            self.page_done.set()
            if self.hard_stop_timer:
                self.hard_stop_timer.cancel()

        def _hard_timeout():
            self.logger.debug('hard timeout')
            self.page_done.set()
            if self.idle_timer:
                self.idle_timer.cancel()

        if self.idle_timer:
            self.idle_timer.cancel()

        self.idle_timer = threading.Timer(30, _idle_timeout)
        self.idle_timer.start()

        if not self.hard_stop_timer: # 15 minutes is as long as we should give 1 page
            self.hard_stop_timer = threading.Timer(900, _hard_timeout)
            self.hard_stop_timer.start()

    def visit_page(self, websock):
        msg = dumps(dict(method="Network.enable", id=next(self.command_id)))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

        msg = dumps(dict(method="Page.enable", id=next(self.command_id)))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

        msg = dumps(dict(method="Console.enable", id=next(self.command_id)))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

        msg = dumps(dict(method="Debugger.enable", id=next(self.command_id)))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

        msg = dumps(dict(method="Debugger.setBreakpointByUrl", id=next(self.command_id), params={"lineNumber": 1, "urlRegex":"https?://www.google-analytics.com/analytics.js"}))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

        msg = dumps(dict(method="Page.navigate", id=next(self.command_id), params={"url": self.url}))
        self.logger.debug('sending message to {}: {}'.format(websock, msg))
        websock.send(msg)

    def send_request_to_amqp(self, chrome_msg):
        payload = chrome_msg['params']['request']
        payload['parentUrl'] = self.url
        payload['parentUrlMetadata'] = self.url_metadata
        self.logger.debug('sending to amqp exchange={} routing_key={} payload={}'.format(self.umbra.umbra_exchange.name, self.client_id, payload))
        with self.umbra.producer_lock:
            self.umbra.producer.publish(payload,
                    exchange=self.umbra.umbra_exchange,
                    routing_key=self.client_id)

    def handle_message(self, websock, message):
        # self.logger.debug("message from {} - {}".format(websock.url, message[:95]))
        # self.logger.debug("message from {} - {}".format(websock.url, message))
        message = loads(message)
        if "method" in message and message["method"] == "Network.requestWillBeSent":
            self._reset_idle_timer()
            if not message["params"]["request"]["url"].lower().startswith("data:"):
                self.send_request_to_amqp(message)
            else:
                self.logger.debug("ignoring data url {}".format(message["params"]["request"]["url"][:80]))
        elif "method" in message and message["method"] == "Page.loadEventFired":
            self.logger.debug("Page.loadEventFired, starting behaviors url={} message={}".format(self.url, message))
            behaviors.execute(self.url, websock, self.command_id)
        elif "method" in message and message["method"] == "Console.messageAdded":
            self.logger.debug("{} console {} {}".format(websock.url,
                message["params"]["message"]["level"],
                message["params"]["message"]["text"]))
        elif "method" in message and message["method"] == "Debugger.paused":
            self.logger.debug("debugger paused! message={}".format(message))
            scriptId = message['params']['callFrames'][0]['location']['scriptId']

            msg = dumps(dict(method="Debugger.setScriptSource", id=next(self.command_id), params={"scriptId": scriptId, "scriptSource":"console.log('google analytics is no more!');"}))
            self.logger.debug('sending message to {}: {}'.format(websock, msg))
            websock.send(msg)

            msg = dumps(dict(method="Debugger.resume", id=next(self.command_id)))
            self.logger.debug('sending message to {}: {}'.format(websock, msg))
            websock.send(msg)


class Umbra:
    logger = logging.getLogger('umbra.Umbra')

    def __init__(self, amqp_url, chrome_exe, browser_wait):
        self.amqp_url = amqp_url
        self.chrome_exe = chrome_exe
        self.browser_wait = browser_wait
        self.producer = None
        self.producer_lock = None
        self.workers = {}
        self.workers_lock = threading.Lock()
        self.amqp_thread = threading.Thread(target=self.consume_amqp)
        self.amqp_stop = threading.Event()
        self.amqp_thread.start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self.amqp_stop.set()
        self.amqp_thread.join()

    def consume_amqp(self):
        while not self.amqp_stop.is_set():
            try:
                self.umbra_exchange = Exchange(name='umbra', type='direct', durable=True)
                url_queue = Queue('urls', routing_key='url', exchange=self.umbra_exchange)
                self.logger.info("connecting to amqp exchange={} at {}".format(self.umbra_exchange.name, self.amqp_url))
                with Connection(self.amqp_url) as conn:
                    if self.producer_lock is None:
                        self.producer_lock = threading.Lock()
                    with self.producer_lock:
                        self.producer = conn.Producer(serializer='json')
                    with conn.Consumer(url_queue, callbacks=[self.fetch_url]) as consumer:
                        import socket
                        while not self.amqp_stop.is_set():
                            try:
                                conn.drain_events(timeout=0.5)
                            except socket.timeout:
                                pass
            except BaseException as e:
                self.logger.error("amqp exception {}".format(e))
                self.logger.error("attempting to reopen amqp connection")

    def fetch_url(self, body, message):
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
        return loads(json)

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
                all_debug_info = loads(raw_json.decode('utf-8'))
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

