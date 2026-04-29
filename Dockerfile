# Softstudio — self-hosted ComfyUI + FastAPI gateway for Softlit AI.
# Runs as a sibling Railway service to the IDE service in the same project.
# Internal-only — Softlit IDE proxies to it via SOFTSTUDIO_URL.
#
# GPU requirements: 16 GB VRAM minimum (LTX-Video and Flux schnell each
# fit on a single L4). Railway GPU plan with NVIDIA L4 or better.

FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: Python 3.12, git (for ComfyUI clone), ffmpeg (LTX video output),
# build essentials for any source-installed wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        ca-certificates \
        curl \
        git \
        ffmpeg \
        build-essential \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

WORKDIR /app

# 1. PyTorch with CUDA 12.8 — heaviest layer, cache aggressively.
RUN python3.12 -m pip install --index-url https://download.pytorch.org/whl/cu128 \
        torch torchvision torchaudio

# 2. Clone ComfyUI at a pinned commit (reproducible builds).
ARG COMFY_REF=master
RUN git clone --depth 1 --branch ${COMFY_REF} \
        https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI \
    && python3.12 -m pip install -r /app/ComfyUI/requirements.txt

# 3. Backend deps + huggingface_hub for model downloads.
RUN python3.12 -m pip install \
        fastapi \
        "uvicorn[standard]" \
        "websockets>=12" \
        python-multipart \
        huggingface_hub \
        httpx

# 4. Copy the gateway code.
COPY backend/ /app/backend/
COPY workflows/ /app/workflows/
COPY scripts/ /app/scripts/

# 5. Startup script — downloads models on first boot (idempotent), then
#    runs ComfyUI on :8188 in the background and FastAPI on $PORT.
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Models live on a Railway volume mounted at /data/models. ComfyUI's
# models/ tree symlinks into it so reboots don't re-download.
VOLUME ["/data/models"]

# FastAPI listens on $PORT (Railway sets it). Default 8000 for local.
ENV PORT=8000 \
    COMFY_URL=http://127.0.0.1:8188 \
    HOST=0.0.0.0

EXPOSE 8000

CMD ["/app/start.sh"]
