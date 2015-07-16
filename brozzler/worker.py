# vim: set sw=4 et:

import os
import logging
import brozzler
import threading
import time
import signal
import kombu
import brozzler.hq
import youtube_dl
import urllib.request
import json

class BrozzlerWorker:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, amqp_url="amqp://guest:guest@localhost:5672/%2f",
            max_browsers=1, chrome_exe="chromium-browser",
            proxy_server=None, ignore_cert_errors=False, 
            enable_warcprox_features=False):

        self._amqp_url = amqp_url
        self._max_browsers = max_browsers
        self._proxy_server = proxy_server
        self._enable_warcprox_features = enable_warcprox_features

        self._browser_pool = brozzler.browser.BrowserPool(max_browsers,
                chrome_exe=chrome_exe, proxy_server=proxy_server,
                ignore_cert_errors=ignore_cert_errors)

        self._shutdown_requested = threading.Event()

        ydl_opts = {
            "outtmpl": "/dev/null",
            "verbose": False,
            "retries": 1,
            "logger": logging,
            "nocheckcertificate": True,
            "hls_prefer_native": True,
            "noprogress": True,
            "nopart": True,
            "no_color": True,
        }
        if self._proxy_server:
            ydl_opts["proxy"] = "http://{}".format(self._proxy_server)
            ## XXX (sometimes?) causes chrome debug websocket to go through
            ## proxy. Maybe not needed thanks to hls_prefer_native.
            ## # see https://github.com/rg3/youtube-dl/issues/6087
            ## os.environ["http_proxy"] = "http://{}".format(self._proxy_server)
        self._ydl = youtube_dl.YoutubeDL(ydl_opts)

    def _next_url(self, site):
        """Raises kombu.simple.Empty if queue is empty"""
        with kombu.Connection(self._amqp_url) as conn:
            q = conn.SimpleQueue("brozzler.sites.{}.crawl_urls".format(site.id))
            msg = q.get(block=True, timeout=0.5)
            crawl_url_dict = msg.payload
            crawl_url = brozzler.CrawlUrl(**crawl_url_dict)
            msg.ack()
            return crawl_url

    def _completed_url(self, site, crawl_url):
        with kombu.Connection(self._amqp_url) as conn:
            q = conn.SimpleQueue("brozzler.sites.{}.completed_urls".format(site.id))
            logging.info("putting {} on queue {}".format(crawl_url, q.queue.name))
            q.put(crawl_url.to_dict())

    def _disclaim_site(self, site, crawl_url=None):
        # XXX maybe should put on "disclaimed" queue and hq should put back on "unclaimed"
        with kombu.Connection(self._amqp_url) as conn:
            q = conn.SimpleQueue("brozzler.sites.unclaimed".format(site.id))
            logging.info("putting {} on queue {}".format(site, q.queue.name))
            q.put(site.to_dict())
            if crawl_url:
                q = conn.SimpleQueue("brozzler.sites.{}.crawl_urls".format(site.id))
                logging.info("putting unfinished url {} on queue {}".format(crawl_url, q.queue.name))
                q.put(crawl_url.to_dict())

    def _putmeta(self, url, content_type, payload):
        assert self._enable_warcprox_features
        request = urllib.request.Request(url, method="PUTMETA", 
                headers={"Content-Type":content_type}, data=payload)
    
        # XXX evil hack to keep urllib from trying to tunnel https urls here
        request.type = "http"
        request.set_proxy("localhost:8000", "http")
    
        try:
            with urllib.request.urlopen(request) as response:
                if response.status != 204:
                    logging.warn("""got "{} {}" response on warcprox PUTMETA request (expected 204)""".format(response.status, response.reason))
        except urllib.error.HTTPError as e:
            logging.warn("""got "{} {}" response on warcprox PUTMETA request (expected 204)""".format(e.getcode(), e.info()))

    def _try_youtube_dl(self, site, crawl_url):
        try:
            logging.info("trying youtube-dl on {}".format(crawl_url))
            info = self._ydl.extract_info(crawl_url.url)
            if self._proxy_server and self._enable_warcprox_features:
                info_json = json.dumps(info, sort_keys=True, indent=4)
                logging.info("sending PUTMETA request to warcprox with youtube-dl json for {}".format(crawl_url))
                self._putmeta(url=crawl_url.url, 
                        content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
                        payload=info_json.encode("utf-8"))
        except BaseException as e:
            if youtube_dl.utils.UnsupportedError in e.exc_info:
                pass
            else:
                raise

    def _on_screenshot(self, site, crawl_url, screenshot_png):
        if self._proxy_server and self._enable_warcprox_features:
            logging.info("sending PUTMETA request to warcprox with screenshot for {}".format(crawl_url))
            self._putmeta(url=crawl_url.url, content_type="image/png", payload=screenshot_png)

    def _brozzle_site(self, browser, site):
        start = time.time()
        crawl_url = None
        try:
            with browser:
                while not self._shutdown_requested.is_set() and time.time() - start < 60:
                    try:
                        crawl_url = self._next_url(site)
                        logging.info("crawling {}".format(crawl_url))
                        self._try_youtube_dl(site, crawl_url)
                        crawl_url.outlinks = browser.browse_page(crawl_url.url,
                                on_screenshot=lambda screenshot_png: self._on_screenshot(site, crawl_url, screenshot_png))
                        self._completed_url(site, crawl_url)
                        crawl_url = None
                    except kombu.simple.Empty:
                        # if some timeout reached, re-raise?
                        pass
        # except kombu.simple.Empty:
        #     logging.info("finished {} (queue is empty)".format(site))
        except brozzler.browser.BrowsingAborted:
            logging.info("{} shut down".format(browser))
        finally:
            self._disclaim_site(site, crawl_url)
            self._browser_pool.release(browser)

    def run(self):
        latest_state = None
        while not self._shutdown_requested.is_set():
            with kombu.Connection(self._amqp_url) as conn:
                q = conn.SimpleQueue("brozzler.sites.unclaimed")
                q_empty = False
                if len(q) > 0:
                    try:
                        browser = self._browser_pool.acquire()
                        try:
                            msg = q.get(block=True, timeout=0.5)
                            site = brozzler.Site(**msg.payload)
                            msg.ack() # XXX ack only after browsing finished? kinda complicated
                            logging.info("browsing site {}".format(site))
                            th = threading.Thread(target=lambda: self._brozzle_site(browser, site), 
                                    name="BrowsingThread-{}".format(site.scope_surt))
                            th.start()
                        except kombu.simple.Empty:
                            q_empty = True
                    except KeyError:
                        if latest_state != "browsers-busy":
                            logging.info("all {} browsers are busy".format(self._max_browsers))
                            latest_state = "browsers-busy"
                else:
                    q_empty = True
    
                if q_empty:
                    if latest_state != "no-unclaimed-sites":
                        logging.info("no unclaimed sites to browse")
                        latest_state = "no-unclaimed-sites"
            time.sleep(0.5)

    def start(self):
        th = threading.Thread(target=self.run, name="BrozzlerWorker")
        th.start()

    def shutdown_now(self):
        logging.info("brozzler worker shutting down")
        self._shutdown_requested.set()
        self._browser_pool.shutdown_now()

