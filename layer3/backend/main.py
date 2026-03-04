#!/usr/bin/env python3
"""
Dashboard backend — FastAPI serving clip approval UI.
Reads from clip:ready, moves approved clips to clip:post:queue,
rejected to clip:rejected. Serves static React build.
"""

import json
import logging
import os
import time
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [dashboard] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
CLIPS_DIR = os.environ.get("CLIPS_DIR", "/clips")

app = FastAPI(title="Clip Dashboard")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def _all_clips() -> list[dict]:
    """Return all items from clip:ready, parsed, with id injected."""
    raw_items = redis_client.lrange("clip:ready", 0, -1)
    clips = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
            item["id"] = f"{item['streamer']}:{item['timestamp']}"
            clips.append(item)
        except (json.JSONDecodeError, KeyError):
            continue
    return clips


def _find_raw(clip_id: str) -> tuple[dict, str] | tuple[None, None]:
    """Find a clip in clip:ready by id. Returns (parsed_item, raw_string) or (None, None)."""
    streamer, _, ts_str = clip_id.partition(":")
    raw_items = redis_client.lrange("clip:ready", 0, -1)
    for raw in raw_items:
        try:
            item = json.loads(raw)
            if item.get("streamer") == streamer and str(item.get("timestamp")) == ts_str:
                return item, raw
        except (json.JSONDecodeError, KeyError):
            continue
    return None, None


# --- Request models ---

class ApproveRequest(BaseModel):
    title: str
    hashtags: list[str]


# --- API routes ---

@app.get("/api/clips")
def get_clips():
    clips = _all_clips()
    clips.sort(key=lambda c: c.get("score", 0), reverse=True)
    return clips


@app.post("/api/clips/{clip_id}/approve")
def approve_clip(clip_id: str, req: ApproveRequest):
    item, raw = _find_raw(clip_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    redis_client.lrem("clip:ready", 1, raw)

    post_entry = {
        "streamer": item["streamer"],
        "timestamp": item["timestamp"],
        "file_path": item["file_path"],
        "thumbnail_path": item.get("thumbnail_path"),
        "title": req.title,
        "hashtags": req.hashtags,
        "score": item.get("score", 0),
        "approved_at": time.time(),
    }
    redis_client.lpush("clip:post:queue", json.dumps(post_entry))
    log.info("[dashboard] Approved clip %s → clip:post:queue", clip_id)
    return {"ok": True}


@app.post("/api/clips/{clip_id}/reject")
def reject_clip(clip_id: str):
    item, raw = _find_raw(clip_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    redis_client.lrem("clip:ready", 1, raw)
    redis_client.lpush("clip:rejected", raw)
    log.info("[dashboard] Rejected clip %s → clip:rejected", clip_id)
    return {"ok": True}


@app.post("/api/bulk-approve")
def bulk_approve():
    clips = _all_clips()
    approved = 0
    for clip in clips:
        if clip.get("score", 0) >= 8:
            clip_id = clip["id"]
            item, raw = _find_raw(clip_id)
            if item is None:
                continue
            redis_client.lrem("clip:ready", 1, raw)
            post_entry = {
                "streamer": item["streamer"],
                "timestamp": item["timestamp"],
                "file_path": item["file_path"],
                "thumbnail_path": item.get("thumbnail_path"),
                "title": item.get("suggested_title", f"{item['streamer']} moment"),
                "hashtags": item.get("suggested_hashtags", []),
                "score": item.get("score", 0),
                "approved_at": time.time(),
            }
            redis_client.lpush("clip:post:queue", json.dumps(post_entry))
            approved += 1

    log.info("[dashboard] Bulk approved %d clips (score >= 8)", approved)
    return {"approved": approved}


@app.get("/api/stats")
def get_stats():
    return {
        "pending": redis_client.llen("clip:ready"),
        "approved": redis_client.llen("clip:post:queue"),
        "rejected": redis_client.llen("clip:rejected"),
        "posted": redis_client.llen("clip:posted"),
    }


@app.get("/clips/{file_path:path}")
def serve_clip(file_path: str):
    full_path = Path(CLIPS_DIR) / file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(full_path))


# Serve React frontend — must come after API routes
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
