"""
brozzler/video_data.py - video data support for brozzler predup

Copyright (C) 2025 Internet Archive

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

import os
from dataclasses import dataclass
from typing import Any, List, Optional

import structlog
import urlcanon

logger = structlog.get_logger(logger_name=__name__)


# video_title, video_display_id, video_resolution, video_capture_status are new fields, mostly from yt-dlp metadata
@dataclass(frozen=True)
class VideoCaptureRecord:
    crawl_job_id: int
    is_test_crawl: bool
    seed_id: int
    collection_id: int
    containing_page_timestamp: str
    containing_page_digest: str
    containing_page_media_index: int
    containing_page_media_count: int
    video_digest: str
    video_timestamp: str
    video_mimetype: str
    video_http_status: int
    video_size: int
    containing_page_url: str
    video_url: str
    video_title: str
    video_display_id: (
        str  # aka yt-dlp metadata as display_id, e.g., youtube watch page v param
    )
    video_resolution: str
    video_capture_status: str  # recrawl?  what else?


class VideoDataClient:
    from psycopg_pool import ConnectionPool, PoolTimeout

    VIDEO_DATA_SOURCE = os.getenv("VIDEO_DATA_SOURCE")

    def __init__(self):
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(self.VIDEO_DATA_SOURCE, min_size=1, max_size=9)
        pool.wait()
        logger.info("pg pool ready")
        # atexit.register(pool.close)

        self.pool = pool

    def _execute_pg_query(self, query_tuple, fetchall=False) -> Optional[Any]:
        from psycopg_pool import PoolTimeout

        query_str, params = query_tuple
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query_str, params)
                    return cur.fetchall() if fetchall else cur.fetchone()
        except PoolTimeout as e:
            logger.warn("hit PoolTimeout: %s", e)
            self.pool.check()
        except Exception as e:
            logger.warn("postgres query failed: %s", e)
        return None

    def get_recent_video_capture(self, site=None, containing_page_url=None) -> List:
        # using ait_account_id as postgres partition id
        partition_id = (
            site["metadata"]["ait_account_id"]
            if site["metadata"]["ait_account_id"]
            else None
        )
        seed_id = (
            site["metadata"]["ait_seed_id"] if site["metadata"]["ait_seed_id"] else None
        )
        result = None

        if partition_id and seed_id and containing_page_url:
            # check for postgres query for most recent record
            pg_query = (
                "SELECT containing_page_timestamp from video where account_id = %s and seed_id = %s and containing_page_url = %s ORDER BY containing_page_timestamp DESC LIMIT 1",
                (partition_id, seed_id, str(urlcanon.aggressive(containing_page_url))),
            )
            try:
                result_tuple = self._execute_pg_query(pg_query)
                if result_tuple:
                    result = result_tuple[0]
                    logger.info("found most recent video capture record: %s", result)

            except Exception as e:
                logger.warn("postgres query failed: %s", e)
        else:
            logger.warn(
                "missing partition_id/account_id, seed_id, or containing_page_url"
            )

        return result

    def get_video_captures(self, site=None, source=None) -> List[str]:
        # using ait_account_id as postgres partition id
        partition_id = (
            site["metadata"]["ait_account_id"]
            if site["metadata"]["ait_account_id"]
            else None
        )
        seed_id = (
            site["metadata"]["ait_seed_id"] if site["metadata"]["ait_seed_id"] else None
        )
        results = []

        if source == "youtube":
            containing_page_url_pattern = "http://youtube.com/watch%"  # yes, video data canonicalization uses "http"
        # support other media sources here

        if partition_id and seed_id and source:
            pg_query = (
                "SELECT containing_page_url from video where account_id = %s and seed_id = %s and containing_page_url like %s",
                (
                    partition_id,
                    seed_id,
                    containing_page_url_pattern,
                ),
            )
            try:
                result = self._execute_pg_query(pg_query, fetchall=True)
                if result:
                    results = [row[0] for row in result]
            except Exception as e:
                logger.warn("postgres query failed: %s", e)
        else:
            logger.warn("missing partition_id/account_id, seed_id, or source")

        return results
