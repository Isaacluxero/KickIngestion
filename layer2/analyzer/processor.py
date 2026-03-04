#!/usr/bin/env python3
"""
FFmpeg post-processing: crop to 9:16, burn word-by-word captions, generate thumbnail.
"""

import logging
import os
import subprocess

import ffmpeg

log = logging.getLogger(__name__)


def _get_video_dimensions(file_path: str) -> tuple[int, int]:
    """Return (width, height) of the video."""
    probe = ffmpeg.probe(file_path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    return int(video["width"]), int(video["height"])


def _build_caption_filter(segments: list[dict]) -> str:
    """
    Build an ffmpeg drawtext filter chain for word-by-word captions.
    Shows each transcript segment in the bottom third of the frame.
    """
    if not segments:
        return ""

    filters = []
    for seg in segments:
        text = seg["text"].replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")
        if not text.strip():
            continue
        start = seg["start"]
        end = seg["end"]
        filter_str = (
            f"drawtext=text='{text}'"
            f":fontcolor=white:fontsize=48:bordercolor=black:borderw=3"
            f":x=(w-text_w)/2:y=h*0.75"
            f":enable='between(t,{start},{end})'"
        )
        filters.append(filter_str)

    return ",".join(filters) if filters else ""


def process_clip(
    file_path: str,
    streamer: str,
    timestamp: float,
    segments: list[dict],
) -> tuple[str, str]:
    """
    Crop to 9:16 if needed, burn captions, generate thumbnail.
    Returns (final_path, thumbnail_path).
    Raises on unrecoverable FFmpeg failure.
    """
    output_dir = os.path.join(os.environ.get("CLIPS_DIR", "/clips"), streamer, "processed")
    os.makedirs(output_dir, exist_ok=True)

    final_path = os.path.join(output_dir, f"{int(timestamp)}_final.mp4")
    thumb_path = os.path.join(output_dir, f"{int(timestamp)}_thumb.jpg")

    width, height = _get_video_dimensions(file_path)
    target_ratio = 9 / 16

    # Determine crop filter
    current_ratio = width / height
    if abs(current_ratio - target_ratio) < 0.05:
        # Already close to 9:16
        crop_filter = None
    elif current_ratio > target_ratio:
        # Wider than 9:16 — crop sides
        new_width = int(height * 9 / 16)
        x_offset = (width - new_width) // 2
        crop_filter = f"crop={new_width}:{height}:{x_offset}:0"
    else:
        # Taller than 9:16 — crop top/bottom
        new_height = int(width * 16 / 9)
        y_offset = (height - new_height) // 2
        crop_filter = f"crop={width}:{new_height}:0:{y_offset}"

    # Build video filter chain
    caption_filter = _build_caption_filter(segments)
    vf_parts = []
    if crop_filter:
        vf_parts.append(crop_filter)
    if caption_filter:
        vf_parts.append(caption_filter)

    vf = ",".join(vf_parts) if vf_parts else "null"

    # Run FFmpeg for main clip
    cmd = ["ffmpeg", "-y", "-i", file_path, "-vf", vf, "-c:a", "copy", final_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (rc={result.returncode}): {result.stderr[:500]}")

    # Generate thumbnail from middle 20% of clip (rough midpoint)
    probe = ffmpeg.probe(final_path)
    duration = float(probe["format"]["duration"])
    thumb_ts = duration * 0.5
    thumb_cmd = [
        "ffmpeg", "-y", "-ss", str(thumb_ts), "-i", final_path,
        "-frames:v", "1", "-q:v", "2", thumb_path,
    ]
    thumb_result = subprocess.run(thumb_cmd, capture_output=True, text=True)
    if thumb_result.returncode != 0:
        log.warning("[processor] Thumbnail generation failed: %s", thumb_result.stderr[:300])
        thumb_path = None  # Non-fatal

    return final_path, thumb_path
