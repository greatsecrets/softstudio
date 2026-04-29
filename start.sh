#!/bin/bash
# Softstudio container entrypoint. Wires up the persistent model
# directory, downloads any missing weights, starts ComfyUI in the
# background, then runs the FastAPI gateway on $PORT.
#
# Models live on a Railway-mounted volume at /data/models. ComfyUI's
# default `models/` tree is symlinked into it so checkpoints persist
# across container restarts.

set -e

cd /app

# 1. Wire ComfyUI's models/ tree to the Railway volume.
mkdir -p /data/models /data/models/checkpoints /data/models/text_encoders /data/models/vae /data/models/loras
if [ -d /app/ComfyUI/models ] && [ ! -L /app/ComfyUI/models ]; then
    rm -rf /app/ComfyUI/models
fi
ln -sfn /data/models /app/ComfyUI/models

# 2. Wire ComfyUI's output/ tree to a tmpfs-style scratch dir on the
#    same volume — generated assets live here and the FastAPI gateway
#    serves them via /assets/{path}.
mkdir -p /data/output
if [ -d /app/ComfyUI/output ] && [ ! -L /app/ComfyUI/output ]; then
    rm -rf /app/ComfyUI/output
fi
ln -sfn /data/output /app/ComfyUI/output

mkdir -p /data/input
if [ -d /app/ComfyUI/input ] && [ ! -L /app/ComfyUI/input ]; then
    rm -rf /app/ComfyUI/input
fi
ln -sfn /data/input /app/ComfyUI/input

# 3. Download models (idempotent — skips if already present).
echo "[start] Checking model weights at /data/models..."
python3.12 /app/scripts/download_models.py || {
    echo "[start] Model download failed — exiting before ComfyUI starts." >&2
    exit 1
}

# 4. ComfyUI in background.
echo "[start] Launching ComfyUI on :8188..."
cd /app/ComfyUI
python3.12 main.py --listen 127.0.0.1 --port 8188 \
    > /tmp/comfy.log 2>&1 &
COMFY_PID=$!

# Trap so SIGTERM from Railway shuts both processes cleanly.
trap "kill $COMFY_PID 2>/dev/null || true; exit 0" SIGTERM SIGINT

# 5. Wait for ComfyUI to come up. Healthcheck via /system_stats.
echo "[start] Waiting for ComfyUI to be ready..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "[start] ComfyUI ready after ${i}s."
        break
    fi
    if ! kill -0 $COMFY_PID 2>/dev/null; then
        echo "[start] ComfyUI exited prematurely. Tail of /tmp/comfy.log:" >&2
        tail -50 /tmp/comfy.log >&2
        exit 1
    fi
    sleep 1
done

# 6. FastAPI gateway in foreground (Railway tracks the foreground PID).
echo "[start] Launching FastAPI gateway on :${PORT:-8000}..."
cd /app
exec python3.12 -m uvicorn backend.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --workers 1 \
    --access-log
