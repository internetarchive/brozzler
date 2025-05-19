"""
brozzler/ydl.py - youtube-dl / yt-dlp support for brozzler

Copyright (C) 2024-2025 Internet Archive

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

import datetime
import json
import os
import random
import tempfile
import threading
import time
import urllib.request

import doublethink
import structlog
import urlcanon
import yt_dlp
from yt_dlp.utils import ExtractorError, match_filter_func

import brozzler

from . import metrics

thread_local = threading.local()


PROXY_ATTEMPTS = 4
YTDLP_WAIT = 10
YTDLP_MAX_REDIRECTS = 5


logger = structlog.get_logger(logger_name=__name__)


def isyoutubehost(url):
    # split 1 splits scheme from url, split 2 splits path from hostname, split 3 splits query string on hostname
    return "youtube.com" in url.split("//")[-1].split("/")[0].split("?")[0]


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


def _build_youtube_dl(worker, destdir, site, page, ytdlp_proxy_endpoints):
    """
    Builds a yt-dlp `yt_dlp.YoutubeDL` for brozzling `site` with `worker`.

    The `YoutubeDL` instance does a few special brozzler-specific things:

    - periodically updates `site.last_claimed` in rethinkdb
    - pushes captured video to warcprox using a WARCPROX_WRITE_RECORD request
    - some logging

    Args:
        worker (brozzler.BrozzlerWorker): the calling brozzler worker
        destdir (str): where to save downloaded videos
        site (brozzler.Site): the site we are brozzling
        page (brozzler.Page): the page we are brozzling

    Returns:
        a yt-dlp `yt_dlp.YoutubeDL` instance
    """

    class _YoutubeDL(yt_dlp.YoutubeDL):
        logger = structlog.get_logger(__module__ + "." + __qualname__)

        def __init__(self, url, params=None, auto_init=True):
            super().__init__(params, auto_init)

            self.url = url
            self.logger = self.logger.bind(url=url)

        def process_ie_result(self, ie_result, download=True, extra_info=None):
            if extra_info is None:
                extra_info = {}
            result_type = ie_result.get("_type", "video")

            if result_type in ("url", "url_transparent"):
                if "extraction_depth" in extra_info:
                    self.logger.info(
                        "Following redirect",
                        redirect_url=ie_result["url"],
                        extraction_depth=extra_info["extraction_depth"],
                    )
                    extra_info["extraction_depth"] = 1 + extra_info.get(
                        "extraction_depth", 0
                    )
                else:
                    extra_info["extraction_depth"] = 0
                if extra_info["extraction_depth"] >= YTDLP_MAX_REDIRECTS:
                    raise ExtractorError(
                        f"Too many hops for URL: {ie_result['url']}",
                        expected=True,
                    )
            return super().process_ie_result(ie_result, download, extra_info)

        def add_default_extra_info(self, ie_result, ie, url):
            # hook in some logging
            super().add_default_extra_info(ie_result, ie, url)
            extract_context = self.logger.bind(extractor=ie.IE_NAME)
            if ie_result.get("_type") == "playlist":
                extract_context.info("found playlist")
                if ie.IE_NAME in {
                    "youtube:playlist",
                    "youtube:tab",
                    "soundcloud:user",
                    "instagram:user",
                }:
                    # At this point ie_result['entries'] is an iterator that
                    # will fetch more metadata from youtube to list all the
                    # videos. We unroll that iterator here partly because
                    # otherwise `process_ie_result()` will clobber it, and we
                    # use it later to extract the watch pages as outlinks.
                    try:
                        ie_result["entries_no_dl"] = list(ie_result["entries"])
                    except Exception:
                        extract_context.warning(
                            "failed to unroll entries ie_result['entries']?",
                            exc_info=True,
                        )
                        ie_result["entries_no_dl"] = []
                    ie_result["entries"] = []
                    self.logger.info(
                        "not downloading media files from this "
                        "playlist because we expect to capture them from "
                        "individual watch/track/detail pages",
                        media_file_count=len(ie_result["entries_no_dl"]),
                    )
            else:
                extract_context.info("found a download")

        def _push_video_to_warcprox(self, site, info_dict, postprocessor):
            # 220211 update: does yt-dlp supply content-type? no, not as such
            # XXX Don't know how to get the right content-type. Youtube-dl
            # doesn't supply it. Sometimes (with --hls-prefer-native)
            # youtube-dl produces a stitched-up video that /usr/bin/file fails
            # to identify (says "application/octet-stream"). `ffprobe` doesn't
            # give us a mimetype.
            if info_dict.get("ext") == "mp4":
                mimetype = "video/mp4"
            else:
                try:
                    import magic

                    mimetype = magic.from_file(info_dict["filepath"], mime=True)
                except ImportError:
                    mimetype = "video/%s" % info_dict["ext"]
                    self.logger.warning(
                        "guessing mimetype due to error",
                        mimetype=mimetype,
                        exc_info=True,
                    )

            # youtube watch page postprocessor is MoveFiles

            if postprocessor == "FixupM3u8" or postprocessor == "Merger":
                url = "youtube-dl:%05d:%s" % (
                    info_dict.get("playlist_index") or 1,
                    info_dict["webpage_url"],
                )
            else:
                url = info_dict.get("url", "")

            # skip urls containing .m3u8, to avoid duplicates handled by FixupM3u8
            if url == "" or ".m3u8" in url:
                return

            size = os.path.getsize(info_dict["filepath"])
            self.logger.info(
                "pushing video to warcprox",
                format=info_dict["format"],
                mimetype=mimetype,
                size=size,
                warcprox=worker._proxy_for(site),
            )
            with open(info_dict["filepath"], "rb") as f:
                # include content-length header to avoid chunked
                # transfer, which warcprox currently rejects
                extra_headers = dict(site.extra_headers())
                extra_headers["content-length"] = size
                request, response = worker._warcprox_write_record(
                    warcprox_address=worker._proxy_for(site),
                    url=url,
                    warc_type="resource",
                    content_type=mimetype,
                    payload=f,
                    extra_headers=extra_headers,
                )

            # consulted by _remember_videos()
            ydl.pushed_videos.append(
                {
                    "url": url,
                    "response_code": response.code,
                    "content-type": mimetype,
                    "content-length": size,
                }
            )

    def maybe_heartbeat_site_last_claimed(*args, **kwargs):
        # in case yt-dlp takes a long time, heartbeat site.last_claimed
        # to prevent another brozzler-worker from claiming the site
        try:
            if (
                site.rr
                and doublethink.utcnow() - site.last_claimed
                > datetime.timedelta(minutes=worker.SITE_SESSION_MINUTES)
            ):
                worker.logger.debug(
                    "heartbeating site.last_claimed to prevent another "
                    "brozzler-worker claiming this site",
                    id=site.id,
                )
                site.last_claimed = doublethink.utcnow()
                site.save()
        except:  # noqa: E722
            worker.logger.debug(
                "problem heartbeating site.last_claimed site",
                id=site.id,
                exc_info=True,
            )

    def ydl_postprocess_hook(d):
        if d["status"] == "finished":
            worker.logger.info(
                "[ydl_postprocess_hook] Finished postprocessing",
                postprocessor=d["postprocessor"],
            )
            is_youtube_host = isyoutubehost(d["info_dict"]["webpage_url"])

            metrics.brozzler_ydl_download_successes.labels(is_youtube_host).inc(1)
            if worker._using_warcprox(site):
                _YoutubeDL._push_video_to_warcprox(
                    _YoutubeDL, site, d["info_dict"], d["postprocessor"]
                )

    # default socket_timeout is 20 -- we hit it often when cluster is busy
    ydl_opts = {
        "outtmpl": "{}/ydl%(autonumber)s.out".format(destdir),
        "retries": 1,
        "nocheckcertificate": True,
        "noplaylist": True,
        "noprogress": True,
        "nopart": True,
        "no_color": True,
        "socket_timeout": 40,
        "progress_hooks": [maybe_heartbeat_site_last_claimed],
        "postprocessor_hooks": [ydl_postprocess_hook],
        # https://github.com/yt-dlp/yt-dlp#format-selection
        # "By default, yt-dlp tries to download the best available quality..."
        # v.2023.07.06 https://www.reddit.com/r/youtubedl/wiki/h264/?rdt=63577
        # recommended: convert working cli to api call with
        # https://github.com/yt-dlp/yt-dlp/blob/master/devscripts/cli_to_api.py
        "format_sort": ["res:720", "vcodec:h264", "acodec:aac"],
        # skip live streams
        "match_filter": match_filter_func("!is_live"),
        "extractor_args": {"generic": {"impersonate": [""]}},
        # --cache-dir local or..
        # this looked like a problem with nsf-mounted homedir, maybe not a problem for brozzler on focal?
        "cache_dir": "/home/archiveit",
        "logger": logger,
        "verbose": False,
        "quiet": False,
        # recommended to avoid bot detection
        "sleep_interval": 7,
        "max_sleep_interval": 27,
    }

    ytdlp_url = page.redirect_url if page.redirect_url else page.url
    is_youtube_host = isyoutubehost(ytdlp_url)
    if is_youtube_host and ytdlp_proxy_endpoints:
        ydl_opts["proxy"] = random.choice(ytdlp_proxy_endpoints)
        # don't log proxy value secrets
        ytdlp_proxy_for_logs = (
            ydl_opts["proxy"].split("@")[1] if "@" in ydl_opts["proxy"] else "@@@"
        )
        logger.info("using yt-dlp proxy ...", proxy=ytdlp_proxy_for_logs)

    # skip warcprox proxying yt-dlp v.2023.07.06: youtube extractor using ranges
    # if worker._proxy_for(site):
    #    ydl_opts["proxy"] = "http://{}".format(worker._proxy_for(site))

    ydl = _YoutubeDL(ytdlp_url, params=ydl_opts)
    if site.extra_headers():
        ydl._opener.add_handler(ExtraHeaderAdder(site.extra_headers(page)))
    ydl.pushed_videos = []
    ydl.is_youtube_host = is_youtube_host

    return ydl


def _remember_videos(page, pushed_videos=None):
    """
    Saves info about videos captured by yt-dlp in `page.videos`.
    """
    if "videos" not in page:
        page.videos = []
    for pushed_video in pushed_videos or []:
        video = {
            "blame": "youtube-dl",
            "url": pushed_video["url"],
            "response_code": pushed_video["response_code"],
            "content-type": pushed_video["content-type"],
            "content-length": pushed_video["content-length"],
        }
        logger.debug("embedded video", video=video)
        page.videos.append(video)


def _try_youtube_dl(worker, ydl, site, page):
    max_attempts = PROXY_ATTEMPTS if ydl.is_youtube_host else 1
    attempt = 0
    while attempt < max_attempts:
        try:
            logger.info("trying yt-dlp", url=ydl.url)
            # should_download_vid = not ydl.is_youtube_host
            # then
            # ydl.extract_info(str(urlcanon.whatwg(ydl.url)), download=should_download_vid)
            # if ydl.is_youtube_host and ie_result:
            #     download_url = ie_result.get("url")
            with brozzler.thread_accept_exceptions():
                # we do whatwg canonicalization here to avoid "<urlopen error
                # no host given>" resulting in ProxyError
                # needs automated test
                # and yt-dlp needs sanitize_info for extract_info
                ie_result = ydl.sanitize_info(
                    ydl.extract_info(str(urlcanon.whatwg(ydl.url)))
                )
            metrics.brozzler_ydl_extract_successes.labels(ydl.is_youtube_host).inc(1)
            break
        except brozzler.ShutdownRequested:
            raise
        except Exception as e:
            if (
                hasattr(e, "exc_info")
                and e.exc_info[0] == yt_dlp.utils.UnsupportedError
            ):
                return None
            elif (
                hasattr(e, "exc_info")
                and e.exc_info[0] == urllib.error.HTTPError
                and hasattr(e.exc_info[1], "code")
                and e.exc_info[1].code == 420
            ):
                raise brozzler.ReachedLimit(e.exc_info[1])
            elif isinstance(e, yt_dlp.utils.DownloadError) and (
                "Redirect loop detected" in e.msg or "Too many redirects" in e.msg
            ):
                raise brozzler.VideoExtractorError(e.msg)
            else:
                # todo: other errors to handle separately?
                # OSError('Tunnel connection failed: 464 Host Not Allowed') (caused by ProxyError...)
                # and others...
                attempt += 1
                if attempt == max_attempts:
                    logger.warning(
                        "Failed after %s attempt(s)",
                        max_attempts,
                        attempts=max_attempts,
                        exc_info=True,
                    )
                    raise brozzler.VideoExtractorError(
                        "yt-dlp hit error extracting info for %s" % ydl.url
                    )
                else:
                    retry_wait = min(60, YTDLP_WAIT * (1.5 ** (attempt - 1)))
                    logger.info(
                        "Attempt %s failed. Retrying in %s seconds...",
                        attempt,
                        retry_wait,
                    )
                    time.sleep(retry_wait)
    else:
        raise brozzler.VideoExtractorError(
            "yt-dlp hit unknown error extracting info for %s" % ydl.url
        )

    logger.info("ytdlp completed successfully")

    _remember_videos(page, ydl.pushed_videos)
    if worker._using_warcprox(site):
        info_json = json.dumps(ie_result, sort_keys=True, indent=4)
        logger.info(
            "sending WARCPROX_WRITE_RECORD request to warcprox with yt-dlp json",
            url=ydl.url,
        )
        worker._warcprox_write_record(
            warcprox_address=worker._proxy_for(site),
            url="youtube-dl:%s" % str(urlcanon.semantic(ydl.url)),
            warc_type="metadata",
            content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
            payload=info_json.encode("utf-8"),
            extra_headers=site.extra_headers(page),
        )
    return ie_result


@metrics.brozzler_ytdlp_duration_seconds.time()
@metrics.brozzler_in_progress_ytdlps.track_inprogress()
def do_youtube_dl(worker, site, page, ytdlp_proxy_endpoints):
    """
    Runs yt-dlp configured for `worker` and `site` to download videos from
    `page`.

    Args:
        worker (brozzler.BrozzlerWorker): the calling brozzler worker
        site (brozzler.Site): the site we are brozzling
        page (brozzler.Page): the page we are brozzling

    Returns:
         `list` of `str`: outlink urls
    """
    with tempfile.TemporaryDirectory(
        prefix="brzl-ydl-", dir=worker._ytdlp_tmpdir
    ) as tempdir:
        logger.info("tempdir for yt-dlp", tempdir=tempdir)
        ydl = _build_youtube_dl(worker, tempdir, site, page, ytdlp_proxy_endpoints)
        ie_result = _try_youtube_dl(worker, ydl, site, page)
        outlinks = set()
        if ie_result and (
            ie_result.get("extractor") == "youtube:playlist"
            or ie_result.get("extractor") == "youtube:tab"
        ):
            # youtube watch pages as outlinks
            outlinks = {
                "https://www.youtube.com/watch?v=%s" % e["id"]
                for e in ie_result.get("entries_no_dl", [])
            }
        # any outlinks for other cases? soundcloud, maybe?
        return outlinks
