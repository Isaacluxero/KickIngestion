#!/usr/bin/env python3
"""
TikTok upload wrapper around tiktok-uploader.
"""

import logging

log = logging.getLogger(__name__)


def upload(file_path: str, description: str, sessionid: str) -> None:
    """
    Upload a video to TikTok using the given session cookie.
    Raises on failure.
    """
    from tiktok_uploader.upload import upload_video

    log.info("[tiktok] Uploading %s (desc=%s...)", file_path, description[:40])
    upload_video(
        file_path,
        description=description,
        sessionid=sessionid,
        headless=True,
    )
    log.info("[tiktok] Upload complete: %s", file_path)
