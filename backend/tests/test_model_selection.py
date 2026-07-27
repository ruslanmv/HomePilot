"""Tests for Ollama chat/vision model selection.

Regression: with no model configured, HomePilot auto-picked the FIRST Ollama
model. When that was a vision-only model (e.g. moondream:latest) a persona's
text turn returned empty content and the agent replied "I couldn't parse the
agent response." Text turns must land on a text-chat model; the user's
configured Chat Model must win; vision turns still get a vision model.
"""
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import llm  # noqa: E402

# The user's real list — moondream is first, which the old code picked.
TAGS = [
    "moondream:latest", "llama3.2:3b", "llama3.2:1b", "gemma3:4b",
    "huihui_ai/qwen3-abliterated:4b", "qwen2.5:0.5b", "deepseek-r1:latest",
    "llama3:8b", "gemma:2b", "nomic-embed-text",
]


def test_auto_pick_avoids_vision_only_model():
    picked = llm.pick_chat_model(TAGS)
    assert picked != "moondream:latest"
    assert llm.is_text_chat_model(picked)


def test_configured_chat_model_wins():
    assert llm.pick_chat_model(TAGS, "huihui_ai/qwen3-abliterated:4b") == "huihui_ai/qwen3-abliterated:4b"


def test_auto_pick_prefers_priority_text_model():
    # llama3.2:3b is top of the priority list and present.
    assert llm.pick_chat_model(TAGS) == "llama3.2:3b"


def test_vision_pick_returns_a_vision_model():
    assert llm.pick_vision_model(TAGS) == "moondream:latest"


def test_is_text_chat_model_classification():
    assert llm.is_text_chat_model("huihui_ai/qwen3-abliterated:4b") is True
    assert llm.is_text_chat_model("llama3:8b") is True
    assert llm.is_text_chat_model("moondream:latest") is False
    assert llm.is_text_chat_model("llava:7b") is False
    assert llm.is_text_chat_model("nomic-embed-text") is False
    assert llm.is_text_chat_model("") is False


def test_only_vision_and_embed_available_falls_back_to_first():
    # Degenerate case: nothing chat-capable — still return something usable.
    only = ["moondream:latest", "nomic-embed-text"]
    assert llm.pick_chat_model(only) == "moondream:latest"


def test_empty_list_returns_empty():
    assert llm.pick_chat_model([]) == ""
    assert llm.pick_vision_model([]) == ""
