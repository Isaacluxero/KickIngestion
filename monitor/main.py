#!/usr/bin/env python3
"""
Chat monitor — always-on service.

Watches Redis `live:streamers`, manages one Pusher websocket per live streamer,
and detects chat spikes using two signals:
  1. msgs/sec >= min_chat_spike (raw message volume)
  2. hype_ratio >= 0.25 (fraction of messages containing a hype emote)

Both signals must fire simultaneously to trigger a spike event.

On spike: checks recent viewer clip activity via the official Kick clips API,
sets priority (high/low/normal), and pushes a JSON event to Redis `clip:queue`.

NOTE: The Pusher websocket approach (wss://ws-us2.pusher.com) is unofficial and
may break when Kick changes their infrastructure. This should be replaced with
official Kick webhooks once they ship websocket/webhook support for chat events.
"""

import asyncio
import json
import logging
import os
import signal
import time
from collections import deque

import aiohttp
import redis.asyncio as aioredis
import websockets
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [monitor] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

ROSTER_PATH = os.environ.get("ROSTER_PATH", "/config/roster.yaml")
EMOTES_PATH = os.environ.get("EMOTES_PATH", "/config/emotes.yaml")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
KICK_CLIENT_ID = os.environ.get("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.environ.get("KICK_CLIENT_SECRET", "")

TOKEN_ENDPOINT = "https://id.kick.com/oauth/token"
CLIPS_API = "https://api.kick.com/public/v1/clips"

# NOTE: Pusher URL is unofficial — may break without notice
PUSHER_URL = (
    "wss://ws-us2.pusher.com/app/eb1d5f283081a78b932c"
    "?protocol=7&client=js&version=7.6.0"
)

WINDOW_SECONDS = 10
HYPE_RATIO_THRESHOLD = 0.25
COOLDOWN_SECONDS = 120
LIVE_SYNC_INTERVAL = 30  # seconds between Redis live:streamers polls

DEFAULT_HYPE_EMOTES = [
    "KEKW", "PogChamp", "Pog", "OMEGALUL", "OMFG", "PauseChamp",
    "monkaS", "monkaW", "EZ", "Clap", "GIGACHAD", "pepeD",
    "Sadge", "peepoHappy", "HYPERS", "PogO", "Copium", "widepeepoHappy",
]


def load_config() -> dict:
    with open(ROSTER_PATH) as f:
        return yaml.safe_load(f)


def load_emotes() -> list[str]:
    """Load hype emote list from config file, falling back to defaults."""
    try:
        with open(EMOTES_PATH) as f:
            data = yaml.safe_load(f)
            emotes = data.get("emotes", DEFAULT_HYPE_EMOTES)
            log.info("Loaded %d hype emotes from %s", len(emotes), EMOTES_PATH)
            return emotes
    except FileNotFoundError:
        log.warning("Emotes config not found at %s — using built-in defaults", EMOTES_PATH)
        return DEFAULT_HYPE_EMOTES


class ChatMonitor:
    def __init__(self, config: dict, redis_client, http_session: aiohttp.ClientSession):
        self.config = config
        self.redis = redis_client
        self.session = http_session
        self.emotes = load_emotes()
        self.min_spike: int = config.get("min_chat_spike", 80)
        self.clip_window: int = config.get("clip_window", 150)
        self._tasks: dict[str, asyncio.Task] = {}
        self._cooldowns: dict[str, float] = {}
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._shutdown = False

    async def _ensure_token(self):
        """Refresh OAuth token if expired or within 60 seconds of expiry."""
        if time.time() < self._token_expiry:
            return
        if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
            log.warning("KICK_CLIENT_ID/SECRET not set — clips API priority check unavailable")
            return
        data = {
            "grant_type": "client_credentials",
            "client_id": KICK_CLIENT_ID,
            "client_secret": KICK_CLIENT_SECRET,
        }
        async with self.session.post(
            TOKEN_ENDPOINT, data=data, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            resp.raise_for_status()
            token_data = await resp.json()
            self._token = token_data["access_token"]
            self._token_expiry = time.time() + token_data.get("expires_in", 3600) - 60
            log.info("OAuth token refreshed, expires_in=%s", token_data.get("expires_in"))

    async def _check_clip_count(self, broadcaster_user_id: str, spike_ts: float) -> tuple[str, int]:
        """
        Query how many viewers independently clipped within 60s of the spike.

        Returns (priority, clip_count):
          - 2+ clips  → "high"
          - 0-1 clips → "low"
          - API error → "normal" (never crashes the spike flow)

        NOTE: This clips endpoint may not yet be publicly available.
        Defaults to "normal" on 404 or any error rather than failing.
        """
        try:
            await self._ensure_token()
            if not self._token:
                return "normal", 0

            params = {
                "broadcaster_user_id": broadcaster_user_id,
                "start_time": int(spike_ts - 60),
            }
            headers = {"Authorization": f"Bearer {self._token}"}
            async with self.session.get(
                CLIPS_API,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 404:
                    log.warning("Clips endpoint returned 404 — not yet available; defaulting to normal priority")
                    return "normal", 0
                if resp.status != 200:
                    log.warning("Clips endpoint returned %s — defaulting to normal priority", resp.status)
                    return "normal", 0

                data = await resp.json()
                clips = data.get("data", [])
                count = len(clips)
                priority = "high" if count >= 2 else "low"
                log.info("Clip count in last 60s: %d → priority=%s", count, priority)
                return priority, count

        except Exception as e:
            log.warning("Clip count check failed: %s — defaulting to normal priority", e)
            return "normal", 0

    async def monitor_streamer(self, slug: str):
        """
        Persistent Pusher websocket monitor for a single streamer.
        Reconnects with exponential backoff on any disconnect or error.
        """
        backoff = 1.0

        while not self._shutdown:
            # Fetch chatroom_id from Redis (written by poller.py)
            info = await self.redis.hgetall(f"streamer:info:{slug}")
            if not info or "chatroom_id" not in info:
                log.warning("[%s] No chatroom info in Redis yet — retrying in %ds", slug, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            chatroom_id = info["chatroom_id"]
            broadcaster_user_id = info.get("broadcaster_user_id", "")
            stream_id = await self.redis.get(f"streamer:stream_id:{slug}") or ""

            # Per-streamer rolling windows
            msg_times: deque = deque()
            hype_times: deque = deque()

            log.info("[%s] Connecting to Pusher (chatroom_id=%s)", slug, chatroom_id)
            try:
                async with websockets.connect(PUSHER_URL) as ws:
                    backoff = 1.0  # reset on successful connect

                    # Wait for Pusher's connection_established handshake
                    raw = await ws.recv()
                    event = json.loads(raw)
                    if event.get("event") != "pusher:connection_established":
                        log.warning("[%s] Unexpected first Pusher event: %s", slug, event.get("event"))

                    # Subscribe to the chatroom channel
                    channel = f"chatrooms.{chatroom_id}.v2"
                    await ws.send(json.dumps({
                        "event": "pusher:subscribe",
                        "data": {"auth": "", "channel": channel},
                    }))
                    log.info("[%s] Subscribed to %s", slug, channel)

                    async for raw_msg in ws:
                        if self._shutdown:
                            break

                        try:
                            msg = json.loads(raw_msg)
                        except json.JSONDecodeError:
                            continue

                        ev = msg.get("event", "")

                        # Respond to Pusher keepalive pings
                        if ev == "pusher:ping":
                            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                            continue

                        if ev != "App\\Events\\ChatMessageEvent":
                            continue

                        now = time.time()
                        msg_times.append(now)
                        cutoff = now - WINDOW_SECONDS

                        # Check message content for hype emotes
                        try:
                            data = json.loads(msg.get("data", "{}"))
                            content = data.get("content", "")
                        except (json.JSONDecodeError, TypeError):
                            content = ""

                        if any(emote in content for emote in self.emotes):
                            hype_times.append(now)

                        # Prune both windows to the last WINDOW_SECONDS
                        while msg_times and msg_times[0] < cutoff:
                            msg_times.popleft()
                        while hype_times and hype_times[0] < cutoff:
                            hype_times.popleft()

                        total = len(msg_times)
                        hype_count = len(hype_times)
                        msgs_per_sec = total / WINDOW_SECONDS
                        hype_ratio = hype_count / total if total > 0 else 0.0

                        # Spike: both signals must fire, and streamer must not be in cooldown
                        cooldown_until = self._cooldowns.get(slug, 0)
                        if (
                            msgs_per_sec >= self.min_spike
                            and hype_ratio >= HYPE_RATIO_THRESHOLD
                            and now > cooldown_until
                        ):
                            log.info(
                                "[%s] SPIKE: %.1f msgs/s, hype_ratio=%.2f — checking clip count",
                                slug, msgs_per_sec, hype_ratio,
                            )
                            self._cooldowns[slug] = now + COOLDOWN_SECONDS

                            priority, clip_count = await self._check_clip_count(broadcaster_user_id, now)

                            spike_event = {
                                "streamer": slug,
                                "timestamp": now,
                                "msgs_per_sec": round(msgs_per_sec, 2),
                                "stream_id": stream_id,
                                "clip_window": self.clip_window,
                                "hype_ratio": round(hype_ratio, 4),
                                "priority": priority,
                                "clip_count": clip_count,
                            }
                            await self.redis.rpush("clip:queue", json.dumps(spike_event))
                            log.info("[%s] Spike event pushed to clip:queue: %s", slug, spike_event)

            except asyncio.CancelledError:
                log.info("[%s] Monitor task cancelled", slug)
                return
            except Exception as e:
                log.warning(
                    "[%s] Websocket error: %s — reconnecting in %ds",
                    slug, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def sync_monitors(self):
        """
        Main loop: reconcile running websocket tasks against Redis live:streamers.
        Runs every LIVE_SYNC_INTERVAL seconds.
        """
        while not self._shutdown:
            try:
                live = await self.redis.smembers("live:streamers")
                live_set = set(live)
                running_set = set(self._tasks.keys())

                # Start monitors for newly live streamers
                for slug in live_set - running_set:
                    log.info("Starting monitor for newly live streamer: %s", slug)
                    task = asyncio.create_task(
                        self.monitor_streamer(slug), name=f"monitor-{slug}"
                    )
                    self._tasks[slug] = task

                # Cancel monitors for streamers that went offline
                for slug in running_set - live_set:
                    log.info("Streamer %s went offline — cancelling monitor", slug)
                    self._tasks[slug].cancel()
                    del self._tasks[slug]

            except Exception as e:
                log.error("Error syncing monitors: %s", e)

            await asyncio.sleep(LIVE_SYNC_INTERVAL)

    def shutdown(self):
        log.info("Shutdown signal received — stopping all monitors")
        self._shutdown = True
        for slug, task in self._tasks.items():
            log.info("Cancelling monitor task for %s", slug)
            task.cancel()


async def main():
    config = load_config()
    log.info(
        "Chat monitor starting — min_spike=%s, clip_window=%s",
        config.get("min_chat_spike"), config.get("clip_window"),
    )

    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    async with aiohttp.ClientSession() as session:
        monitor = ChatMonitor(config, redis, session)

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, monitor.shutdown)
        loop.add_signal_handler(signal.SIGINT, monitor.shutdown)

        await monitor.sync_monitors()

    await redis.aclose()
    log.info("Chat monitor stopped")


if __name__ == "__main__":
    asyncio.run(main())
