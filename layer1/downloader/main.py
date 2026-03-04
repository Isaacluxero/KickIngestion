#!/usr/bin/env python3
"""
Clip downloader — consumes clip:queue from Redis and runs yt-dlp.

Priority handling:
  - "high"   → download immediately (2+ viewer clips detected at spike time)
  - "normal" → download immediately (clips API unavailable)
  - "low"    → wait 5 minutes before downloading (confirms the moment was genuinely viral)

Retries up to 3 times on yt-dlp failure.
Failed events (after all retries) are pushed to Redis list `clip:failed`.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [downloader] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
CLIPS_DIR = os.environ.get("CLIPS_DIR", "/clips")
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds between yt-dlp retry attempts
LOW_PRIORITY_DELAY = 300  # 5 minutes


async def run_ytdlp(streamer: str, timestamp: float, clip_window: int) -> tuple[bool, str]:
    """
    Download a VOD segment with yt-dlp.
    Returns (success, error_message).
    """
    start = timestamp - clip_window
    end = timestamp + clip_window
    out_path = f"{CLIPS_DIR}/{streamer}/{int(timestamp)}.%(ext)s"
    url = f"https://kick.com/{streamer}"

    cmd = [
        "yt-dlp",
        "--download-sections", f"*{start}-{end}",
        "-o", out_path,
        url,
    ]

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        log.info(
            "[%s] yt-dlp attempt %d/%d: window=%.0f-%.0f → %s",
            streamer, attempt, MAX_RETRIES, start, end, out_path,
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                log.info("[%s] Download succeeded on attempt %d", streamer, attempt)
                return True, ""

            last_error = stderr.decode(errors="replace").strip()
            log.warning(
                "[%s] yt-dlp failed (attempt %d/%d, rc=%d): %.500s",
                streamer, attempt, MAX_RETRIES, proc.returncode, last_error,
            )

        except Exception as e:
            last_error = str(e)
            log.error("[%s] Exception running yt-dlp (attempt %d): %s", streamer, attempt, e)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAY)

    return False, f"All {MAX_RETRIES} attempts failed. Last error: {last_error}"


async def process_event(redis_client, event: dict):
    """Process a single clip:queue event end-to-end."""
    streamer = event["streamer"]
    timestamp = event["timestamp"]
    clip_window = event.get("clip_window", 150)
    priority = event.get("priority", "normal")
    msgs_per_sec = event.get("msgs_per_sec", 0)
    hype_ratio = event.get("hype_ratio", 0)
    clip_count = event.get("clip_count", 0)

    log.info(
        "[%s] Event received: priority=%s msgs/s=%.1f hype_ratio=%.2f clip_count=%d",
        streamer, priority, msgs_per_sec, hype_ratio, clip_count,
    )

    # Low-priority: hold 5 minutes before downloading to confirm the moment was viral
    if priority == "low":
        log.info("[%s] Low priority — waiting %ds before download", streamer, LOW_PRIORITY_DELAY)
        await asyncio.sleep(LOW_PRIORITY_DELAY)

    # Ensure output directory exists
    out_dir = Path(CLIPS_DIR) / streamer
    out_dir.mkdir(parents=True, exist_ok=True)

    success, error = await run_ytdlp(streamer, timestamp, clip_window)

    if success:
        # Find the actual downloaded file (yt-dlp resolves %(ext)s at runtime)
        matches = list(out_dir.glob(f"{int(timestamp)}.*"))
        if matches:
            file_path = str(matches[0])
            transcribe_entry = {
                "streamer": streamer,
                "timestamp": timestamp,
                "msgs_per_sec": msgs_per_sec,
                "stream_id": event.get("stream_id", ""),
                "clip_window": clip_window,
                "hype_ratio": hype_ratio,
                "priority": priority,
                "clip_count": clip_count,
                "file_path": file_path,
            }
            await redis_client.lpush("clip:queue:transcribe", json.dumps(transcribe_entry))
            log.info("[%s] Clip saved to %s — queued for analysis", streamer, file_path)
        else:
            log.warning("[%s] Download success but no file found at %s/%d.*", streamer, out_dir, int(timestamp))
    else:
        failure_entry = {**event, "error": error}
        await redis_client.rpush("clip:failed", json.dumps(failure_entry))
        log.error("[%s] All download attempts failed — logged to clip:failed", streamer)


async def main():
    log.info("Clip downloader starting — watching clip:queue (clips_dir=%s)", CLIPS_DIR)

    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    active_tasks: set[asyncio.Task] = set()

    try:
        while True:
            try:
                # Blocking pop — waits until an item is available
                result = await redis.blpop("clip:queue", timeout=0)
                if result is None:
                    continue

                _, raw = result
                event = json.loads(raw)

                # Process events concurrently so low-priority delays don't block high-priority ones
                task = asyncio.create_task(process_event(redis, event))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)

            except json.JSONDecodeError as e:
                log.error("Malformed event in clip:queue: %s", e)
            except Exception as e:
                log.error("Error reading from clip:queue: %s — retrying in 2s", e)
                await asyncio.sleep(2)

    finally:
        if active_tasks:
            log.info("Waiting for %d active download tasks to finish", len(active_tasks))
            await asyncio.gather(*active_tasks, return_exceptions=True)
        await redis.aclose()
        log.info("Clip downloader stopped")


if __name__ == "__main__":
    asyncio.run(main())
