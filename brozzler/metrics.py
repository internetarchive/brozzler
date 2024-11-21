from typing import Optional

try:
    from http_sd_registry.client import (
        Client,
        Env,
        Registration,
        Scheme,
        format_self_target,
    )
    from http_sd_registry.config import ClientConfig
except ImportError:
    # for users without access to http_sd_registry
    http_sd_registry = None


from prometheus_client import Counter, Gauge, Histogram, start_http_server

# fmt: off
brozzler_in_progress_pages = Gauge("brozzler_in_progress_pages", "number of pages currently processing with brozzler")
brozzler_page_processing_duration_seconds = Histogram("brozzler_page_processing_duration_seconds", "time spent processing a page in brozzler")
brozzler_in_progress_headers = Gauge("brozzler_in_progress_headers", "number of headers currently processing with brozzler")
brozzler_header_processing_duration_seconds = Histogram("brozzler_header_processing_duration_seconds", "time spent processing one page's headers in brozzler")
brozzler_in_progress_browses = Gauge("brozzler_in_progress_browses", "number of pages currently browsing with brozzler")
brozzler_browsing_duration_seconds = Histogram("brozzler_browsing_duration_seconds", "time spent browsing a page in brozzler")
brozzler_in_progress_ytdlps = Gauge("brozzler_in_progress_ytdlps", "number of ytdlp sessions currently in progress with brozzler")
brozzler_ytdlp_duration_seconds = Histogram("brozzler_ytdlp_duration_seconds", "time spent running ytdlp for a page in brozzler")
brozzler_pages_crawled = Counter("brozzler_pages_crawled", "number of pages visited by brozzler")
brozzler_outlinks_found = Counter("brozzler_outlinks_found", "number of outlinks found by brozzler")
brozzler_last_page_crawled_time = Gauge("brozzler_last_page_crawled_time", "time of last page visit, in seconds since UNIX epoch")
brozzler_ydl_urls_checked = Counter("brozzler_ydl_urls_checked", "count of urls checked by brozzler yt-dlp")
brozzler_ydl_extract_successes = Counter("brozzler_ydl_extract_successes", "count of extracts completed by brozzler yt-dlp", labelnames=["youtube_host"])
brozzler_ydl_download_successes = Counter("brozzler_ydl_download_successes", "count of downloads completed by brozzler yt-dlp", labelnames=["youtube_host"])
# fmt: on


def register_prom_metrics(
    metrics_port: int = 8888,
    registry_url: Optional[str] = None,
    env: Optional[str] = None,
):
    # Start metrics endpoint for scraping
    start_http_server(metrics_port)

    if registry_url is None:
        return

    if env == "qa":
        env_for_prom = Env.qa
    elif env == "prod":
        env_for_prom = Env.prod
    else:
        env_for_prom = Env.qa

    config = ClientConfig(server_url_base=registry_url)
    client = Client(config)
    target = format_self_target(scrape_port=metrics_port)
    registration = Registration(
        target=target,
        env=env_for_prom,
        scheme=Scheme.http,
    )
    client.keep_registered_threaded(registration)
