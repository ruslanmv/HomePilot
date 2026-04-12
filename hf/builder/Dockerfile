# =============================================================================
# HomePilot — Hugging Face Spaces Dockerfile
# =============================================================================
# Three-stage build:
#   1. Build React frontend (Vite)
#   2. Runtime: Ollama + FastAPI + pre-built frontend + Chata personas
#
# HF Spaces constraints:
#   - Must listen on port 7860
#   - Only /tmp is writable at runtime
#   - Free tier: 2 vCPU, 16GB RAM, no GPU
# =============================================================================

# ── Stage 1: Frontend build ──────────────────────────────
FROM node:20-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund 2>/dev/null

COPY frontend/ ./
ENV VITE_API_URL=""
RUN npm run build && ls -la dist/

# ── Stage 2: Runtime ─────────────────────────────────────
FROM python:3.11-slim

# System deps + Ollama
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates procps zstd \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://ollama.com/install.sh | sh

# HF Spaces user (uid 1000)
RUN useradd -m -u 1000 hpuser && \
    mkdir -p /app /tmp/ollama /tmp/homepilot/data \
             /tmp/homepilot/uploads /tmp/homepilot/outputs && \
    chown -R hpuser:hpuser /app /tmp/ollama /tmp/homepilot

WORKDIR /app

# Python deps (cached layer)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/app ./app
# Ensure __init__.py exists (created by deploy script)
RUN touch ./app/__init__.py

# Community persona samples
COPY community/sample ./community/sample

# Chata personas (pre-installed)
COPY deploy/huggingface-space/chata-personas ./chata-personas

# Pre-built frontend from stage 1
COPY --from=frontend /build/dist ./frontend

# HF Space wrapper (serves frontend + patches config)
COPY deploy/huggingface-space/hf_wrapper.py ./hf_wrapper.py
COPY deploy/huggingface-space/auto_import_personas.py ./auto_import_personas.py

# Startup script (copied to root by deploy script)
COPY start.sh ./start.sh
RUN chmod +x start.sh

USER hpuser
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/health || exit 1

CMD ["./start.sh"]
