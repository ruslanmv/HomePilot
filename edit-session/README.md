# edit-session (HomePilot Sidecar)

A production-grade sidecar service that adds **natural image editing sessions** on top of HomePilot without modifying HomePilot code.

## Overview

This service enables a "upload once, chat to edit" workflow:

1. User uploads an image once
2. User sends natural language edit instructions ("remove background", "make it sunset")
3. Service automatically uses the active image without requiring URLs in every message
4. User can select results, undo, and branch from history

## Architecture

```
┌─────────────┐     ┌────────────────┐     ┌─────────────┐
│   Frontend  │────▶│  edit-session  │────▶│  HomePilot  │
│             │     │   (sidecar)    │     │   backend   │
└─────────────┘     └────────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Storage   │
                    │ (SQLite/    │
                    │  Redis)     │
                    └─────────────┘
```

## Key Features

- **Active Image Session**: Maintains an active image per conversation
- **Natural Language Edits**: No need to include URLs in every message
- **Image History**: Undo/branch from any previous image
- **Drop-in Compatible**: `/upload` and `/chat` endpoints match HomePilot's API
- **Dual Storage**: SQLite (single instance) or Redis (multi-instance)
- **Security**: API key auth, rate limiting, SSRF protection

## Quick Start

### Local Development

```bash
cd edit-session
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set HomePilot backend URL
export HOME_PILOT_BASE_URL=http://localhost:8000

# Run the service
uvicorn app.main:app --reload --port 8010
```

### Docker

```bash
# Build
docker build -t edit-session:latest .

# Run (adjust HOME_PILOT_BASE_URL as needed)
docker run -p 8010:8010 \
  -e HOME_PILOT_BASE_URL=http://host.docker.internal:8000 \
  -v edit-session-data:/data \
  edit-session:latest
```

### Docker Compose (with HomePilot)

```bash
cd infra
docker compose -f docker-compose.yml -f docker-compose.edit-session.yml up
```

## API Endpoints

### Compatibility Endpoints (Drop-in for Frontend)

These endpoints are compatible with HomePilot's API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload image + optionally set as active |
| POST | `/chat` | Chat/edit with automatic active image injection |

### Session Management Endpoints (New API)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/edit-sessions/{id}/image` | Upload and set active image |
| POST | `/v1/edit-sessions/{id}/message` | Apply natural language edit |
| POST | `/v1/edit-sessions/{id}/select` | Set result as new active image |
| GET | `/v1/edit-sessions/{id}` | Get session state |
| DELETE | `/v1/edit-sessions/{id}` | Clear session |
| GET | `/v1/edit-sessions/{id}/history` | Get image history |
| POST | `/v1/edit-sessions/{id}/revert` | Revert to history image |

### Health Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Basic health check |
| GET | `/health/live` | Kubernetes liveness probe |
| GET | `/health/ready` | Kubernetes readiness probe |

## Configuration

All settings via environment variables:

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `HOME_PILOT_BASE_URL` | `http://backend:8000` | HomePilot backend URL |

### Security (Recommended for Production)

| Variable | Default | Description |
|----------|---------|-------------|
| `EDIT_SESSION_API_KEY` | (none) | API key for this service |
| `HOME_PILOT_API_KEY` | (none) | API key for HomePilot |
| `ALLOWED_EXTERNAL_IMAGE_HOSTS` | (none) | Comma-separated allowed hosts |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `STORE` | `sqlite` | Storage backend: `sqlite` or `redis` |
| `SQLITE_PATH` | `/data/edit_sessions.sqlite` | SQLite database path |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |

### Session Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TTL_SECONDS` | `604800` (7 days) | Session expiration time |
| `HISTORY_LIMIT` | `10` | Max images in history |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_RPS` | `3.0` | Requests per second per IP |
| `RATE_LIMIT_BURST` | `10` | Burst capacity |

### Upload Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_UPLOAD_MB` | `20` | Maximum upload size in MB |

## Usage Examples

### 1. Upload and Set Active Image

```bash
# Upload image and set as active for conversation
curl -X POST http://localhost:8010/upload \
  -F "file=@photo.png" \
  -F "conversation_id=conv-123"
```

### 2. Apply Natural Language Edit

```bash
# Edit using natural language (no URL needed!)
curl -X POST http://localhost:8010/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "remove the background and make it transparent",
    "mode": "edit",
    "conversation_id": "conv-123"
  }'
```

### 3. Select Result as New Base

```bash
# Use a generated result as the new base for further edits
curl -X POST http://localhost:8010/v1/edit-sessions/conv-123/select \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "http://backend:8000/files/result-001.png"
  }'
```

### 4. Revert to Previous Version

```bash
# Revert to a previous image from history
curl -X POST "http://localhost:8010/v1/edit-sessions/conv-123/revert?index=1"
```

## Frontend Integration

### Option 1: Minimal Change (Recommended)

Point your frontend's `backendUrl` to this service instead of HomePilot directly:

```javascript
// Before
const BACKEND_URL = 'http://localhost:8000';

// After
const BACKEND_URL = 'http://localhost:8010';
```

The `/upload` and `/chat` endpoints are compatible.

### Option 2: Full Integration

Use the new session endpoints for enhanced UX:

```javascript
// Upload and start editing
const upload = await fetch('/v1/edit-sessions/conv-123/image', {
  method: 'POST',
  body: formData  // contains 'file' and optional 'instruction'
});

// Apply edits
const edit = await fetch('/v1/edit-sessions/conv-123/message', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: 'make it vibrant' })
});

// Select result
await fetch('/v1/edit-sessions/conv-123/select', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ image_url: result.images[0] })
});
```

## Production Deployment

### Single Instance (SQLite)

```yaml
services:
  edit-session:
    image: homepilot-edit-session:latest
    environment:
      - HOME_PILOT_BASE_URL=http://backend:8000
      - EDIT_SESSION_API_KEY=your-secret-key
      - STORE=sqlite
    volumes:
      - edit-session-data:/data
```

### Multi-Instance (Redis)

```yaml
services:
  edit-session:
    image: homepilot-edit-session:latest
    deploy:
      replicas: 3
    environment:
      - HOME_PILOT_BASE_URL=http://backend:8000
      - EDIT_SESSION_API_KEY=your-secret-key
      - STORE=redis
      - REDIS_URL=redis://redis:6379/0

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: edit-session
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: edit-session
          image: homepilot-edit-session:latest
          env:
            - name: STORE
              value: redis
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: edit-session-secrets
                  key: redis-url
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8010
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8010
```

## Testing

```bash
cd edit-session
pip install -r requirements.txt
pytest app/tests/ -v
```

## Security Considerations

1. **API Key**: Set `EDIT_SESSION_API_KEY` in production
2. **SSRF Protection**: Only HomePilot-hosted URLs allowed by default
3. **Rate Limiting**: Built-in per-IP rate limiting
4. **Input Validation**: Image validation prevents malicious uploads
5. **EXIF Stripping**: Metadata removed by default for privacy

## License

Same license as HomePilot.
