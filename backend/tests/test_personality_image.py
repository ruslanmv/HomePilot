"""Tests for personality-aware image prompt enrichment.

When a user says "generate a photo" during an active personality session,
the system should enrich the vague prompt with conversation context and
the personality's visual style — even when LLM prompt refinement is disabled.
"""
import pytest


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

def test_is_vague_imagine_prompt_vague_cases():
    """Bare command phrases should be detected as vague."""
    from app.orchestrator import _is_vague_imagine_prompt

    assert _is_vague_imagine_prompt("generate a photo") is True
    assert _is_vague_imagine_prompt("make an image") is True
    assert _is_vague_imagine_prompt("create art") is True
    assert _is_vague_imagine_prompt("imagine a picture") is True
    assert _is_vague_imagine_prompt("draw a pic") is True
    assert _is_vague_imagine_prompt("show me a photo") is True
    assert _is_vague_imagine_prompt("give me an image") is True
    assert _is_vague_imagine_prompt("Generate A Photo") is True  # case-insensitive


def test_is_vague_imagine_prompt_specific_cases():
    """Prompts with descriptive content should NOT be detected as vague."""
    from app.orchestrator import _is_vague_imagine_prompt

    assert _is_vague_imagine_prompt("generate a photo of a cat") is False
    assert _is_vague_imagine_prompt("imagine a sunset over mountains") is False
    assert _is_vague_imagine_prompt("a robot in space") is False
    assert _is_vague_imagine_prompt("create a picture of a dragon flying") is False
    assert _is_vague_imagine_prompt("beautiful landscape with rivers") is False


def test_enrich_from_personality_context_with_history(app):
    """Enrichment should use conversation history and personality style hint."""
    from app.orchestrator import _enrich_from_personality_context
    from app.personalities import registry as personality_registry
    from app.storage import add_message

    cid = "test-enrich-history"

    # Seed some conversation history
    add_message(cid, "user", "Hey! I love The Mandalorian, Baby Yoda is the best!")
    add_message(cid, "assistant", "YES! Grogu is everything. That little green bean changed Star Wars forever.")
    add_message(cid, "user", "generate a photo")

    agent = personality_registry.get("fan_service")
    assert agent is not None

    enriched = _enrich_from_personality_context("generate a photo", agent, cid)

    # Should NOT contain the bare command
    assert enriched != "generate a photo"
    # Should contain quality anchors
    assert "detailed" in enriched.lower() or "quality" in enriched.lower()
    # Should contain the personality's image style hint
    assert "intimate" in enriched.lower() or "sensual" in enriched.lower() or "boudoir" in enriched.lower()
    # Should reference conversation topics
    assert "Mandalorian" in enriched or "Grogu" in enriched or "scene" in enriched.lower()


def test_enrich_from_personality_context_no_history(app):
    """Enrichment without history should use personality label as fallback."""
    from app.orchestrator import _enrich_from_personality_context
    from app.personalities import registry as personality_registry

    cid = "test-enrich-no-history"
    agent = personality_registry.get("therapist")
    assert agent is not None

    enriched = _enrich_from_personality_context("make a picture", agent, cid)

    assert enriched != "make a picture"
    assert "detailed" in enriched.lower() or "quality" in enriched.lower()
    # Should reference the personality label as theme
    assert agent.label.lower() in enriched.lower() or "scene" in enriched.lower()


# ---------------------------------------------------------------------------
# Integration test: vague prompt via /chat endpoint with personality
# ---------------------------------------------------------------------------

def test_chat_imagine_vague_prompt_enriched_with_personality(client, mock_outbound):
    """A vague 'generate a photo' with active personality should enrich the prompt."""
    cid = "test-vague-personality-img"

    # 1. Seed the conversation so there's context to draw from
    r1 = client.post("/chat", json={
        "message": "Tell me about space exploration!",
        "conversation_id": cid,
        "mode": "voice",
        "personalityId": "storyteller",
        "provider": "ollama",
    })
    assert r1.status_code == 200

    # 2. Now request a vague image with personality active
    r2 = client.post("/chat", json={
        "message": "generate a photo",
        "conversation_id": cid,
        "mode": "imagine",
        "personalityId": "storyteller",
        "promptRefinement": False,  # Even with refinement OFF
        "provider": "ollama",
    })
    assert r2.status_code == 200
    data = r2.json()

    # The response should have media (images generated)
    # and the prompt should have been enriched (not bare "generate a photo")
    if data.get("media") and data["media"].get("final_prompt"):
        assert data["media"]["final_prompt"] != "generate a photo", \
            "Vague prompt should be enriched when personality is active"


def test_chat_imagine_specific_prompt_not_enriched(client, mock_outbound):
    """A specific prompt should pass through unchanged (not over-enriched)."""
    r = client.post("/chat", json={
        "message": "generate a photo of a beautiful sunset over the ocean",
        "conversation_id": "test-specific-prompt",
        "mode": "imagine",
        "personalityId": "fan_service",
        "promptRefinement": False,
        "provider": "ollama",
    })
    assert r.status_code == 200
    data = r.json()

    # With a specific prompt and refinement disabled, the prompt should pass through
    if data.get("media") and data["media"].get("final_prompt"):
        assert "sunset" in data["media"]["final_prompt"].lower(), \
            "Specific prompt content should be preserved"
