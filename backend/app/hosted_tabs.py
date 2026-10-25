"""What each sidebar tab can do on a HomePilot, and what a linked Hugging Face account turns on.

The hosted Space (edition ``web``) has no GPU and no ComfyUI. Linking a Hugging Face
account bills Inference Providers to that account. That account then runs chat, vision,
new images, video, instruction edits, storyboard frames, scene pictures, and faces.
Brush masks, outfit lock, LoRAs, and the Teams tool servers stay on a computer with a GPU.
"""
from __future__ import annotations

from typing import Any, Dict, List

# unlocked_by:
#   huggingface — a linked account (or, on the web edition, the Space token) runs this
#   space       — the Space's own small model runs this without an account
#   local-gpu   — ComfyUI / a local model install; a token cannot turn it on
#   builtin     — HomePilot itself (files, schedule); no extra engine

_TABS: List[Dict[str, str]] = [
    {"id": "chat", "label": "Chat", "unlocked_by": "huggingface",
     "works": "Answers with the linked account's chat models. If Hugging Face cannot answer, the Space's own small model does."},
    {"id": "voice", "label": "Voice", "unlocked_by": "space",
     "works": "Listens with the Space's speech model and answers with the same chat engine. Spoken replies need a voice model on that machine; linking an account does not add one."},
    {"id": "imagine", "label": "Imagine", "unlocked_by": "huggingface",
     "works": "Draws with the linked account's image models. Without ComfyUI every image goes there instead of asking you to install one."},
    {"id": "animate", "label": "Animate", "unlocked_by": "huggingface",
     "works": "Makes video with the linked account's video models, from text or from a picture."},
    {"id": "project", "label": "Project", "unlocked_by": "builtin",
     "works": "Projects and personas saved on this HomePilot. On the Space they live until the machine sleeps."},
    {"id": "interactive", "label": "Interactive", "unlocked_by": "huggingface",
     "works": "Plans a story with the chat engine. Each scene picture is drawn with the linked account when ComfyUI is absent."},
    {"id": "edit", "label": "Edit", "unlocked_by": "huggingface",
     "works": "Redraws the picture from your instruction with the linked account. A brush mask, outpaint, and background replace stay on a computer with a GPU."},
    {"id": "studio", "label": "Studio", "unlocked_by": "huggingface",
     "works": "Storyboard pictures are drawn with the linked account, the same way Imagine draws. A finished clip of one scene is Animate. ComfyUI shot graphs stay on a computer with a GPU."},
    {"id": "avatar", "label": "Avatar", "unlocked_by": "huggingface",
     "works": "Draws a face with the linked account. Locking that face onto outfits and a body stays on a computer with a GPU."},
    {"id": "models", "label": "Models", "unlocked_by": "huggingface",
     "works": "Chat, vision, image, video, and edit list the models the linked account can run. Upscale, LoRA, and add-ons download into ComfyUI and stay on a GPU computer."},
    {"id": "teams", "label": "Teams", "unlocked_by": "local-gpu",
     "works": "Team tools are local MCP servers. The Space image does not ship them, and a Hugging Face token does not start them."},
    {"id": "routines", "label": "Routines", "unlocked_by": "builtin",
     "works": "Schedules run on this HomePilot. A routine that draws or answers uses the same engines as Imagine and Chat."},
    {"id": "meetings", "label": "Meetings", "unlocked_by": "space",
     "works": "Transcription uses the Space's speech model. Summaries use the chat engine. A linked account does not add a meeting recorder."},
]


def tab_status(*, web: bool) -> List[Dict[str, Any]]:
    """One row per sidebar tab. On a local install the GPU tabs are the machine's own."""
    rows: List[Dict[str, Any]] = []
    for tab in _TABS:
        unlocked = tab["unlocked_by"]
        if not web and unlocked == "local-gpu":
            available = True
            needs_link = False
        elif unlocked in ("builtin", "space"):
            available = True
            needs_link = False
        elif unlocked == "huggingface":
            # On the Space these tabs run on the linked account (or the Space token).
            # A local install already runs them with Ollama and ComfyUI.
            available = True
            needs_link = web
        else:
            available = False
            needs_link = False
        rows.append({
            "id": tab["id"],
            "label": tab["label"],
            "unlocked_by": unlocked,
            "available": available,
            "needs_hugging_face": needs_link,
            "works": tab["works"],
        })
    return rows
