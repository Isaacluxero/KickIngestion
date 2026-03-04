#!/usr/bin/env python3
"""
TikTok Analytics API fetcher.
Fetches view counts and engagement metrics for posted clips.
"""

import logging
import os

import requests

log = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


def fetch_video_stats(video_id: str) -> dict | None:
    """
    Fetch view count and engagement stats for a TikTok video.
    Returns dict with views, completion_rate, traffic_source or None on failure.
    """
    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
    if not token:
        log.warning("[fetcher] TIKTOK_ACCESS_TOKEN not set — cannot fetch stats")
        return None

    url = f"{TIKTOK_API_BASE}/video/query/"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "filters": {"video_ids": [video_id]},
        "fields": ["id", "view_count", "average_time_watched", "video_duration", "reach_type"],
    }

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        videos = data.get("data", {}).get("videos", [])
        if not videos:
            return None

        v = videos[0]
        duration = v.get("video_duration", 1) or 1
        avg_watch = v.get("average_time_watched", 0) or 0
        completion_rate = round(avg_watch / duration, 3)

        return {
            "views": v.get("view_count", 0),
            "completion_rate": completion_rate,
            "traffic_source": v.get("reach_type", "unknown"),
        }
    except Exception as e:
        log.warning("[fetcher] Failed to fetch stats for video %s: %s", video_id, e)
        return None


def extract_video_id(tiktok_url: str) -> str | None:
    """Extract numeric video ID from a TikTok URL."""
    if not tiktok_url:
        return None
    parts = tiktok_url.rstrip("/").split("/")
    for part in reversed(parts):
        if part.isdigit():
            return part
    return None
