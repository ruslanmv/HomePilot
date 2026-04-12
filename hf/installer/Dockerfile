FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git git-lfs ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install \
    && useradd -m -u 1000 app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R app:app /app
USER app

EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
