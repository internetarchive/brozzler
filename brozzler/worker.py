"""
brozzler/worker.py - BrozzlerWorker brozzles pages from the frontier, meaning
it runs yt-dlp on them, browses them and runs behaviors if appropriate,
scopes and adds outlinks to the frontier

Copyright (C) 2014-2025 Internet Archive

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import brozzler
import brozzler.browser
import datetime
import threading
import time
import urllib.request
import json
import PIL.Image
import io
import socket
import random
import requests
import structlog
import urllib3
from urllib3.exceptions import TimeoutError, ProxyError
import doublethink
import tempfile
import urlcanon
from requests.structures import CaseInsensitiveDict
import rethinkdb as rdb
from . import metrics
from . import ydl

r = rdb.RethinkDB()


class BrozzlerWorker:
    logger = structlog.get_logger(logger_name=__module__ + "." + __qualname__)

    # 3⅓ min heartbeat interval => 10 min ttl
    # This is kind of a long time, because `frontier.claim_sites()`, which runs
    # in the same thread as the heartbeats, can take a while on a busy brozzler
    # cluster with slow rethinkdb.
    HEARTBEAT_INTERVAL = 200.0
    SITE_SESSION_MINUTES = 15
    HEADER_REQUEST_TIMEOUT = 30
    FETCH_URL_TIMEOUT = 60

    def __init__(
        self,
        frontier,
        service_registry=None,
        skip_av_seeds=None,
        ytdlp_proxy_endpoints=None,
        max_browsers=1,
        chrome_exe="chromium-browser",
        warcprox_auto=False,
        proxy=None,
        skip_extract_outlinks=False,
        skip_visit_hashtags=False,
        skip_youtube_dl=False,
        ytdlp_tmpdir="/tmp",
        simpler404=False,
        screenshot_full_page=False,
        page_timeout=300,
        behavior_timeout=300,
        extract_outlinks_timeout=60,
        download_throughput=-1,
        stealth=False,
        window_height=900,
        window_width=1400,
        metrics_port=0,
        registry_url=None,
        env=None,
    ):
        self._frontier = frontier
        self._service_registry = service_registry
        self._skip_av_seeds = skip_av_seeds
        self._ytdlp_proxy_endpoints = ytdlp_proxy_endpoints
        self._max_browsers = max_browsers

        self._warcprox_auto = warcprox_auto
        self._proxy = proxy
        assert not (warcprox_auto and proxy)
        self._proxy_is_warcprox = None
        self._skip_extract_outlinks = skip_extract_outlinks
        self._skip_visit_hashtags = skip_visit_hashtags
        self._skip_youtube_dl = skip_youtube_dl
        self._ytdlp_tmpdir = ytdlp_tmpdir
        self._simpler404 = simpler404
        self._screenshot_full_page = screenshot_full_page
        self._page_timeout = page_timeout
        self._behavior_timeout = behavior_timeout
        self._extract_outlinks_timeout = extract_outlinks_timeout
        self._download_throughput = download_throughput
        self._window_height = window_height
        self._window_width = window_width
        self._stealth = stealth
        self._metrics_port = metrics_port
        self._registry_url = registry_url
        self._env = env

        self._browser_pool = brozzler.browser.BrowserPool(
            max_browsers, chrome_exe=chrome_exe, ignore_cert_errors=True
        )
        self._browsing_threads = set()
        self._browsing_threads_lock = threading.Lock()

        self._thread = None
        self._start_stop_lock = threading.Lock()
        self._shutdown = threading.Event()

        # set up metrics
        if self._metrics_port > 0:
            metrics.register_prom_metrics(
                self._metrics_port, self._registry_url, self._env
            )
        else:
            self.logger.warning(
                "not starting prometheus scrape endpoint: metrics_port is undefined"
            )

    def _choose_warcprox(self):
        warcproxes = self._service_registry.available_services("warcprox")
        if not warcproxes:
            return None
        # .group('proxy').count() makes this query about 99% more efficient
        reql = (
            self._frontier.rr.table("sites")
            .between(
                ["ACTIVE", r.minval],
                ["ACTIVE", r.maxval],
                index="sites_last_disclaimed",
            )
            .group("proxy")
            .count()
        )
        # returns results like
        # {
        #    "wbgrp-svc030.us.archive.org:8000": 148,
        #    "wbgrp-svc030.us.archive.org:8001": 145
        # }
        proxy_scoreboard = dict(reql.run())
        for warcprox in warcproxes:
            address = "%s:%s" % (warcprox["host"], warcprox["port"])
            warcprox["assigned_sites"] = proxy_scoreboard.get(address, 0)
        warcproxes.sort(
            key=lambda warcprox: (warcprox["assigned_sites"], warcprox["load"])
        )
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
                    "no available instances of warcprox in the service " "registry"
                )
            site.proxy = "%s:%s" % (svc["host"], svc["port"])
            site.save()
            self.logger.info(
                "chose warcprox instance from service registry",
                instance=site.proxy,
                registry=site,
            )
            return site.proxy
        return None

    def _using_warcprox(self, site):
        if self._proxy:
            if self._proxy_is_warcprox is None:
                try:
                    response = requests.get("http://%s/status" % self._proxy)
                    status = json.loads(response.text)
                    self._proxy_is_warcprox = status["role"] == "warcprox"
                except Exception as e:
                    self._proxy_is_warcprox = False
                self.logger.info(
                    "%s %s warcprox",
                    self._proxy,
                    "IS" if self._proxy_is_warcprox else "IS NOT",
                )
            return self._proxy_is_warcprox
        else:
            # I should have commented when I originally wrote this code, but I
            # think this works because `site.proxy` is only set when the proxy
            # is warcprox
            return bool(site.proxy or self._warcprox_auto)

    def _warcprox_write_record(
        self,
        warcprox_address,
        url,
        warc_type,
        content_type,
        payload,
        extra_headers=None,
    ):
        headers = {"Content-Type": content_type, "WARC-Type": warc_type, "Host": "N/A"}
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            url, method="WARCPROX_WRITE_RECORD", headers=headers, data=payload
        )

        # XXX setting request.type="http" is a hack to stop urllib from trying
        # to tunnel if url is https
        request.type = "http"
        request.set_proxy(warcprox_address, "http")

        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                if response.getcode() != 204:
                    self.logger.warning(
                        "got unexpected response on warcprox "
                        "WARCPROX_WRITE_RECORD request (expected 204)",
                        code=response.getcode(),
                        reason=response.reason,
                    )
                return request, response
        except urllib.error.HTTPError as e:
            self.logger.warning(
                "got unexpected response on warcprox "
                "WARCPROX_WRITE_RECORD request (expected 204)",
                code=e.getcode(),
                reason=e.info(),
            )
            return request, None
        except urllib.error.URLError as e:
            raise brozzler.ProxyError(
                "proxy error on WARCPROX_WRITE_RECORD %s" % url
            ) from e
        except ConnectionError as e:
            raise brozzler.ProxyError(
                "proxy error on WARCPROX_WRITE_RECORD %s" % url
            ) from e

    def thumb_jpeg(self, full_jpeg):
        """Create JPEG thumbnail."""
        img = PIL.Image.open(io.BytesIO(full_jpeg))
        thumb_width = 300
        thumb_height = (thumb_width / img.size[0]) * img.size[1]
        img.thumbnail((thumb_width, thumb_height))
        out = io.BytesIO()
        img.save(out, "jpeg", quality=95)
        return out.getbuffer()

    @metrics.brozzler_page_processing_duration_seconds.time()
    @metrics.brozzler_in_progress_pages.track_inprogress()
    def brozzle_page(
        self,
        browser,
        site,
        page,
        on_screenshot=None,
        on_request=None,
        enable_youtube_dl=True,
    ):
        page_logger = self.logger.bind(page=page)
        page_logger.info("brozzling")
        outlinks = set()

        page_headers = self._get_page_headers(site, page)

        if not self._needs_browsing(page_headers):
            page_logger.info("needs fetch")
            self._fetch_url(site, page=page)
        else:
            page_logger.info("needs browsing")
            try:
                browser_outlinks = self._browse_page(
                    browser, site, page, on_screenshot, on_request
                )
                outlinks.update(browser_outlinks)
                status_code = browser.websock_thread.page_status
                if status_code in [502, 504]:
                    raise brozzler.PageConnectionError()
            except brozzler.PageInterstitialShown:
                page_logger.info("page interstitial shown (http auth)")

            if enable_youtube_dl and ydl.should_ytdlp(
                site, page, status_code, self._skip_av_seeds
            ):
                try:
                    ydl_outlinks = ydl.do_youtube_dl(
                        self, site, page, self._ytdlp_proxy_endpoints
                    )
                    metrics.brozzler_ydl_urls_checked.inc(1)
                    outlinks.update(ydl_outlinks)
                except brozzler.ReachedLimit as e:
                    raise
                except brozzler.ShutdownRequested:
                    raise
                except brozzler.ProxyError:
                    raise
                except brozzler.VideoExtractorError as e:
                    self.logger.exception("error extracting video info")
                except Exception as e:
                    if (
                        hasattr(e, "exc_info")
                        and len(e.exc_info) >= 2
                        and hasattr(e.exc_info[1], "code")
                        and e.exc_info[1].code == 430
                    ):
                        self.logger.info(
                            "youtube-dl encountered an error",
                            code=e.exc_info[1].code,
                            message=e.exc_info[1].msg,
                            url=page.url,
                        )
                    else:
                        self.logger.exception("youtube_dl raised exception", page=page)
        return outlinks

    @metrics.brozzler_header_processing_duration_seconds.time()
    @metrics.brozzler_in_progress_headers.track_inprogress()
    def _get_page_headers(self, site, page):
        url_logger = self.logger.bind(url=page.url)
        # bypassing warcprox, requests' stream=True defers downloading the body of the response
        # see https://docs.python-requests.org/en/latest/user/advanced/#body-content-workflow
        try:
            user_agent = site.get("user_agent")
            headers = {"User-Agent": user_agent} if user_agent else {}
            url_logger.info("getting page headers")
            with requests.get(
                page.url,
                stream=True,
                verify=False,
                headers=headers,
                timeout=self.HEADER_REQUEST_TIMEOUT,
            ) as r:
                return r.headers
        except requests.exceptions.Timeout as e:
            url_logger.warning("Timed out trying to get headers", exc_info=True)
        except requests.exceptions.RequestException as e:
            url_logger.warning("Failed to get headers", exc_info=True)
        return {}

    def _needs_browsing(self, page_headers):
        if (
            "content-type" in page_headers
            and "html" not in page_headers["content-type"]
        ):
            return False
        return True

    @metrics.brozzler_browsing_duration_seconds.time()
    @metrics.brozzler_in_progress_browses.track_inprogress()
    def _browse_page(self, browser, site, page, on_screenshot=None, on_request=None):
        def update_page_metrics(page, outlinks):
            """Update page-level Prometheus metrics."""
            metrics.brozzler_last_page_crawled_time.set_to_current_time()
            metrics.brozzler_pages_crawled.inc(1)
            metrics.brozzler_outlinks_found.inc(len(outlinks))

        def _on_screenshot(screenshot_jpeg):
            if on_screenshot:
                on_screenshot(screenshot_jpeg)
            if self._using_warcprox(site):
                self.logger.info(
                    "sending WARCPROX_WRITE_RECORD request",
                    proxy=self._proxy_for(site),
                    screenshot_for_page=page,
                )
                thumbnail_jpeg = self.thumb_jpeg(screenshot_jpeg)
                self._warcprox_write_record(
                    warcprox_address=self._proxy_for(site),
                    url="screenshot:%s" % str(urlcanon.semantic(page.url)),
                    warc_type="resource",
                    content_type="image/jpeg",
                    payload=screenshot_jpeg,
                    extra_headers=site.extra_headers(page),
                )
                self._warcprox_write_record(
                    warcprox_address=self._proxy_for(site),
                    url="thumbnail:%s" % str(urlcanon.semantic(page.url)),
                    warc_type="resource",
                    content_type="image/jpeg",
                    payload=thumbnail_jpeg,
                    extra_headers=site.extra_headers(page),
                )

        def _on_response(chrome_msg):
            if (
                "params" in chrome_msg
                and "response" in chrome_msg["params"]
                and "mimeType" in chrome_msg["params"]["response"]
                and chrome_msg["params"]["response"]
                .get("mimeType", "")
                .startswith("video/")
                # skip manifests of DASH segmented video -
                # see https://github.com/internetarchive/brozzler/pull/70
                and chrome_msg["params"]["response"]["mimeType"]
                != "video/vnd.mpeg.dash.mpd"
                and chrome_msg["params"]["response"].get("status") in (200, 206)
            ):
                video = {
                    "blame": "browser",
                    "url": chrome_msg["params"]["response"].get("url"),
                    "response_code": chrome_msg["params"]["response"]["status"],
                    "content-type": chrome_msg["params"]["response"]["mimeType"],
                }
                response_headers = CaseInsensitiveDict(
                    chrome_msg["params"]["response"]["headers"]
                )
                if "content-length" in response_headers:
                    video["content-length"] = int(response_headers["content-length"])
                if "content-range" in response_headers:
                    video["content-range"] = response_headers["content-range"]
                self.logger.debug("embedded video", video=video)
                if not "videos" in page:
                    page.videos = []
                page.videos.append(video)

        sw_fetched = set()

        def _on_service_worker_version_updated(chrome_msg):
            # https://github.com/internetarchive/brozzler/issues/140
            self.logger.debug("service worker updated", chrome_msg=chrome_msg)
            if chrome_msg.get("params", {}).get("versions"):
                url = chrome_msg.get("params", {}).get("versions")[0].get("scriptURL")
                if url and url.startswith("http") and url not in sw_fetched:
                    self.logger.info("fetching service worker script", url=url)
                    self._fetch_url(site, url=url)
                    sw_fetched.add(url)

        if not browser.is_running():
            browser.start(
                proxy=self._proxy_for(site),
                cookie_db=site.get("cookie_db"),
                window_height=self._window_height,
                window_width=self._window_width,
            )
        final_page_url, outlinks = browser.browse_page(
            page.url,
            extra_headers=site.extra_headers(page),
            behavior_parameters=site.get("behavior_parameters"),
            username=site.get("username"),
            password=site.get("password"),
            user_agent=site.get("user_agent"),
            on_screenshot=_on_screenshot,
            on_response=_on_response,
            on_request=on_request,
            on_service_worker_version_updated=_on_service_worker_version_updated,
            hashtags=page.hashtags,
            skip_extract_outlinks=self._skip_extract_outlinks,
            skip_visit_hashtags=self._skip_visit_hashtags,
            skip_youtube_dl=self._skip_youtube_dl,
            ytdlp_tmpdir=self._ytdlp_tmpdir,
            simpler404=self._simpler404,
            screenshot_full_page=self._screenshot_full_page,
            page_timeout=self._page_timeout,
            behavior_timeout=self._behavior_timeout,
            extract_outlinks_timeout=self._extract_outlinks_timeout,
            download_throughput=self._download_throughput,
            stealth=self._stealth,
        )
        if final_page_url != page.url:
            page.note_redirect(final_page_url)
        update_page_metrics(page, outlinks)
        return outlinks

    def _fetch_url(self, site, url=None, page=None):
        proxy_url = self._proxy_for(site)

        if page:
            url = page.url

        if proxy_url:
            http = urllib3.ProxyManager("http://%s" % proxy_url, cert_reqs="CERT_NONE")
        else:
            http = urllib3.PoolManager()

        user_agent = site.get("user_agent")
        headers = {"User-Agent": user_agent} if user_agent else {}
        headers.update(site.extra_headers(page))

        self.logger.info("fetching url", url=url)
        try:
            # response is ignored
            http.request(
                "GET",
                url,
                headers=headers,
                timeout=self.FETCH_URL_TIMEOUT,
                retries=False,
            )
            self.logger.info("Completed fetching url", url=url)
        except TimeoutError as e:
            self.logger.warning("Timed out fetching url", url=url)
            raise brozzler.PageConnectionError() from e
        except ProxyError as e:
            raise brozzler.ProxyError("proxy error fetching %s" % url) from e
        except urllib3.exceptions.RequestError as e:
            self.logger.warning("Failed to fetch url", url=url, exc_info=True)
            raise brozzler.PageConnectionError() from e

    def brozzle_site(self, browser, site):
        site_logger = self.logger.bind(site=site)
        try:
            site.last_claimed_by = "%s:%s" % (socket.gethostname(), browser.chrome.port)
            site.save()
            start = time.time()
            page = None
            self._frontier.enforce_time_limit(site)
            self._frontier.honor_stop_request(site)
            # _proxy_for() call in log statement can raise brozzler.ProxyError
            # which is why we honor time limit and stop request first☝🏻
            site_logger.info("brozzling site", proxy=self._proxy_for(site))
            while time.time() - start < self.SITE_SESSION_MINUTES * 60:
                site.refresh()
                self._frontier.enforce_time_limit(site)
                self._frontier.honor_stop_request(site)
                page = self._frontier.claim_page(
                    site, "%s:%s" % (socket.gethostname(), browser.chrome.port)
                )

                if page.needs_robots_check and not brozzler.is_permitted_by_robots(
                    site, page.url, self._proxy_for(site)
                ):
                    self.logger.warning("page is blocked by robots.txt", url=page.url)
                    page.blocked_by_robots = True
                    self._frontier.completed_page(site, page)
                else:
                    outlinks = self.brozzle_page(
                        browser, site, page, enable_youtube_dl=not self._skip_youtube_dl
                    )
                    self._frontier.completed_page(site, page)
                    self._frontier.scope_and_schedule_outlinks(site, page, outlinks)
                    if browser.is_running():
                        site.cookie_db = browser.chrome.persist_and_read_cookie_db()

                page = None
        except brozzler.ShutdownRequested:
            self.logger.info("shutdown requested")
        except brozzler.NothingToClaim:
            site_logger.info("no pages left for site")
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
                self.logger.exception(
                    "proxy error, will try to choose a "
                    "healthy instance next time site is brozzled",
                    site_proxy=site.proxy,
                )
                site.proxy = None
            else:
                # using brozzler-worker --proxy, nothing to do but try the
                # same proxy again next time
                self.logger.exception("proxy error", self_proxy=self._proxy)
        except (brozzler.PageConnectionError, Exception) as e:
            if isinstance(e, brozzler.PageConnectionError):
                site_logger.exception(
                    "Page status code possibly indicates connection failure between host and warcprox",
                    page=page,
                )
            else:
                site_logger.exception("unexpected exception", page=page)
            if page:
                # Calculate backoff in seconds based on number of failed attempts.
                # Minimum of 60, max of 135 giving delays of 60, 90, 135, 135...
                retry_delay = min(135, 60 * (1.5 ** (page.failed_attempts or 0)))
                page.retry_after = doublethink.utcnow() + datetime.timedelta(
                    seconds=retry_delay
                )
                page.failed_attempts = (page.failed_attempts or 0) + 1
                if page.failed_attempts >= brozzler.MAX_PAGE_FAILURES:
                    self.logger.info(
                        'marking page "completed" after several unexpected '
                        "exceptions attempting to brozzle",
                        failed_attempts=page.failed_attempts,
                        page=page,
                    )
                    self._frontier.completed_page(site, page)
                    page = None
                else:
                    page.save()
        finally:
            if start:
                site.active_brozzling_time = (
                    (site.active_brozzling_time or 0) + time.time() - start
                )
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
        status_info["load"] = (
            1.0 * self._browser_pool.num_in_use() / self._browser_pool.size
        )
        status_info["browser_pool_size"] = self._browser_pool.size
        status_info["browsers_in_use"] = self._browser_pool.num_in_use()

        try:
            self.status_info = self._service_registry.heartbeat(status_info)
            self.logger.debug("status in service registry", status=self.status_info)
        except r.ReqlError as e:
            self.logger.exception(
                "failed to send heartbeat and update service registry",
                info=status_info,
            )

    def _service_heartbeat_if_due(self):
        """Sends service registry heartbeat if due"""
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
        """
        Starts browsing some sites.

        Raises:
            NoBrowsersAvailable if none available
        """
        # acquire_multi() raises NoBrowsersAvailable if none available
        browsers = self._browser_pool.acquire_multi(
            (self._browser_pool.num_available() + 1) // 2
        )
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
                    daemon=True,
                )
                with self._browsing_threads_lock:
                    self._browsing_threads.add(th)
                th.start()
            else:
                self._browser_pool.release(browsers[i])

    def run(self):
        self.logger.warn("brozzler %s - brozzler-worker starting", brozzler.__version__)
        last_nothing_to_claim = 0
        try:
            while not self._shutdown.is_set():
                self._service_heartbeat_if_due()
                if time.time() - last_nothing_to_claim > 20:
                    try:
                        self._start_browsing_some_sites()
                    except brozzler.browser.NoBrowsersAvailable:
                        self.logger.debug(
                            "all browsers are in use", max_browsers=self._max_browsers
                        )
                    except brozzler.NothingToClaim:
                        last_nothing_to_claim = time.time()
                        self.logger.debug(
                            "nothing to claim, all available active sites "
                            "are already claimed by a brozzler worker"
                        )
                time.sleep(0.5)

            self.logger.warn("shutdown requested")
        except r.ReqlError as e:
            self.logger.exception("caught rethinkdb exception, will try to proceed")
        except brozzler.ShutdownRequested:
            self.logger.info("shutdown requested")
        except:
            self.logger.critical(
                "thread exiting due to unexpected exception", exc_info=True
            )
        finally:
            if self._service_registry and hasattr(self, "status_info"):
                try:
                    self._service_registry.unregister(self.status_info["id"])
                except:
                    self.logger.exception("failed to unregister from service registry")

            self.logger.info(
                "shutting down brozzling threads",
                thread_count=len(self._browsing_threads),
            )
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
                    "ignoring start request because self._thread is " "not None"
                )
                return
            self._thread = threading.Thread(target=self.run, name="BrozzlerWorker")
            self.logger = self.logger.bind(thread=self._thread)
            self._thread.start()

    def shutdown_now(self):
        self.stop()

    def stop(self):
        self._shutdown.set()

    def is_alive(self):
        return self._thread and self._thread.is_alive()
