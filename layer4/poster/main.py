#!/usr/bin/env python3
"""
Clip poster — consumes clip:post:queue and posts to TikTok with
scheduled slots, account rotation, and cross-platform n8n webhook.
"""

import json
import logging
import os
import time

import redis
import requests

import scheduler
import tiktok

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [poster] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
MAX_POST_RETRIES = 3


def get_next_account(redis_client) -> str:
    """Round-robin account selection from TIKTOK_SESSIONIDS env var."""
    accounts = os.environ["TIKTOK_SESSIONIDS"].split(",")
    idx = int(redis_client.get("post:account:idx") or 0)
    account = accounts[idx % len(accounts)]
    redis_client.set("post:account:idx", idx + 1)
    return account.strip()


def trigger_n8n(item: dict):
    """Fire n8n webhook for cross-platform distribution (Instagram Reels, YouTube Shorts)."""
    if not N8N_WEBHOOK_URL:
        return
    try:
        requests.post(
            N8N_WEBHOOK_URL,
            json={
                "file_path": item["file_path"],
                "title": item["title"],
                "hashtags": item["hashtags"],
                "streamer": item["streamer"],
            },
            timeout=10,
        )
    except Exception as e:
        log.warning("[poster] n8n webhook failed (non-fatal): %s", e)


def post_clip(redis_client, item: dict):
    """Post one clip to TikTok, retrying with a different account on failure."""
    description = item["title"] + " " + " ".join(f"#{tag}" for tag in item.get("hashtags", []))

    for attempt in range(1, MAX_POST_RETRIES + 1):
        account = get_next_account(redis_client)

        if not scheduler.min_gap_elapsed(redis_client, account):
            log.info("[poster] Account %s...%s posted recently — skipping this attempt", account[:8], account[-4:])
            continue

        try:
            tiktok.upload(item["file_path"], description, account)
            scheduler.record_post(redis_client, account)

            posted_entry = {
                "streamer": item["streamer"],
                "timestamp": item["timestamp"],
                "tiktok_url": "",  # tiktok-uploader doesn't return the URL directly
                "account": account[:8] + "...",
                "posted_at": time.time(),
                "score": item.get("score", 0),
            }
            redis_client.lpush("clip:posted", json.dumps(posted_entry))
            log.info("[poster] Posted %s/%s successfully on attempt %d", item["streamer"], item["timestamp"], attempt)

            trigger_n8n(item)
            return

        except Exception as e:
            log.warning("[poster] Post attempt %d/%d failed: %s", attempt, MAX_POST_RETRIES, e)
            if attempt < MAX_POST_RETRIES:
                time.sleep(10)

    # All retries exhausted
    redis_client.lpush("clip:post:failed", json.dumps({**item, "error": "All posting retries failed"}))
    log.error("[poster] Failed to post %s/%s after %d attempts — moved to clip:post:failed",
              item["streamer"], item["timestamp"], MAX_POST_RETRIES)


def main():
    log.info("[poster] Starting — watching clip:post:queue")
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    while True:
        try:
            if not scheduler.should_post_now(redis_client):
                time.sleep(60)
                continue

            # A slot is available — pop a clip
            result = redis_client.brpop("clip:post:queue", timeout=5)
            if result is None:
                log.info("[poster] Slot available but clip:post:queue is empty")
                time.sleep(60)
                continue

            _, raw = result
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as e:
                log.error("[poster] Malformed item in clip:post:queue: %s", e)
                continue

            post_clip(redis_client, item)

        except Exception as e:
            log.error("[poster] Unexpected error in main loop: %s — retrying in 30s", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
