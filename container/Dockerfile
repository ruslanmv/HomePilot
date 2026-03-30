# HomePilot Container - Self-Hosted GPU-Ready Deployment
# Works on: Personal PCs (Docker + NVIDIA GPU), RunPod, Google Colab
#
# Build:
#   docker build -f container/Dockerfile -t homepilot .
#
# Run (local GPU):
#   docker run --gpus all -p 7860:7860 homepilot
#
# Run (CPU-only):
#   docker run -p 7860:7860 homepilot

# ============================================================
# Stage 1: Build Frontend
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ============================================================
# Stage 2: Runtime (Backend + Frontend static + Nginx)
# ============================================================
FROM python:3.11-slim

LABEL maintainer="ruslanmv"
LABEL description="HomePilot - Self-hosted AI assistant container"
LABEL org.opencontainers.image.source="https://github.com/ruslanmv/HomePilot"

# Set environment
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    ffmpeg \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 user

# Setup directories
RUN mkdir -p /home/user/app/data \
    /home/user/app/data/uploads \
    /home/user/app/data/comfy_cache \
    /home/user/app/data/models \
    /var/log/supervisor \
    /var/run/nginx \
    && chown -R user:user /home/user \
    && chown -R user:user /var/log/supervisor \
    && chown -R user:user /var/log/nginx \
    && chown -R user:user /var/lib/nginx \
    && chown -R user:user /var/run/nginx \
    && chown -R user:user /etc/nginx

WORKDIR /home/user/app

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

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
