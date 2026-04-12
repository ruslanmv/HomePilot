---
title: HomePilot Installer
emoji: 🏠
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 5.29.0
app_file: app.py
pinned: true
short_description: Install HomePilot into your own HF Space
---

# HomePilot Installer

Install your own private HomePilot AI assistant on Hugging Face Spaces.

## What it does

1. Authenticates with your HF token
2. Creates a new private Docker Space in your account
3. Pushes the HomePilot template (backend + frontend + Ollama + 14 Chata personas)
4. Guides you to enable GPU hardware

## Requirements

- A [Hugging Face account](https://huggingface.co/join)
- A [write-access token](https://huggingface.co/settings/tokens)
- (Optional) GPU hardware on the target Space for better performance

## Pre-installed content

- **14 Chata social personas** (Starter + Retro packs)
- **Ollama** with qwen2.5:1.5b (auto-pulled on first start)
- **HomePilot** full-stack (FastAPI backend + React frontend)
