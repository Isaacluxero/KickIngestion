#!/usr/bin/env python3
"""
Whisper transcription using faster-whisper.
First call downloads the model — can take a few minutes.
"""

import logging
import os

log = logging.getLogger(__name__)

_model = None


def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        model_size = os.environ.get("WHISPER_MODEL_SIZE", "base")
        log.info("[transcriber] Downloading Whisper model '%s', this may take a few minutes...", model_size)
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        log.info("[transcriber] Whisper model loaded")
    return _model


def transcribe(file_path: str) -> tuple[str, list[dict], float]:
    """
    Transcribe a video/audio file.
    Returns (transcript_text, segment_list, duration_seconds).
    Raises on failure.
    """
    model = get_model()
    log.info("[transcriber] Transcribing %s", file_path)

    segments, info = model.transcribe(file_path)
    segment_list = []
    words = []
    for seg in segments:
        segment_list.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        words.append(seg.text.strip())

    transcript = " ".join(words)
    duration = info.duration if info.duration else 0.0

    log.info("[transcriber] Transcription done: %.1f seconds, %d words", duration, len(transcript.split()))
    return transcript, segment_list, duration
