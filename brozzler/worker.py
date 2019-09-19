'''
brozzler/worker.py - BrozzlerWorker brozzles pages from the frontier, meaning
it runs youtube-dl on them, browses them and runs behaviors if appropriate,
scopes and adds outlinks to the frontier

Copyright (C) 2014-2018 Internet Archive

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
import brozzler
import brozzler.browser
import threading
import time
import urllib.request
import json
import PIL.Image
import io
import socket
import requests
import doublethink
import tempfile
import urlcanon
from requests.structures import CaseInsensitiveDict
import rethinkdb as r
from . import ydl

class BrozzlerWorker:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    # 3⅓ min heartbeat interval => 10 min ttl
    # This is kind of a long time, because `frontier.claim_sites()`, which runs
    # in the same thread as the heartbeats, can take a while on a busy brozzler
    # cluster with slow rethinkdb.
    HEARTBEAT_INTERVAL = 200.0
    SITE_SESSION_MINUTES = 15

    def __init__(
            self, frontier, service_registry=None, max_browsers=1,
            chrome_exe="chromium-browser", warcprox_auto=False, proxy=None,
            skip_extract_outlinks=False, skip_visit_hashtags=False,
            skip_youtube_dl=False, page_timeout=300, behavior_timeout=900,
            headless=False):
        self._frontier = frontier
        self._service_registry = service_registry
        self._max_browsers = max_browsers

        self._warcprox_auto = warcprox_auto
        self._proxy = proxy
        assert not (warcprox_auto and proxy)
        self._proxy_is_warcprox = None
        self._skip_extract_outlinks = skip_extract_outlinks
        self._skip_visit_hashtags = skip_visit_hashtags
        self._skip_youtube_dl = skip_youtube_dl
        self._page_timeout = page_timeout
        self._behavior_timeout = behavior_timeout

        self._browser_pool = brozzler.browser.BrowserPool(
            max_browsers, chrome_exe=chrome_exe, headless=headless,
            ignore_cert_errors=True)
        self._browsing_threads = set()
        self._browsing_threads_lock = threading.Lock()

        self._thread = None
        self._start_stop_lock = threading.Lock()
        self._shutdown = threading.Event()

    def _choose_warcprox(self):
        warcproxes = self._service_registry.available_services('warcprox')
        if not warcproxes:
            return None
        reql = self._frontier.rr.table('sites').between(
                ['ACTIVE', r.minval], ['ACTIVE', r.maxval],
                index='sites_last_disclaimed')
        active_sites = list(reql.run())
        for warcprox in warcproxes:
            address = '%s:%s' % (warcprox['host'], warcprox['port'])
            warcprox['assigned_sites'] = len([
                site for site in active_sites
                if 'proxy' in site and site['proxy'] == address])
        warcproxes.sort(key=lambda warcprox: (
            warcprox['assigned_sites'], warcprox['load']))
        # XXX make this heuristic more advanced?
        return warcproxes[0]

    def _proxy_for(self, site):
        if self._proxy:
            return self._proxy
        elif site.proxy:
            return site.proxy
        elif self._warcprox_auto:
            svc = self._choose_warcprox()
            if svc is None:
                raise brozzler.ProxyError(
                        'no available instances of warcprox in the service '
                        'registry')
            site.proxy = '%s:%s' % (svc['host'], svc['port'])
            site.save()
            self.logger.info(
                    'chose warcprox instance %r from service registry for %r',
                    site.proxy, site)
            return site.proxy
        return None

    def _using_warcprox(self, site):
        if self._proxy:
            if self._proxy_is_warcprox is None:
                try:
                    response = requests.get('http://%s/status' % self._proxy)
                    status = json.loads(response.text)
                    self._proxy_is_warcprox = (status['role'] == 'warcprox')
                except Exception as e:
                    self._proxy_is_warcprox = False
                logging.info(
                        '%s %s warcprox', self._proxy,
                        'IS' if self._proxy_is_warcprox else 'IS NOT')
            return self._proxy_is_warcprox
        else:
            # I should have commented when I originally wrote this code, but I
            # think this works because `site.proxy` is only set when the proxy
            # is warcprox
            return bool(site.proxy or self._warcprox_auto)

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
            with urllib.request.urlopen(request, timeout=600) as response:
                if response.getcode() != 204:
                    self.logger.warning(
                            'got "%s %s" response on warcprox '
                            'WARCPROX_WRITE_RECORD request (expected 204)',
                            response.getcode(), response.reason)
                return request, response
        except urllib.error.HTTPError as e:
            self.logger.warning(
                    'got "%s %s" response on warcprox '
                    'WARCPROX_WRITE_RECORD request (expected 204)',
                    e.getcode(), e.info())
            return request, None
        except urllib.error.URLError as e:
            raise brozzler.ProxyError(
                    'proxy error on WARCPROX_WRITE_RECORD %s' % url) from e
        except ConnectionError as e:
            raise brozzler.ProxyError(
                    'proxy error on WARCPROX_WRITE_RECORD %s' % url) from e

    def full_and_thumb_jpegs(self, large_png):
        # these screenshots never have any alpha (right?)
        img = PIL.Image.open(io.BytesIO(large_png)).convert('RGB')

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

    def brozzle_page(self, browser, site, page, on_screenshot=None,
                     on_request=None, enable_youtube_dl=True):
        self.logger.info("brozzling {}".format(page))
        ydl_fetches = None
        outlinks = set()
        if enable_youtube_dl:
            try:
                ydl_fetches, outlinks = ydl.do_youtube_dl(self, site, page)
            except brozzler.ReachedLimit as e:
                raise
            except brozzler.ShutdownRequested:
                raise
            except brozzler.ProxyError:
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
                            'youtube_dl raised exception on %s', page,
                            exc_info=True)

        if self._needs_browsing(page, ydl_fetches):
            self.logger.info('needs browsing: %s', page)
            try:
                browser_outlinks = self._browse_page(
                    browser, site, page, on_screenshot, on_request)
                outlinks.update(browser_outlinks)
            except brozzler.PageInterstitialShown:
                self.logger.info('page interstitial shown (http auth): %s', page)
        else:
            if not self._already_fetched(page, ydl_fetches):
                self.logger.info('needs fetch: %s', page)
                self._fetch_url(site, page.url)
            else:
                self.logger.info('already fetched: %s', page)

        return outlinks

    def _browse_page(self, browser, site, page, on_screenshot=None, on_request=None):
        def _on_screenshot(screenshot_png):
            if on_screenshot:
                on_screenshot(screenshot_png)
            if self._using_warcprox(site):
                self.logger.info(
                        "sending WARCPROX_WRITE_RECORD request to %s with "
                        "screenshot for %s", self._proxy_for(site), page)
                screenshot_jpeg, thumbnail_jpeg = self.full_and_thumb_jpegs(
                        screenshot_png)
                self._warcprox_write_record(
                        warcprox_address=self._proxy_for(site),
                        url="screenshot:%s" % str(urlcanon.semantic(page.url)),
                        warc_type="resource", content_type="image/jpeg",
                        payload=screenshot_jpeg,
                        extra_headers=site.extra_headers())
                self._warcprox_write_record(
                        warcprox_address=self._proxy_for(site),
                        url="thumbnail:%s" % str(urlcanon.semantic(page.url)),
                        warc_type="resource", content_type="image/jpeg",
                        payload=thumbnail_jpeg,
                        extra_headers=site.extra_headers())

        def _on_response(chrome_msg):
            if ('params' in chrome_msg
                    and 'response' in chrome_msg['params']
                    and 'mimeType' in chrome_msg['params']['response']
                    and chrome_msg['params']['response'].get('mimeType', '').startswith('video/')
                    # skip manifests of DASH segmented video -
                    # see https://github.com/internetarchive/brozzler/pull/70
                    and chrome_msg['params']['response']['mimeType'] != 'video/vnd.mpeg.dash.mpd'
                    and chrome_msg['params']['response'].get('status') in (200, 206)):
                video = {
                    'blame': 'browser',
                    'url': chrome_msg['params']['response'].get('url'),
                    'response_code': chrome_msg['params']['response']['status'],
                    'content-type': chrome_msg['params']['response']['mimeType'],
                }
                response_headers = CaseInsensitiveDict(
                        chrome_msg['params']['response']['headers'])
                if 'content-length' in response_headers:
                    video['content-length'] = int(response_headers['content-length'])
                if 'content-range' in response_headers:
                    video['content-range'] = response_headers['content-range']
                logging.debug('embedded video %s', video)
                if not 'videos' in page:
                    page.videos = []
                page.videos.append(video)

        sw_fetched = set()
        def _on_service_worker_version_updated(chrome_msg):
            # https://github.com/internetarchive/brozzler/issues/140
            self.logger.trace('%r', chrome_msg)
            if chrome_msg.get('params', {}).get('versions'):
                url = chrome_msg.get('params', {}).get('versions')[0]\
                        .get('scriptURL')
                if url and url not in sw_fetched:
                    self.logger.info('fetching service worker script %s', url)
                    self._fetch_url(site, url)
                    sw_fetched.add(url)

        if not browser.is_running():
            browser.start(
                    proxy=self._proxy_for(site),
                    cookie_db=site.get('cookie_db'))
        final_page_url, outlinks = browser.browse_page(
                page.url, extra_headers=site.extra_headers(),
                behavior_parameters=site.get('behavior_parameters'),
                username=site.get('username'), password=site.get('password'),
                user_agent=site.get('user_agent'),
                on_screenshot=_on_screenshot, on_response=_on_response,
                on_request=on_request,
                on_service_worker_version_updated=_on_service_worker_version_updated,
                hashtags=page.hashtags,
                skip_extract_outlinks=self._skip_extract_outlinks,
                skip_visit_hashtags=self._skip_visit_hashtags,
                skip_youtube_dl=self._skip_youtube_dl,
                page_timeout=self._page_timeout,
                behavior_timeout=self._behavior_timeout)
        if final_page_url != page.url:
            page.note_redirect(final_page_url)
        return outlinks

    def _fetch_url(self, site, url):
        proxies = None
        if self._proxy_for(site):
            proxies = {
                'http': 'http://%s' % self._proxy_for(site),
                'https': 'http://%s' % self._proxy_for(site),
            }

        self.logger.info('fetching %s', url)
        try:
            # response is ignored
            requests.get(
                    url, proxies=proxies, headers=site.extra_headers(),
                    verify=False)
        except requests.exceptions.ProxyError as e:
            raise brozzler.ProxyError(
                    'proxy error fetching %s' % url) from e

    def _needs_browsing(self, page, ydl_fetches):
        if ydl_fetches:
            final_bounces = ydl.final_bounces(ydl_fetches, page.url)
            if not final_bounces:
                return True
            for txn in final_bounces:
                if txn['response_headers'].get_content_type() in [
                        'text/html', 'application/xhtml+xml']:
                    return True
            return False
        else:
            return True

    def _already_fetched(self, page, ydl_fetches):
        if ydl_fetches:
            for fetch in ydl.final_bounces(ydl_fetches, page.url):
                if (fetch['method'] == 'GET' and fetch['response_code'] == 200):
                    return True
        return False

    def brozzle_site(self, browser, site):
        try:
            site.last_claimed_by = '%s:%s' % (
                    socket.gethostname(), browser.chrome.port)
            site.save()
            start = time.time()
            page = None
            self._frontier.enforce_time_limit(site)
            self._frontier.honor_stop_request(site)
            # _proxy_for() call in log statement can raise brozzler.ProxyError
            # which is why we honor time limit and stop request first☝🏻
            self.logger.info(
                    "brozzling site (proxy=%r) %s",
                    self._proxy_for(site), site)
            while time.time() - start < self.SITE_SESSION_MINUTES * 60:
                site.refresh()
                self._frontier.enforce_time_limit(site)
                self._frontier.honor_stop_request(site)
                page = self._frontier.claim_page(site, "%s:%s" % (
                    socket.gethostname(), browser.chrome.port))

                if (page.needs_robots_check and
                        not brozzler.is_permitted_by_robots(
                            site, page.url, self._proxy_for(site))):
                    logging.warning("page %s is blocked by robots.txt", page.url)
                    page.blocked_by_robots = True
                    self._frontier.completed_page(site, page)
                else:
                    outlinks = self.brozzle_page(
                            browser, site, page,
                            enable_youtube_dl=not self._skip_youtube_dl)
                    self._frontier.completed_page(site, page)
                    self._frontier.scope_and_schedule_outlinks(
                            site, page, outlinks)
                    if browser.is_running():
                        site.cookie_db = browser.chrome.persist_and_read_cookie_db()

                page = None
        except brozzler.ShutdownRequested:
            self.logger.info("shutdown requested")
        except brozzler.NothingToClaim:
            self.logger.info("no pages left for site %s", site)
        except brozzler.ReachedLimit as e:
            self._frontier.reached_limit(site, e)
        except brozzler.ReachedTimeLimit as e:
            self._frontier.finished(site, "FINISHED_TIME_LIMIT")
        except brozzler.CrawlStopped:
            self._frontier.finished(site, "FINISHED_STOP_REQUESTED")
        # except brozzler.browser.BrowsingAborted:
        #     self.logger.info("{} shut down".format(browser))
        except brozzler.ProxyError as e:
            if self._warcprox_auto:
                logging.error(
                        'proxy error (site.proxy=%s), will try to choose a '
                        'healthy instance next time site is brozzled: %s',
                        site.proxy, e)
                site.proxy = None
            else:
                # using brozzler-worker --proxy, nothing to do but try the
                # same proxy again next time
                logging.error(
                        'proxy error (self._proxy=%r)', self._proxy, exc_info=1)
        except:
            self.logger.critical("unexpected exception", exc_info=True)
        finally:
            if start:
                site.active_brozzling_time = (site.active_brozzling_time or 0) + time.time() - start
            self._frontier.disclaim_site(site, page)

    def _brozzle_site_thread_target(self, browser, site):
        try:
            self.brozzle_site(browser, site)
        finally:
            browser.stop()
            self._browser_pool.release(browser)
            with self._browsing_threads_lock:
                self._browsing_threads.remove(threading.current_thread())

    def _service_heartbeat(self):
        if hasattr(self, "status_info"):
            status_info = self.status_info
        else:
            status_info = {
                "role": "brozzler-worker",
                "ttl": self.HEARTBEAT_INTERVAL * 3,
            }
        status_info["load"] = 1.0 * self._browser_pool.num_in_use() / self._browser_pool.size
        status_info["browser_pool_size"] = self._browser_pool.size
        status_info["browsers_in_use"] = self._browser_pool.num_in_use()

        try:
            self.status_info = self._service_registry.heartbeat(status_info)
            self.logger.trace(
                    "status in service registry: %s", self.status_info)
        except r.ReqlError as e:
            self.logger.error(
                    "failed to send heartbeat and update service registry "
                    "with info %s: %s", status_info, e)

    def _service_heartbeat_if_due(self):
        '''Sends service registry heartbeat if due'''
        due = False
        if self._service_registry:
            if not hasattr(self, "status_info"):
                due = True
            else:
                d = doublethink.utcnow() - self.status_info["last_heartbeat"]
                due = d.total_seconds() > self.HEARTBEAT_INTERVAL

        if due:
            self._service_heartbeat()

    def _start_browsing_some_sites(self):
        '''
        Starts browsing some sites.

        Raises:
            NoBrowsersAvailable if none available
        '''
        # acquire_multi() raises NoBrowsersAvailable if none available
        browsers = self._browser_pool.acquire_multi(
                (self._browser_pool.num_available() + 1) // 2)
        try:
            sites = self._frontier.claim_sites(len(browsers))
        except:
            self._browser_pool.release_all(browsers)
            raise

        for i in range(len(browsers)):
            if i < len(sites):
                th = threading.Thread(
                        target=self._brozzle_site_thread_target,
                        args=(browsers[i], sites[i]),
                        name="BrozzlingThread:%s" % browsers[i].chrome.port,
                        daemon=True)
                with self._browsing_threads_lock:
                    self._browsing_threads.add(th)
                th.start()
            else:
                self._browser_pool.release(browsers[i])

    def run(self):
        self.logger.notice(
                'brozzler %s - brozzler-worker starting', brozzler.__version__)
        last_nothing_to_claim = 0
        try:
            while not self._shutdown.is_set():
                self._service_heartbeat_if_due()
                if time.time() - last_nothing_to_claim > 20:
                    try:
                        self._start_browsing_some_sites()
                    except brozzler.browser.NoBrowsersAvailable:
                        logging.trace(
                                "all %s browsers are in use",
                                self._max_browsers)
                    except brozzler.NothingToClaim:
                        last_nothing_to_claim = time.time()
                        logging.trace(
                                "nothing to claim, all available active sites "
                                "are already claimed by a brozzler worker")
                time.sleep(0.5)

            self.logger.notice("shutdown requested")
        except r.ReqlError as e:
            self.logger.error(
                    "caught rethinkdb exception, will try to proceed",
                    exc_info=True)
        except brozzler.ShutdownRequested:
            self.logger.info("shutdown requested")
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

            self.logger.info(
                    'shutting down %s brozzling threads',
                    len(self._browsing_threads))
            with self._browsing_threads_lock:
                for th in self._browsing_threads:
                    if th.is_alive():
                        brozzler.thread_raise(th, brozzler.ShutdownRequested)
            self._browser_pool.shutdown_now()
            # copy to avoid "RuntimeError: Set changed size during iteration"
            thredz = set(self._browsing_threads)
            for th in thredz:
                th.join()

    def start(self):
        with self._start_stop_lock:
            if self._thread:
                self.logger.warning(
                        'ignoring start request because self._thread is '
                        'not None')
                return
            self._thread = threading.Thread(
                    target=self.run, name="BrozzlerWorker")
            self._thread.start()

    def shutdown_now(self):
        self.stop()

    def stop(self):
        self._shutdown.set()

    def is_alive(self):
        return self._thread and self._thread.is_alive()

