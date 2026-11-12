"""
Connectors — accounts on other services that HomePilot can use on the user's behalf.

Additive: a connector is linked in Settings → Connectors, its secret stays on the server
(``store.py``), and the parts of HomePilot that use it (chat, vision, images, video) look it up
for the user making the request (``context.py``). Nothing changes until one is connected.

Connectors so far:
  * ``huggingface`` — Inference Providers on the user's Hugging Face account: chat, multimodal,
    text-to-image and text-to-video models, picked in Models → provider "Hugging Face".

  * ``gitpilot`` — coding: GitPilot plans a change, applies it on a branch and opens a pull
    request. Agent chats get ``code.*`` tools; every change waits for the user's approval.

Only connectors that work are listed. A new one is a module here plus an entry in CATALOG.
"""
from __future__ import annotations

from typing import Any, Dict, List

CATALOG: List[Dict[str, Any]] = [
    {
        "id": "huggingface",
        "name": "Hugging Face",
        "description": "Chat, vision, image and video models on your Hugging Face account.",
        "auth": "token",
        "token_url": "https://huggingface.co/settings/tokens/new?tokenType=fineGrained",
        "token_hint": "A token with the “Make calls to Inference Providers” permission.",
        "grants": [
            "See your Hugging Face username and avatar",
            "Run chat, vision, image and video models with Inference Providers",
        ],
        "billing": "Usage is billed to your Hugging Face account (free monthly credits, or Pro).",
        "featured": True,
    },
    {
        "id": "gitpilot",
        "name": "GitPilot",
        "description": "Plan code changes, apply them on a branch and open pull requests — from chat.",
        "auth": "token",
        # This connector also needs to know where GitPilot runs.
        "endpoint": True,
        "endpoint_label": "GitPilot address",
        "endpoint_placeholder": "http://localhost:8000",
        "token_optional": True,
        "token_provider": "GitHub",
        "token_placeholder": "ghp_…",
        "disconnect_note": "HomePilot forgets the address and the token on this server, and chats "
                           "lose the coding tools. Nothing changes in your repositories.",
        "token_url": "https://github.com/settings/tokens/new?scopes=repo&description=HomePilot%20%2B%20GitPilot",
        "token_hint": "A GitHub token that can read and write the repositories you want to work on. "
                      "Leave it empty if your GitPilot already signs in to GitHub.",
        "grants": [
            "See your GitHub username and avatar",
            "List your repositories and read their code to make a plan",
            "Write changes to a new branch and open a pull request — only after you approve each one",
        ],
        "billing": "GitPilot runs on your own installation and uses the AI provider configured there.",
        "featured": False,
    },
]


def catalog_entry(connector_id: str) -> Dict[str, Any] | None:
    return next((c for c in CATALOG if c["id"] == connector_id), None)
