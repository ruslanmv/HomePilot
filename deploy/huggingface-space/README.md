---
title: HomePilot
emoji: 🏠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Private AI assistant with persistent personas
hf_oauth: true
hf_oauth_scopes:
  - inference-api
---

# HomePilot — Hugging Face Space

Your private AI assistant with persistent personas, powered by Ollama.
This Space runs HomePilot with a built-in LLM runtime — no external
API keys required.

## Pre-installed Personas (Chata Edition)

This Space comes with **14 Chata social personas** ready to use:

**Starter Pack**: Lunalite Greeter, Chillbro Regular, Curiosa Driver, Hypekid Reactions

**Retro Pack**: Volt Buddy, Ronin Zero, Rival Kaiju, Glitchbyte, Questkid 99,
Sigma Sage, Wildcard Loki, Oldroot Oracle, Morphling X, Nova Void

## Endpoints

| Check | URL |
|---|---|
| App | `/` |
| Health | `/health` |
| API Docs | `/docs` |
| Persona Gallery | `/community/registry` |
| Chat API | `/v1/chat/completions` |

## Larger chat models (optional)

The Space answers with the local model already running in this session. No
account is required.

To use a larger model, open **Models → Chat** and choose **Hugging Face (your
account)**. The same choice is in **Settings → Chat provider**. Sign in with
Hugging Face — the access token stays on the server — then choose **Use for
chat**. Inference Providers bill that account, whether that is the free monthly
credits or a Pro plan. Image, video, and multimodal keep their own providers.

If you stay signed out, or the account cannot run a request, the reply comes
from the local model and a short note says so. While chat is still on Ollama,
the Space suggests signing in. It does not require an account.

Sign-in starts after this metadata is on the Space and it rebuilds. Until
then, chat keeps using the local model.

## Environment (HF Secrets)

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | LLM model (pulled on first start) |
| `API_KEY` | _(empty)_ | Protect the API |
| `OLLABRIDGE_CLOUD_URL` | _(empty)_ | Link to OllaBridge Cloud |
