# HomePilot Container — Self-Hosted, GPU-Ready Deployment
# Works on: Personal PCs (Docker + NVIDIA GPU), RunPod, Google Colab
#
# Build:
#   docker build -f container/Dockerfile -t homepilot .
#
# Run (local GPU):
#   docker run --gpus all -p 7860:7860 homepilot
#
# Run (CPU-only, default):
#   docker run -p 7860:7860 homepilot
#
# Size notes:
#   Base runtime image is python:3.11-slim (~150 MB).
#   Backend Python deps add ~500 MB. ComfyUI + CPU-only torch adds ~1.5 GB.
#   Total image is ~2.3 GB uncompressed. This is intentional: without
#   ComfyUI the desktop install cannot generate images or videos.
#
#   A GPU-accelerated variant (CUDA torch, xformers) belongs in a
#   separate tag (`:latest-cuda`, built from an nvidia/cuda base) so
#   CPU users are not forced to download a 6+ GB image. That variant
#   is not yet wired into this Dockerfile.

# ============================================================
# Stage 1: Frontend build
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ============================================================
# Stage 2: ComfyUI build
#
# We clone ComfyUI at a pinned tag, create a dedicated venv at
# /opt/comfy-venv, and install CPU-only torch wheels plus ComfyUI's
# own requirements. A separate builder stage lets us drop build-only
# tooling (pip cache, git metadata) out of the final image.
# ============================================================
FROM python:3.11-slim AS comfy-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pin to a specific ComfyUI tag so image builds are reproducible.
# Override with `--build-arg COMFYUI_REF=<tag-or-sha>` when you need
# a newer version. v0.3.10 is a widely-adopted stable release.
ARG COMFYUI_REF=v0.3.10

RUN git clone --depth 1 --branch "${COMFYUI_REF}" \
    https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI \
    && rm -rf /opt/ComfyUI/.git

# Create an isolated venv for ComfyUI so its torch install cannot
# conflict with the backend's much smaller dependency tree.
RUN python3 -m venv /opt/comfy-venv
ENV PATH="/opt/comfy-venv/bin:${PATH}"

# Install CPU-only torch first so pip's dependency resolver does not
# pull the default GPU wheel (3 GB) when a transitive dep pins torch.
# Users who want GPU acceleration should use the :latest-cuda tag.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0

# ComfyUI's own requirements. `--constraint` pins torch back to the
# CPU wheels we just installed so any transitive `torch` pin cannot
# silently re-download a GPU wheel from PyPI.
RUN printf "torch==2.3.0\ntorchvision==0.18.0\ntorchaudio==2.3.0\n" > /tmp/torch-pin.txt \
    && pip install --no-cache-dir \
        --constraint /tmp/torch-pin.txt \
        -r /opt/ComfyUI/requirements.txt

# Face-restoration + segmentation helpers the `make install` path also
# ships (facexlib/gfpgan). Used by the avatar pipeline + some custom
# node graphs. Patch basicsr for torchvision >= 0.18 compatibility
# (imports functional_tensor, which moved to .functional in 0.18).
RUN pip install --no-cache-dir \
        --constraint /tmp/torch-pin.txt \
        facexlib gfpgan \
    && SITE_PKG="$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
    && if [ -f "$SITE_PKG/basicsr/data/degradations.py" ]; then \
         sed -i 's|from torchvision.transforms.functional_tensor import rgb_to_grayscale|from torchvision.transforms.functional import rgb_to_grayscale|' \
           "$SITE_PKG/basicsr/data/degradations.py"; \
       fi

# ============================================================
# Stage 3: Runtime (Backend + Frontend static + Nginx + ComfyUI)
# ============================================================
FROM python:3.11-slim

LABEL maintainer="ruslanmv"
LABEL description="HomePilot — self-hosted AI assistant with ComfyUI"
LABEL org.opencontainers.image.source="https://github.com/ruslanmv/HomePilot"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    # Backend talks to ComfyUI on loopback inside the container.
    COMFY_BASE_URL=http://127.0.0.1:8188 \
    # Point ComfyUI at the CPU-only venv we built in stage 2.
    COMFYUI_VENV=/opt/comfy-venv \
    COMFYUI_HOME=/opt/ComfyUI \
    # Interactive tab: on by default in packaged builds so users
    # get a complete feature surface out of the box. Operators who
    # need to disable it can pass -e INTERACTIVE_ENABLED=false at
    # docker run time.
    INTERACTIVE_ENABLED=true \
    # Playback phase-2 swaps: LLM composer + live renderer. Both
    # default off inside the container because the LLM and Comfy
    # endpoints might not be ready at first boot; the player
    # gracefully falls back to the phase-1 heuristic / stub paths.
    # Flip either to true once the backend is warmed up.
    INTERACTIVE_PLAYBACK_LLM=false \
    INTERACTIVE_PLAYBACK_RENDER=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    ffmpeg \
    curl \
    wget \
    git \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 user

# Setup directories
RUN mkdir -p /home/user/app/data \
    /home/user/app/data/uploads \
    /home/user/app/data/comfy_cache \
    /home/user/app/data/models \
    /home/user/app/data/comfy/models \
    /home/user/app/data/comfy/output \
    /home/user/app/data/comfy/input \
    /var/log/supervisor \
    /var/run/nginx \
    && chown -R user:user /home/user \
    && chown -R user:user /var/log/supervisor \
    && chown -R user:user /var/log/nginx \
    && chown -R user:user /var/lib/nginx \
    && chown -R user:user /var/run/nginx \
    && chown -R user:user /etc/nginx

WORKDIR /home/user/app

# Install backend Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy ComfyUI + its dedicated venv from the builder stage.
# Chown so the non-root runtime user can write into ComfyUI's model /
# output / input folders when entrypoint.sh links the persistent
# volumes in.
COPY --from=comfy-builder --chown=user:user /opt/comfy-venv /opt/comfy-venv
COPY --from=comfy-builder --chown=user:user /opt/ComfyUI   /opt/ComfyUI

# Copy backend source
COPY backend/app ./app

# Copy built frontend
COPY --from=frontend-builder /build/dist ./static

# Copy container configuration
COPY container/nginx.conf /etc/nginx/nginx.conf
COPY container/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY container/entrypoint.sh /home/user/app/entrypoint.sh
RUN chmod +x /home/user/app/entrypoint.sh

# Switch to non-root user
USER user

# Default port (configurable via HOMEPILOT_EXTERNAL_PORT env var)
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:7860/api/health || exit 1

CMD ["/home/user/app/entrypoint.sh"]
