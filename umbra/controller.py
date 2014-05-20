#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import time
import threading
import kombu
from umbra.browser import Browser

class AmqpBrowserController:
    """Consumes amqp messages representing requests to browse urls, from the
    amqp queue "urls" on exchange "umbra". Incoming amqp message is a json
    object with 3 attributes:
      {
        "clientId": "umbra.client.123",
        "url": "http://example.com/my_fancy_page",
        "metadata": {"arbitrary":"fields", "etc":4}
      }

    "url" is the url to browse.

    "clientId" uniquely identifies the client of
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

    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, amqp_url='amqp://guest:guest@localhost:5672/%2f', 
            chrome_exe='chromium-browser', browser_wait=60,
            max_active_workers=1, queue_name='urls', routing_key='url', 
            exchange_name='umbra'):

        self.amqp_url = amqp_url
        self.chrome_exe = chrome_exe
        self.browser_wait = browser_wait
        self.max_active_workers = max_active_workers
        self.queue_name = queue_name
        self.routing_key = routing_key
        self.exchange_name = exchange_name
        self._exchange = kombu.Exchange(name=self.exchange_name, type='direct', durable=True)

        self.producer = None
        self.producer_lock = threading.Lock()
        with self.producer_lock:
            self.producer_conn = kombu.Connection(self.amqp_url)
            self.producer = self.producer_conn.Producer(serializer='json')

        self.browsers = {}
        self.browsers_lock = threading.Lock()
        self.num_active_workers = 0
        self.amqp_thread = threading.Thread(target=self._consume_amqp)
        self.amqp_stop = threading.Event()
        self.amqp_thread.start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self.amqp_stop.set()
        self.amqp_thread.join()

    def _consume_amqp(self):
        # XXX https://webarchive.jira.com/browse/ARI-3811
        # After running for some amount of time (3 weeks in the latest case),
        # consumer looks normal but doesn't consume any messages. Not clear if
        # it's hanging in drain_events() or not. As a temporary measure for
        # mitigation (if it works) or debugging (if it doesn't work), close and
        # reopen the connection every 15 minutes
        RECONNECT_AFTER_SECONDS = 15 * 60

        while not self.amqp_stop.is_set():
            try:
                url_queue = kombu.Queue(self.queue_name, routing_key=self.routing_key, exchange=self._exchange)
                self.logger.info("connecting to amqp exchange={} at {}".format(self._exchange.name, self.amqp_url))
                with kombu.Connection(self.amqp_url) as conn:
                    conn_opened = time.time()
                    with conn.Consumer(url_queue, callbacks=[self._browse_page_requested]) as consumer:
                        import socket
                        while (not self.amqp_stop.is_set() and time.time() - conn_opened < RECONNECT_AFTER_SECONDS):
                            try:
                                conn.drain_events(timeout=0.5)
                            except socket.timeout:
                                pass
            except BaseException as e:
                self.logger.error("amqp exception {}".format(e))
                self.logger.error("attempting to reopen amqp connection")

    def _browse_page_requested(self, body, message):
        """Kombu Consumer callback. Provisions a Browser and
        asynchronously asks it to browse the requested url."""
        client_id = body['clientId']

        def on_request(chrome_msg):
            payload = chrome_msg['params']['request']
            payload['parentUrl'] = body['url']
            payload['parentUrlMetadata'] = body['metadata']
            self.logger.debug('sending to amqp exchange={} routing_key={} payload={}'.format(self.exchange_name, client_id, payload))
            with self.producer_lock:
                publish = self.producer_conn.ensure(self.producer, self.producer.publish)
                publish(payload, exchange=self._exchange, routing_key=client_id)

        with self.browsers_lock:
            if client_id in self.browsers:
                browser = self.browsers[client_id]
            else:
                # XXX should reuse ports
                port = 9222 + len(self.browsers)
                browser = Browser(chrome_port=port, chrome_exe=self.chrome_exe,
                        chrome_wait=self.browser_wait, client_id=client_id)
                self.browsers[client_id] = browser

        def browse_page_async():
            self.logger.info('client_id={} body={}'.format(client_id, body))
            while True:
                with self.browsers_lock:
                    if self.num_active_workers < self.max_active_workers:
                        self.num_active_workers += 1
                        break
                time.sleep(0.5)

            browser.browse_page(body['url'], on_request=on_request)

            with self.browsers_lock:
                self.num_active_workers -= 1

        threading.Thread(target=browse_page_async).start()

        message.ack()

