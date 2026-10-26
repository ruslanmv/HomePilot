"""
Connectors — accounts on other services that HomePilot can use on the user's behalf.

Additive: a connector is linked in Settings → Connectors, its secret stays on the server
(``store.py``), and the parts of HomePilot that use it (chat, vision, images, video) look it up
for the user making the request (``context.py``). Nothing changes until one is connected.

Connectors so far:
  * ``huggingface`` — Inference Providers on the user's Hugging Face account: chat, multimodal,
    text-to-image and text-to-video models, picked in Models → provider "Hugging Face".

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
]


def catalog_entry(connector_id: str) -> Dict[str, Any] | None:
    return next((c for c in CATALOG if c["id"] == connector_id), None)
