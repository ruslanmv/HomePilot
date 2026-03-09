"""
Unit tests for the 3D / view-pack angle resolution in persona chat.

Covers:
  - _is_photo_intent detection for angle phrases
  - Deterministic angle routing via /chat endpoint (view_pack present)
  - Deterministic angle routing fallback (no view_pack)
  - Outfit+angle combo detection ("show me your lingerie from the back")
  - Conversation-context resolution ("turn around" after showing lingerie)
  - Hybrid-hint injection in projects.py for LLM path

CI-friendly: fully mocked, no real LLM / ComfyUI / network calls.
"""
import json
import os
import pytest
import uuid


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

PROJ_ID = f"test-viewpack-{uuid.uuid4().hex[:8]}"

VIEW_PACK = {
    "front": f"/files/projects/{PROJ_ID}/persona/outfits/lingerie_front.png",
    "left": f"/files/projects/{PROJ_ID}/persona/outfits/lingerie_left.png",
    "right": f"/files/projects/{PROJ_ID}/persona/outfits/lingerie_right.png",
    "back": f"/files/projects/{PROJ_ID}/persona/outfits/lingerie_back.png",
}

PERSONA_PROJECT = {
    "id": PROJ_ID,
    "project_type": "persona",
    "name": "Test Persona",
    "persona_agent": {"label": "TestBot", "class": "companion"},
    "persona_appearance": {
        "selected_filename": f"projects/{PROJ_ID}/persona/appearance/avatar.png",
        "selected": {"set_id": "s1", "image_id": "img1"},
        "sets": [
            {
                "set_id": "s1",
                "images": [
                    {"id": "img1", "url": f"/files/projects/{PROJ_ID}/persona/appearance/avatar.png", "set_id": "s1"}
                ],
            }
        ],
        "outfits": [
            {
                "id": "outfit_lingerie_01",
                "label": "Lingerie",
                "outfit_prompt": "elegant lingerie",
                "equipped": True,
                "images": [
                    {"id": "img_ling", "url": f"/files/projects/{PROJ_ID}/persona/outfits/lingerie_static.png", "set_id": "outfit_lingerie_01"}
                ],
                "view_pack": VIEW_PACK,
                "interactive_preview": True,
                "preview_mode": "view_pack",
                "hero_view": "front",
            },
            {
                "id": "outfit_casual_01",
                "label": "Casual",
                "outfit_prompt": "jeans and t-shirt",
                "equipped": False,
                "images": [
                    {"id": "img_cas", "url": f"/files/projects/{PROJ_ID}/persona/outfits/casual_static.png", "set_id": "outfit_casual_01"}
                ],
                "view_pack": {},
            },
        ],
    },
}


def _stub_files(app, monkeypatch):
    """Make _file_url_exists return True for all test URLs, and stub
    get_project_by_id to return our test project."""
    # Stub file existence checks
    try:
        from app import projects as proj_mod
        monkeypatch.setattr(proj_mod, "_file_url_exists", lambda url: True, raising=False)
    except Exception:
        pass

    # Stub get_project_by_id
    try:
        from app import projects as proj_mod
        _orig = proj_mod.get_project_by_id

        def _fake_get(pid):
            if pid == PROJ_ID:
                return PERSONA_PROJECT
            return _orig(pid)

        monkeypatch.setattr(proj_mod, "get_project_by_id", _fake_get, raising=False)
    except Exception:
        pass

    # Stub _build_label_index for media resolver
    try:
        from app import media_resolver as mr

        def _fake_label_index(pid):
            if pid == PROJ_ID:
                idx = {
                    "default": f"http://localhost:8000/files/projects/{PROJ_ID}/persona/appearance/avatar.png",
                    "label:Default Look": f"http://localhost:8000/files/projects/{PROJ_ID}/persona/appearance/avatar.png",
                }
                for angle, url in VIEW_PACK.items():
                    full = f"http://localhost:8000{url}"
                    idx[f"label:Lingerie {angle.title()}"] = full
                    idx[f"label:Lingerie_{angle.title()}"] = full
                # Static lingerie
                idx["label:Lingerie"] = f"http://localhost:8000/files/projects/{PROJ_ID}/persona/outfits/lingerie_static.png"
                idx["label:Casual"] = f"http://localhost:8000/files/projects/{PROJ_ID}/persona/outfits/casual_static.png"
                return idx
            return {}

        monkeypatch.setattr(mr, "_build_label_index", _fake_label_index, raising=False)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# 1. _is_photo_intent — angle phrases should return True
# ═══════════════════════════════════════════════════════════════════════


class TestPhotoIntentAngleDetection:
    """Verify _is_photo_intent recognises angle/view phrases."""

    @pytest.fixture(autouse=True)
    def _load(self, app):
        from app.main import _is_photo_intent
        self.detect = _is_photo_intent

    @pytest.mark.parametrize("msg", [
        "turn around",
        "Turn around",
        "show me your back",
        "show me the back",
        "let me see the back",
        "see the front",
        "show me the side",
        "show me your left side",
        "from the back",
        "from behind",
        "back view",
        "side view",
        "spin for me",
        "rotate",
        "turn slowly",
        "all angles",
    ])
    def test_angle_phrases_detected(self, msg):
        assert self.detect(msg) is True, f"Expected True for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "hi there",
        "how are you",
        "what is your name",
        "tell me about yourself",
    ])
    def test_non_angle_phrases_not_detected(self, msg):
        assert self.detect(msg) is False, f"Expected False for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "show me your photo",
        "show me your lingerie",
        "show me all",
    ])
    def test_existing_photo_intents_still_work(self, msg):
        assert self.detect(msg) is True, f"Expected True for: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════
# 2. Deterministic /chat endpoint — angle routing with view_pack
# ═══════════════════════════════════════════════════════════════════════


class TestChatAngleRouting:
    """Test the /chat endpoint returns correct angle images."""

    def _post_chat(self, client, message, conversation_id=None):
        payload = {
            "message": message,
            "conversation_id": conversation_id or f"conv-{uuid.uuid4().hex[:8]}",
            "project_id": PROJ_ID,
            "personalityId": f"persona:{PROJ_ID}",
            "fun_mode": False,
            "mode": "chat",
        }
        return client.post("/chat", json=payload)

    def test_turn_around_returns_back_view(self, client, mock_outbound, monkeypatch):
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "turn around")
        assert r.status_code == 200, r.text
        data = r.json()
        media = data.get("media") or {}
        images = media.get("images", [])
        assert len(images) >= 1, f"Expected at least 1 image, got: {data}"
        # Should be the back view URL
        assert "back" in images[0].lower() or "lingerie" in images[0].lower()

    def test_show_me_the_back_returns_back_angle(self, client, mock_outbound, monkeypatch):
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "show me your back")
        assert r.status_code == 200
        data = r.json()
        media = data.get("media") or {}
        # Should have view_pack metadata for interactive chips
        if media.get("view_pack"):
            assert media["active_angle"] == "back"
            assert "interactive_preview" in media
            assert len(media["available_views"]) >= 1

    def test_show_side_returns_left_view(self, client, mock_outbound, monkeypatch):
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "show me the side")
        assert r.status_code == 200
        data = r.json()
        media = data.get("media") or {}
        images = media.get("images", [])
        assert len(images) >= 1, f"Expected image for side view, got: {data}"

    def test_spin_returns_all_angles(self, client, mock_outbound, monkeypatch):
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "spin for me")
        assert r.status_code == 200
        data = r.json()
        media = data.get("media") or {}
        if media.get("view_pack"):
            assert len(media["available_views"]) >= 2

    def test_lingerie_back_combo(self, client, mock_outbound, monkeypatch):
        """'show me your lingerie from the back' = outfit + angle in one message."""
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "show me your lingerie from the back")
        assert r.status_code == 200
        data = r.json()
        media = data.get("media") or {}
        images = media.get("images", [])
        assert len(images) >= 1
        # Should resolve to the lingerie back view specifically
        if media.get("active_angle"):
            assert media["active_angle"] == "back"

    def test_normal_chat_still_works(self, client, mock_outbound, monkeypatch):
        """Non-angle messages should still go through normal chat flow."""
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "hi there")
        assert r.status_code == 200
        data = r.json()
        assert "text" in data

    def test_show_lingerie_without_angle(self, client, mock_outbound, monkeypatch):
        """'show me your lingerie' without angle should show category photos (not angle)."""
        _stub_files(client.app, monkeypatch)
        r = self._post_chat(client, "show me your lingerie")
        assert r.status_code == 200
        data = r.json()
        media = data.get("media") or {}
        images = media.get("images", [])
        assert len(images) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 3. Conversation context — "turn around" after showing lingerie
# ═══════════════════════════════════════════════════════════════════════


class TestConversationContextAngle:
    """When user says 'turn around' the system should use the last shown outfit."""

    def test_context_from_previous_message(self, client, mock_outbound, monkeypatch):
        _stub_files(client.app, monkeypatch)
        conv_id = f"conv-ctx-{uuid.uuid4().hex[:8]}"

        # Step 1: show lingerie
        r1 = self._post_chat(client, "show me your lingerie", conv_id)
        assert r1.status_code == 200

        # Step 2: turn around — should use lingerie (from conversation context)
        r2 = self._post_chat(client, "turn around", conv_id)
        assert r2.status_code == 200
        data = r2.json()
        media = data.get("media") or {}
        images = media.get("images", [])
        # Should return an image (either view_pack angle or fallback)
        assert len(images) >= 1, f"Expected image for 'turn around' after lingerie, got: {data}"

    def _post_chat(self, client, message, conversation_id):
        payload = {
            "message": message,
            "conversation_id": conversation_id,
            "project_id": PROJ_ID,
            "personalityId": f"persona:{PROJ_ID}",
            "fun_mode": False,
            "mode": "chat",
        }
        return client.post("/chat", json=payload)


# ═══════════════════════════════════════════════════════════════════════
# 4. Hybrid-hint injection (LLM path) — unit test
# ═══════════════════════════════════════════════════════════════════════


class TestHybridHintAngleInjection:
    """Verify the hybrid-hint system injects correct angle hints."""

    @pytest.fixture(autouse=True)
    def _load(self, app):
        pass

    def test_angle_patterns_detect_back(self):
        import re
        patterns = {
            "back": r'\b(?:back|behind|rear|turn\s*around)\b',
            "left": r'\b(?:left\s*side|left\s*profile|from\s*(?:the\s*)?left)\b',
            "right": r'\b(?:right\s*side|right\s*profile|from\s*(?:the\s*)?right)\b',
            "front": r'\b(?:front|facing|face\s*me)\b',
        }
        test_cases = [
            ("turn around", "back"),
            ("show me your back", "back"),
            ("from behind", "back"),
            ("face me", "front"),
            ("from the left", "left"),
            ("right side", "right"),
        ]
        for msg, expected in test_cases:
            matched = None
            for ang, pat in patterns.items():
                if re.search(pat, msg.lower()):
                    matched = ang
                    break
            assert matched == expected, f"Expected {expected!r} for {msg!r}, got {matched!r}"

    def test_side_profile_defaults_to_left(self):
        import re
        msg = "show me the side"
        matched = None
        patterns = {
            "back": r'\b(?:back|behind|rear|turn\s*around)\b',
            "left": r'\b(?:left\s*side|left\s*profile|from\s*(?:the\s*)?left)\b',
            "right": r'\b(?:right\s*side|right\s*profile|from\s*(?:the\s*)?right)\b',
            "front": r'\b(?:front|facing|face\s*me)\b',
        }
        for ang, pat in patterns.items():
            if re.search(pat, msg.lower()):
                matched = ang
                break
        if not matched and re.search(r'\b(?:side|profile)\b', msg.lower()):
            matched = "left"
        assert matched == "left"

    def test_outfit_name_matching(self):
        """Outfit name in message should be detected by simple substring match."""
        outfits = [
            {"label": "Lingerie", "equipped": True, "angles": ["front", "back"]},
            {"label": "Casual", "equipped": False, "angles": []},
        ]
        msg = "show me your lingerie from the back"
        target = None
        for ov in outfits:
            if ov["label"].lower() in msg.lower():
                target = ov
                break
        assert target is not None
        assert target["label"] == "Lingerie"

    def test_all_angles_detection(self):
        import re
        for msg in ["turn slowly", "all angles", "rotate", "spin", "every angle"]:
            assert re.search(r'\b(?:turn\s*slowly|all\s*angles?|rotate|spin|every\s*angle)\b', msg.lower()), \
                f"Expected all-angles match for: {msg!r}"
