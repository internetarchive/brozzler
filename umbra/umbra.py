#!/usr/bin/env python
# vim: set sw=4 et:

from json import dumps, loads
from itertools import count
import os,sys,argparse, urllib.request, urllib.error, urllib.parse
import websocket
import time
import uuid
import logging
import threading
from kombu import Connection, Exchange, Queue

class Umbra:
    logger = logging.getLogger('umbra.Umbra')
    def __init__(self, amqp_url, chrome_args):
        self.producer = None
        self.amqp_url = amqp_url
        self.chrome_args = chrome_args
        self.producer_lock = threading.Lock()
        self.consume_amqp()

    def watchdog(self, command_id):
        def wrapped():
            timer = None
            while True:
                ws = yield
                if timer:
                    self.logger.info("Cancelling")
                    timer.cancel()
                def go():
                    close_exp = "window.open('', '_self', ''); window.close(); "
                    ws.send(dumps(dict(method="Runtime.evaluate", params={"expression": close_exp}, id=next(command_id))))
                    self.logger.info("Going")
                    ws.close()
                timer = threading.Timer(10, go)
                timer.start()
        result = wrapped()
        next(result)
        return result

    def get_message_handler(self, url, url_metadata, command_id):
        this_watchdog = self.watchdog(command_id)
        def handle_message(ws, message):
            this_watchdog.send(ws)
            message = loads(message)
            if "method" in message.keys() and message["method"] == "Network.requestWillBeSent":
                to_send = {}
                to_send.update(message['params']['request'])
                to_send.update(dict(parentUrl=url,parentUrlMetadata=url_metadata))
                self.logger.debug('sending to amqp: {}'.format(to_send))
                with self.producer_lock:
                    self.producer.publish(to_send,
                            routing_key='request',
                            exchange=self.umbra_exchange)
        return handle_message

    def consume_amqp(self):
        self.umbra_exchange = Exchange('umbra', 'direct', durable=True)
        url_queue = Queue('urls', routing_key='url', exchange=self.umbra_exchange)
        self.logger.info("connecting to amqp {} at {}".format(repr(self.umbra_exchange), self.amqp_url))
        with Connection(self.amqp_url) as conn:
            self.producer = conn.Producer(serializer='json')
            with conn.Consumer(url_queue, callbacks=[self.fetch_url]) as consumer:
                while True:
                    conn.drain_events()

    def fetch_url(self, body, message):
        url, metadata = body['url'], body['metadata']
        command_id = count(1)
        def send_websocket_commands(ws):
            ws.send(dumps(dict(method="Network.enable", id=next(command_id))))
            ws.send(dumps(dict(method="Page.navigate", id=next(command_id), params={"url": url})))
            
            from umbra import behaviors
            behaviors.execute(url, ws, command_id)            
            
            message.ack()

        with Chrome(*self.chrome_args) as websocket_url:
            websock = websocket.WebSocketApp(websocket_url)
            websock.on_message = self.get_message_handler(url, metadata, command_id)
            websock.on_open = send_websocket_commands
            websock.run_forever()

class Chrome():
    logger = logging.getLogger('umbra.Chrome')

    def __init__(self, port, executable, browser_wait):
        self.port = port
        self.executable = executable
        self.browser_wait = browser_wait

    def fetch_debugging_json():
        raw_json = urllib.request.urlopen("http://localhost:%s/json" % self.port).read()
        json = raw_json.decode('utf-8')
        return loads(json)

    def __enter__(self):
        import subprocess
        chrome_args = [self.executable, "--temp-profile",
                "--remote-debugging-port=%s" % self.port,
                "--disable-web-sockets", "--disable-cache",
                "--window-size=1100,900", "--enable-logging"
                "--homepage=about:blank", "about:blank"]
        self.logger.info("running {}".format(chrome_args))
        self.chrome_process = subprocess.Popen(chrome_args)
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
        self.chrome_process.kill()

def main():
    # logging.basicConfig(stream=sys.stdout, level=logging.INFO,
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
            format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')

    arg_parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]),
            description='umbra - Browser automation tool',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    arg_parser.add_argument('-w', '--browser-wait', dest='browser_wait', default='10',
            help='Seconds to wait for browser initialization')
    arg_parser.add_argument('-e', '--executable', dest='executable', default='chromium-browser',
            help='Executable to use to invoke chrome')
    arg_parser.add_argument('-p', '--port', dest='port', default='9222',
            help='Port to have invoked chrome listen on for debugging connections')
    arg_parser.add_argument('-u', '--url', dest='amqp_url', default='amqp://guest:guest@localhost:5672/%2f',
            help='URL identifying the amqp server to talk to')
    args = arg_parser.parse_args(args=sys.argv[1:])
    chrome_args = (args.port, args.executable, args.browser_wait)
    umbra = Umbra(args.amqp_url, chrome_args)

if __name__ == "__main__":
    main()

