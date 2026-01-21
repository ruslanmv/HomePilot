# QuickStart - Local Development

Get HomePilot running locally in 5 simple steps (no Docker needed).

## Prerequisites

- **Python 3.11 or 3.12**
- **Node.js 18+**
- **Ollama** (for LLM inference)

## Quick Setup

### 1. Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart your terminal.

### 2. Install HomePilot

```bash
make install
```

This will:
- Create a Python virtual environment with uv
- Install all backend dependencies (FastAPI, ChromaDB, etc.)
- Install frontend dependencies (React, Vite, etc.)

### 3. Configure Environment (Optional)

For most users, the defaults work fine. But if you want to customize:

```bash
# Copy the example environment file
cp .env.local.example backend/.env.local

# Edit backend/.env.local to change settings
# (e.g., different Ollama URL, API keys, etc.)
```

### 4. Start Ollama and Pull a Model

```bash
# Start Ollama server (in a separate terminal)
ollama serve

# Pull a model (in another terminal)
ollama pull llama3:8b
```

### 5. Start HomePilot

```bash
make start
```

This will start:
- **Backend** on http://localhost:8000
- **Frontend** on http://localhost:3000

Press `Ctrl+C` to stop both services.

## Development Workflow

### Start individual services

```bash
# Start only backend
make start-backend

# Start only frontend  
make start-frontend
```

### Run tests

```bash
# Run backend tests
make test-local
```

### Download AI models for ComfyUI

```bash
# Download minimal models (~7GB - FLUX Schnell)
make download-minimal

# Download recommended models (~14GB - FLUX + SDXL)
make download-recommended

# Download all models (~65GB)
make download-full
```

## Docker Deployment (Optional)

If you prefer Docker:

```bash
# Setup Docker environment
make setup

# Start with Docker (without Ollama container)
make up

# Start with Docker (with Ollama container)
make run
```

## Troubleshooting

### Backend won't start

```bash
# Reinstall backend dependencies
cd backend
rm -rf .venv
cd ..
make install
```

### Frontend won't start

```bash
# Reinstall frontend dependencies
cd frontend
rm -rf node_modules package-lock.json
npm install
cd ..
```

### Permission errors or "No such file or directory: '/app/data'"

This happens when the backend tries to use Docker paths instead of local paths.

**Solution:** The backend now auto-detects local vs Docker environments. If you still see this error:

```bash
# Set DATA_DIR explicitly for local development
echo "DATA_DIR=./backend/data" > backend/.env.local
```

Then restart with `make start`.

### ChromaDB errors

ChromaDB is optional. If you don't need RAG features:
- The app will work fine without it
- You'll see a warning: "ChromaDB not available. RAG functionality disabled."

To enable ChromaDB:
```bash
cd backend
.venv/bin/pip install chromadb PyPDF2
```

## Project Structure

```
HomePilot/
├── backend/          # FastAPI backend
│   ├── app/         # Application code
│   ├── .venv/       # Virtual environment (created by make install)
│   └── pyproject.toml  # Python dependencies
├── frontend/        # React frontend
│   ├── src/        # Source code
│   └── node_modules/  # NPM dependencies
├── models/          # AI models (downloaded with make download-*)
└── Makefile        # Build automation
```

## Available Make Commands

Run `make help` to see all available commands:

```bash
make help
```

Key commands:
- `make install` - Install everything locally with uv
- `make start` - Start backend + frontend locally
- `make setup` - Setup Docker environment
- `make test-local` - Run backend tests
- `make download-recommended` - Download AI models
- `make health-check` - Check service health
