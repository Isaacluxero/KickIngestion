#!/usr/bin/env python3
"""
Virality scoring via Claude API.
"""

import json
import logging
import os
import time

import anthropic

log = logging.getLogger(__name__)

# Simple streamer→category mapping; defaults to "Just Chatting"
STREAMER_CATEGORIES = {
    "xqc": "Just Chatting",
    "adin": "Just Chatting",
    "trainwreckstv": "Slots",
    "kaicenat": "Just Chatting",
    "jynxzi": "Rainbow Six Siege",
    "fanum": "Just Chatting",
    "sketch": "Just Chatting",
}


def get_category(streamer: str) -> str:
    return STREAMER_CATEGORIES.get(streamer.lower(), "Just Chatting")


def score_clip(
    streamer: str,
    transcript: str,
    msgs_per_sec: float,
    hype_ratio: float,
    clip_count: int,
    duration: float,
) -> dict:
    """
    Score a clip for TikTok virality using Claude.
    Returns dict with: score, reason, suggested_title, suggested_hashtags.
    Retries once on API/parse failure. Raises on second failure.
    """
    category = get_category(streamer)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an expert at identifying viral streaming clips for TikTok.

Streamer: {streamer}
Category: {category}
Chat spike: {msgs_per_sec:.1f} msgs/sec
Hype emote ratio: {hype_ratio:.2f} ({hype_ratio * 100:.0f}% of messages were hype emotes)
Viewer clip count: {clip_count} viewers independently clipped this moment
Clip duration: {duration:.0f} seconds

Transcript:
{transcript}

Score this clip 1-10 for TikTok virality. Consider:
- Humor, surprise, or shock value
- Reaction quality (streamer reaction visible/audible)
- Rewatch value and out-of-context comprehensibility
- Streaming culture (KEKW=funny, PogChamp=impressive, monkaS=tense/scary)
- Penalty for: raids, giveaways, loading screens, technical issues

Return ONLY valid JSON, no other text:
{{"score": 7, "reason": "one sentence explanation", "suggested_title": "catchy title under 8 words", "suggested_hashtags": ["tag1", "tag2", "tag3"]}}"""

    for attempt in range(1, 3):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(message.content[0].text)
            # Validate required fields
            score = int(result["score"])
            return {
                "score": score,
                "reason": str(result.get("reason", "")),
                "suggested_title": str(result.get("suggested_title", f"{streamer} moment")),
                "suggested_hashtags": list(result.get("suggested_hashtags", [streamer, "kick", "streaming"])),
                "category": category,
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.warning("[scorer] Parse error on attempt %d: %s", attempt, e)
            if attempt < 2:
                time.sleep(2)
        except Exception as e:
            log.warning("[scorer] API error on attempt %d: %s", attempt, e)
            if attempt < 2:
                time.sleep(5)

    raise RuntimeError(f"Claude scoring failed after 2 attempts for {streamer}")
