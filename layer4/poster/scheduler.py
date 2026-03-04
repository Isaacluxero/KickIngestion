#!/usr/bin/env python3
"""
Post scheduling — generates daily time slots with jitter and checks
whether the current time matches a pending slot.
"""

import json
import logging
import os
import random
from datetime import datetime

log = logging.getLogger(__name__)

DAILY_SLOTS = int(os.environ.get("DAILY_SLOTS", "25"))
WAKING_START = int(os.environ.get("WAKING_START_HOUR", "8"))
WAKING_END = int(os.environ.get("WAKING_END_HOUR", "26"))
MIN_GAP_MINUTES = 10  # minimum minutes between posts on the same account


def _today_key() -> str:
    return f"post:slots:{datetime.now().strftime('%Y-%m-%d')}"


def ensure_slots(redis_client) -> list[float]:
    """
    Return today's scheduled post slots (minutes since midnight).
    Generates and caches in Redis if not already created.
    """
    key = _today_key()
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)

    total_minutes = (WAKING_END - WAKING_START) * 60
    slot_interval = total_minutes / DAILY_SLOTS

    slots = []
    for i in range(DAILY_SLOTS):
        base = WAKING_START * 60 + i * slot_interval
        jitter = random.uniform(-0.2, 0.2) * slot_interval
        slots.append(base + jitter)

    slots = sorted(slots)
    redis_client.set(key, json.dumps(slots), ex=60 * 60 * 48)
    log.info("[scheduler] Generated %d slots for today (start=%dh end=%dh)", DAILY_SLOTS, WAKING_START, WAKING_END)
    return slots


def should_post_now(redis_client, tolerance_minutes: float = 2.0) -> bool:
    """
    Return True if the current time is within `tolerance_minutes` of any
    scheduled slot that hasn't been consumed yet.
    Marks matched slots as consumed in Redis.
    """
    slots = ensure_slots(redis_client)
    consumed_key = f"post:slots:consumed:{datetime.now().strftime('%Y-%m-%d')}"
    consumed = set(json.loads(redis_client.get(consumed_key) or "[]"))

    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute + now.second / 60.0

    for slot in slots:
        if slot in consumed:
            continue
        if abs(now_minutes - slot) <= tolerance_minutes:
            consumed.add(slot)
            redis_client.set(consumed_key, json.dumps(list(consumed)), ex=60 * 60 * 48)
            return True

    return False


def min_gap_elapsed(redis_client, account: str) -> bool:
    """Check that at least MIN_GAP_MINUTES has passed since this account last posted."""
    key = f"post:last:{account}"
    last = redis_client.get(key)
    if last is None:
        return True
    import time
    elapsed_minutes = (time.time() - float(last)) / 60.0
    return elapsed_minutes >= MIN_GAP_MINUTES


def record_post(redis_client, account: str):
    """Record the current timestamp as the last post time for this account."""
    import time
    redis_client.set(f"post:last:{account}", str(time.time()), ex=60 * 60 * 24)
