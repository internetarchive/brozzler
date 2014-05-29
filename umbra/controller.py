#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import time
import threading
import kombu
from umbra.browser import BrowserPool

class AmqpBrowserController:
    """
    Consumes amqp messages representing requests to browse urls, from the
    specified amqp queue (default: "urls") on the specified amqp exchange
    (default: "umbra"). Incoming amqp message is a json object with 3
    attributes:

      {
        "clientId": "umbra.client.123",
        "url": "http://example.com/my_fancy_page",
        "metadata": {"arbitrary":"fields", "etc":4}
      }

    "url" is the url to browse.

    "clientId" uniquely identifies the client of umbra. Umbra uses the clientId
    as the amqp routing key, to direct information via amqp back to the client.
    It sends this information on the same specified amqp exchange (default:
    "umbra").

    Each url requested in the browser is published to amqp this way. The
    outgoing amqp message is a json object:

      {
        "url": "http://example.com/images/embedded_thing.jpg",
        "method": "GET",
        "headers": {"User-Agent": "...", "Accept": "...", ...},
        "parentUrl": "http://example.com/my_fancy_page",
        "parentUrlMetadata": {"arbitrary":"fields", "etc":4, ...}
      }

    POST requests have an additional field, postData.
    """

    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, amqp_url='amqp://guest:guest@localhost:5672/%2f',
            chrome_exe='chromium-browser', browser_wait=60,
            max_active_browsers=1, queue_name='urls', routing_key='url',
            exchange_name='umbra'):
        self.amqp_url = amqp_url
        self.queue_name = queue_name
        self.routing_key = routing_key
        self.exchange_name = exchange_name

        self._browser_pool = BrowserPool(size=max_active_browsers,
                chrome_exe=chrome_exe, chrome_wait=browser_wait)

    def start(self):
        self._exchange = kombu.Exchange(name=self.exchange_name, type='direct',
                durable=True)

        self._producer = None
        self._producer_lock = threading.Lock()
        with self._producer_lock:
            self._producer_conn = kombu.Connection(self.amqp_url)
            self._producer = self._producer_conn.Producer(serializer='json')

        self._amqp_thread = threading.Thread(target=self._consume_amqp, name='AmqpConsumerThread')
        self._amqp_stop = threading.Event()
        self._amqp_thread.start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self._amqp_stop.set()
        self._amqp_thread.join()
        # with self._producer_lock:
        #     self._producer_conn.close()
        #     self._producer_conn = None

    def shutdown_now(self):
        self._browser_pool.shutdown_now()

    def _consume_amqp(self):
        # XXX https://webarchive.jira.com/browse/ARI-3811
        # After running for some amount of time (3 weeks in the latest case),
        # consumer looks normal but doesn't consume any messages. Not clear if
        # it's hanging in drain_events() or not. As a temporary measure for
        # mitigation (if it works) or debugging (if it doesn't work), close and
        # reopen the connection every 15 minutes
        RECONNECT_AFTER_SECONDS = 15 * 60

        url_queue = kombu.Queue(self.queue_name, routing_key=self.routing_key,
                exchange=self._exchange)

        while not self._amqp_stop.is_set():
            try:
                self.logger.info("connecting to amqp exchange={} at {}".format(self._exchange.name, self.amqp_url))
                with kombu.Connection(self.amqp_url) as conn:
                    conn_opened = time.time()
                    with conn.Consumer(url_queue) as consumer:
                        consumer.qos(prefetch_count=1)
                        while (not self._amqp_stop.is_set() and time.time() - conn_opened < RECONNECT_AFTER_SECONDS):
                            import socket
                            try:
                                browser = self._browser_pool.acquire() # raises KeyError if none available
                                consumer.callbacks = [self._make_callback(browser)]
                                conn.drain_events(timeout=0.5)
                                consumer.callbacks = None
                            except KeyError:
                                # no browsers available
                                time.sleep(0.5)
                            except socket.timeout:
                                # no urls in the queue
                                self._browser_pool.release(browser)

            except BaseException as e:
                self.logger.error("caught exception {}".format(e), exc_info=True)
                time.sleep(0.5)
                self.logger.error("attempting to reopen amqp connection")

    def _make_callback(self, browser):
        def callback(body, message):
            self._browse_page(browser, body['clientId'], body['url'], body['metadata'])
            message.ack()
        return callback

    def _browse_page(self, browser, client_id, url, parent_url_metadata):
        def on_request(chrome_msg):
            payload = chrome_msg['params']['request']
            payload['parentUrl'] = url
            payload['parentUrlMetadata'] = parent_url_metadata
            self.logger.debug('sending to amqp exchange={} routing_key={} payload={}'.format(self.exchange_name, client_id, payload))
            with self._producer_lock:
                publish = self._producer_conn.ensure(self._producer, self._producer.publish)
                publish(payload, exchange=self._exchange, routing_key=client_id)

        def browse_page_async():
            self.logger.info('browser={} client_id={} url={}'.format(browser, client_id, url))
            try:
                browser.browse_page(url, on_request=on_request)
            finally:
                self._browser_pool.release(browser)

        import random
        threadName = "BrowsingThread{}-{}".format(browser.chrome_port,
                ''.join((random.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))))
        threading.Thread(target=browse_page_async, name=threadName).start()

