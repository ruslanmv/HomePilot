FROM python:3.11-slim AS base

LABEL maintainer="HomePilot Community"
LABEL description="Optional StyleGAN2 face-generation microservice for Avatar Studio"

WORKDIR /app

# System deps for Pillow image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libwebp-dev libpng-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps (base — no GPU)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY app/ app/
COPY scripts/ scripts/

# Create output directory
RUN mkdir -p /app/uploads

EXPOSE 8020

HEALTHCHECK --interval=20s --timeout=5s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8020/v1/avatars/capabilities').read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]

# ---------------------------------------------------------------------------
# GPU variant — use: docker build --target gpu ...
# ---------------------------------------------------------------------------
FROM base AS gpu

# Install PyTorch with CUDA support
RUN pip install --no-cache-dir ".[gpu]" --extra-index-url https://download.pytorch.org/whl/cu121

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
