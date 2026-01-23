# backend/app/game_mode.py
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

from pydantic import BaseModel, Field, ValidationError

from . import storage
from .llm import chat_ollama
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL


# ----------------------------
# DB (SQLite)
# ----------------------------

def _db_path() -> str:
    # Reuse HomePilot's resolved DB path logic
    return storage._get_db_path()  # noqa: SLF001 (internal reuse is fine)


def init_game_db() -> None:
    """
    Create tables for game-mode sessions and events.
    Safe to call multiple times.
    """
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_sessions(
            id TEXT PRIMARY KEY,
            base_prompt TEXT NOT NULL,
            options_json TEXT NOT NULL,
            memory_json TEXT NOT NULL,
            counter INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            n INTEGER NOT NULL,
            variation_prompt TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(session_id) REFERENCES game_sessions(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_game_events_session ON game_events(session_id)")
    con.commit()
    con.close()


# ----------------------------
# Models / Options
# ----------------------------

class GameLocks(BaseModel):
    """
    Things that should stay stable across generations.
    Default keeps *world/style* stable but allows characters to change.
    """
    lock_world: bool = True
    lock_style: bool = True
    lock_subject_type: bool = True   # "a detective", "a dragon rider", etc.
    lock_main_character: bool = False  # if True, try to keep same character identity
    lock_palette: bool = False
    lock_time_of_day: bool = False


class GameOptions(BaseModel):
    """
    Controls how diverse the variations are.
    """
    strength: float = Field(0.65, ge=0.0, le=1.0)  # 0 subtle -> 1 wild
    locks: GameLocks = Field(default_factory=GameLocks)

    # How aggressively to avoid repeats:
    avoid_repeat_window: int = Field(30, ge=5, le=200)

    # Optional stable "world bible" you can supply from UI later:
    world_bible: str = Field("", max_length=4000)


class VariationOut(BaseModel):
    variation_prompt: str
    tags: Dict[str, str] = Field(default_factory=dict)


@dataclass
class VariationResult:
    session_id: str
    counter: int
    base_prompt: str
    variation_prompt: str
    tags: Dict[str, str]


# ----------------------------
# Memory strategy (anti-repeat)
# ----------------------------

def _default_memory() -> Dict[str, Any]:
    return {
        "recent_variations": [],  # list[str]
        "used_traits": {
            "character": [],
            "setting": [],
            "camera": [],
            "mood": [],
        },
    }


def _push_unique(lst: List[str], value: str, max_len: int) -> None:
    value = (value or "").strip()
    if not value:
        return
    # keep unique, newest first
    if value in lst:
        lst.remove(value)
    lst.insert(0, value)
    del lst[max_len:]


# ----------------------------
# DB helpers
# ----------------------------

def _load_session(session_id: str) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any], int]]:
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    cur.execute(
        "SELECT base_prompt, options_json, memory_json, counter FROM game_sessions WHERE id=?",
        (session_id,),
    )
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    base_prompt, options_json, memory_json, counter = row
    try:
        options = json.loads(options_json)
    except Exception:
        options = {}
    try:
        memory = json.loads(memory_json)
    except Exception:
        memory = _default_memory()
    return str(base_prompt), options, memory, int(counter)


def _save_session(session_id: str, base_prompt: str, options: Dict[str, Any], memory: Dict[str, Any], counter: int) -> None:
    now = int(time.time())
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO game_sessions(id, base_prompt, options_json, memory_json, counter, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            base_prompt=excluded.base_prompt,
            options_json=excluded.options_json,
            memory_json=excluded.memory_json,
            counter=excluded.counter,
            updated_at=excluded.updated_at
        """,
        (
            session_id,
            base_prompt,
            json.dumps(options, ensure_ascii=False),
            json.dumps(memory, ensure_ascii=False),
            int(counter),
            now,
            now,
        ),
    )
    con.commit()
    con.close()


def _insert_event(session_id: str, n: int, variation_prompt: str, tags: Dict[str, str]) -> None:
    now = int(time.time())
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO game_events(session_id, n, variation_prompt, tags_json, created_at)
        VALUES (?,?,?,?,?)
        """,
        (session_id, int(n), variation_prompt, json.dumps(tags, ensure_ascii=False), now),
    )
    con.commit()
    con.close()


# ----------------------------
# LLM prompt
# ----------------------------

def _build_variation_system_prompt() -> str:
    return (
        "You generate *one* variation of an image prompt for a generative art system.\n"
        "Return STRICT JSON only (no markdown):\n"
        "{\n"
        '  "variation_prompt": "string",\n'
        '  "tags": { "character": "...", "setting": "...", "camera": "...", "mood": "..." }\n'
        "}\n"
        "Rules:\n"
        "- Keep the core concept aligned to the user's base prompt.\n"
        "- Vary character identity, small details, props, camera, composition, weather, lighting.\n"
        "- Avoid repeating recent variations and recently used traits.\n"
        "- Keep it a single prompt (no lists).\n"
        "- Do NOT add disallowed or unsafe content.\n"
    )


def _build_variation_user_prompt(
    *,
    base_prompt: str,
    options: GameOptions,
    memory: Dict[str, Any],
    counter: int,
) -> str:
    locks = options.locks
    recent = (memory.get("recent_variations") or [])[: options.avoid_repeat_window]
    used = (memory.get("used_traits") or {}) if isinstance(memory.get("used_traits"), dict) else {}

    def _fmt_used(k: str) -> str:
        vals = used.get(k) or []
        if not isinstance(vals, list):
            return ""
        vals = [str(x) for x in vals][: options.avoid_repeat_window]
        return ", ".join(vals)

    # Strength guidance:
    if options.strength < 0.34:
        strength_hint = "Subtle variation. Mostly keep composition/style; change 1-2 details."
    elif options.strength < 0.67:
        strength_hint = "Medium variation. Change character + 2-4 scene details; keep theme consistent."
    else:
        strength_hint = "Wild variation. Keep theme but vary character, setting details, camera, mood significantly."

    lock_notes = []
    if locks.lock_world:
        lock_notes.append("Keep the world/setting theme consistent.")
    if locks.lock_style:
        lock_notes.append("Keep the art style consistent.")
    if locks.lock_subject_type:
        lock_notes.append("Keep the same subject category (e.g., still 'a detective', still 'a dragon rider').")
    if locks.lock_main_character:
        lock_notes.append("Try to keep the same main character identity (name/appearance) consistent.")
    if locks.lock_palette:
        lock_notes.append("Keep color palette consistent.")
    if locks.lock_time_of_day:
        lock_notes.append("Keep time of day consistent.")
    if not lock_notes:
        lock_notes.append("No locks. Free to vary widely while staying on-theme.")

    world_bible = (options.world_bible or "").strip()
    world_bible_txt = f"\nWorld bible:\n{world_bible}\n" if world_bible else ""

    return (
        f"Base prompt:\n{base_prompt.strip()}\n\n"
        f"Generation number: {counter + 1}\n"
        f"Variation strength: {options.strength:.2f}\n"
        f"Guidance: {strength_hint}\n\n"
        f"Locks:\n- " + "\n- ".join(lock_notes) + "\n\n"
        f"Do NOT repeat these recent full prompts:\n{json.dumps(recent, ensure_ascii=False)}\n\n"
        f"Try not to reuse these recent traits:\n"
        f"- character: {_fmt_used('character')}\n"
        f"- setting: {_fmt_used('setting')}\n"
        f"- camera: {_fmt_used('camera')}\n"
        f"- mood: {_fmt_used('mood')}\n"
        f"{world_bible_txt}\n"
        "Now output the JSON variation."
    )


def _safe_parse_variation(text: str) -> VariationOut:
    """
    Robust parsing:
    - Try strict JSON
    - If it fails, fallback to using raw text as variation_prompt
    """
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        return VariationOut.model_validate(obj)
    except Exception:
        # Some models accidentally wrap JSON; attempt to extract first {...}
        l = raw.find("{")
        r = raw.rfind("}")
        if l != -1 and r != -1 and r > l:
            try:
                obj = json.loads(raw[l : r + 1])
                return VariationOut.model_validate(obj)
            except Exception:
                pass
        # Fallback: use whole text as prompt
        return VariationOut(variation_prompt=raw or "A detailed cinematic image.", tags={})


# ----------------------------
# Public API
# ----------------------------

def start_session(*, base_prompt: str, options: Optional[Dict[str, Any]] = None) -> str:
    session_id = str(uuid.uuid4())
    base_prompt = (base_prompt or "").strip()
    opt = GameOptions.model_validate(options or {}).model_dump()
    mem = _default_memory()
    _save_session(session_id, base_prompt, opt, mem, counter=0)
    return session_id


async def next_variation(
    *,
    base_prompt: str,
    session_id: Optional[str],
    options: Optional[Dict[str, Any]] = None,
    # Ollama overrides (optional)
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
) -> VariationResult:
    """
    Returns a new variation prompt while maintaining session memory to avoid repeats.
    """
    base_prompt = (base_prompt or "").strip()
    if not base_prompt:
        raise ValueError("base_prompt is required")

    # Create or load session
    if session_id:
        loaded = _load_session(session_id)
    else:
        loaded = None

    if not loaded:
        session_id = start_session(base_prompt=base_prompt, options=options)
        loaded = _load_session(session_id)

    assert session_id is not None
    assert loaded is not None
    stored_base, stored_options, memory, counter = loaded

    # Allow updating base prompt if new base provided (rare but useful)
    if base_prompt and base_prompt != stored_base:
        stored_base = base_prompt

    # Merge options: stored + patch
    merged = dict(stored_options or {})
    if options:
        merged.update(options)

    # Validate options
    try:
        opts = GameOptions.model_validate(merged)
    except ValidationError:
        opts = GameOptions()

    # Call Ollama
    sys_msg = _build_variation_system_prompt()
    user_msg = _build_variation_user_prompt(base_prompt=stored_base, options=opts, memory=memory, counter=counter)

    effective_base_url = ollama_base_url or OLLAMA_BASE_URL
    # Fallback chain for model: explicit param -> config -> hardcoded default
    # This prevents empty model string which causes Ollama to return empty response
    effective_model = ollama_model or OLLAMA_MODEL or "llama3:8b"

    print(f"[GAME MODE VARIATION] Calling Ollama: base_url={effective_base_url}, model={effective_model}")
    print(f"[GAME MODE VARIATION] Base prompt: {stored_base[:100]}...")

    out = await chat_ollama(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.75,
        max_tokens=450,
        base_url=effective_base_url,
        model=effective_model,
    )

    text = ((out.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "") or ""
    print(f"[GAME MODE VARIATION] Raw LLM response: {text[:200] if text else '(empty)'}...")

    parsed = _safe_parse_variation(text)
    print(f"[GAME MODE VARIATION] Parsed variation_prompt: {parsed.variation_prompt[:100] if parsed.variation_prompt else '(empty)'}...")

    variation_prompt = (parsed.variation_prompt or "").strip()
    if not variation_prompt:
        variation_prompt = stored_base

    tags = parsed.tags or {}

    # Update memory (anti-repeat)
    if not isinstance(memory, dict):
        memory = _default_memory()

    recent_variations = memory.get("recent_variations")
    if not isinstance(recent_variations, list):
        recent_variations = []
        memory["recent_variations"] = recent_variations

    used_traits = memory.get("used_traits")
    if not isinstance(used_traits, dict):
        used_traits = {"character": [], "setting": [], "camera": [], "mood": []}
        memory["used_traits"] = used_traits

    _push_unique(recent_variations, variation_prompt, max_len=opts.avoid_repeat_window)

    for k in ["character", "setting", "camera", "mood"]:
        lst = used_traits.get(k)
        if not isinstance(lst, list):
            lst = []
            used_traits[k] = lst
        _push_unique(lst, str(tags.get(k, "")), max_len=opts.avoid_repeat_window)

    counter = int(counter) + 1

    # Persist session + event
    _save_session(session_id, stored_base, opts.model_dump(), memory, counter)
    _insert_event(session_id, counter, variation_prompt, tags)

    return VariationResult(
        session_id=session_id,
        counter=counter,
        base_prompt=stored_base,
        variation_prompt=variation_prompt,
        tags={k: str(v) for k, v in tags.items()},
    )


def get_session_events(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(200, int(limit)))
    con = sqlite3.connect(_db_path())
    cur = con.cursor()
    cur.execute(
        """
        SELECT n, variation_prompt, tags_json, created_at
        FROM game_events
        WHERE session_id=?
        ORDER BY n DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = cur.fetchall()
    con.close()

    out: List[Dict[str, Any]] = []
    for n, vp, tj, created_at in rows:
        try:
            tags = json.loads(tj) if tj else {}
        except Exception:
            tags = {}
        out.append(
            {
                "n": int(n),
                "variation_prompt": str(vp),
                "tags": tags if isinstance(tags, dict) else {},
                "created_at": int(created_at),
            }
        )
    # return chronological
    return list(reversed(out))
