"""
brozzler/ydl.py - youtube-dl / yt-dlp support for brozzler

Copyright (C) 2024 Internet Archive

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

import logging
import yt_dlp
from yt_dlp.utils import match_filter_func
import brozzler
import urllib.request
import tempfile
import urlcanon
import os
import json
import doublethink
import datetime
import threading

thread_local = threading.local()


def should_ytdlp(worker, site, page):
    # called only after we've passed needs_browsing() check
    if page.status_code != 200:
        logging.info("skipping ytdlp: non-200 page status")
        return False
    if site.skip_ytdlp:
        logging.info("skipping ytdlp: site marked skip_ytdlp")
        return False

    ytdlp_seed = site["metadata"]["ait_seed_id"] if "metadata" in site and "ait_seed_id" in site["metadata"] else None

    if ytdlp_seed and not site.skip_ytdlp:
        if ytdlp_seed in worker.skip_av_seeds:
            logging.info("skipping ytdlp: site in skip_av_seeds")
            site.skip_ytdlp = True
            return False
        else:
            site.skip_ytdlp = False

    ytdlp_url = page.redirect_url if page.redirect_url else page.url

    if "chrome-error:" in ytdlp_url:
        return False

    return True


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


def _build_youtube_dl(worker, destdir, site, page):
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
        logger = logging.getLogger(__module__ + "." + __qualname__)

        def add_default_extra_info(self, ie_result, ie, url):
            # hook in some logging
            super().add_default_extra_info(ie_result, ie, url)
            if ie_result.get("_type") == "playlist":
                self.logger.info("extractor %r found playlist in %s", ie.IE_NAME, url)
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
                    except Exception as e:
                        self.logger.warning(
                            "failed to unroll ie_result['entries']? for %s, %s; exception %s",
                            ie.IE_NAME,
                            url,
                            e,
                        )
                        ie_result["entries_no_dl"] = []
                    ie_result["entries"] = []
                    self.logger.info(
                        "not downloading %s media files from this "
                        "playlist because we expect to capture them from "
                        "individual watch/track/detail pages",
                        len(ie_result["entries_no_dl"]),
                    )
            else:
                self.logger.info("extractor %r found a download in %s", ie.IE_NAME, url)

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
                except ImportError as e:
                    mimetype = "video/%s" % info_dict["ext"]
                    self.logger.warning("guessing mimetype %s because %r", mimetype, e)

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
                "pushing %r video as %s (%s bytes) to " "warcprox at %s with url %s",
                info_dict["format"],
                mimetype,
                size,
                worker._proxy_for(site),
                url,
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
                    "brozzler-worker claiming this site id=%r",
                    site.id,
                )
                site.last_claimed = doublethink.utcnow()
                site.save()
        except:
            worker.logger.debug(
                "problem heartbeating site.last_claimed site id=%r",
                site.id,
                exc_info=True,
            )

    def ydl_postprocess_hook(d):
        if d["status"] == "finished":
            worker.logger.info("[ydl_postprocess_hook] Finished postprocessing")
            worker.logger.info(
                "[ydl_postprocess_hook] postprocessor: {}".format(d["postprocessor"])
            )
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
        # pre-v.2023.07.06: "format_sort": ["ext"],
        # v.2023.07.06 https://www.reddit.com/r/youtubedl/wiki/h264/?rdt=63577
        # recommended: convert working cli to api call with
        # https://github.com/yt-dlp/yt-dlp/blob/master/devscripts/cli_to_api.py
        "format": "b/bv+ba",
        "format_sort": ["res:720", "vcodec:h264", "acodec:aac"],
        # skip live streams
        "match_filter": match_filter_func("!is_live"),
        "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},
        # --cache-dir local or..
        # this looked like a problem with nsf-mounted homedir, maybe not a problem for brozzler on focal?
        "cache_dir": "/home/archiveit",
        "logger": logging.getLogger("yt_dlp"),
        "verbose": False,
        "quiet": False,
    }

    # skip proxying yt-dlp v.2023.07.06
    # if worker._proxy_for(site):
    #    ydl_opts["proxy"] = "http://{}".format(worker._proxy_for(site))

    ydl = _YoutubeDL(ydl_opts)
    if site.extra_headers():
        ydl._opener.add_handler(ExtraHeaderAdder(site.extra_headers(page)))
    ydl.pushed_videos = []

    return ydl


def _remember_videos(page, pushed_videos=None):
    """
    Saves info about videos captured by yt-dlp in `page.videos`.
    """
    if not "videos" in page:
        page.videos = []
    for pushed_video in pushed_videos or []:
        video = {
            "blame": "youtube-dl",
            "url": pushed_video["url"],
            "response_code": pushed_video["response_code"],
            "content-type": pushed_video["content-type"],
            "content-length": pushed_video["content-length"],
        }
        logging.debug("embedded video %s", video)
        page.videos.append(video)


def _try_youtube_dl(worker, ydl, site, page):
    ytdlp_url = page.redirect_url if page.redirect_url else page.url
    try:
        logging.info("trying yt-dlp on %s", ytdlp_url)

        with brozzler.thread_accept_exceptions():
            # we do whatwg canonicalization here to avoid "<urlopen error
            # no host given>" resulting in ProxyError
            # needs automated test
            # and yt-dlp needs sanitize_info for extract_info
            ie_result = ydl.sanitize_info(
                ydl.extract_info(str(urlcanon.whatwg(ytdlp_url)))
            )
        _remember_videos(page, ydl.pushed_videos)
        if worker._using_warcprox(site):
            info_json = json.dumps(ie_result, sort_keys=True, indent=4)
            logging.info(
                "sending WARCPROX_WRITE_RECORD request to warcprox "
                "with yt-dlp json for %s",
                ytdlp_url,
            )
            worker._warcprox_write_record(
                warcprox_address=worker._proxy_for(site),
                url="youtube-dl:%s" % str(urlcanon.semantic(ytdlp_url)),
                warc_type="metadata",
                content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
                payload=info_json.encode("utf-8"),
                extra_headers=site.extra_headers(page),
            )
        return ie_result
    except brozzler.ShutdownRequested as e:
        raise
    except Exception as e:
        if hasattr(e, "exc_info") and e.exc_info[0] == yt_dlp.utils.UnsupportedError:
            return None
        elif (
            hasattr(e, "exc_info")
            and e.exc_info[0] == urllib.error.HTTPError
            and hasattr(e.exc_info[1], "code")
            and e.exc_info[1].code == 420
        ):
            raise brozzler.ReachedLimit(e.exc_info[1])
        elif (
            hasattr(e, "exc_info")
            and e.exc_info[0] == urllib.error.URLError
            and worker._proxy_for(site)
        ):
            # connection problem when using a proxy == proxy error (XXX?)
            raise brozzler.ProxyError(
                "yt-dlp hit apparent proxy error from " "%s" % ytdlp_url
            ) from e
        else:
            raise


def do_youtube_dl(worker, site, page):
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
    with tempfile.TemporaryDirectory(prefix="brzl-ydl-") as tempdir:
        ydl = _build_youtube_dl(worker, tempdir, site, page)
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
