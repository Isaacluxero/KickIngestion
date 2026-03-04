#!/usr/bin/env python3
"""
Live poller — CronJob script.

Checks which streamers from the roster are currently live on Kick,
updates the Redis set `live:streamers`, and caches slug → chatroom_id mappings.

NOTE: The slug resolution endpoint (kick.com/api/v2/channels/{slug}) is unofficial
and may break without notice. Replace with an official Kick API endpoint if one ships.
"""

import asyncio
import json
import logging
import os
import time

import aiohttp
import redis.asyncio as aioredis
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [poller] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

ROSTER_PATH = os.environ.get("ROSTER_PATH", "/config/roster.yaml")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
KICK_CLIENT_ID = os.environ["KICK_CLIENT_ID"]
KICK_CLIENT_SECRET = os.environ["KICK_CLIENT_SECRET"]

TOKEN_ENDPOINT = "https://id.kick.com/oauth/token"
CHANNELS_API = "https://api.kick.com/public/v1/channels"
SLUG_API = "https://kick.com/api/v2/channels/{slug}"

# Rotate User-Agent strings on 403/security errors from the unofficial slug endpoint
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def load_roster() -> dict:
    with open(ROSTER_PATH) as f:
        return yaml.safe_load(f)


async def get_token(session: aiohttp.ClientSession) -> dict:
    """Fetch OAuth token using client_credentials grant."""
    data = {
        "grant_type": "client_credentials",
        "client_id": KICK_CLIENT_ID,
        "client_secret": KICK_CLIENT_SECRET,
    }
    async with session.post(TOKEN_ENDPOINT, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        token_data = await resp.json()
        log.info("Token fetched, expires_in=%s", token_data.get("expires_in"))
        return token_data


async def resolve_slug(session: aiohttp.ClientSession, slug: str) -> dict | None:
    """
    Resolve slug → broadcaster_user_id + chatroom_id via unofficial endpoint.

    NOTE: kick.com/api/v2 is unofficial — replace with the official Kick API
    slug resolution endpoint if one becomes available.
    """
    url = SLUG_API.format(slug=slug)
    for ua in USER_AGENTS:
        try:
            async with session.get(
                url,
                headers={"User-Agent": ua},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {
                        "broadcaster_user_id": str(data["id"]),
                        "chatroom_id": str(data["chatroom"]["id"]),
                    }
                    log.info(
                        "Resolved %s → broadcaster_id=%s chatroom_id=%s",
                        slug,
                        result["broadcaster_user_id"],
                        result["chatroom_id"],
                    )
                    return result
                else:
                    text = await resp.text()
                    log.warning(
                        "Slug resolve %s status=%s with UA=%.40s: %.100s",
                        slug, resp.status, ua, text,
                    )
        except Exception as e:
            log.warning("Slug resolve %s failed with UA=%.40s: %s", slug, ua, e)

    log.error("All User-Agent attempts exhausted for slug %s — skipping", slug)
    return None


async def check_live(
    session: aiohttp.ClientSession, token: str, broadcaster_user_id: str
) -> dict | None:
    """
    Check if a streamer is live via the official Kick API.
    Returns stream metadata dict or None if offline.
    """
    params = {"broadcaster_user_id": broadcaster_user_id}
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(
        CHANNELS_API,
        params=params,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        if resp.status != 200:
            log.warning("Live check for broadcaster %s returned status %s", broadcaster_user_id, resp.status)
            return None
        data = await resp.json()
        channels = data.get("data", [])
        if not channels:
            return None
        ch = channels[0]
        if ch.get("is_live"):
            stream_id = str((ch.get("stream") or {}).get("id", ""))
            return {"stream_id": stream_id}
        return None


async def main():
    roster = load_roster()
    slugs = roster.get("streamers", [])
    log.info("Polling live status for %d streamers: %s", len(slugs), slugs)

    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    async with aiohttp.ClientSession() as session:
        token_data = await get_token(session)
        token = token_data["access_token"]
        token_expiry = time.time() + token_data.get("expires_in", 3600) - 60

        # Resolve all slugs — use Redis cache to avoid hitting the unofficial API every run
        slug_info: dict[str, dict] = {}
        for slug in slugs:
            cached = await redis.hgetall(f"streamer:info:{slug}")
            if cached and "broadcaster_user_id" in cached:
                slug_info[slug] = cached
                log.info("Using cached info for %s (broadcaster_id=%s)", slug, cached["broadcaster_user_id"])
            else:
                info = await resolve_slug(session, slug)
                if info:
                    slug_info[slug] = info
                    await redis.hset(f"streamer:info:{slug}", mapping=info)

        # Check live status for each resolved streamer
        live_slugs = []
        for slug, info in slug_info.items():
            # Refresh token proactively if near expiry
            if time.time() >= token_expiry:
                log.info("Token near expiry — refreshing before continuing")
                token_data = await get_token(session)
                token = token_data["access_token"]
                token_expiry = time.time() + token_data.get("expires_in", 3600) - 60

            stream_info = await check_live(session, token, info["broadcaster_user_id"])
            if stream_info:
                live_slugs.append(slug)
                await redis.set(f"streamer:stream_id:{slug}", stream_info["stream_id"])
                log.info("%s is LIVE (stream_id=%s)", slug, stream_info["stream_id"])
            else:
                log.info("%s is offline", slug)
                await redis.delete(f"streamer:stream_id:{slug}")

        # Atomically replace live:streamers set
        pipe = redis.pipeline()
        pipe.delete("live:streamers")
        if live_slugs:
            pipe.sadd("live:streamers", *live_slugs)
        await pipe.execute()

        log.info("live:streamers updated — live: %s", live_slugs)

    await redis.aclose()
    log.info("Poller complete")


if __name__ == "__main__":
    asyncio.run(main())
