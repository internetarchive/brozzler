'''
brozzler/ydl.py - youtube-dl support for brozzler

Copyright (C) 2018 Internet Archive

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
import youtube_dl
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
_orig__finish_frag_download = youtube_dl.downloader.fragment.FragmentFD._finish_frag_download
def _finish_frag_download(ffd_self, ctx):
    '''
    We monkey-patch this youtube-dl internal method `_finish_frag_download()`
    because it gets called after downloading the last segment of a segmented
    video, which is a good time to upload the stitched-up video that youtube-dl
    creates for us to warcprox. We have it call a thread-local callback
    since different threads may be youtube-dl'ing at the same time.
    '''
    result = _orig__finish_frag_download(ffd_self, ctx)
    if hasattr(thread_local, 'finish_frag_download_callback'):
        thread_local.finish_frag_download_callback(ffd_self, ctx)
    return result
youtube_dl.downloader.fragment.FragmentFD._finish_frag_download = _finish_frag_download

_orig_webpage_read_content = youtube_dl.extractor.generic.GenericIE._webpage_read_content
def _webpage_read_content(self, *args, **kwargs):
    content = _orig_webpage_read_content(self, *args, **kwargs)
    if len(content) > 20000000:
        logging.warn(
                'bypassing youtube-dl extraction because content is '
                'too large (%s characters)', len(content))
        return ''
    return content
youtube_dl.extractor.generic.GenericIE._webpage_read_content = _webpage_read_content

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
    logger = logging.getLogger(__module__ + "." + __qualname__)

    def __init__(self):
        self.reset()

    def _http_response(self, request, response):
        fetch = {
            'url': request.full_url,
            'method': request.get_method(),
            'response_code': response.code,
            'response_headers': response.headers,
        }
        self.fetches.append(fetch)
        return response

    http_response = https_response = _http_response

    def reset(self):
        self.fetches = []

def final_bounces(fetches, url):
    """
    Resolves redirect chains in `fetches` and returns a list of fetches
    representing the final redirect destinations of the given url. There could
    be more than one if for example youtube-dl hit the same url with HEAD and
    then GET requests.
    """
    redirects = {}
    for fetch in fetches:
         # XXX check http status 301,302,303,307? check for "uri" header
         # as well as "location"? see urllib.request.HTTPRedirectHandler
         if 'location' in fetch['response_headers']:
             redirects[fetch['url']] = fetch

    final_url = url
    while final_url in redirects:
        fetch = redirects.pop(final_url)
        final_url = urllib.parse.urljoin(
                fetch['url'], fetch['response_headers']['location'])

    final_bounces = []
    for fetch in fetches:
        if fetch['url'] == final_url:
            final_bounces.append(fetch)

    return final_bounces

def _build_youtube_dl(worker, destdir, site):
    '''
    Builds a `youtube_dl.YoutubeDL` for brozzling `site` with `worker`.

    The `YoutubeDL` instance does a few special brozzler-specific things:

    - keeps track of urls fetched using a `YoutubeDLSpy`
    - periodically updates `site.last_claimed` in rethinkdb
    - if brozzling through warcprox and downloading segmented videos (e.g.
      HLS), pushes the stitched-up video created by youtube-dl to warcprox
      using a WARCPROX_WRITE_RECORD request
    - some logging

    Args:
        worker (brozzler.BrozzlerWorker): the calling brozzler worker
        destdir (str): where to save downloaded videos
        site (brozzler.Site): the site we are brozzling

    Returns:
        a `youtube_dl.YoutubeDL` instance
    '''

    class _YoutubeDL(youtube_dl.YoutubeDL):
        logger = logging.getLogger(__module__ + "." + __qualname__)

        def urlopen(self, req):
            try:
                url = req.full_url
            except AttributeError:
                url = req
            self.logger.debug('fetching %r', url)
            return super().urlopen(req)

        def add_default_extra_info(self, ie_result, ie, url):
            # hook in some logging
            super().add_default_extra_info(ie_result, ie, url)
            if ie_result.get('_type') == 'playlist':
                self.logger.info(
                        'extractor %r found playlist in %s', ie.IE_NAME, url)
                if ie.IE_NAME == 'youtube:playlist':
                    # At this point ie_result['entries'] is an iterator that
                    # will fetch more metadata from youtube to list all the
                    # videos. We unroll that iterator here partly because
                    # otherwise `process_ie_result()` will clobber it, and we
                    # use it later to extract the watch pages as outlinks.
                    ie_result['entries_no_dl'] = list(ie_result['entries'])
                    ie_result['entries'] = []
                    self.logger.info(
                            'not downoading %s videos from this youtube '
                            'playlist because we expect to capture them from '
                            'individual watch pages',
                            len(ie_result['entries_no_dl']))
            else:
                self.logger.info(
                        'extractor %r found a video in %s', ie.IE_NAME, url)

        def _push_stitched_up_vid_to_warcprox(self, site, info_dict, ctx):
            # XXX Don't know how to get the right content-type. Youtube-dl
            # doesn't supply it. Sometimes (with --hls-prefer-native)
            # youtube-dl produces a stitched-up video that /usr/bin/file fails
            # to identify (says "application/octet-stream"). `ffprobe` doesn't
            # give us a mimetype.
            if info_dict.get('ext') == 'mp4':
                mimetype = 'video/mp4'
            else:
                try:
                    import magic
                    mimetype = magic.from_file(ctx['filename'], mime=True)
                except ImportError as e:
                    mimetype = 'video/%s' % info_dict['ext']
                    self.logger.warn(
                            'guessing mimetype %s because %r', mimetype, e)

            url = 'youtube-dl:%05d:%s' % (
                    info_dict.get('playlist_index') or 1,
                    info_dict['webpage_url'])
            size = os.path.getsize(ctx['filename'])
            self.logger.info(
                    'pushing %r video stitched-up as %s (%s bytes) to '
                    'warcprox at %s with url %s', info_dict['format'],
                    mimetype, size, worker._proxy_for(site), url)
            with open(ctx['filename'], 'rb') as f:
                # include content-length header to avoid chunked
                # transfer, which warcprox currently rejects
                extra_headers = dict(site.extra_headers())
                extra_headers['content-length'] = size
                request, response = worker._warcprox_write_record(
                        warcprox_address=worker._proxy_for(site), url=url,
                        warc_type='resource', content_type=mimetype, payload=f,
                        extra_headers=extra_headers)
                # consulted by _remember_videos()
                self.stitch_ups.append({
                    'url': url,
                    'response_code': response.code,
                    'content-type': mimetype,
                    'content-length': size,
                })

        def process_info(self, info_dict):
            '''
            See comment above on `_finish_frag_download()`
            '''
            def ffd_callback(ffd_self, ctx):
                if worker._using_warcprox(site):
                    self._push_stitched_up_vid_to_warcprox(site, info_dict, ctx)
            try:
                thread_local.finish_frag_download_callback = ffd_callback
                return super().process_info(info_dict)
            finally:
                delattr(thread_local, 'finish_frag_download_callback')

    def maybe_heartbeat_site_last_claimed(*args, **kwargs):
        # in case youtube-dl takes a long time, heartbeat site.last_claimed
        # to prevent another brozzler-worker from claiming the site
        try:
            if site.rr and doublethink.utcnow() - site.last_claimed > datetime.timedelta(minutes=worker.SITE_SESSION_MINUTES):
                worker.logger.debug(
                        'heartbeating site.last_claimed to prevent another '
                        'brozzler-worker claiming this site id=%r', site.id)
                site.last_claimed = doublethink.utcnow()
                site.save()
        except:
            worker.logger.debug(
                    'problem heartbeating site.last_claimed site id=%r',
                    site.id, exc_info=True)

    ydl_opts = {
        "outtmpl": "{}/ydl%(autonumber)s.out".format(destdir),
        "retries": 1,
        "nocheckcertificate": True,
        "hls_prefer_native": True,
        "noprogress": True,
        "nopart": True,
        "no_color": True,
        "progress_hooks": [maybe_heartbeat_site_last_claimed],

         # https://github.com/rg3/youtube-dl/blob/master/README.md#format-selection
         # "best: Select the best quality format represented by a single
         # file with video and audio."
        "format": "best/bestvideo+bestaudio",

        ### we do our own logging
        # "logger": logging.getLogger("youtube_dl"),
        "verbose": False,
        "quiet": True,
    }
    if worker._proxy_for(site):
        ydl_opts["proxy"] = "http://{}".format(worker._proxy_for(site))
    ydl = _YoutubeDL(ydl_opts)
    if site.extra_headers():
        ydl._opener.add_handler(ExtraHeaderAdder(site.extra_headers()))
    ydl.fetch_spy = YoutubeDLSpy()
    ydl.stitch_ups = []
    ydl._opener.add_handler(ydl.fetch_spy)
    return ydl

def _remember_videos(page, fetches, stitch_ups=None):
    '''
    Saves info about videos captured by youtube-dl in `page.videos`.
    '''
    if not 'videos' in page:
        page.videos = []
    for fetch in fetches or []:
        content_type = fetch['response_headers'].get_content_type()
        if (content_type.startswith('video/')
                # skip manifests of DASH segmented video -
                # see https://github.com/internetarchive/brozzler/pull/70
                and content_type != 'video/vnd.mpeg.dash.mpd'
                and fetch['method'] == 'GET'
                and fetch['response_code'] in (200, 206)):
            video = {
                'blame': 'youtube-dl',
                'url': fetch['url'],
                'response_code': fetch['response_code'],
                'content-type': content_type,
            }
            if 'content-length' in fetch['response_headers']:
                video['content-length'] = int(
                        fetch['response_headers']['content-length'])
            if 'content-range' in fetch['response_headers']:
                video['content-range'] = fetch[
                        'response_headers']['content-range']
            logging.debug('embedded video %s', video)
            page.videos.append(video)
    for stitch_up in stitch_ups or []:
        if stitch_up['content-type'].startswith('video/'):
            video = {
                'blame': 'youtube-dl',
                'url': stitch_up['url'],
                'response_code': stitch_up['response_code'],
                'content-type': stitch_up['content-type'],
                'content-length': stitch_up['content-length'],
            }
            logging.debug('embedded video %s', video)
            page.videos.append(video)

def _try_youtube_dl(worker, ydl, site, page):
    try:
        logging.info("trying youtube-dl on %s", page)

        with brozzler.thread_accept_exceptions():
            # we do whatwg canonicalization here to avoid "<urlopen error
            # no host given>" resulting in ProxyError
            # needs automated test
            ie_result = ydl.extract_info(str(urlcanon.whatwg(page.url)))
        _remember_videos(page, ydl.fetch_spy.fetches, ydl.stitch_ups)
        if worker._using_warcprox(site):
            info_json = json.dumps(ie_result, sort_keys=True, indent=4)
            logging.info(
                    "sending WARCPROX_WRITE_RECORD request to warcprox "
                    "with youtube-dl json for %s", page)
            worker._warcprox_write_record(
                    warcprox_address=worker._proxy_for(site),
                    url="youtube-dl:%s" % str(urlcanon.semantic(page.url)),
                    warc_type="metadata",
                    content_type="application/vnd.youtube-dl_formats+json;charset=utf-8",
                    payload=info_json.encode("utf-8"),
                    extra_headers=site.extra_headers())
        return ie_result
    except brozzler.ShutdownRequested as e:
        raise
    except Exception as e:
        if hasattr(e, "exc_info") and e.exc_info[0] == youtube_dl.utils.UnsupportedError:
            return None
        elif (hasattr(e, "exc_info")
                and e.exc_info[0] == urllib.error.HTTPError
                and hasattr(e.exc_info[1], "code")
                and e.exc_info[1].code == 420):
            raise brozzler.ReachedLimit(e.exc_info[1])
        elif (hasattr(e, 'exc_info')
                and e.exc_info[0] == urllib.error.URLError
                and worker._proxy_for(site)):
            # connection problem when using a proxy == proxy error (XXX?)
            raise brozzler.ProxyError(
                    'youtube-dl hit apparent proxy error from '
                    '%s' % page.url) from e
        else:
            raise

def do_youtube_dl(worker, site, page):
    '''
    Runs youtube-dl configured for `worker` and `site` to download videos from
    `page`.

    Args:
        worker (brozzler.BrozzlerWorker): the calling brozzler worker
        site (brozzler.Site): the site we are brozzling
        page (brozzler.Page): the page we are brozzling

    Returns:
        tuple with two entries:
            `list` of `dict`: with info about urls fetched:
                [{
                    'url': ...,
                    'method': ...,
                    'response_code': ...,
                    'response_headers': ...,
                }, ...]
            `list` of `str`: outlink urls
    '''
    with tempfile.TemporaryDirectory(prefix='brzl-ydl-') as tempdir:
        ydl = _build_youtube_dl(worker, tempdir, site)
        ie_result = _try_youtube_dl(worker, ydl, site, page)
        outlinks = set()
        if ie_result and ie_result.get('extractor') == 'youtube:playlist':
            # youtube watch pages as outlinks
            outlinks = {'https://www.youtube.com/watch?v=%s' % e['id']
                        for e in ie_result.get('entries_no_dl', [])}
        # any outlinks for other cases?
        return ydl.fetch_spy.fetches, outlinks
