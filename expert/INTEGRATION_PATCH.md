# Expert Module — Integration Patch Guide
# =========================================
# ONLY 4 small additive changes needed in existing files.
# Nothing is removed or modified — purely additive.
#
# ─────────────────────────────────────────────────────────────────────────────
# 1. backend/app/main.py  — add 2 lines
# ─────────────────────────────────────────────────────────────────────────────
#
# Find this block (around line 70, after the other router imports):
#
#   from .capabilities import router as capabilities_router
#   ...
#   app.include_router(capabilities_router)
#
# Add immediately after:
#
#   from .expert import router as expert_router          # <-- ADD THIS
#   app.include_router(expert_router)                    # <-- ADD THIS
#
# That's it for the backend. The expert module is now live at /v1/expert/*.
#
#
# ─────────────────────────────────────────────────────────────────────────────
# 2. frontend/src/ui/App.tsx — add 3 lines
# ─────────────────────────────────────────────────────────────────────────────
#
# A) Find the import block at the top (where ImagineView, StudioView etc. are):
#
#   import ImagineView from './Imagine'
#   import StudioView from './Studio'
#
# Add:
#
#   import ExpertView from './Expert'                    # <-- ADD THIS
#
#
# B) Find the Mode type definition (line ~275):
#
#   type Mode = 'chat' | 'voice' | ... | 'teams'
#
# Add 'expert' to the union:
#
#   type Mode = 'chat' | 'voice' | ... | 'teams' | 'expert'   # <-- ADD 'expert'
#
#
# C) Find the NavItem list in the sidebar (line ~1254, near 'Studio' nav item):
#
#   <NavItem icon={Server} label="Models" ... onClick={() => setMode('models')} ... />
#
# Add after it:
#
#   <NavItem icon={Brain} label="Expert" active={mode === 'expert'} onClick={() => setMode('expert')} collapsed={collapsed} />
#
# (Brain is already imported from lucide-react in App.tsx)
#
#
# D) Find the render switch block (line ~5255, near mode === 'models' check):
#
#   ) : mode === 'models' ? (
#     <ModelsView ... />
#   ) : mode === 'studio' ? (
#
# Add before the 'studio' check:
#
#   ) : mode === 'expert' ? (
#     <ExpertView />                                     # <-- ADD THIS BLOCK
#   ) : mode === 'studio' ? (
#
#
# ─────────────────────────────────────────────────────────────────────────────
# 3. .env.example — add Expert section
# ─────────────────────────────────────────────────────────────────────────────
#
# Append to .env.example:

# ── Expert Module ────────────────────────────────────────────────────────────
# xAI Grok (https://console.x.ai)
GROK_API_KEY=
GROK_MODEL=grok-3
GROK_BASE_URL=https://api.x.ai/v1

# Groq — free tier, ultra fast Llama 3.3 70B (https://console.groq.com)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_BASE_URL=https://api.groq.com/openai/v1

# Google Gemini (https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# Local Ollama — override if Ollama runs on a different host/port
EXPERT_OLLAMA_URL=http://localhost:11434
EXPERT_LOCAL_MODEL=deepseek-r1:32b
EXPERT_LOCAL_FAST_MODEL=llama3.2:3b

# Routing thresholds (0-10 complexity scale)
EXPERT_LOCAL_THRESHOLD=3
EXPERT_GROQ_THRESHOLD=6

# Debug: set to 1 to include raw provider response in API replies
EXPERT_DEBUG=0
#
#
# ─────────────────────────────────────────────────────────────────────────────
# 4. Copy new files into the project
# ─────────────────────────────────────────────────────────────────────────────
#
#   cp -r expert_module/backend/app/expert  backend/app/expert/
#   cp expert_module/frontend/src/expertApi.ts  frontend/src/expertApi.ts
#   cp expert_module/frontend/src/ui/Expert.tsx  frontend/src/ui/Expert.tsx
#
#
# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION  — after patching, run:
# ─────────────────────────────────────────────────────────────────────────────
#
#   # Backend: check the new endpoints appear
#   curl http://localhost:8000/v1/expert/info
#
#   # Expected output includes:
#   # {"available_providers":["local"],"default_provider":"auto",...}
#
#   # With Groq key set:
#   # {"available_providers":["local","groq"],...}
#
#   # Test routing debug endpoint:
#   curl -X POST "http://localhost:8000/v1/expert/route?query=hi"
#   # → {"complexity_score":0,"selected_provider":"local",...}
#
#   curl -X POST "http://localhost:8000/v1/expert/route?query=analyze+the+architectural+tradeoffs+of+distributed+systems"
#   # → {"complexity_score":7,"selected_provider":"grok",...}  (if GROK_API_KEY set)
