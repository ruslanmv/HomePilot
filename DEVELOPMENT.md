# Development Guide

This guide helps you develop and troubleshoot HomePilot.

## Quick Start

```bash
# 1. Install everything
make install

# 2. Start backend and frontend
make start
```

## Testing

```bash
# Run all tests
make test

# Run specific test file
cd backend
.venv/bin/pytest tests/test_health.py -v

# Run with coverage
.venv/bin/pytest --cov=app tests/
```

## Troubleshooting

### ERR_CONNECTION_REFUSED Errors

**Symptoms:** Frontend shows `Failed to fetch` or `ERR_CONNECTION_REFUSED` errors for `:8000/health`, `:8000/projects`, etc.

**Causes:**
1. Backend not running
2. Backend crashed on startup
3. Backend running on different port

**Solutions:**

1. **Check if backend is running:**
   ```bash
   curl http://localhost:8000/health
   ```

   If this fails, the backend is not running.

2. **Check backend logs:**
   ```bash
   # If you started with `make start`, check terminal for backend errors
   # Look for Python tracebacks or permission errors
   ```

3. **Restart backend manually:**
   ```bash
   # Stop everything (Ctrl+C)
   cd backend
   .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Check for permission errors:**
   ```bash
   # If you see "Permission denied: '/app/data'"
   # The backend should auto-detect local vs Docker
   # If it doesn't, set DATA_DIR explicitly:
   export DATA_DIR=./backend/data
   cd backend
   .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Wait for backend to be ready:**
   ```bash
   # Use the helper script
   ./scripts/wait-for-backend.sh
   
   # Then open frontend
   open http://localhost:3000
   ```

### Python Version Issues

**Error:** `requires-python = ">=3.11,<3.14"` constraint fails

**Solution:** Install Python 3.11, 3.12, or 3.13:
```bash
# Check version
python3 --version

# If you have Python 3.13 but uv fails:
cd backend
uv venv .venv --python python3.13
uv pip install -e .
```

### ChromaDB Not Available

**Warning:** `Warning: ChromaDB not available. RAG functionality disabled.`

This is **optional**. The app works fine without it.

**To enable ChromaDB:**
```bash
cd backend
.venv/bin/pip install chromadb PyPDF2
```

### Frontend Not Finding Backend

**Error:** API requests go to wrong URL

**Check settings:**
1. Open http://localhost:3000
2. Click settings (gear icon)
3. Verify "Backend URL" is set to `http://localhost:8000`
4. Save settings

The default is `http://localhost:8000` so this should work out of the box.

### Example Projects Not Showing

**Symptoms:** "Examples" tab is empty, no default projects

**Solution:** 
The backend should return 4 example projects by default. Test this:

```bash
curl http://localhost:8000/projects/examples
```

You should see JSON with 4 examples. If not:
1. Check backend logs for errors
2. Verify `backend/app/projects.py` has EXAMPLE_PROJECTS defined
3. Restart backend

### Tests Failing

```bash
# Make sure backend is installed
make install

# Run tests
make test

# If specific tests fail, run with verbose output
cd backend
.venv/bin/pytest -vv --tb=long
```

## Development Workflow

### Backend Development

```bash
# Start backend with auto-reload
make start-backend

# Or manually:
cd backend
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Any changes to `.py` files will auto-reload the server.

### Frontend Development

```bash
# Start frontend with hot module reload
make start-frontend

# Or manually:
cd frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

Changes to `.tsx` files will hot-reload in the browser.

### Full Stack Development

```bash
# Start both backend and frontend
make start

# They run in parallel with auto-reload enabled
```

## Environment Variables

### Backend (.env.local)

```bash
# Copy example
cp .env.local.example backend/.env.local

# Edit as needed
```

Key variables:
- `DEFAULT_PROVIDER` - LLM provider (ollama, openai_compat)
- `OLLAMA_BASE_URL` - Ollama URL (default: http://localhost:11434)
- `OLLAMA_MODEL` - Ollama model (default: llama3:8b)
- `DATA_DIR` - Data directory (auto-detected for local dev)

### Frontend

Frontend gets backend URL from localStorage (configurable in settings).

## API Endpoints

### Health & Status

```bash
# Health check
curl http://localhost:8000/health

# Available providers
curl http://localhost:8000/providers
```

### Projects

```bash
# List all projects
curl http://localhost:8000/projects

# Get example templates
curl http://localhost:8000/projects/examples

# Create from example
curl -X POST http://localhost:8000/projects/from-example/legal-reviewer

# Get specific project
curl http://localhost:8000/projects/{project_id}
```

### Conversations

```bash
# List conversations
curl http://localhost:8000/conversations

# Get conversation messages
curl http://localhost:8000/conversations/{id}/messages

# Search conversation
curl "http://localhost:8000/conversations/{id}/search?q=query"
```

## Project Structure

```
HomePilot/
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI app
│   │   ├── projects.py     # Projects & examples
│   │   ├── vectordb.py     # ChromaDB (RAG)
│   │   ├── search.py       # Conversation search
│   │   └── config.py       # Configuration
│   ├── tests/
│   │   └── test_health.py  # API tests
│   ├── data/               # Local data (auto-created)
│   └── pyproject.toml      # Python dependencies
├── frontend/
│   ├── src/
│   │   └── ui/
│   │       ├── App.tsx     # Main app
│   │       └── ProjectsView.tsx  # Projects UI
│   └── package.json        # NPM dependencies
├── scripts/
│   └── wait-for-backend.sh # Helper script
├── Makefile                # Build commands
└── QUICKSTART.md          # Quick start guide
```

## Common Commands

```bash
make help              # Show all commands
make install           # Install everything
make start             # Start backend + frontend
make test              # Run tests
make start-backend     # Start only backend
make start-frontend    # Start only frontend
make clean             # Clean build artifacts
```

## Debugging

### Enable Verbose Logging

```bash
# Backend
cd backend
export LOG_LEVEL=DEBUG
.venv/bin/uvicorn app.main:app --reload --log-level debug

# Frontend (check browser console)
# Open DevTools (F12) and check Console tab
```

### Check Database

```bash
# SQLite database location
ls -lh backend/data/homepilot.db

# Query database
sqlite3 backend/data/homepilot.db "SELECT * FROM conversations LIMIT 5;"
```

### Check Uploads

```bash
# Uploads directory
ls -lh backend/data/uploads/

# Vector database (if ChromaDB enabled)
ls -lh backend/data/chroma_db/
```

## Getting Help

1. Check QUICKSTART.md for installation issues
2. Check this guide for development issues
3. Check backend logs for API errors
4. Check browser console for frontend errors
5. Run `make test` to verify everything works
