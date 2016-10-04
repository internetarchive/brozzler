'''
brozzler/worker.py - BrozzlerWorker brozzles pages from the frontier, meaning
it runs youtube-dl on them, browses them and runs behaviors if appropriate,
scopes and adds outlinks to the frontier

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

import os
import logging
import brozzler
import brozzler.browser
import threading
import time
import signal
import youtube_dl
import urllib.request
import json
import PIL.Image
import io
import socket
import datetime
import collections
import requests
import rethinkstuff
import tempfile

class ExtraHeaderAdder(urllib.request.BaseHandler):
    def __init__(self, extra_headers):
        self.extra_headers = extra_headers
        self.http_request = self._http_request
        self.https_request = self._http_request

    def _http_request(self, req):
        for h, v in self.extra_headers.items():
            if h.capitalize() not in req.headers:
                req.add_header(h, v)
        return req

class YoutubeDLSpy(urllib.request.BaseHandler):
    Transaction = collections.namedtuple('Transaction', ['request', 'response'])

    def __init__(self):
        self.reset()

    def _http_response(self, request, response):
        self.transactions.append(YoutubeDLSpy.Transaction(request,response))
        return response

    http_response = https_response = _http_response

    def reset(self):
        self.transactions = []

    def final_bounces(self, url):
        """Resolves redirect chains in self.transactions, returns a list of
        Transaction representing the final redirect destinations of the given
        url. There could be more than one if for example youtube-dl hit the
        same url with HEAD and then GET requests."""
        redirects = {}
        for txn in self.transactions:
             # XXX check http status 301,302,303,307? check for "uri" header
             # as well as "location"? see urllib.request.HTTPRedirectHandler
             if ((txn.request.full_url == url
                     or txn.request.full_url in redirects)
                     and 'location' in txn.response.headers):
                 redirects[txn.request.full_url] = txn

        final_url = url
        while final_url in redirects:
            final_url = redirects[final_url].response.headers['location']

        final_bounces = []
        for txn in self.transactions:
            if txn.request.full_url == final_url:
                final_bounces.append(txn)

        return final_bounces

class BrozzlerWorker:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    HEARTBEAT_INTERVAL = 20.0

    def __init__(
            self, frontier, service_registry=None, max_browsers=1,
            chrome_exe="chromium-browser", proxy=None,
            enable_warcprox_features=False):
        self._frontier = frontier
        self._service_registry = service_registry
        self._max_browsers = max_browsers

        # these two settings can be overridden by the job/site configuration
        self.__proxy = proxy
        self.__enable_warcprox_features = enable_warcprox_features

        self._browser_pool = brozzler.browser.BrowserPool(max_browsers,
                chrome_exe=chrome_exe, ignore_cert_errors=True)
        self._shutdown_requested = threading.Event()
        self._thread = None
        self._start_stop_lock = threading.Lock()
        self._browsing_threads = set()

    def _proxy(self, site):
        return site.proxy or self.__proxy

    def _enable_warcprox_features(self, site):
        if site.enable_warcprox_features is not None:
            return site.enable_warcprox_features
        else:
            return self.__enable_warcprox_features

    def _youtube_dl(self, destdir, site):
        ydl_opts = {
            "outtmpl": "{}/ydl%(autonumber)s.out".format(destdir),
            "verbose": False,
            "retries": 1,
            "logger": logging.getLogger("youtube_dl"),
            "nocheckcertificate": True,
            "hls_prefer_native": True,
            "noprogress": True,
            "nopart": True,
            "no_color": True,
        }
        if self._proxy(site):
            ydl_opts["proxy"] = "http://{}".format(self._proxy(site))
            ## XXX (sometimes?) causes chrome debug websocket to go through
            ## proxy. Maybe not needed thanks to hls_prefer_native.
            ## # see https://github.com/rg3/youtube-dl/issues/6087
            ## os.environ["http_proxy"] = "http://{}".format(self._proxy(site))
        ydl = youtube_dl.YoutubeDL(ydl_opts)
        if site.extra_headers():
            ydl._opener.add_handler(ExtraHeaderAdder(site.extra_headers()))
        ydl.brozzler_spy = YoutubeDLSpy()
        ydl._opener.add_handler(ydl.brozzler_spy)
        return ydl

    def _warcprox_write_record(
            self, warcprox_address, url, warc_type, content_type,
            payload, extra_headers=None):
        headers = {"Content-Type":content_type,"WARC-Type":warc_type,"Host":"N/A"}
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(url, method="WARCPROX_WRITE_RECORD",
                headers=headers, data=payload)

        # XXX setting request.type="http" is a hack to stop urllib from trying
        # to tunnel if url is https
        request.type = "http"
        request.set_proxy(warcprox_address, "http")

        try:
            with urllib.request.urlopen(request) as response:
                if response.status != 204:
                    self.logger.warn(
                            'got "%s %s" response on warcprox '
                            'WARCPROX_WRITE_RECORD request (expected 204)',
                            response.status, response.reason)
        except urllib.error.HTTPError as e:
            self.logger.warn(
                    'got "%s %s" response on warcprox '
                    'WARCPROX_WRITE_RECORD request (expected 204)',
                    e.getcode(), e.info())

    def _try_youtube_dl(self, ydl, site, page):
        try:
            self.logger.info("trying youtube-dl on {}".format(page))
            info = ydl.extract_info(page.url)
            if self._proxy(site) and self._enable_warcprox_features(site):
                info_json = json.dumps(info, sort_keys=True, indent=4)
                self.logger.info(
                        "sending WARCPROX_WRITE_RECORD request to warcprox "
                        "with youtube-dl json for %s", page)
                self._warcprox_write_record(
                        warcprox_address=self._proxy(site),
                        url="youtube-dl:%s" % page.url, warc_type="metadata",
                        content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
                        payload=info_json.encode("utf-8"),
                        extra_headers=site.extra_headers())
        except BaseException as e:
            if hasattr(e, "exc_info") and e.exc_info[0] == youtube_dl.utils.UnsupportedError:
                pass
            elif (hasattr(e, "exc_info") and e.exc_info[0] ==
                    urllib.error.HTTPError and hasattr(e.exc_info[1], "code")
                    and e.exc_info[1].code == 420):
                raise brozzler.ReachedLimit(e.exc_info[1])
            else:
                raise

    def full_and_thumb_jpegs(self, large_png):
        img = PIL.Image.open(io.BytesIO(large_png))

        out = io.BytesIO()
        img.save(out, "jpeg", quality=95)
        full_jpeg = out.getbuffer()

        thumb_width = 300
        thumb_height = (thumb_width / img.size[0]) * img.size[1]
        img.thumbnail((thumb_width, thumb_height))
        out = io.BytesIO()
        img.save(out, "jpeg", quality=95)
        thumb_jpeg = out.getbuffer()

        return full_jpeg, thumb_jpeg

    def brozzle_page(self, browser, site, page, on_screenshot=None):
        def _on_screenshot(screenshot_png):
            if on_screenshot:
                on_screenshot(screenshot_png)
            elif self._proxy(site) and self._enable_warcprox_features(site):
                self.logger.info("sending WARCPROX_WRITE_RECORD request "
                                 "to warcprox with screenshot for %s", page)
                screenshot_jpeg, thumbnail_jpeg = self.full_and_thumb_jpegs(
                        screenshot_png)
                self._warcprox_write_record(warcprox_address=self._proxy(site),
                        url="screenshot:{}".format(page.url),
                        warc_type="resource", content_type="image/jpeg",
                        payload=screenshot_jpeg,
                        extra_headers=site.extra_headers())
                self._warcprox_write_record(warcprox_address=self._proxy(site),
                        url="thumbnail:{}".format(page.url),
                        warc_type="resource", content_type="image/jpeg",
                        payload=thumbnail_jpeg,
                        extra_headers=site.extra_headers())

        self.logger.info("brozzling {}".format(page))
        try:
            with tempfile.TemporaryDirectory(prefix='brzl-ydl-') as tempdir:
                ydl = self._youtube_dl(tempdir, site)
                ydl_spy = ydl.brozzler_spy # remember for later
                self._try_youtube_dl(ydl, site, page)
        except brozzler.ReachedLimit as e:
            raise
        except Exception as e:
            if (hasattr(e, 'exc_info') and len(e.exc_info) >= 2
                    and hasattr(e.exc_info[1], 'code')
                    and e.exc_info[1].code == 430):
                self.logger.info(
                        'youtube-dl got %s %s processing %s',
                        e.exc_info[1].code, e.exc_info[1].msg, page.url)
            else:
                self.logger.error(
                        "youtube_dl raised exception on %s", page, exc_info=True)

        if self._needs_browsing(page, ydl_spy):
            self.logger.info('needs browsing: %s', page)
            if not browser.is_running():
                browser.start(proxy=self._proxy(site), cookie_db=site.cookie_db)
            outlinks = browser.browse_page(
                    page.url, extra_headers=site.extra_headers(),
                    user_agent=site.user_agent,
                    on_screenshot=_on_screenshot,
                    on_url_change=page.note_redirect)
            return outlinks
        else:
            if not self._already_fetched(page, ydl_spy):
                self.logger.info('needs fetch: %s', page)
                self._fetch_url(site, page)
            else:
                self.logger.info('already fetched: %s', page)
            return []

    def _fetch_url(self, site, page):
        proxies = None
        if self._proxy(site):
            proxies = {
                'http': 'http://%s' % self._proxy(site),
                'https': 'http://%s' % self._proxy(site),
            }

        self.logger.info('fetching %s', page)
        # response is ignored
        requests.get(
                page.url, proxies=proxies, headers=site.extra_headers(),
                verify=False)

    def _needs_browsing(self, page, brozzler_spy):
        final_bounces = brozzler_spy.final_bounces(page.url)
        if not final_bounces:
            return True
        for txn in final_bounces:
            if txn.response.headers.get_content_type() in [
                    'text/html', 'application/xhtml+xml']:
                return True
        return False

    def _already_fetched(self, page, brozzler_spy):
        for txn in brozzler_spy.final_bounces(page.url):
            if (txn.request.get_method() == 'GET'
                    and txn.response.status == 200):
                return True
        return False

    def _brozzle_site(self, browser, site):
        start = time.time()
        page = None
        try:
            while (not self._shutdown_requested.is_set()
                   and time.time() - start < 7 * 60):
                self._frontier.honor_stop_request(site.job_id)
                page = self._frontier.claim_page(site, "%s:%s" % (
                    socket.gethostname(), browser.chrome_port))
                outlinks = self.brozzle_page(browser, site, page)
                if browser.is_running():
                    site.cookie_db = browser.persist_and_read_cookie_db()
                self._frontier.completed_page(site, page)
                self._frontier.scope_and_schedule_outlinks(
                        site, page, outlinks)
                page = None
        except brozzler.NothingToClaim:
            self.logger.info("no pages left for site %s", site)
        except brozzler.ReachedLimit as e:
            self._frontier.reached_limit(site, e)
        except brozzler.CrawlJobStopped:
            self._frontier.finished(site, "FINISHED_STOP_REQUESTED")
        except brozzler.browser.BrowsingAborted:
            self.logger.info("{} shut down".format(browser))
        except:
            self.logger.critical("unexpected exception", exc_info=True)
        finally:
            self.logger.info("finished session brozzling site, stopping "
                             "browser and disclaiming site")
            browser.stop()
            self._frontier.disclaim_site(site, page)
            self._browser_pool.release(browser)
            self._browsing_threads.remove(threading.current_thread())

    def _service_heartbeat(self):
        if hasattr(self, "status_info"):
            status_info = self.status_info
        else:
            status_info = {
                "role": "brozzler-worker",
                "heartbeat_interval": self.HEARTBEAT_INTERVAL,
            }
        status_info["load"] = 1.0 * self._browser_pool.num_in_use() / self._browser_pool.size
        status_info["browser_pool_size"] = self._browser_pool.size
        status_info["browsers_in_use"] = self._browser_pool.num_in_use()

        try:
            self.status_info = self._service_registry.heartbeat(status_info)
            self.logger.log(
                    brozzler.TRACE, "status in service registry: %s",
                    self.status_info)
        except rethinkdb.ReqlError as e:
            self.logger.error(
                    "failed to send heartbeat and update service registry "
                    "with info %s: %s", status_info, e)

    def run(self):
        try:
            latest_state = None
            while not self._shutdown_requested.is_set():
                if self._service_registry and (
                        not hasattr(self, "status_info")
                        or (rethinkstuff.utcnow() -
                            self.status_info["last_heartbeat"]).total_seconds()
                        > self.HEARTBEAT_INTERVAL):
                    self._service_heartbeat()

                try:
                    browser = self._browser_pool.acquire()
                    try:
                        site = self._frontier.claim_site("{}:{}".format(
                            socket.gethostname(), browser.chrome_port))
                        self.logger.info("brozzling site %s", site)
                        th = threading.Thread(
                                target=lambda: self._brozzle_site(
                                    browser, site),
                                name="BrozzlingThread:%s" % site.seed)
                        th.start()
                        self._browsing_threads.add(th)
                    except:
                        self._browser_pool.release(browser)
                        raise
                except brozzler.browser.NoBrowsersAvailable:
                    if latest_state != "browsers-busy":
                        self.logger.info(
                                "all %s browsers are busy", self._max_browsers)
                        latest_state = "browsers-busy"
                except brozzler.NothingToClaim:
                    if latest_state != "no-unclaimed-sites":
                        self.logger.info("no unclaimed sites to browse")
                        latest_state = "no-unclaimed-sites"
                time.sleep(0.5)
        except:
            self.logger.critical(
                    "thread exiting due to unexpected exception",
                    exc_info=True)
        finally:
            if self._service_registry and hasattr(self, "status_info"):
                try:
                    self._service_registry.unregister(self.status_info["id"])
                except:
                    self.logger.error(
                            "failed to unregister from service registry",
                            exc_info=True)

    def start(self):
        with self._start_stop_lock:
            if self._thread:
                self.logger.warn(
                        'ignoring start request because self._thread is '
                        'not None')
                return
            self._thread = threading.Thread(
                    target=self.run, name="BrozzlerWorker")
            self._thread.start()

    def shutdown_now(self):
        with self._start_stop_lock:
            self.logger.info("brozzler worker shutting down")
            self._shutdown_requested.set()
            self._browser_pool.shutdown_now()
            while self._browsing_threads:
                time.sleep(0.5)
            self._thread = None

    def is_alive(self):
        return self._thread and self._thread.is_alive()

