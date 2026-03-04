# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**KickIngestion / ClipAgency** — A 5-layer automated pipeline for detecting, analyzing, approving, and posting viral Kick.tv streaming clips to TikTok.

## Build & Deploy

```bash
# Build all layers
./build.sh

# Build a single layer
./build.sh layer1      # monitor + downloader
./build.sh layer2      # analyzer
./build.sh layer3      # dashboard
./build.sh layer4      # poster
./build.sh layer5      # tracker
./build.sh monitor     # kick-monitor only
./build.sh downloader  # kick-downloader only

# Deploy manifests per layer
kubectl apply -f k8s/layer1/   # already applied; skip unless changed
kubectl apply -f k8s/layer2/
kubectl apply -f k8s/layer3/
kubectl apply -f k8s/layer4/
kubectl apply -f k8s/layer5/
```

All images use `imagePullPolicy: Never` — built with `nerdctl` directly into k3s's containerd namespace (`k8s.io`). No external registry, no save/import step.

## Monorepo Structure

```text
layer1/            Chat monitor + VOD downloader (deployed, do not break)
  monitor/         kick-monitor image — chat spike detection via Pusher WS
  downloader/      kick-downloader image — yt-dlp VOD clipping
  config/          roster.yaml + emotes.yaml (source for k8s ConfigMap)

layer2/            AI analysis (kick-analyzer image)
  analyzer/        main.py + transcriber.py + scorer.py + processor.py

layer3/            Approval dashboard (kick-dashboard image, multi-stage build)
  backend/         FastAPI (Python, sync redis)
  frontend/        React + TypeScript + Tailwind (Vite, built into backend/static)

layer4/            Auto posting (kick-poster image)
  poster/          main.py + scheduler.py + tiktok.py

layer5/            Analytics tracking CronJob (kick-tracker image)
  tracker/         main.py + fetcher.py

k8s/
  layer1/          Deployed k8s manifests for Layer 1
  layer2/          analyzer-secret.yaml, analyzer-configmap.yaml, analyzer-deployment.yaml
  layer3/          dashboard-deployment.yaml, dashboard-service.yaml (NodePort 30080)
  layer4/          poster-secret.yaml, poster-configmap.yaml, poster-deployment.yaml
  layer5/          tracker-secret.yaml, tracker-cronjob.yaml (runs daily at 09:00)
```

## Redis Queue Flow

```text
clip:queue          L1 internal  — spike events for yt-dlp downloader
clip:queue:transcribe  L1 → L2  — clip metadata after successful download
clip:processing     L2 internal  — BRPOPLPUSH working list (crash recovery)
clip:ready          L2 → L3      — scored clips waiting for approval
clip:post:queue     L3 → L4      — approved clips ready to post
clip:posted         L4 → L5      — successfully posted clips with TikTok URL
clip:post:failed    L4 internal  — clips that exhausted posting retries
clip:rejected       L3 internal  — rejected clips (audit log)
clip:failed         Any layer    — catch-all error list
```

## Layer Architecture

### Layer 1 — Monitor + Downloader

- **Chat monitor** (`layer1/monitor/main.py`): Pusher WS per streamer, two-signal spike detection (msgs/sec ≥ 80 AND hype ratio ≥ 25%), 120s cooldown, pushes to `clip:queue`
- **Live poller** (`layer1/monitor/poller.py`): CronJob every 5 min, updates `live:streamers` in Redis
- **Downloader** (`layer1/downloader/main.py`): Consumes `clip:queue`, runs yt-dlp with `--download-sections`, pushes to `clip:queue:transcribe` on success

### Layer 2 — AI Analysis

- **transcriber.py**: faster-whisper (`base` model, CPU, int8). Model downloads on first run — may take minutes.
- **scorer.py**: Claude API (`claude-sonnet-4-20250514`). Returns score 1–10, reason, title, hashtags. Retries once on parse/API failure.
- **processor.py**: FFmpeg — detects aspect ratio, crops to 9:16, burns word-by-word captions from Whisper segments, extracts thumbnail at 50% duration.
- **main.py**: Sequential sync loop. `BRPOPLPUSH clip:queue:transcribe → clip:processing` for crash safety. FFmpeg only runs if `score >= MIN_SCORE` (default 6). If FFmpeg fails, raw file is used. All failures log to `clip:failed`.

### Layer 3 — Dashboard

- **Backend** (`layer3/backend/main.py`): FastAPI + sync redis. `GET /api/clips` scans `clip:ready` without popping. Approve/reject uses LREM + push to appropriate queue. Streams clip files via `FileResponse`.
- **Frontend**: React + TypeScript + Tailwind. Dark (`bg-gray-950`). Score badges color-coded (green ≥8, yellow 6–7, red <6). Editable title and hashtag pills per clip. Bulk-approve at score ≥ 8.
- **Access**: `http://<homelab-ip>:30080`

### Layer 4 — Auto Poster

- **scheduler.py**: Generates `DAILY_SLOTS` (default 25) time slots between `WAKING_START_HOUR` (8) and `WAKING_END_HOUR` (26 = 2am) with ±20% jitter. Cached in Redis keyed by date. Enforces 10-minute minimum gap per account.
- **tiktok.py**: Wraps `tiktok-uploader` library.
- **main.py**: Polls `should_post_now()` every 60s. On a slot match, pops from `clip:post:queue`, rotates accounts via `post:account:idx` in Redis, retries up to 3×. Fires n8n webhook after success (non-fatal).

### Layer 5 — Tracker

- CronJob at 09:00 daily. Reads all `clip:posted` entries, fetches TikTok Analytics API stats, stores per-clip tracking in Redis at `clip:tracking:{streamer}:{timestamp}` (30-day TTL). Prints daily summary to logs.

## Shared Conventions

- **namespace**: `default` on all k8s resources
- **REDIS_URL**: `redis://redis:6379` as plain env var (not from secret) on all containers
- **CLIPS_DIR**: `/clips` as plain env var; backed by PVC `clips-pvc` (100Gi, local-path)
- **Secrets**: always via `secretKeyRef`; config via `configMapKeyRef`
- **Logging**: Python `logging` module, timestamps, `[service]` prefix on every log line
- **Error handling**: all external calls (Redis, Claude API, subprocess) wrapped in try/except — log and continue, never crash the service

## Secrets to Fill In

| File                               | Key                     | What to put                              |
| ---------------------------------- | ----------------------- | ---------------------------------------- |
| `k8s/layer2/analyzer-secret.yaml`  | `ANTHROPIC_API_KEY`     | Anthropic API key                        |
| `k8s/layer4/poster-secret.yaml`    | `TIKTOK_SESSIONIDS`     | Comma-separated TikTok sessionid cookies |
| `k8s/layer4/poster-secret.yaml`    | `BLOTATO_API_KEY`       | Blotato API key                          |
| `k8s/layer4/poster-configmap.yaml` | `N8N_WEBHOOK_URL`       | n8n webhook URL                          |
| `k8s/layer5/tracker-secret.yaml`   | `TIKTOK_ACCESS_TOKEN`   | TikTok Analytics OAuth token             |
| `k8s/layer1/secret.yaml`           | `KICK_CLIENT_ID/SECRET` | Kick OAuth credentials                   |

## Operations

```bash
# Layer 1
kubectl logs -f deployment/chat-monitor
kubectl logs -f deployment/clip-downloader
kubectl exec -it deployment/redis -- redis-cli SMEMBERS live:streamers

# Layer 2
kubectl logs -f deployment/clip-analyzer
kubectl exec -it deployment/redis -- redis-cli LLEN clip:queue:transcribe
kubectl exec -it deployment/redis -- redis-cli LLEN clip:ready

# Layer 3
# Open http://<homelab-ip>:30080

# Layer 4
kubectl logs -f deployment/clip-poster
kubectl exec -it deployment/redis -- redis-cli LLEN clip:post:queue

# Layer 5 — trigger manually
kubectl create job --from=cronjob/clip-tracker tracker-manual-$(date +%s)

# Queue health
kubectl exec -it deployment/redis -- redis-cli LLEN clip:failed
kubectl exec -it deployment/redis -- redis-cli LRANGE clip:failed 0 2

# Smoke test Layer 2 (push fake item)
kubectl exec -it deployment/redis -- redis-cli LPUSH clip:queue:transcribe \
  '{"streamer":"test","timestamp":1234567890,"msgs_per_sec":100,"stream_id":"abc","clip_window":150,"hype_ratio":0.4,"priority":"high","clip_count":2,"file_path":"/clips/test/1234567890.mp4"}'
```

## Tunable Parameters

| Parameter | File | Default |
|-----------|------|---------|
| `min_chat_spike` | `layer1/config/roster.yaml` | 80 msgs/sec |
| `clip_window` | `layer1/config/roster.yaml` | 150 s |
| `WHISPER_MODEL_SIZE` | `k8s/layer2/analyzer-configmap.yaml` | `base` |
| `MIN_SCORE` | `k8s/layer2/analyzer-configmap.yaml` | 6 |
| `DAILY_SLOTS` | `k8s/layer4/poster-configmap.yaml` | 25 |
| `WAKING_START_HOUR` | `k8s/layer4/poster-configmap.yaml` | 8 |
| `WAKING_END_HOUR` | `k8s/layer4/poster-configmap.yaml` | 26 (= 2am) |
| `HYPE_RATIO_THRESHOLD` | `layer1/monitor/main.py:56` | 0.25 (hardcoded) |
| `COOLDOWN_SECONDS` | `layer1/monitor/main.py:57` | 120 s (hardcoded) |
| `LOW_PRIORITY_DELAY` | `layer1/downloader/main.py:33` | 300 s (hardcoded) |
