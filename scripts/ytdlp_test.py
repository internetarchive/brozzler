import math
import sys

import brozzler

CHROME_EXE = brozzler.suggest_default_chrome_exe()


def brozzle_page(worker, page) -> bool:
    site = brozzler.Site(None, {})

    with brozzler.Browser(chrome_exe=CHROME_EXE) as browser:
        worker.brozzle_page(browser, site, page)

    # This gets assigned after a video is captured; if an
    # exception was raised by yt-dlp, it never gets assigned.
    if "videos" not in page:
        return False

    if len(page.videos) > 0:
        response_code = page.videos[0]["response_code"]
        if (
            response_code >= 200
            and response_code < 300
            and page.videos[0]["content-length"] > 0
        ):
            return True

    return False


worker = brozzler.BrozzlerWorker(None, proxy="localhost:8000")

youtube_videos = [
    # Short YouTube video
    "https://www.youtube.com/watch?v=AdtZtvlFi9o",
    # Long YouTube video (former livestream we've had trouble capturing)
    "https://www.youtube.com/watch?v=v4f6InE9X_c",
    # YouTube Short
    "https://www.youtube.com/shorts/ee_lH4qlfzc",
]

videos = [
    # Vimeo
    "https://vimeo.com/175568834",
    # Instagram
    "https://www.instagram.com/reel/DFZMmHONL8K/",
    # Audio in a webpage
    "https://www.woxx.lu/am-bistro-mat-der-woxx-308-grenzenlose-fitness/",
    # Video in a webpage
    "https://play.rtl.lu/shows/lb/eurovision/episodes/r/3414779",
    # TikTok
    "https://www.tiktok.com/@cbcnews/video/7498842317630033157",
    # Twitter
    "https://x.com/NationalZoo/status/690915532539838464",
    # Facebook
    "https://www.facebook.com/100064323443815/videos/1421958299004555",
]

successes = 0
min_successes = math.floor(len(videos) * 0.75) or 1

# We expect YouTube videos to fail, so we separate these out and
# don't count these towards failures. It's still useful to perform
# the setup and attempt so we get insight into whether other things
# may have messed up.
for url in youtube_videos:
    page = brozzler.Page(None, {"url": url})
    brozzle_page(worker, page)

for url in videos:
    page = brozzler.Page(None, {"url": url})
    if brozzle_page(worker, page):
        successes += 1

if successes >= min_successes:
    print(f"Success! {successes}/{len(videos)} captures succeeded.")
else:
    print(f"Failure: {successes}/{len(videos)} captures succeeded.")
    sys.exit(1)
