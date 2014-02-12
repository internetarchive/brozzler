#!/usr/bin/env python
# vim: set sw=4 et:

from json import dumps, loads
import os,sys,argparse, urllib.request, urllib.error, urllib.parse
import websocket
import time
import uuid
import logging
import threading
from kombu import Connection, Exchange, Queue

class Umbra:
    logger = logging.getLogger('umbra.Umbra')
    def __init__(self, websocket_url, amqp_url):
        self.cmd_id = 0
        self.producer = None
        self.browser_lock = threading.Lock()
        self.amqp_url = amqp_url
        self.producer_lock = threading.Lock()
        self.websocket_url = websocket_url
        self.websock = websocket.WebSocketApp(websocket_url, on_message = self.handle_message)
        self.amqp_thread = threading.Thread(target=self.consume_amqp)
        self.amqp_stop = threading.Event()
        self.websock.on_open = lambda ws: self.amqp_thread.start()
        threading.Thread(target=self.websock.run_forever).start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self.amqp_stop.set()
        self.logger.info("shutting down websocket {}".format(self.websocket_url))
        self.websock.close()
        self.amqp_thread.join()

    def handle_message(self, ws, message):
        # self.logger.debug("handling message from websocket {} - {}".format(ws, message))
        message = loads(message)
        if "method" in message.keys() and message["method"] == "Network.requestWillBeSent":
            to_send = message['params']['request']
            to_send['parentUrl'] = self.url
            to_send['parentUrlMetadata'] = self.url_metadata
            self.logger.debug('sending to amqp: {}'.format(to_send))
            request_queue = Queue('requests',  routing_key='request', 
                    exchange=self.umbra_exchange)
            with self.producer_lock:
                self.producer.publish(to_send,
                        routing_key='request',
                        exchange=self.umbra_exchange,
                        declare=[request_queue])

    def consume_amqp(self):
        self.umbra_exchange = Exchange('umbra', 'direct', durable=True)
        url_queue = Queue('urls', routing_key='url', exchange=self.umbra_exchange)
        self.logger.info("connecting to amqp {} at {}".format(repr(self.umbra_exchange), self.amqp_url))
        with Connection(self.amqp_url) as conn:
            self.producer = conn.Producer(serializer='json')
            with conn.Consumer(url_queue, callbacks=[self.fetch_url]) as consumer:
                import socket
                while not self.amqp_stop.is_set():
                    try:
                        conn.drain_events(timeout=0.5)
                    except socket.timeout:
                        pass

    def send_command(self, **kwargs):
        self.logger.debug("sending command kwargs={}".format(kwargs))
        command = {}
        command.update(kwargs)
        self.cmd_id += 1
        command['id'] = self.cmd_id
        self.websock.send(dumps(command))

    def fetch_url(self, body, message):
        self.logger.debug("body={} message={} message.headers={} message.payload={}".format(repr(body), message, message.headers, message.payload))

        self.url = body['url']
        self.url_metadata = body['metadata']

        with self.browser_lock:
            self.send_command(method="Network.enable")
            self.send_command(method="Page.navigate", params={"url": self.url})

            # XXX more logic goes here
            time.sleep(10)

            message.ack()

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
    with Chrome(args.port, args.executable, args.browser_wait) as websocket_url:
        umbra = Umbra(websocket_url, args.amqp_url)
        try:
            while True:
                time.sleep(0.5)
        except:
            pass
        finally:
            umbra.shutdown()


if __name__ == "__main__":
    main()

