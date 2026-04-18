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

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException
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

    # ──────────────────────────────────────────────────────────────────
    # Communication (reachability) — ADDITIVE, non-destructive
    # ──────────────────────────────────────────────────────────────────
    # Where the AI can contact the user. This block is intentionally
    # OPTIONAL with safe defaults so existing on-disk profiles continue
    # to load unchanged and existing PUT payloads without this field
    # are still accepted. The AI never auto-reads these; access is
    # gated per-field by ``field_access_policy`` (see below), and the
    # overall outbound kill-switch defaults to OFF.
    #
    # Design doc: "Communication — additive, non-destructive design"
    # in this session's summary.
    communication: "CommunicationInfo" = Field(default_factory=lambda: CommunicationInfo())

    # Per-field access policy for AI prompt-injection + tool-call reads.
    # Keys are dotted paths like ``profile.birthday`` or
    # ``communication.phone_e164``. Values: "always" | "on_demand" |
    # "sensitive". Missing keys are treated as "on_demand" (safe
    # middle). Seeded with sensible defaults on first read — see
    # ``_seed_field_access_policy`` below.
    field_access_policy: dict[str, str] = Field(default_factory=dict)


class CommunicationInfo(BaseModel):
    """User reachability — phone, WhatsApp, Telegram, and preferences.

    Not secrets (those live in the vault). These are the display-level
    contact points the persona uses when it decides to reach out.
    Every field has an empty-string / "none" default so the whole
    block can be absent without breaking anything.
    """
    phone_e164: str = ""                      # "+14155551212"
    whatsapp_e164: str = ""                   # usually same as phone
    telegram_username: str = ""               # stored without leading "@"
    preferred_contact_channel: str = "none"   # none | phone | whatsapp | telegram
    preferred_call_channel: str = "none"      # none | phone | voip_app_did
    allow_ai_outbound: bool = False           # master kill-switch

    @classmethod
    def _normalize_e164(cls, value: str) -> str:
        """Strip whitespace, dashes, parens; keep leading + if present.
        Doesn't attempt full E.164 validation — provider tools reject
        bad numbers on first use, which is the right surface."""
        v = (value or "").strip()
        if not v:
            return ""
        plus = v.startswith("+")
        digits = "".join(c for c in v if c.isdigit())
        return ("+" if plus else "") + digits


# Rebuild the forward reference so pydantic wires CommunicationInfo into
# UserProfile. Cheap at import time; required because CommunicationInfo
# is declared after UserProfile to keep the additive block visually
# together without forcing a top-of-file reorg.
UserProfile.model_rebuild()


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
    # Back-fill the additive ``communication`` block for profiles that
    # predate it — pydantic default has handled new installs; this
    # handles pre-existing JSON files so the frontend always sees the
    # expected shape.
    if "communication" not in data or not isinstance(data.get("communication"), dict):
        data["communication"] = CommunicationInfo().model_dump()
    # Seed the per-field access policy without clobbering user overrides.
    data["field_access_policy"] = _seed_field_access_policy(
        data.get("field_access_policy") or {}
    )
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

    # Communication — normalise phone-shaped fields + clamp enum values.
    # Defensive about the shape because old clients may send the field
    # as null or missing entirely; in both cases the pydantic default
    # already populated it, but a buggy client PUT could still get here
    # with a dict that's missing keys.
    comm = p.get("communication") or {}
    if not isinstance(comm, dict):
        comm = {}
    comm["phone_e164"] = CommunicationInfo._normalize_e164(str(comm.get("phone_e164", "")))
    comm["whatsapp_e164"] = CommunicationInfo._normalize_e164(str(comm.get("whatsapp_e164", "")))
    tg = str(comm.get("telegram_username", "")).strip().lstrip("@")
    comm["telegram_username"] = tg
    if comm.get("preferred_contact_channel") not in ("none", "phone", "whatsapp", "telegram"):
        comm["preferred_contact_channel"] = "none"
    if comm.get("preferred_call_channel") not in ("none", "phone", "voip_app_did"):
        comm["preferred_call_channel"] = "none"
    comm["allow_ai_outbound"] = bool(comm.get("allow_ai_outbound", False))
    p["communication"] = comm

    # Field-access policy — clamp each value to the 3 allowed tiers.
    # Unknown tiers collapse to "on_demand" (safe middle).
    fap = p.get("field_access_policy") or {}
    if not isinstance(fap, dict):
        fap = {}
    _allowed_tiers = {"always", "on_demand", "sensitive"}
    p["field_access_policy"] = {
        str(k): (v if v in _allowed_tiers else "on_demand")
        for k, v in fap.items()
    }

    root = _data_root()
    path = root / PROFILE_FILE
    _atomic_write_json(path, p)
    return {"ok": True}


# Default access policy applied when a field has no explicit entry.
# See design doc § "How personas consume it" — most identity fields
# are "on_demand" (persona asks when it needs them); reachability
# data starts "sensitive" so the persona has to prompt the user
# before using a phone number / WhatsApp / Telegram handle.
_DEFAULT_FIELD_ACCESS_POLICY: Dict[str, str] = {
    # Profile — always safe to inject in every prompt
    "profile.display_name": "always",
    "profile.locale": "always",
    "profile.timezone": "always",
    # Profile — on demand
    "profile.birthday": "on_demand",
    "profile.company": "on_demand",
    "profile.role": "on_demand",
    "profile.bio": "on_demand",
    "profile.website": "on_demand",
    "profile.linkedin": "on_demand",
    # Communication — sensitive by default
    "communication.phone_e164": "sensitive",
    "communication.whatsapp_e164": "sensitive",
    "communication.telegram_username": "sensitive",
    # Communication — routing preferences (on demand)
    "communication.preferred_contact_channel": "on_demand",
    "communication.preferred_call_channel": "on_demand",
}


def _seed_field_access_policy(stored: Dict[str, str]) -> Dict[str, str]:
    """Fill in missing entries from the default policy. Stored user
    overrides win — we never flip a user-set policy back to default.
    Returns a fresh dict (stored values unchanged)."""
    out: Dict[str, str] = dict(_DEFAULT_FIELD_ACCESS_POLICY)
    if isinstance(stored, dict):
        for k, v in stored.items():
            if v in ("always", "on_demand", "sensitive"):
                out[str(k)] = v
    return out


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


# ---------------------------------------------------------------------------
# Auto-sync helpers (additive — read_profile, meta, PATCH)
# ---------------------------------------------------------------------------

def read_profile() -> Dict[str, Any]:
    """Instance-wide profile reader used by agent context builders."""
    root = _data_root()
    path = root / PROFILE_FILE
    defaults = UserProfile().model_dump()
    data = _read_json(path, default=defaults)
    return {**defaults, **(data or {})}


def _profile_etag(profile: Dict[str, Any], updated_at: str) -> str:
    """Stable ETag for polling / concurrency."""
    payload = json.dumps(
        {"profile": profile, "updated_at": updated_at},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _profile_updated_at(path: Path) -> str:
    """File mtime as monotonic updated_at."""
    try:
        st = path.stat()
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
    except Exception:
        return ""


def _normalize_profile_fields(p: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize fields for safe merge (same rules as PUT)."""
    for k in (
        "likes", "dislikes", "favorite_persona_tags",
        "preferred_terms_of_endearment", "hard_boundaries",
        "sensitive_topics", "allowed_content_tags", "blocked_content_tags",
    ):
        if k in p:
            p[k] = _norm_list(p.get(k, []))

    if "affection_level" in p and p.get("affection_level") not in ("friendly", "affectionate", "romantic"):
        p["affection_level"] = "friendly"
    if "preferred_tone" in p and p.get("preferred_tone") not in ("neutral", "friendly", "formal"):
        p["preferred_tone"] = "neutral"

    if "default_spicy_strength" in p:
        try:
            s = float(p.get("default_spicy_strength", 0.30))
        except Exception:
            s = 0.30
        p["default_spicy_strength"] = max(0.0, min(1.0, s))

    return p


def _merge_profile(existing: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow merge (field-level). Lists replaced, not concatenated."""
    merged = dict(existing or {})
    for k, v in (patch or {}).items():
        merged[k] = v
    defaults = UserProfile().model_dump()
    merged = {**defaults, **merged}
    return _normalize_profile_fields(merged)


def _get_profile_with_meta() -> Dict[str, Any]:
    root = _data_root()
    path = root / PROFILE_FILE
    profile = read_profile()
    updated_at = _profile_updated_at(path) if path.exists() else ""
    etag = _profile_etag(profile, updated_at)
    return {"profile": profile, "updated_at": updated_at, "etag": etag}


# ---------------------------------------------------------------------------
# Additive endpoints (meta + PATCH)
# ---------------------------------------------------------------------------

@router.get("/meta", dependencies=[Depends(require_api_key)])
def get_profile_meta() -> Dict[str, Any]:
    """Lightweight polling endpoint for real-time freshness checks."""
    meta = _get_profile_with_meta()
    return {"ok": True, "updated_at": meta["updated_at"], "etag": meta["etag"]}


@router.patch("", dependencies=[Depends(require_api_key)])
def patch_profile(
    patch: Dict[str, Any] = Body(default_factory=dict),
    if_match: Optional[str] = Header(default=None, convert_underscores=False),
) -> Dict[str, Any]:
    """
    Partial update (auto-sync safe).
    Optional concurrency: client may send If-Match: <etag>.
    If mismatch → 409.
    """
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="Patch body must be an object")

    root = _data_root()
    path = root / PROFILE_FILE

    current = _get_profile_with_meta()
    if if_match and if_match.strip() and if_match.strip() != current["etag"]:
        raise HTTPException(status_code=409, detail="Profile changed; refresh and retry")

    merged = _merge_profile(current["profile"], patch)
    _atomic_write_json(path, merged)

    out = _get_profile_with_meta()
    return {"ok": True, "profile": out["profile"], "updated_at": out["updated_at"], "etag": out["etag"]}
