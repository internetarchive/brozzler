# vim: set sw=4 et:

import os
import logging
import brozzler
import threading
import time
import signal
import youtube_dl
import urllib.request
import json

__all__ = ["BrozzlerWorker"]

class BrozzlerWorker:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self, frontier, max_browsers=1, chrome_exe="chromium-browser"):
        self._frontier = frontier
        self._max_browsers = max_browsers
        self._browser_pool = brozzler.browser.BrowserPool(max_browsers,
                chrome_exe=chrome_exe, ignore_cert_errors=True)
        self._shutdown_requested = threading.Event()

    def _youtube_dl(self, site):
        ydl_opts = {
            "outtmpl": "/dev/null",
            "verbose": False,
            "retries": 1,
            "logger": logging.getLogger("youtube_dl"),
            "nocheckcertificate": True,
            "hls_prefer_native": True,
            "noprogress": True,
            "nopart": True,
            "no_color": True,
        }
        if site.extra_headers:
            ydl_opts["extra_http_headers"] = site.extra_headers
        if site.proxy:
            ydl_opts["proxy"] = "http://{}".format(site.proxy)
            ## XXX (sometimes?) causes chrome debug websocket to go through
            ## proxy. Maybe not needed thanks to hls_prefer_native.
            ## # see https://github.com/rg3/youtube-dl/issues/6087
            ## os.environ["http_proxy"] = "http://{}".format(site.proxy)
        return youtube_dl.YoutubeDL(ydl_opts)

    def _warcprox_write_record(self, warcprox_address, url, warc_type, content_type, payload, extra_headers=None):
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
                    self.logger.warn("""got "{} {}" response on warcprox WARCPROX_WRITE_RECORD request (expected 204)""".format(response.status, response.reason))
        except urllib.error.HTTPError as e:
            self.logger.warn("""got "{} {}" response on warcprox WARCPROX_WRITE_RECORD request (expected 204)""".format(e.getcode(), e.info()))

    def _try_youtube_dl(self, ydl, site, page):
        try:
            self.logger.info("trying youtube-dl on {}".format(page))
            info = ydl.extract_info(page.url)
            if site.proxy and site.enable_warcprox_features:
                info_json = json.dumps(info, sort_keys=True, indent=4)
                self.logger.info("sending WARCPROX_WRITE_RECORD request to warcprox with youtube-dl json for %s", page)
                self._warcprox_write_record(warcprox_address=site.proxy,
                        url=page.url, warc_type="metadata",
                        content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
                        payload=info_json.encode("utf-8"),
                        extra_headers=site.extra_headers)
        except BaseException as e:
            if hasattr(e, "exc_info") and e.exc_info[0] == youtube_dl.utils.UnsupportedError:
                pass
            elif (hasattr(e, "exc_info") and e.exc_info[0] ==
                    urllib.error.HTTPError and hasattr(e.exc_info[1], "code")
                    and e.exc_info[1].code == 420):
                raise brozzler.ReachedLimit(e.exc_info[1])
            else:
                raise

    def brozzle_page(self, browser, ydl, site, page):
        def on_screenshot(screenshot_png):
            if site.proxy and site.enable_warcprox_features:
                self.logger.info("sending WARCPROX_WRITE_RECORD request to warcprox with screenshot for %s", page)
                self._warcprox_write_record(warcprox_address=site.proxy,
                        url="screenshot:{}".format(page.url),
                        warc_type="resource", content_type="image/png",
                        payload=screenshot_png,
                        extra_headers=site.extra_headers)
                # XXX thumbnail

        self.logger.info("brozzling {}".format(page))
        try:
            self._try_youtube_dl(ydl, site, page)
        except brozzler.ReachedLimit as e:
            raise
        except:
            self.logger.error("youtube_dl raised exception on {}".format(page), exc_info=True)

        outlinks = browser.browse_page(page.url,
                extra_headers=site.extra_headers, on_screenshot=on_screenshot,
                on_url_change=page.note_redirect)
        return outlinks

    def _brozzle_site(self, browser, ydl, site):
        start = time.time()
        page = None
        try:
            browser.start(proxy=site.proxy)
            while not self._shutdown_requested.is_set() and time.time() - start < 60:
                page = self._frontier.claim_page(site)
                outlinks = self.brozzle_page(browser, ydl, site, page)
                self._frontier.completed_page(site, page)
                self._frontier.scope_and_schedule_outlinks(site, page, outlinks)
                page = None
        except brozzler.NothingToClaim:
            self.logger.info("no pages left for site %s", site)
        except brozzler.ReachedLimit as e:
            site.note_limit_reached(e)
        except brozzler.browser.BrowsingAborted:
            self.logger.info("{} shut down".format(browser))
        except:
            self.logger.critical("unexpected exception", exc_info=True)
        finally:
            self.logger.info("finished session brozzling site, stopping browser and disclaiming site")
            browser.stop()
            self._frontier.disclaim_site(site, page)
            self._browser_pool.release(browser)

    def run(self):
        try:
            latest_state = None
            while not self._shutdown_requested.is_set():
                try:
                    browser = self._browser_pool.acquire()
                    try:
                        site = self._frontier.claim_site()
                        self.logger.info("brozzling site %s", site)
                        ydl = self._youtube_dl(site)
                        th = threading.Thread(target=lambda: self._brozzle_site(browser, ydl, site),
                            name="BrowsingThread-{}".format(site.seed))
                        th.start()
                    except:
                        self._browser_pool.release(browser)
                        raise
                except brozzler.browser.NoBrowsersAvailable:
                    if latest_state != "browsers-busy":
                        self.logger.info("all %s browsers are busy", self._max_browsers)
                        latest_state = "browsers-busy"
                except brozzler.NothingToClaim:
                    if latest_state != "no-unclaimed-sites":
                        self.logger.info("no unclaimed sites to browse")
                        latest_state = "no-unclaimed-sites"
                time.sleep(0.5)
        except:
            self.logger.critical("thread exiting due to unexpected exception", exc_info=True)

    def start(self):
        th = threading.Thread(target=self.run, name="BrozzlerWorker")
        th.start()

    def shutdown_now(self):
        self.logger.info("brozzler worker shutting down")
        self._shutdown_requested.set()
        self._browser_pool.shutdown_now()

