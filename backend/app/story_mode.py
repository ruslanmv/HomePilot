# backend/app/story_mode.py
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from .llm import chat_ollama
from . import storage
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL


# --------------------------------------------------------------------------------------
# Storage locations
# --------------------------------------------------------------------------------------

def _story_root() -> Path:
    # Use the same data directory as the main database
    db_path = Path(storage._get_db_path())
    root = db_path.parent / "story_mode"
    root.mkdir(parents=True, exist_ok=True)
    (root / "audio").mkdir(parents=True, exist_ok=True)
    return root


def _db_path() -> str:
    # Reuse HomePilot's resolved DB path for consistency
    return storage._get_db_path()


def init_story_db() -> None:
    """
    Create tables for story-mode sessions and scenes.
    Safe to call multiple times.
    """
    con = sqlite3.connect(_db_path())
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS story_sessions(
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            title TEXT NOT NULL,
            premise TEXT NOT NULL,
            options_json TEXT NOT NULL,
            bible_json TEXT NOT NULL,
            state_json TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS story_scenes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            scene_json TEXT NOT NULL,
            UNIQUE(session_id, idx),
            FOREIGN KEY(session_id) REFERENCES story_sessions(id)
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_story_scenes_session ON story_scenes(session_id)")
    con.commit()
    con.close()


# --------------------------------------------------------------------------------------
# Pydantic models
# --------------------------------------------------------------------------------------

class StoryOptions(BaseModel):
    # LLM behavior
    temperature: float = Field(0.75, ge=0.0, le=1.2)
    max_scenes: int = Field(24, ge=1, le=200)

    # Visual consistency
    visual_style: str = Field(
        "cinematic, high detail, coherent lighting, strong composition",
        max_length=500,
    )
    aspect_ratio: str = Field("16:9", max_length=20)

    # How different each scene should feel
    variation_strength: float = Field(0.55, ge=0.0, le=1.0)

    # Prompt refinement (LLM)
    refine_image_prompt: bool = True

    # Safety
    allow_nsfw: bool = False

    # TTS options
    tts_enabled: bool = False
    tts_engine: str = Field("piper", max_length=50)
    piper_binary: str = Field("piper", max_length=200)
    piper_voice_model: str = Field("", max_length=500)
    piper_speaker: Optional[int] = None
    narration_speed: float = Field(1.0, ge=0.5, le=2.0)


class StoryBible(BaseModel):
    title: str
    logline: str
    setting: str
    visual_style_rules: List[str] = Field(default_factory=list)
    recurring_characters: List[Dict[str, str]] = Field(default_factory=list)
    recurring_locations: List[str] = Field(default_factory=list)
    do_not_change: List[str] = Field(default_factory=list)


class StoryState(BaseModel):
    # memory to avoid repetition + maintain continuity
    scene_index_next: int = 1
    summary_so_far: str = ""
    used_beats: List[str] = Field(default_factory=list)
    used_locations: List[str] = Field(default_factory=list)
    used_camera: List[str] = Field(default_factory=list)
    used_mood: List[str] = Field(default_factory=list)


class StoryStartRequest(BaseModel):
    premise: str = Field(..., min_length=3, max_length=4000)
    title_hint: str = Field("", max_length=200)
    options: Optional[Dict[str, Any]] = None


class StoryStartResponse(BaseModel):
    ok: bool = True
    session_id: str
    title: str
    bible: StoryBible
    options: StoryOptions


class SceneOut(BaseModel):
    idx: int
    narration: str
    image_prompt: str
    negative_prompt: str = ""
    duration_s: int = 7
    tags: Dict[str, str] = Field(default_factory=dict)
    audio_url: Optional[str] = None
    audio_path: Optional[str] = None
    image_url: Optional[str] = None  # Set by frontend after generation


class StoryNextRequest(BaseModel):
    session_id: str
    refine_image_prompt: Optional[bool] = None
    tts_enabled: Optional[bool] = None


class StoryNextResponse(BaseModel):
    ok: bool = True
    session_id: str
    title: str
    scene: SceneOut
    bible: StoryBible


# --------------------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


def _save_session(
    session_id: str,
    *,
    title: str,
    premise: str,
    options: StoryOptions,
    bible: StoryBible,
    state: StoryState,
) -> None:
    con = _db()
    cur = con.cursor()
    ts = _now()
    cur.execute(
        """
        INSERT INTO story_sessions(id, created_at, updated_at, title, premise, options_json, bible_json, state_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            updated_at=excluded.updated_at,
            title=excluded.title,
            premise=excluded.premise,
            options_json=excluded.options_json,
            bible_json=excluded.bible_json,
            state_json=excluded.state_json
        """,
        (
            session_id,
            ts,
            ts,
            title,
            premise,
            options.model_dump_json(),
            bible.model_dump_json(),
            state.model_dump_json(),
        ),
    )
    con.commit()
    con.close()


def _load_session(session_id: str) -> Optional[Tuple[str, str, StoryOptions, StoryBible, StoryState]]:
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM story_sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None

    title = str(row["title"])
    premise = str(row["premise"])

    try:
        options = StoryOptions.model_validate_json(row["options_json"])
    except Exception:
        options = StoryOptions()

    try:
        bible = StoryBible.model_validate_json(row["bible_json"])
    except Exception:
        bible = StoryBible(
            title=title,
            logline="",
            setting="",
            visual_style_rules=[],
            recurring_characters=[],
            recurring_locations=[],
            do_not_change=[],
        )

    try:
        state = StoryState.model_validate_json(row["state_json"])
    except Exception:
        state = StoryState()

    return title, premise, options, bible, state


def _insert_scene(session_id: str, idx: int, scene: SceneOut) -> None:
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO story_scenes(session_id, idx, created_at, scene_json)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, int(idx), _now(), scene.model_dump_json()),
    )
    con.commit()
    con.close()


def list_scenes(session_id: str, limit: int = 200) -> List[SceneOut]:
    limit = max(1, min(500, int(limit)))
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT scene_json FROM story_scenes
        WHERE session_id=?
        ORDER BY idx ASC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = cur.fetchall()
    con.close()

    out: List[SceneOut] = []
    for r in rows:
        try:
            out.append(SceneOut.model_validate_json(r["scene_json"]))
        except Exception:
            continue
    return out


def list_story_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """List all story sessions for the Studio UI."""
    limit = max(1, min(200, int(limit)))
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, title, premise, created_at, updated_at
        FROM story_sessions
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    con.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": str(r["id"]),
            "title": str(r["title"]),
            "premise": str(r["premise"])[:200],
            "created_at": int(r["created_at"]),
            "updated_at": int(r["updated_at"]),
        })
    return out


def delete_story_session(session_id: str) -> bool:
    """Delete a story session and all its scenes."""
    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM story_scenes WHERE session_id=?", (session_id,))
    cur.execute("DELETE FROM story_sessions WHERE id=?", (session_id,))
    con.commit()
    deleted = cur.rowcount > 0
    con.close()
    return deleted


# --------------------------------------------------------------------------------------
# Ollama helpers
# --------------------------------------------------------------------------------------

async def _ollama_chat(
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    base_url: str,
    model: str
) -> str:
    resp = await chat_ollama(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url,
        model=model,
    )
    text = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return str(text).strip()


def _extract_json(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        l = raw.find("{")
        r = raw.rfind("}")
        if l != -1 and r != -1 and r > l:
            try:
                return json.loads(raw[l : r + 1])
            except Exception:
                pass
    return {}


def _clamp_text(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) > max_len:
        return s[:max_len].rstrip()
    return s


# --------------------------------------------------------------------------------------
# LLM prompts
# --------------------------------------------------------------------------------------

def _planner_system_prompt() -> str:
    return (
        "You are a story showrunner for a visual AI TV-like story.\n"
        "You must output STRICT JSON ONLY (no markdown).\n"
        "Create a short story bible for consistent image generation.\n"
        "Keep it safe and non-graphic. No illegal content. No sexual content.\n"
        "JSON schema:\n"
        "{\n"
        '  "title": "string",\n'
        '  "logline": "string",\n'
        '  "setting": "string",\n'
        '  "visual_style_rules": ["..."],\n'
        '  "recurring_characters": [{"name":"...","description":"..."}],\n'
        '  "recurring_locations": ["..."],\n'
        '  "do_not_change": ["..."]\n'
        "}\n"
    )


def _planner_user_prompt(premise: str, title_hint: str, opts: StoryOptions) -> str:
    hint = f"Title hint: {title_hint}\n" if title_hint.strip() else ""
    return (
        f"{hint}"
        f"Premise:\n{premise.strip()}\n\n"
        "Constraints:\n"
        f"- Visual style (global): {opts.visual_style}\n"
        f"- Aspect ratio: {opts.aspect_ratio}\n"
        "- Create 3-6 recurring characters.\n"
        "- Create 2-6 recurring locations.\n"
        "- Add 5-10 do_not_change rules (for consistency).\n"
    )


def _scene_system_prompt(allow_nsfw: bool) -> str:
    safety = "No graphic violence. No hate. No illegal instructions."
    if allow_nsfw:
        safety = "Keep it cinematic and safe."
    return (
        "You write ONE scene for a story that will be rendered as one image + narration.\n"
        "Output STRICT JSON ONLY (no markdown).\n"
        f"Safety rules: {safety}\n"
        "JSON schema:\n"
        "{\n"
        '  "narration": "string (2-6 sentences)",\n'
        '  "image_prompt": "string (single prompt, no lists)",\n'
        '  "negative_prompt": "string (optional)",\n'
        '  "duration_s": 7,\n'
        '  "tags": {"location":"...","camera":"...","mood":"...","beat":"..."}\n'
        "}\n"
        "Guidelines:\n"
        "- Maintain continuity with the bible and summary.\n"
        "- Keep the story progressing.\n"
        "- Vary camera/mood/location over time, avoid repeats.\n"
    )


def _scene_user_prompt(
    bible: StoryBible,
    state: StoryState,
    idx: int,
    opts: StoryOptions,
) -> str:
    return (
        f"Story title: {bible.title}\n"
        f"Logline: {bible.logline}\n"
        f"Setting: {bible.setting}\n\n"
        "Visual rules:\n"
        + "\n".join(f"- {x}" for x in (bible.visual_style_rules or []))
        + "\n\n"
        "Do not change:\n"
        + "\n".join(f"- {x}" for x in (bible.do_not_change or []))
        + "\n\n"
        "Recurring characters:\n"
        + "\n".join(f"- {c.get('name','?')}: {c.get('description','')}" for c in (bible.recurring_characters or []))
        + "\n\n"
        f"Summary so far:\n{state.summary_so_far}\n\n"
        f"Scene number: {idx}\n"
        f"Variation strength: {opts.variation_strength:.2f}\n\n"
        "Avoid repeating these recently used items:\n"
        f"- beats: {', '.join(state.used_beats[-12:])}\n"
        f"- locations: {', '.join(state.used_locations[-12:])}\n"
        f"- camera: {', '.join(state.used_camera[-12:])}\n"
        f"- mood: {', '.join(state.used_mood[-12:])}\n\n"
        f"Global image style addendum: {opts.visual_style}\n"
        f"Aspect ratio: {opts.aspect_ratio}\n"
    )


def _refine_system_prompt() -> str:
    return (
        "You refine image prompts for a diffusion/ComfyUI pipeline.\n"
        "Output STRICT JSON ONLY:\n"
        "{\n"
        '  "image_prompt": "string",\n'
        '  "negative_prompt": "string"\n'
        "}\n"
        "Rules:\n"
        "- Return a single concise but detailed prompt.\n"
        "- Keep all story constraints.\n"
        "- Do not add unsafe content.\n"
    )


def _refine_user_prompt(bible: StoryBible, raw_prompt: str, raw_negative: str, opts: StoryOptions) -> str:
    return (
        f"Story title: {bible.title}\n"
        f"Setting: {bible.setting}\n"
        "Do not change:\n"
        + "\n".join(f"- {x}" for x in (bible.do_not_change or []))
        + "\n\n"
        f"Global style: {opts.visual_style}\n"
        f"Aspect ratio: {opts.aspect_ratio}\n\n"
        f"Raw image prompt:\n{raw_prompt}\n\n"
        f"Raw negative prompt:\n{raw_negative}\n"
    )


# --------------------------------------------------------------------------------------
# TTS (Piper local-first)
# --------------------------------------------------------------------------------------

def _tts_piper(text: str, *, session_id: str, idx: int, opts: StoryOptions) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (audio_url, audio_path).
    """
    text = (text or "").strip()
    if not text:
        return None, None

    if not opts.piper_voice_model:
        return None, None

    out_dir = _story_root() / "audio" / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"scene_{idx:04d}.wav"

    cmd = [opts.piper_binary, "--model", opts.piper_voice_model, "--output_file", str(wav_path)]
    if opts.piper_speaker is not None:
        cmd += ["--speaker", str(opts.piper_speaker)]

    try:
        subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except Exception:
        return None, None

    audio_path = str(wav_path)
    audio_url = None
    return audio_url, audio_path


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

async def start_story(
    premise: str,
    *,
    title_hint: str = "",
    options: Optional[Dict[str, Any]] = None,
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
) -> StoryStartResponse:
    init_story_db()

    premise = _clamp_text(premise, 4000)
    if not premise:
        raise ValueError("premise is required")

    try:
        opts = StoryOptions.model_validate(options or {})
    except ValidationError:
        opts = StoryOptions()

    sys_msg = _planner_system_prompt()
    user_msg = _planner_user_prompt(premise, title_hint, opts)

    text = await _ollama_chat(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        temperature=opts.temperature,
        max_tokens=900,
        base_url=(ollama_base_url or OLLAMA_BASE_URL),
        model=(ollama_model or OLLAMA_MODEL),
    )
    obj = _extract_json(text)

    try:
        bible = StoryBible.model_validate(obj)
    except Exception:
        bible = StoryBible(
            title=(title_hint.strip() or "Untitled Story"),
            logline=premise[:180],
            setting="",
            visual_style_rules=[opts.visual_style, f"aspect ratio {opts.aspect_ratio}"],
            recurring_characters=[],
            recurring_locations=[],
            do_not_change=[],
        )

    title = bible.title.strip() or (title_hint.strip() or "Untitled Story")

    state = StoryState(scene_index_next=1, summary_so_far="", used_beats=[], used_locations=[], used_camera=[], used_mood=[])

    session_id = str(uuid.uuid4())
    _save_session(
        session_id,
        title=title,
        premise=premise,
        options=opts,
        bible=bible,
        state=state,
    )

    return StoryStartResponse(session_id=session_id, title=title, bible=bible, options=opts)


async def next_scene(
    *,
    session_id: str,
    refine_image_prompt: Optional[bool] = None,
    tts_enabled: Optional[bool] = None,
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
) -> StoryNextResponse:
    init_story_db()

    loaded = _load_session(session_id)
    if not loaded:
        raise ValueError("session not found")

    title, premise, opts, bible, state = loaded

    if refine_image_prompt is not None:
        opts.refine_image_prompt = bool(refine_image_prompt)
    if tts_enabled is not None:
        opts.tts_enabled = bool(tts_enabled)

    idx = int(state.scene_index_next)
    if idx > opts.max_scenes:
        raise ValueError("max scenes reached")

    sys_msg = _scene_system_prompt(allow_nsfw=opts.allow_nsfw)
    user_msg = _scene_user_prompt(bible=bible, state=state, idx=idx, opts=opts)

    raw = await _ollama_chat(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        temperature=opts.temperature,
        max_tokens=700,
        base_url=(ollama_base_url or OLLAMA_BASE_URL),
        model=(ollama_model or OLLAMA_MODEL),
    )
    obj = _extract_json(raw)

    narration = _clamp_text(str(obj.get("narration") or ""), 2000)
    image_prompt = _clamp_text(str(obj.get("image_prompt") or ""), 2000)
    negative_prompt = _clamp_text(str(obj.get("negative_prompt") or ""), 800)
    duration_s = int(obj.get("duration_s") or 7)
    duration_s = max(3, min(30, duration_s))
    tags = obj.get("tags") if isinstance(obj.get("tags"), dict) else {}

    if not narration:
        narration = f"Scene {idx}: The story continues."
    if not image_prompt:
        image_prompt = f"{bible.setting}. {opts.visual_style}. cinematic still."

    if opts.refine_image_prompt:
        ref_sys = _refine_system_prompt()
        ref_user = _refine_user_prompt(bible=bible, raw_prompt=image_prompt, raw_negative=negative_prompt, opts=opts)
        ref_raw = await _ollama_chat(
            [{"role": "system", "content": ref_sys}, {"role": "user", "content": ref_user}],
            temperature=max(0.2, min(0.8, opts.temperature)),
            max_tokens=450,
            base_url=(ollama_base_url or OLLAMA_BASE_URL),
            model=(ollama_model or OLLAMA_MODEL),
        )
        ref_obj = _extract_json(ref_raw)
        rp = ref_obj.get("image_prompt")
        rn = ref_obj.get("negative_prompt")
        if isinstance(rp, str) and rp.strip():
            image_prompt = _clamp_text(rp, 2000)
        if isinstance(rn, str) and rn.strip():
            negative_prompt = _clamp_text(rn, 800)

    scene = SceneOut(
        idx=idx,
        narration=narration,
        image_prompt=image_prompt,
        negative_prompt=negative_prompt,
        duration_s=duration_s,
        tags={k: str(v) for k, v in (tags or {}).items()},
        audio_url=None,
        audio_path=None,
    )

    if opts.tts_enabled and opts.tts_engine.lower() == "piper":
        audio_url, audio_path = _tts_piper(narration, session_id=session_id, idx=idx, opts=opts)
        scene.audio_url = audio_url
        scene.audio_path = audio_path

    _insert_scene(session_id, idx, scene)

    beat = (scene.tags.get("beat") or "").strip()
    loc = (scene.tags.get("location") or "").strip()
    cam = (scene.tags.get("camera") or "").strip()
    mood = (scene.tags.get("mood") or "").strip()

    if beat:
        state.used_beats.append(beat)
        state.used_beats = state.used_beats[-50:]
    if loc:
        state.used_locations.append(loc)
        state.used_locations = state.used_locations[-50:]
    if cam:
        state.used_camera.append(cam)
        state.used_camera = state.used_camera[-50:]
    if mood:
        state.used_mood.append(mood)
        state.used_mood = state.used_mood[-50:]

    state.summary_so_far = _clamp_text((state.summary_so_far + "\n" + narration).strip(), 2500)
    state.scene_index_next = idx + 1

    _save_session(session_id, title=title, premise=premise, options=opts, bible=bible, state=state)

    return StoryNextResponse(session_id=session_id, title=title, scene=scene, bible=bible)


def get_story(session_id: str) -> Dict[str, Any]:
    init_story_db()
    loaded = _load_session(session_id)
    if not loaded:
        raise ValueError("session not found")

    title, premise, opts, bible, state = loaded
    scenes = list_scenes(session_id, limit=500)

    return {
        "ok": True,
        "session_id": session_id,
        "title": title,
        "premise": premise,
        "options": opts.model_dump(),
        "bible": bible.model_dump(),
        "state": state.model_dump(),
        "scenes": [s.model_dump() for s in scenes],
    }
