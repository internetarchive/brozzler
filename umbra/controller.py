#!/usr/bin/env python
# vim: set sw=4 et:

import logging
import time
import threading
import kombu
import socket
from umbra.browser import BrowserPool, BrowsingException

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
            chrome_exe='chromium-browser', max_active_browsers=1, 
            queue_name='urls', exchange_name='umbra'):
        self.amqp_url = amqp_url
        self.queue_name = queue_name
        self.exchange_name = exchange_name
        self.max_active_browsers = max_active_browsers

        self._browser_pool = BrowserPool(size=max_active_browsers, chrome_exe=chrome_exe)

    def start(self):
        self._browsing_threads = set()
        self._browsing_threads_lock = threading.Lock()

        self._exchange = kombu.Exchange(name=self.exchange_name, type='direct',
                durable=True)

        self._reconnect_requested = False

        self._producer = None
        self._producer_lock = threading.Lock()
        with self._producer_lock:
            self._producer_conn = kombu.Connection(self.amqp_url)
            self._producer = self._producer_conn.Producer(serializer='json')

        self._consumer_thread = threading.Thread(target=self._consume_amqp, name='AmqpConsumerThread')
        self._consumer_stop = threading.Event()
        self._consumer_thread.start()

    def shutdown(self):
        self.logger.info("shutting down amqp consumer {}".format(self.amqp_url))
        self._consumer_stop.set()
        self._consumer_thread.join()

    def shutdown_now(self):
        self._consumer_stop.set()
        self._browser_pool.shutdown_now()
        self._consumer_thread.join()

    def reconnect(self, *args, **kwargs):
        self._reconnect_requested = True
        self._browser_pool.shutdown_now()

    def _wait_for_and_browse_urls(self, conn, consumer, timeout):
        start = time.time()
        browser = None
        consumer.qos(prefetch_count=self.max_active_browsers)

        while not self._consumer_stop.is_set() and time.time() - start < timeout and not self._reconnect_requested:
            try:
                browser = self._browser_pool.acquire() # raises KeyError if none available
                browser.start()

                def callback(body, message):
                    try:
                        client_id, url, metadata = body['clientId'], body['url'], body['metadata']
                    except:
                        self.logger.error("unable to decipher message {}".format(message), exc_info=True)
                        self.logger.error("discarding bad message")
                        message.reject()
                        browser.stop()
                        self._browser_pool.release(browser)
                        return
                    self._start_browsing_page(browser, message, client_id, url, metadata)

                consumer.callbacks = [callback]

                while True:
                    try:
                        conn.drain_events(timeout=0.5)
                        break # out of "while True" to acquire another browser
                    except socket.timeout:
                        pass
                    except socket.error:
                        self.logger.error("problem consuming messages from AMQP, will try reconnecting after active browsing finishes", exc_info=True)
                        self._reconnect_requested = True

                    if self._consumer_stop.is_set() or time.time() - start >= timeout or self._reconnect_requested:
                        browser.stop()
                        self._browser_pool.release(browser)
                        break

            except KeyError:
                # no browsers available
                time.sleep(0.5)
            except:
                self.logger.critical("problem with browser initialization", exc_info=True)
                time.sleep(0.5)
            finally:
                consumer.callbacks = None

    def _wait_for_active_browsers(self):
        self.logger.info("waiting for browsing threads to finish")
        while True:
            with self._browsing_threads_lock:
                if len(self._browsing_threads) == 0:
                    break
            time.sleep(0.5)
        self.logger.info("active browsing threads finished")

    def _consume_amqp(self):
        # XXX https://webarchive.jira.com/browse/ARI-3811
        # After running for some amount of time (3 weeks in the latest case),
        # consumer looks normal but doesn't consume any messages. Not clear if
        # it's hanging in drain_events() or not. As a temporary measure for
        # mitigation (if it works) or debugging (if it doesn't work), close and
        # reopen the connection every 2.5 hours
        RECONNECT_AFTER_SECONDS = 150 * 60

        url_queue = kombu.Queue(self.queue_name, exchange=self._exchange)

        while not self._consumer_stop.is_set():
            try:
                self.logger.info("connecting to amqp exchange={} at {}".format(self._exchange.name, self.amqp_url))
                self._reconnect_requested = False
                with kombu.Connection(self.amqp_url) as conn:
                    with conn.Consumer(url_queue) as consumer:
                        self._wait_for_and_browse_urls(conn, consumer, timeout=RECONNECT_AFTER_SECONDS)

                    # need to wait for browsers to finish here, before closing
                    # the amqp connection,  because they use it to do
                    # message.ack() after they finish browsing a page
                    self._wait_for_active_browsers()
            except BaseException as e:
                self.logger.error("caught exception {}".format(e), exc_info=True)
                time.sleep(0.5)
                self.logger.error("attempting to reopen amqp connection")

    def _start_browsing_page(self, browser, message, client_id, url, parent_url_metadata):
        def on_request(chrome_msg):
            payload = chrome_msg['params']['request']
            payload['parentUrl'] = url
            payload['parentUrlMetadata'] = parent_url_metadata
            self.logger.debug('sending to amqp exchange={} routing_key={} payload={}'.format(self.exchange_name, client_id, payload))
            with self._producer_lock:
                publish = self._producer_conn.ensure(self._producer, self._producer.publish)
                publish(payload, exchange=self._exchange, routing_key=client_id)

        def browse_page_sync():
            self.logger.info('browser={} client_id={} url={}'.format(browser, client_id, url))
            try:
                browser.browse_page(url, on_request=on_request)
                message.ack()
            except BrowsingException as e:
                self.logger.warn("browsing did not complete normally, requeuing url {} - {}".format(url, e))
                message.requeue()
            except:
                self.logger.critical("problem browsing page, requeuing url {}, may have lost browser process".format(url), exc_info=True)
                message.requeue()
            finally:
                browser.stop()
                self._browser_pool.release(browser)

        def browse_thread_run_then_cleanup():
            browse_page_sync()
            with self._browsing_threads_lock:
                self._browsing_threads.remove(threading.current_thread())

        import random
        thread_name = "BrowsingThread{}-{}".format(browser.chrome_port,
                ''.join((random.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))))
        th = threading.Thread(target=browse_thread_run_then_cleanup, name=thread_name)
        with self._browsing_threads_lock:
            self._browsing_threads.add(th)
        th.start()

