#!/usr/bin/env python3
"""
Clip tracker — daily CronJob that fetches TikTok analytics for recently
posted clips and prints a summary report to logs.
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import redis

import fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [tracker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
TRACKING_TTL = 60 * 60 * 24 * 30  # 30 days


def update_tracking(redis_client, item: dict):
    """Fetch and store analytics for one posted clip."""
    video_id = fetcher.extract_video_id(item.get("tiktok_url", ""))
    key = f"clip:tracking:{item['streamer']}:{item['timestamp']}"

    existing_raw = redis_client.get(key)
    tracking = json.loads(existing_raw) if existing_raw else {
        "streamer": item["streamer"],
        "tiktok_url": item.get("tiktok_url", ""),
        "posted_at": item.get("posted_at", 0),
        "score": item.get("score", 0),
        "views_1h": None,
        "views_24h": None,
        "views_7d": None,
        "completion_rate": None,
        "traffic_source": None,
    }

    if not video_id:
        redis_client.set(key, json.dumps(tracking), ex=TRACKING_TTL)
        return tracking

    stats = fetcher.fetch_video_stats(video_id)
    if stats:
        posted_at = item.get("posted_at", 0)
        age_hours = (time.time() - posted_at) / 3600

        views = stats["views"]
        if age_hours < 2:
            tracking["views_1h"] = views
        elif age_hours < 26:
            tracking["views_24h"] = views
        else:
            tracking["views_7d"] = views

        tracking["completion_rate"] = stats["completion_rate"]
        tracking["traffic_source"] = stats["traffic_source"]

    redis_client.set(key, json.dumps(tracking), ex=TRACKING_TTL)
    return tracking


def print_daily_report(redis_client, all_tracking: list[dict]):
    """Print a formatted daily summary to stdout/logs."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday_cutoff = time.time() - 86400

    yesterday_clips = [t for t in all_tracking if t.get("posted_at", 0) >= yesterday_cutoff]

    total_views_24h = sum(t.get("views_24h") or 0 for t in yesterday_clips)

    # Per-streamer breakdown
    streamer_views: dict[str, int] = defaultdict(int)
    streamer_count: dict[str, int] = defaultdict(int)
    for t in yesterday_clips:
        streamer_views[t["streamer"]] += t.get("views_24h") or 0
        streamer_count[t["streamer"]] += 1

    top_streamers = sorted(streamer_views.items(), key=lambda x: x[1], reverse=True)[:3]

    best = max(yesterday_clips, key=lambda t: t.get("views_24h") or 0, default=None)

    # Score correlation
    buckets: dict[str, list[int]] = {"8-10": [], "6-7": [], "<6": []}
    for t in all_tracking:
        v = t.get("views_24h") or 0
        s = t.get("score", 0)
        if s >= 8:
            buckets["8-10"].append(v)
        elif s >= 6:
            buckets["6-7"].append(v)
        else:
            buckets["<6"].append(v)

    def avg(lst): return int(sum(lst) / len(lst)) if lst else 0

    queue_stats = {
        "pending": redis_client.llen("clip:ready"),
        "approved": redis_client.llen("clip:post:queue"),
        "posted_today": len(yesterday_clips),
    }

    sep = "=" * 40
    log.info(sep)
    log.info("=== Daily Clip Report — %s ===", today)
    log.info("Posted yesterday:     %d clips", len(yesterday_clips))
    log.info("Total views (24h):    %s", f"{total_views_24h:,}")
    log.info("")

    if top_streamers:
        log.info("Top streamer:")
        for streamer, views in top_streamers:
            log.info("  %-20s %s views, %d clips", streamer, f"{views:,}", streamer_count[streamer])
    log.info("")

    if best and best.get("views_24h"):
        label = f"{best['streamer']}/{int(best['timestamp'])}"
        log.info("Best clip:     %s — %s views, score %s", label, f"{best['views_24h']:,}", best.get("score", "?"))
    log.info("")

    log.info("Score correlation:")
    log.info("  Score 8-10:  avg %s views per clip", f"{avg(buckets['8-10']):,}")
    log.info("  Score 6-7:   avg %s views per clip", f"{avg(buckets['6-7']):,}")
    log.info("  Score < 6:   avg %s views per clip", f"{avg(buckets['<6']):,}")
    log.info("")

    log.info("Queue status:")
    log.info("  pending:   %d clips", queue_stats["pending"])
    log.info("  approved:  %d clips", queue_stats["approved"])
    log.info("  posted:    %d clips today", queue_stats["posted_today"])
    log.info(sep)


def main():
    log.info("[tracker] Starting daily tracking run")
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    # Fetch all posted clips
    raw_items = redis_client.lrange("clip:posted", 0, -1)
    log.info("[tracker] Found %d posted clips to track", len(raw_items))

    all_tracking = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
            tracking = update_tracking(redis_client, item)
            all_tracking.append(tracking)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("[tracker] Skipping malformed posted entry: %s", e)

    print_daily_report(redis_client, all_tracking)
    log.info("[tracker] Done")


if __name__ == "__main__":
    main()
