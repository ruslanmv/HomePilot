SHELL := /bin/bash

# Fix uv hardlink warning on WSL / multi-filesystem setups (optional, safe default)
export UV_LINK_MODE ?= copy

.PHONY: help install setup run up down stop logs health dev build test clean download download-minimal download-recommended download-full download-edit download-enhance download-video download-verify download-health start start-backend start-frontend

help: ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Installation & Setup -----------------------------------------------------

install: ## Install HomePilot locally with uv (Python 3.11+)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Installing HomePilot Locally (uv + Python 3.11)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@# Check for uv
	@command -v uv >/dev/null 2>&1 || { \
		echo "ERROR: 'uv' not found."; \
		echo ""; \
		echo "Install it with:"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo ""; \
		echo "Then reopen your terminal and run: make install"; \
		exit 1; \
	}
	@# Check Python version
	@python3 --version 2>&1 | grep -q "Python 3.11" || python3 --version 2>&1 | grep -q "Python 3.12" || { \
		echo "WARNING: Python 3.11 or 3.12 recommended. Current version:"; \
		python3 --version; \
		echo ""; \
	}
	@echo "✓ Installing backend with uv..."
	@cd backend && uv venv .venv --python 3.11 || uv venv .venv
	@cd backend && uv pip install -e .
	@cd backend && uv pip install --group dev
	@echo ""
	@echo "✓ Installing edit-session service with uv..."
	@cd edit-session && uv venv .venv --python 3.11 || uv venv .venv
	cd edit-session && uv pip install -e . --python .venv/bin/python
	@cd edit-session && uv pip install --group dev --python .venv/bin/python 2>/dev/null || true
	@test -f edit-session/.venv/bin/uvicorn || (echo "  ❌ ERROR: edit-session uvicorn not found after install"; exit 1)
	@echo "  ✓ Edit-session service installed"
	@echo ""
	@echo "✓ Installing frontend dependencies..."
	@cd frontend && npm install
	@echo ""
	@echo "✓ Installing ComfyUI..."
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "  Cloning ComfyUI repository..."; \
		rm -rf ComfyUI; \
		git clone https://github.com/comfyanonymous/ComfyUI.git ComfyUI; \
	else \
		echo "  ComfyUI already present"; \
	fi
	@echo "  Setting up ComfyUI virtual environment..."
	@if [ ! -d "ComfyUI/.venv" ]; then \
		python3 -m venv ComfyUI/.venv; \
	fi
	@echo "  Installing ComfyUI dependencies..."
	@ComfyUI/.venv/bin/pip install -U pip setuptools wheel >/dev/null 2>&1 || true
	@ComfyUI/.venv/bin/pip install -r ComfyUI/requirements.txt
	@echo "  Installing face restoration dependencies (GFPGAN/CodeFormer)..."
	@if ComfyUI/.venv/bin/pip install facexlib gfpgan >/dev/null 2>&1; then \
		echo "  ✓ Face restoration dependencies installed"; \
	else \
		echo "    (optional: facexlib/gfpgan install skipped)"; \
	fi
	@echo "  Installing ComfyUI-Impact-Pack for face restore nodes..."
	@if [ ! -d "ComfyUI/custom_nodes/ComfyUI-Impact-Pack" ]; then \
		mkdir -p ComfyUI/custom_nodes && \
		if git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ComfyUI/custom_nodes/ComfyUI-Impact-Pack 2>/dev/null && \
		   ComfyUI/.venv/bin/pip install -r ComfyUI/custom_nodes/ComfyUI-Impact-Pack/requirements.txt >/dev/null 2>&1; then \
			echo "  ✓ ComfyUI-Impact-Pack installed"; \
		else \
			echo "    (optional: Impact-Pack install skipped)"; \
		fi; \
	else \
		echo "  ✓ ComfyUI-Impact-Pack already installed"; \
	fi
	@echo ""
	@echo "✓ Setting up model directories..."
	@mkdir -p models/comfy/checkpoints models/comfy/unet models/comfy/clip models/comfy/vae models/comfy/controlnet models/comfy/sams models/comfy/rembg models/comfy/upscale_models models/comfy/gfpgan
	@echo "  Linking ComfyUI models to ./models/comfy..."
	@rm -rf ComfyUI/models
	@ln -s $$(pwd)/models/comfy ComfyUI/models
	@test -L ComfyUI/models || (echo "  ❌ ERROR: Failed to create symlink"; exit 1)
	@echo "  ✓ Symlink created successfully"
	@echo ""
	@echo "✓ Verifying ComfyUI install..."
	@test -f ComfyUI/main.py || (echo "  ❌ ERROR: ComfyUI/main.py missing"; exit 1)
	@test -x ComfyUI/.venv/bin/python || (echo "  ❌ ERROR: ComfyUI venv missing"; exit 1)
	@ComfyUI/.venv/bin/python -c "import torch; print('  ✓ torch:', torch.__version__)" 2>/dev/null || echo "  ✓ torch: (will be loaded at runtime)"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Installation Complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Download models: make download-recommended (~14GB)"
	@echo "  2. Start Ollama: ollama serve"
	@echo "  3. Pull a model: ollama pull llama3:8b"
	@echo "  4. Start HomePilot: make start"
	@echo ""

verify-install: ## Verify that all components are properly installed
	@echo "Verifying installation..."
	@test -f backend/.venv/bin/uvicorn || (echo "❌ backend not installed"; exit 1)
	@echo "  ✓ Backend installed"
	@test -f edit-session/.venv/bin/uvicorn || (echo "❌ edit-session not installed"; exit 1)
	@echo "  ✓ Edit-session installed"
	@test -d frontend/node_modules || (echo "❌ frontend not installed"; exit 1)
	@echo "  ✓ Frontend installed"
	@test -f ComfyUI/main.py || (echo "❌ ComfyUI missing"; exit 1)
	@echo "  ✓ ComfyUI cloned"
	@test -x ComfyUI/.venv/bin/python || (echo "❌ ComfyUI deps missing"; exit 1)
	@echo "  ✓ ComfyUI dependencies installed"
	@test -L ComfyUI/models || (echo "❌ ComfyUI/models not linked"; exit 1)
	@echo "  ✓ ComfyUI models linked"
	@test -d models/comfy/checkpoints || (echo "❌ model directories missing"; exit 1)
	@echo "  ✓ Model directories created"
	@echo ""
	@echo "✅ All components verified successfully!"

setup: ## Setup Docker environment (install deps + build images)
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

# --- Local development (no Docker) --------------------------------------------

start: ## Start HomePilot locally (backend + frontend + ComfyUI)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot LOCALLY (All Services)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Prerequisites:"
	@echo "  ✓ Run 'make install' first"
	@echo "  ✓ Ollama running: ollama serve"
	@echo "  ✓ Ollama model: ollama pull llama3:8b (or your preferred model)"
	@echo ""
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "❌ Frontend not installed. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -f "edit-session/.venv/bin/uvicorn" ]; then \
		echo "❌ Edit-session not installed or incomplete. Run: make install"; \
		echo "   Or manually: cd edit-session && uv pip install -e ."; \
		exit 1; \
	fi
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "⚠️  ComfyUI not found. Run: make install"; \
		echo "    Image/video generation will not work without ComfyUI."; \
		echo ""; \
	fi
	@echo "Services:"
	@echo "  Backend:      http://localhost:8000"
	@echo "  Edit-Session: http://localhost:8010"
	@echo "  Frontend:     http://localhost:3000"
	@if [ -f "ComfyUI/main.py" ]; then \
		echo "  ComfyUI:      http://localhost:8188"; \
	fi
	@echo ""
	@echo "Press Ctrl+C to stop ALL services"
	@echo ""
	@bash -c ' \
		set -e; \
		ROOT="$$(pwd)"; \
		pids=""; \
		cleanup() { \
			echo ""; \
			echo "════════════════════════════════════════════════════════════════════════════════"; \
			echo "  Stopping all services..."; \
			echo "════════════════════════════════════════════════════════════════════════════════"; \
			[ -n "$$pids" ] && kill $$pids 2>/dev/null || true; \
			wait 2>/dev/null || true; \
			echo "All services stopped."; \
		}; \
		trap cleanup INT TERM EXIT; \
		\
		echo "Starting backend..."; \
		cd "$$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 & \
		pids="$$pids $$!"; \
		\
		echo "Starting edit-session service..."; \
		cd "$$ROOT/edit-session" && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8010 & \
		pids="$$pids $$!"; \
		\
		echo "Starting frontend..."; \
		cd "$$ROOT/frontend" && npm run dev -- --host 0.0.0.0 --port 3000 & \
		pids="$$pids $$!"; \
		\
		if [ -f "$$ROOT/ComfyUI/main.py" ] && [ -f "$$ROOT/ComfyUI/.venv/bin/python" ]; then \
			if [ -d "$$ROOT/models/comfy" ] && [ ! -L "$$ROOT/ComfyUI/models" ]; then \
				echo "Linking ComfyUI models to ./models/comfy..."; \
				rm -rf "$$ROOT/ComfyUI/models"; \
				ln -s "$$ROOT/models/comfy" "$$ROOT/ComfyUI/models"; \
			fi; \
			echo "Starting ComfyUI..."; \
			cd "$$ROOT/ComfyUI" && .venv/bin/python main.py --listen 0.0.0.0 --port 8188 & \
			pids="$$pids $$!"; \
		fi; \
		\
		echo ""; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		echo "  ✅ All services started!"; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		echo ""; \
		wait \
	'

start-backend: ## Start backend locally with uv
	@echo "Starting backend..."
	@if [ ! -d "backend/.venv" ]; then \
		echo "Virtual environment not found. Run: make install"; \
		exit 1; \
	fi
	@cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

start-edit-session: ## Start edit-session sidecar locally (port 8010)
	@echo "Starting edit-session service..."
	@if [ ! -d "edit-session/.venv" ]; then \
		echo "Virtual environment not found. Run: make install"; \
		exit 1; \
	fi
	@cd edit-session && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8010

start-frontend: ## Start frontend locally
	@echo "Starting frontend..."
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Node modules not found. Run: make install"; \
		exit 1; \
	fi
	@cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

start-comfyui: ## Start ComfyUI locally (required for image/video generation)
	@echo "Starting ComfyUI..."
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "❌ ComfyUI not found. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -f "ComfyUI/.venv/bin/python" ]; then \
		echo "❌ ComfyUI venv not found. Run: make install"; \
		exit 1; \
	fi
	@if [ -d "models/comfy" ] && [ ! -L "ComfyUI/models" ]; then \
		echo "ℹ️  Auto-linking models..."; \
		rm -rf ComfyUI/models; \
		ln -s $$(pwd)/models/comfy ComfyUI/models; \
	fi
	@cd ComfyUI && .venv/bin/python main.py --listen 0.0.0.0 --port 8188

# --- Testing & Development ----------------------------------------------------

test: test-local  ## Run all tests (alias for test-local)

test-local: ## Run backend tests locally with pytest
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running HomePilot Tests"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo ""
	@echo "Testing backend API endpoints..."
	@cd backend && .venv/bin/pytest -v --tb=short
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ All tests passed!"
	@echo "════════════════════════════════════════════════════════════════════════════════"

# --- Docker stack -------------------------------------------------------------

run: ## Production: Start full stack with Ollama container (docker)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot PRODUCTION (All Containers + Ollama)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	docker compose -f infra/docker-compose.yml --profile ollama up -d --build
	@echo ""
	@echo "✅ All containers started (including Ollama)"
	@echo ""
	@echo "Services:"
	@echo "  UI      : http://localhost:3000"
	@echo "  Backend : http://localhost:8000/docs"
	@echo "  LLM API : http://localhost:8001/v1"
	@echo "  ComfyUI : http://localhost:8188"
	@echo "  Ollama  : http://localhost:11434"
	@echo ""
	@echo "NOTE: Ollama is running in Docker. Pull models with:"
	@echo "  docker exec -it homepilot_ollama ollama pull llama3:8b"
	@echo ""
	@echo "For local development without Ollama container, use: make local"
	@echo ""

up: ## Development: Start stack WITHOUT Ollama container (use host Ollama)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot DEVELOPMENT (Containers without Ollama)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	docker compose -f infra/docker-compose.yml up -d --build
	@echo ""
	@echo "✅ Containers started (without Ollama - use host Ollama)"
	@echo ""
	@echo "Services:"
	@echo "  UI      : http://localhost:3000"
	@echo "  Backend : http://localhost:8000/docs"
	@echo "  LLM API : http://localhost:8001/v1"
	@echo "  ComfyUI : http://localhost:8188"
	@echo ""
	@echo "NOTE: Using Ollama on your host machine at host.docker.internal:11434"
	@echo "  Make sure Ollama is running: ollama serve"
	@echo ""
	@echo "For production with Ollama in Docker, use: make run"
	@echo ""

down: ## Stop all containers (including Ollama if running)
	docker compose -f infra/docker-compose.yml --profile ollama down

stop: ## Stop all local HomePilot processes (kills processes on ports 3000, 8000, 8188)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Stopping HomePilot Services"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@# Kill processes by port (works on Linux/macOS/WSL)
	@for port in 3000 8000 8188; do \
		echo "Checking port $$port..."; \
		pid=$$(lsof -ti :$$port 2>/dev/null || true); \
		if [ -n "$$pid" ]; then \
			echo "  Killing process(es) on port $$port: $$pid"; \
			echo "$$pid" | xargs -r kill -9 2>/dev/null || true; \
		else \
			echo "  No process on port $$port"; \
		fi; \
	done
	@# Also kill by process name as backup (in case lsof misses something)
	@echo ""
	@echo "Cleaning up by process name..."
	@-pkill -9 -f "ComfyUI/main.py" 2>/dev/null && echo "  Killed ComfyUI" || true
	@-pkill -9 -f "uvicorn app.main:app" 2>/dev/null && echo "  Killed backend" || true
	@-pkill -9 -f "vite.*--port 3000" 2>/dev/null && echo "  Killed frontend" || true
	@echo "  Done"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ All HomePilot services stopped"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "You can now safely run: make start"
	@echo ""

logs: ## Tail logs
	docker compose -f infra/docker-compose.yml logs -f --tail=200

health: ## Health checks (best-effort)
	@curl -fsS http://localhost:8000/health | jq . || true
	@curl -fsS http://localhost:8188/system_stats | jq . || true
	@curl -fsS http://localhost:8001/v1/models | jq . || true

dev: ## Frontend dev locally; backend stack in docker
	docker compose -f infra/docker-compose.yml up -d backend llm comfyui media
	cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

build: ## Build production frontend bundle
	cd frontend && npm run build

test: ## Run backend tests (pytest) inside backend container
	docker compose -f infra/docker-compose.yml run --rm backend pytest -q

download: download-recommended ## Download models (alias for download-recommended)

download-minimal: ## Download minimal models (~7GB - FLUX Schnell + encoders)
	@bash scripts/download_models.sh minimal

download-recommended: ## Download recommended models (~24GB - FLUX Schnell + SDXL + edit models)
	@bash scripts/download_models.sh recommended

download-full: ## Download all models (~63GB - FLUX, SDXL, SD1.5, SVD, all edit models)
	@bash scripts/download_models.sh full

download-edit: ## Download only edit mode models (inpainting, controlnet, etc.)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Edit Mode Models"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/checkpoints models/comfy/controlnet models/comfy/sams models/comfy/rembg
	@echo ""
	@echo "[1/5] Downloading SDXL Inpainting 0.1..."
	@wget -c --progress=bar:force -O models/comfy/checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors \
		"https://huggingface.co/wangqyqq/sd_xl_base_1.0_inpainting_0.1.safetensors/resolve/main/sd_xl_base_1.0_inpainting_0.1.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/5] Downloading SD 1.5 Inpainting..."
	@wget -c --progress=bar:force -O models/comfy/checkpoints/sd-v1-5-inpainting.ckpt \
		"https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting/resolve/main/sd-v1-5-inpainting.ckpt" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/5] Downloading ControlNet Inpaint..."
	@wget -c --progress=bar:force -O models/comfy/controlnet/control_v11p_sd15_inpaint.safetensors \
		"https://huggingface.co/lllyasviel/control_v11p_sd15_inpaint/resolve/main/diffusion_pytorch_model.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[4/5] Downloading SAM ViT-H..."
	@wget -c --progress=bar:force -O models/comfy/sams/sam_vit_h_4b8939.pth \
		"https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[5/5] Downloading U2Net..."
	@wget -c --progress=bar:force -O models/comfy/rembg/u2net.onnx \
		"https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Edit mode model download complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@du -sh models/comfy/checkpoints/*inpaint* models/comfy/controlnet/* models/comfy/sams/* models/comfy/rembg/* 2>/dev/null || true

download-enhance: ## Download upscale/enhance models (4x-UltraSharp, RealESRGAN, SwinIR, GFPGAN)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Upscale/Enhance Models"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/upscale_models models/comfy/gfpgan
	@echo ""
	@echo "[1/5] Downloading 4x-UltraSharp (REQUIRED - default upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/4x-UltraSharp.pth \
		"https://huggingface.co/philz1337x/upscaler/resolve/main/4x-UltraSharp.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/5] Downloading RealESRGAN x4+ (Photo upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/RealESRGAN_x4plus.pth \
		"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/5] Downloading SwinIR 4x (Restoration upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/SwinIR_4x.pth \
		"https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[4/5] Downloading Real-ESRGAN General x4v3 (Mixed content)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/realesr-general-x4v3.pth \
		"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[5/5] Downloading GFPGAN v1.4 (Face restoration)..."
	@wget -c --progress=bar:force -O models/comfy/gfpgan/GFPGANv1.4.pth \
		"https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Upscale/Enhance model download complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@du -sh models/comfy/upscale_models/* models/comfy/gfpgan/* 2>/dev/null || true

download-video: ## Download video generation models (LTX-Video recommended, ~6GB)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Video Generation Models"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Available video models:"
	@echo "  • LTX-Video 2B v0.9.1 (RECOMMENDED) - 5.72 GB, fast, works on RTX 4080+"
	@echo "  • SVD XT 1.1 (gated - requires HF token) - 9.56 GB"
	@echo "  • HunyuanVideo GGUF Q4 (pack) - 9.5 GB total"
	@echo "  • Wan 2.2 5B (pack) - 21.5 GB total"
	@echo "  • Mochi FP8 (pack) - 28 GB total"
	@echo ""
	@echo "[1/1] Downloading LTX-Video 2B v0.9.1 (recommended)..."
	@python3 scripts/download.py --model ltx-video-2b-v0.9.1.safetensors || echo "  ⚠️  Failed - check output above"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Video model download complete!"
	@echo ""
	@echo "  To download additional video models, use:"
	@echo "    python3 scripts/download.py --model <model_id>"
	@echo ""
	@echo "  Available models:"
	@echo "    • svd_xt_1_1.safetensors (requires HF token + license acceptance)"
	@echo "    • hunyuanvideo_t2v_720p_gguf_q4_k_m_pack"
	@echo "    • wan2.2_5b_fp16_pack"
	@echo "    • mochi_preview_fp8_pack"
	@echo "════════════════════════════════════════════════════════════════════════════════"

download-health: ## Check health of model download URLs
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Checking Model Download URL Health"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@python scripts/check_model_health.py

download-verify: ## Verify downloaded models and show disk usage
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Model Verification"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@if [ -d "models/comfy" ]; then \
		echo "ComfyUI Models:"; \
		echo ""; \
		echo "  Checkpoints (image generation):"; \
		ls -lh models/comfy/checkpoints/*.safetensors models/comfy/checkpoints/*.ckpt 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  UNET Models (FLUX/Video):"; \
		ls -lh models/comfy/unet/*.safetensors models/comfy/unet/*.gguf 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Diffusion Models (Video):"; \
		ls -lh models/comfy/diffusion_models/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  CLIP Encoders:"; \
		ls -lh models/comfy/clip/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  VAE Models:"; \
		ls -lh models/comfy/vae/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  ControlNet (edit guidance):"; \
		ls -lh models/comfy/controlnet/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  SAM Models (segmentation):"; \
		ls -lh models/comfy/sams/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Rembg Models (background removal):"; \
		ls -lh models/comfy/rembg/*.onnx 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Upscale Models (image enhancement):"; \
		ls -lh models/comfy/upscale_models/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  GFPGAN Models (face restoration):"; \
		ls -lh models/comfy/gfpgan/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Total ComfyUI storage: $$(du -sh models/comfy 2>/dev/null | cut -f1)"; \
		echo ""; \
	else \
		echo "❌ models/comfy directory not found"; \
		echo "   Run: make download-recommended"; \
		echo ""; \
	fi
	@if [ -d "models/llm" ]; then \
		echo "LLM Models:"; \
		ls -lh models/llm/ 2>/dev/null | tail -n +2 || echo "  (managed by Ollama/vLLM)"; \
		echo ""; \
	fi
	@echo "════════════════════════════════════════════════════════════════════════════════"

clean: ## Remove local artifacts
	rm -rf frontend/node_modules frontend/dist
	rm -rf backend/data/*.db || true

health-check: ## Comprehensive health check of all services
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  HomePilot Health Check"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Checking all services..."
	@echo ""
	@echo "1. Backend API"
	@curl -fsS http://localhost:8000/health 2>/dev/null | jq '.' || echo "❌ Backend not running"
	@echo ""
	@echo "2. Detailed Service Health"
	@curl -fsS http://localhost:8000/health/detailed 2>/dev/null | jq '.' || echo "❌ Backend not running"
	@echo ""
	@echo "3. Direct Service Checks:"
	@echo ""
	@echo "   Ollama:"
	@curl -fsS http://localhost:11434 2>/dev/null && echo "   ✅ Ollama is running" || echo "   ❌ Ollama not reachable at localhost:11434"
	@echo ""
	@echo "   ComfyUI:"
	@curl -fsS http://localhost:8188/system_stats 2>/dev/null >/dev/null && echo "   ✅ ComfyUI is running" || echo "   ❌ ComfyUI not reachable at localhost:8188"
	@echo ""
	@echo "   vLLM:"
	@curl -fsS http://localhost:8001/v1/models 2>/dev/null >/dev/null && echo "   ✅ vLLM is running" || echo "   ❌ vLLM not reachable at localhost:8001"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"

# --- Backward Compatibility Aliases -------------------------------------------

local: start  ## Alias for 'make start' (backward compatibility)

local-backend: start-backend  ## Alias for 'make start-backend' (backward compatibility)

local-frontend: start-frontend  ## Alias for 'make start-frontend' (backward compatibility)
