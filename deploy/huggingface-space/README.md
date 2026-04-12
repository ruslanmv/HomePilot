---
title: HomePilot
emoji: 🏠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Private AI assistant with persistent personas
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

## Environment (HF Secrets)

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | LLM model (pulled on first start) |
| `API_KEY` | _(empty)_ | Protect the API |
| `OLLABRIDGE_CLOUD_URL` | _(empty)_ | Link to OllaBridge Cloud |
