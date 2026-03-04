#!/usr/bin/env python3
"""
Clip analyzer — consumes clip:queue:transcribe, transcribes with Whisper,
scores with Claude, processes with FFmpeg, pushes to clip:ready.

Sequential processing — one clip at a time, no threads or asyncio.
Uses BRPOPLPUSH for crash-safe queue consumption.
"""

import json
import logging
import os
import time

import redis

import processor
import scorer
import transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [analyzer] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
MIN_SCORE = int(os.environ.get("MIN_SCORE", "6"))


def _log(streamer: str, ts: float, msg: str):
    label = f"{streamer}/{int(ts)}.mp4"
    log.info("[analyzer] %s — %s", label, msg)


def process_item(redis_client: redis.Redis, item: dict, raw: str):
    streamer = item["streamer"]
    timestamp = item["timestamp"]
    file_path = item["file_path"]
    msgs_per_sec = item.get("msgs_per_sec", 0)
    hype_ratio = item.get("hype_ratio", 0)
    clip_count = item.get("clip_count", 0)
    priority = item.get("priority", "normal")

    _log(streamer, timestamp, "received from queue")

    # --- Step 2: Transcription ---
    _log(streamer, timestamp, "transcription started")
    t0 = time.time()
    try:
        transcript, segments, duration = transcriber.transcribe(file_path)
    except Exception as e:
        log.error("[analyzer] Transcription failed for %s/%d: %s", streamer, int(timestamp), e)
        redis_client.lmove("clip:processing", "clip:failed", "RIGHT", "LEFT")
        return

    elapsed = time.time() - t0
    _log(streamer, timestamp, f"transcription done ({elapsed:.1f}s), {len(transcript.split())} words")

    # --- Step 3: Scoring ---
    try:
        score_result = scorer.score_clip(
            streamer=streamer,
            transcript=transcript,
            msgs_per_sec=msgs_per_sec,
            hype_ratio=hype_ratio,
            clip_count=clip_count,
            duration=duration,
        )
    except Exception as e:
        log.error("[analyzer] Scoring failed for %s/%d: %s", streamer, int(timestamp), e)
        redis_client.lmove("clip:processing", "clip:failed", "RIGHT", "LEFT")
        return

    score = score_result["score"]
    reason = score_result["reason"]
    _log(streamer, timestamp, f'score: {score} — "{reason}"')

    # --- Step 4: FFmpeg processing (only if score >= MIN_SCORE) ---
    final_path = file_path
    thumb_path = None

    if score >= MIN_SCORE:
        _log(streamer, timestamp, "FFmpeg started")
        t1 = time.time()
        try:
            final_path, thumb_path = processor.process_clip(
                file_path=file_path,
                streamer=streamer,
                timestamp=timestamp,
                segments=segments,
            )
            elapsed2 = time.time() - t1
            _log(streamer, timestamp, f"FFmpeg done ({elapsed2:.1f}s)")
        except Exception as e:
            log.warning("[analyzer] FFmpeg failed for %s/%d, using raw file: %s", streamer, int(timestamp), e)
            final_path = file_path
            thumb_path = None
    else:
        _log(streamer, timestamp, f"score {score} < {MIN_SCORE} — skipping FFmpeg")

    # --- Step 5: Push to clip:ready ---
    ready_entry = {
        "streamer": streamer,
        "timestamp": timestamp,
        "score": score,
        "reason": reason,
        "suggested_title": score_result["suggested_title"],
        "suggested_hashtags": score_result["suggested_hashtags"],
        "hype_ratio": hype_ratio,
        "priority": priority,
        "clip_count": clip_count,
        "file_path": final_path,
        "thumbnail_path": thumb_path,
        "transcript": transcript,
        "duration": duration,
        "category": score_result["category"],
        "msgs_per_sec": msgs_per_sec,
    }
    redis_client.lpush("clip:ready", json.dumps(ready_entry))
    _log(streamer, timestamp, "pushed to clip:ready")

    # Remove from crash-recovery working list
    redis_client.lrem("clip:processing", 1, raw)


def main():
    log.info("[analyzer] Starting — watching clip:queue:transcribe (MIN_SCORE=%d)", MIN_SCORE)

    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    while True:
        try:
            # Atomically move from queue:transcribe to processing list (crash-safe)
            raw = redis_client.brpoplpush("clip:queue:transcribe", "clip:processing", timeout=30)
            if raw is None:
                continue  # timeout, loop again

            try:
                item = json.loads(raw)
            except json.JSONDecodeError as e:
                log.error("[analyzer] Malformed item in queue: %s", e)
                redis_client.lrem("clip:processing", 1, raw)
                continue

            process_item(redis_client, item, raw)

        except Exception as e:
            log.error("[analyzer] Unexpected error in main loop: %s — retrying in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
