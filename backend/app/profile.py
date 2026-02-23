"""
User Profile API — additive module (v1).

Provides /v1/profile endpoints for storing user identity, preferences,
companion-mode settings, content-preference metadata, and a secrets vault.

IMPORTANT: NSFW on/off remains a global setting in the existing SettingsPanel.
Profile only stores *preference metadata* (default_spicy_strength, allowed/blocked
content tags) that are consumed when global NSFW mode is already ON.

Storage: local JSON files next to the DB (profile.json, profile_secrets.json).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import require_api_key
from .config import DATA_DIR, SQLITE_PATH

router = APIRouter(prefix="/v1/profile", tags=["profile"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_root() -> Path:
    """Resolve the data root directory (same location as DB / uploads)."""
    if DATA_DIR:
        return Path(DATA_DIR)
    return Path(SQLITE_PATH).parent


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _mask_secret(value: str) -> str:
    v = value or ""
    if len(v) <= 6:
        return "••••••"
    return f"{v[:2]}••••••{v[-2:]}"


def _norm_list(xs: List[str]) -> List[str]:
    return sorted({(x or "").strip() for x in (xs or []) if (x or "").strip()})


PROFILE_FILE = "profile.json"
SECRETS_FILE = "profile_secrets.json"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    # Personal / contact
    display_name: str = ""
    email: str = ""
    linkedin: str = ""
    website: str = ""
    company: str = ""
    role: str = ""
    locale: str = "en"
    timezone: str = ""
    bio: str = ""
    birthday: str = ""  # ISO date string e.g. "1990-05-15" (YYYY-MM-DD)

    # Preferences (for future recommendations)
    personalization_enabled: bool = True
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    favorite_persona_tags: list[str] = Field(default_factory=list)
    preferred_tone: str = "neutral"  # neutral | friendly | formal

    allow_usage_for_recommendations: bool = True

    # Companion / relationship style (user-controlled)
    companion_mode_enabled: bool = False
    affection_level: str = "friendly"  # friendly | affectionate | romantic
    preferred_name: str = ""
    preferred_pronouns: str = ""
    preferred_terms_of_endearment: list[str] = Field(default_factory=list)

    # Boundaries & consent
    hard_boundaries: list[str] = Field(default_factory=list)
    sensitive_topics: list[str] = Field(default_factory=list)
    consent_notes: str = ""

    # Content preferences (IMPORTANT):
    # NSFW ON/OFF is controlled globally by SettingsPanel nsfwMode.
    # Profile stores only preference metadata.
    default_spicy_strength: float = Field(0.30, ge=0.0, le=1.0)
    allowed_content_tags: list[str] = Field(default_factory=list)
    blocked_content_tags: list[str] = Field(default_factory=list)


class SecretUpsert(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    value: str = Field(..., min_length=1, max_length=4096)
    description: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", dependencies=[Depends(require_api_key)])
def get_profile() -> Dict[str, Any]:
    root = _data_root()
    path = root / PROFILE_FILE
    data = _read_json(path, default=UserProfile().model_dump())
    return {"ok": True, "profile": data}


@router.put("", dependencies=[Depends(require_api_key)])
def put_profile(profile: UserProfile) -> Dict[str, Any]:
    p = profile.model_dump()

    # Normalize list fields
    for k in (
        "likes",
        "dislikes",
        "favorite_persona_tags",
        "preferred_terms_of_endearment",
        "hard_boundaries",
        "sensitive_topics",
        "allowed_content_tags",
        "blocked_content_tags",
    ):
        p[k] = _norm_list(p.get(k, []))

    # Normalize enums
    if p.get("affection_level") not in ("friendly", "affectionate", "romantic"):
        p["affection_level"] = "friendly"
    if p.get("preferred_tone") not in ("neutral", "friendly", "formal"):
        p["preferred_tone"] = "neutral"

    # Clamp spicy strength (Pydantic already enforces, but keep defensive)
    try:
        s = float(p.get("default_spicy_strength", 0.30))
    except Exception:
        s = 0.30
    p["default_spicy_strength"] = max(0.0, min(1.0, s))

    root = _data_root()
    path = root / PROFILE_FILE
    _atomic_write_json(path, p)
    return {"ok": True}


@router.get("/secrets", dependencies=[Depends(require_api_key)])
def list_secrets() -> Dict[str, Any]:
    """Returns only masked values to avoid accidental leakage in the UI."""
    root = _data_root()
    path = root / SECRETS_FILE
    secrets = _read_json(path, default={})

    items = []
    for k, v in secrets.items():
        items.append(
            {
                "key": k,
                "masked": _mask_secret(v.get("value", "")),
                "description": v.get("description", ""),
            }
        )
    items.sort(key=lambda x: x["key"].lower())
    return {"ok": True, "secrets": items}


@router.put("/secrets", dependencies=[Depends(require_api_key)])
def upsert_secret(body: SecretUpsert) -> Dict[str, Any]:
    root = _data_root()
    path = root / SECRETS_FILE
    secrets = _read_json(path, default={})

    key = body.key.strip()
    if not key.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid secret key format")

    secrets[key] = {
        "value": body.value,
        "description": (body.description or "").strip(),
    }
    _atomic_write_json(path, secrets)
    return {"ok": True}


@router.delete("/secrets/{key}", dependencies=[Depends(require_api_key)])
def delete_secret(key: str) -> Dict[str, Any]:
    root = _data_root()
    path = root / SECRETS_FILE
    secrets = _read_json(path, default={})

    if key in secrets:
        secrets.pop(key, None)
        _atomic_write_json(path, secrets)
    return {"ok": True}
