# KickIngestion — Chat Monitor & Clipping Pipeline

Monitors Kick.tv chat in real-time, detects viral moments via two-signal spike detection, and automatically clips VOD segments with yt-dlp. Runs on k3s.

---

## Architecture

```text
┌─────────────────┐   every 5 min    ┌─────────────────────┐
│  live-poller    │ ──────────────→  │  Redis              │
│  (CronJob)      │  live:streamers  │                     │
│                 │  streamer:info:* │  live:streamers     │
│  Kick OAuth API │                  │  streamer:info:{s}  │
│  Live status    │                  │  streamer:stream_id │
└─────────────────┘                  │  clip:queue (list)  │
                                     │  clip:failed (list) │
┌─────────────────┐   reads Redis    │                     │
│  chat-monitor   │ ←─────────────── │                     │
│  (Deployment)   │   pushes spikes  │                     │
│                 │ ──────────────→  │                     │
│  Pusher WS per  │                  └─────────────────────┘
│  live streamer  │                           │
└─────────────────┘                           │ BLPOP
                                              ↓
                                   ┌─────────────────────┐
                                   │  clip-downloader    │
                                   │  (Deployment)       │
                                   │                     │
                                   │  yt-dlp → /clips    │
                                   └─────────────────────┘
```

### Spike Detection (two signals, both required)

1. **Volume**: `msgs/sec >= min_chat_spike` (default 80)
2. **Hype ratio**: `>= 25%` of messages in the last 10s contain a hype emote

**Priority** (from Kick clips API — how many viewers clipped in the last 60s):

- `high` → 2+ viewer clips → download immediately
- `low` → 0–1 viewer clips → wait 5 minutes then download
- `normal` → clips API unavailable → download immediately

---

## Prerequisites

- k3s cluster with `local-path` storage class (default on k3s)
- A container registry accessible from the cluster
- Kick developer credentials ([kick.com/settings/developer](https://kick.com/settings/developer))

---

## Quick Start

### 1. Fill in credentials

Edit `k8s/secret.yaml` and replace the placeholder values:

```yaml
stringData:
  KICK_CLIENT_ID: "your-actual-client-id"
  KICK_CLIENT_SECRET: "your-actual-client-secret"
```

### 2. Build and import images into k3s

No external registry needed. `build.sh` builds both images with Docker and imports them directly into k3s's containerd store using `k3s ctr images import`:

```bash
chmod +x build.sh
./build.sh
```

To rebuild a single image:

```bash
./build.sh monitor      # kick-monitor:latest only
./build.sh downloader   # kick-downloader:latest only
```

Verify the images are visible to k3s:

```bash
sudo k3s ctr images ls | grep kick
```

All manifests use `imagePullPolicy: Never`, so k3s will only use the locally imported images and never attempt to pull from a registry.

### 3. Apply manifests (order matters)

```bash
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/redis-service.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/chat-monitor-deployment.yaml
kubectl apply -f k8s/live-poller-cronjob.yaml
kubectl apply -f k8s/clip-downloader-deployment.yaml
```

Or all at once after Redis is ready:

```bash
kubectl apply -f k8s/
kubectl rollout status deployment/redis
kubectl rollout status deployment/chat-monitor
kubectl rollout status deployment/clip-downloader
```

---

## Operations

### Check which streamers are live

```bash
kubectl exec -it deploy/redis -- redis-cli SMEMBERS live:streamers
```

### Check resolved streamer info (chatroom IDs)

```bash
kubectl exec -it deploy/redis -- redis-cli HGETALL streamer:info:xqc
```

### Inspect the clip queue

```bash
# How many events pending
kubectl exec -it deploy/redis -- redis-cli LLEN clip:queue

# Peek at the next event
kubectl exec -it deploy/redis -- redis-cli LRANGE clip:queue 0 0
```

### Check failed downloads

```bash
kubectl exec -it deploy/redis -- redis-cli LRANGE clip:failed 0 -1
```

### Watch live logs

```bash
# Chat monitor (websocket connections + spike events)
kubectl logs -f deploy/chat-monitor

# Live poller (runs every 5 min via CronJob)
kubectl logs -l app=live-poller --since=10m

# Clip downloader (yt-dlp output)
kubectl logs -f deploy/clip-downloader
```

### Manually trigger a poll

```bash
kubectl create job --from=cronjob/live-poller manual-poll-$(date +%s)
```

---

## Adding or Removing Streamers

Edit `k8s/configmap.yaml`, update the `streamers:` list, then:

```bash
kubectl apply -f k8s/configmap.yaml
```

The next CronJob run will pick up the change automatically. The chat-monitor reads the live set from Redis, so it will start monitoring newly live streamers within 30 seconds of the poller updating Redis.

> **Note:** The chat-monitor loads `emotes.yaml` at startup. To update the emote list without restarting the pod, you can set `EMOTES_PATH` to a path backed by a ConfigMap volume with `subPath` (already configured), then restart the deployment after `kubectl apply -f k8s/configmap.yaml`.

---

## Tuning

| Config key | Default | Effect |
| --- | --- | --- |
| `min_chat_spike` | `80` | msgs/sec threshold for spike signal 1 |
| `clip_window` | `150` | seconds before+after spike timestamp to clip |
| `poll_interval` | `300` | CronJob interval (also set in the CronJob schedule) |
| `HYPE_RATIO_THRESHOLD` | `0.25` | hardcoded in `monitor/main.py` |
| `COOLDOWN_SECONDS` | `120` | hardcoded in `monitor/main.py` — per-streamer cooldown |
| `LOW_PRIORITY_DELAY` | `300` | hardcoded in `downloader/main.py` — delay before low-priority download |

---

## Known Limitations & Caveats

- **Pusher websocket**: `wss://ws-us2.pusher.com/app/eb1d5f283081a78b932c` is an unofficial endpoint. Kick may change or block it without notice. The code will auto-reconnect with exponential backoff, but if Kick rotates the app key the entire monitor will stop receiving messages. Replace with official Kick webhooks once they ship websocket/webhook chat event support.

- **Slug resolution** (`kick.com/api/v2/channels/{slug}`): Also unofficial. Resolved IDs are cached in Redis to minimize hits. The poller retries with 5 different User-Agent strings on 403 responses.

- **Clips API**: `GET /public/v1/clips` for priority scoring may not be available yet. The monitor defaults to `"normal"` priority on 404 or any error and never crashes the spike flow.

- **Single replica**: The chat-monitor is a single stateful process managing all websocket connections. If it restarts, it will reconnect to all live streamers within one sync cycle (30 seconds). No clips are missed during the reconnect window because yt-dlp uses a sliding window relative to the spike timestamp.

---

## File Structure

```text
KickIngestion/
├── monitor/
│   ├── main.py           # always-on chat-monitor (Pusher websocket manager)
│   ├── poller.py         # CronJob script — live status checker
│   ├── requirements.txt
│   └── Dockerfile
├── downloader/
│   ├── main.py           # clip downloader (Redis consumer → yt-dlp)
│   ├── requirements.txt
│   └── Dockerfile
├── k8s/
│   ├── secret.yaml
│   ├── configmap.yaml
│   ├── redis-deployment.yaml
│   ├── redis-service.yaml
│   ├── pvc.yaml
│   ├── chat-monitor-deployment.yaml
│   ├── live-poller-cronjob.yaml
│   └── clip-downloader-deployment.yaml
├── config/
│   ├── roster.yaml       # local dev / reference copy
│   └── emotes.yaml       # local dev / reference copy
└── README.md
```
