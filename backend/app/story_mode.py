# backend/app/story_mode.py
from __future__ import annotations

import json
import re
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

    # Story arc - gives the story a clear structure with beginning, middle, end
    story_arc: Dict[str, str] = Field(default_factory=lambda: {
        "beginning": "",      # Setup/hook - introduce characters and world
        "rising_action": "",  # Build tension, develop conflict
        "climax": "",         # Peak of the story, major turning point
        "falling_action": "", # Consequences of climax
        "resolution": "",     # How the story ends
    })

    # Scene outline - planned scenes with brief descriptions
    # This makes the story finite with a clear ending
    scene_outline: List[str] = Field(default_factory=list)

    # Total planned scenes (story is NOT infinite)
    # Minimum 6 scenes for a complete story arc (setup, rising action, climax, falling action, resolution)
    total_scenes: int = Field(default=8, ge=6, le=50)


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


def update_scene_image(session_id: str, idx: int, image_url: str) -> bool:
    """Update a scene's image_url and persist to database."""
    con = _db()
    cur = con.cursor()

    # Load existing scene
    cur.execute(
        "SELECT scene_json FROM story_scenes WHERE session_id=? AND idx=?",
        (session_id, int(idx)),
    )
    row = cur.fetchone()
    if not row:
        con.close()
        return False

    try:
        scene = SceneOut.model_validate_json(row["scene_json"])
        scene.image_url = image_url

        # Save updated scene
        cur.execute(
            """
            UPDATE story_scenes SET scene_json=?, created_at=?
            WHERE session_id=? AND idx=?
            """,
            (scene.model_dump_json(), _now(), session_id, int(idx)),
        )
        con.commit()
        con.close()
        return True
    except Exception as e:
        print(f"[STORY] Failed to update scene image: {e}")
        con.close()
        return False


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
    model: str,
    response_format: Optional[str] = None,
    stop: Optional[List[str]] = None,
) -> str:
    resp = await chat_ollama(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url,
        model=model,
        response_format=response_format,
        stop=stop,
    )
    text = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return str(text).strip()


# Stop tokens tuned for local models (deepseek-r1, llama3) to prevent non-JSON chatter.
_JSON_STOP_DEFAULT: List[str] = [
    "</think>",
    "```",
    "\n\nAssistant:",
    "\n\nExplanation:",
]


def _extract_first_json_object(text: str) -> str:
    """
    Extract the first balanced JSON object from text.
    Handles preface/suffix text and avoids truncation issues from rfind.
    Returns empty string if no valid balanced object found.
    """
    s = (text or "").strip()
    if not s:
        return ""

    start = s.find("{")
    if start == -1:
        return ""

    depth = 0
    in_str = False
    esc = False

    for i in range(start, len(s)):
        ch = s[i]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]

    return ""  # incomplete/truncated


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Extract and parse a JSON object from LLM output.
    Uses balanced brace extraction for robustness against:
    - Preface text ("Here's the JSON: {...}")
    - Suffix text
    - Extra commentary
    """
    raw = (text or "").strip()

    # First try direct parse (ideal case: pure JSON)
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Use balanced brace extraction
    candidate = _extract_first_json_object(raw)
    if candidate:
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return {}


# --- JSON robustness helpers ---------------------------------------------------------

_CODE_FENCE_PREFIXES = ("```json", "```JSON", "```")


def _strip_code_fences(raw: str) -> str:
    """Strip markdown code fences from LLM output."""
    s = (raw or "").strip()
    if not s:
        return ""
    for p in _CODE_FENCE_PREFIXES:
        if s.startswith(p):
            # drop first fence line
            s = s.split("\n", 1)[1] if "\n" in s else ""
            break
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _repair_json_text(raw: str) -> str:
    """Best-effort, conservative JSON repair for common LLM mistakes."""
    s = _strip_code_fences(raw)

    # Trim any leading junk before first '{'
    i = s.find("{")
    if i > 0:
        s = s[i:]

    # Trim any trailing junk after the last '}' (helps when model adds commentary)
    j = s.rfind("}")
    if j != -1:
        s = s[: j + 1]

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Replace curly quotes with straight quotes (rare but happens)
    s = s.replace(""", '"').replace(""", '"').replace("'", "'")

    return s.strip()


def _looks_truncated_json(raw: str) -> bool:
    """Check if JSON appears truncated (has opening brace but no balanced close)."""
    s = _strip_code_fences(raw)
    if "{" not in s:
        return False
    # if we can't find a balanced object but there is an opening brace, it's likely truncation
    return _extract_first_json_object(s) == ""


def _extract_json_robust(raw: str) -> Dict[str, Any]:
    """Parse JSON with multiple fallbacks + light repair."""
    s = (raw or "").strip()
    if not s:
        return {}

    # 1) direct parse
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) brace-extract then parse
    candidate = _extract_first_json_object(s)
    if candidate:
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 3) repair then parse
    repaired = _repair_json_text(s)
    if repaired and repaired != s:
        try:
            return json.loads(repaired)
        except Exception:
            pass
        candidate = _extract_first_json_object(repaired)
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                pass

    return {}


async def _continue_if_truncated(
    *,
    sys_msg: str,
    base_url: str,
    model: str,
    raw: str,
    max_tokens: int = 320,
) -> str:
    """If output looks truncated, ask the model to continue the same JSON without repeating."""
    if not _looks_truncated_json(raw):
        return raw

    print(f"[STORY] Detected truncated JSON, requesting continuation...")

    cont_user = (
        "Continue the SAME JSON object exactly where you stopped.\n"
        "Output ONLY the remaining JSON characters needed to complete it.\n"
        "Do NOT repeat any earlier text. Do NOT add commentary."
    )

    tail = await _ollama_chat(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": cont_user}],
        temperature=0.0,
        max_tokens=max_tokens,
        base_url=base_url,
        model=model,
        response_format="json",
        stop=_JSON_STOP_DEFAULT,
    )
    return (raw or "") + (tail or "")


def _clamp_text(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) > max_len:
        return s[:max_len].rstrip()
    return s


def _normalize_string_list(items: Any) -> List[str]:
    """
    Normalize a list that should contain strings but might contain dicts.
    LLMs sometimes return [{"rule": "...", "priority": 1}] instead of ["..."]
    """
    if not isinstance(items, list):
        return []

    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            # Try common keys that might contain the actual text
            for key in ["rule", "name", "description", "text", "value", "content"]:
                if key in item and isinstance(item[key], str):
                    result.append(item[key])
                    break
            else:
                # Fallback: join all string values
                str_vals = [str(v) for v in item.values() if isinstance(v, str)]
                if str_vals:
                    result.append(str_vals[0])
    return result


def _normalize_story_bible_json(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize LLM-generated story bible JSON to match expected Pydantic schema.
    Handles cases where LLM returns objects instead of strings in arrays.
    """
    if not isinstance(obj, dict):
        return obj

    # Normalize arrays that should be List[str]
    for key in ["visual_style_rules", "recurring_locations", "do_not_change", "scene_outline"]:
        if key in obj:
            obj[key] = _normalize_string_list(obj[key])

    # Normalize recurring_characters - should be List[Dict[str, str]]
    if "recurring_characters" in obj and isinstance(obj["recurring_characters"], list):
        normalized_chars = []
        for char in obj["recurring_characters"]:
            if isinstance(char, dict):
                # Ensure it has name and description as strings
                normalized_char = {}
                for k, v in char.items():
                    if isinstance(v, str):
                        normalized_char[k] = v
                    elif isinstance(v, dict):
                        # Flatten nested dicts
                        normalized_char[k] = str(v.get("value") or v.get("text") or list(v.values())[0] if v else "")
                    else:
                        normalized_char[k] = str(v)
                if normalized_char:
                    normalized_chars.append(normalized_char)
            elif isinstance(char, str):
                # Convert string to dict format
                normalized_chars.append({"name": "Character", "description": char})
        obj["recurring_characters"] = normalized_chars

    # Normalize story_arc - should be Dict[str, str]
    if "story_arc" in obj:
        arc = obj["story_arc"]
        if isinstance(arc, dict):
            normalized_arc = {}
            for k, v in arc.items():
                if isinstance(v, str):
                    normalized_arc[k] = v
                elif isinstance(v, dict):
                    normalized_arc[k] = str(v.get("description") or v.get("text") or list(v.values())[0] if v else "")
                else:
                    normalized_arc[k] = str(v) if v else ""
            obj["story_arc"] = normalized_arc
        elif isinstance(arc, str):
            # If it's just a string, put it in beginning
            obj["story_arc"] = {"beginning": arc, "rising_action": "", "climax": "", "falling_action": "", "resolution": ""}

    # Normalize total_scenes - should be int
    if "total_scenes" in obj:
        try:
            obj["total_scenes"] = int(obj["total_scenes"])
        except (ValueError, TypeError):
            obj["total_scenes"] = 8  # Default

    # Ensure scene_outline has entries if total_scenes is set
    if "total_scenes" in obj and "scene_outline" not in obj:
        obj["scene_outline"] = []

    return obj


# --------------------------------------------------------------------------------------
# LLM prompts
# --------------------------------------------------------------------------------------

def _planner_system_prompt() -> str:
    return (
        "You are a story showrunner for a visual AI TV-like story.\n"
        "You must output STRICT JSON ONLY (no markdown).\n"
        "Create a COMPLETE story bible with a FINITE story arc.\n"
        "The story MUST have a clear beginning, middle, and END.\n"
        "Keep it safe and non-graphic. No illegal content. No sexual content.\n"
        "JSON schema:\n"
        "{\n"
        '  "title": "string",\n'
        '  "logline": "string (1-2 sentences summarizing the whole story)",\n'
        '  "setting": "string",\n'
        '  "visual_style_rules": ["rule1", "rule2", ...],\n'
        '  "recurring_characters": [{"name":"...","description":"..."}],\n'
        '  "recurring_locations": ["location1", "location2", ...],\n'
        '  "do_not_change": ["consistency rule 1", ...],\n'
        '  "story_arc": {\n'
        '    "beginning": "1-2 sentences: setup, introduce characters",\n'
        '    "rising_action": "1-2 sentences: build tension, develop conflict",\n'
        '    "climax": "1-2 sentences: peak moment, major turning point",\n'
        '    "falling_action": "1-2 sentences: consequences of climax",\n'
        '    "resolution": "1-2 sentences: how the story ends"\n'
        '  },\n'
        '  "scene_outline": [\n'
        '    "Scene 1: brief description of what happens",\n'
        '    "Scene 2: brief description...",\n'
        '    "...continue for ALL planned scenes..."\n'
        '  ],\n'
        '  "total_scenes": 8\n'
        "}\n"
        "IMPORTANT:\n"
        "- Plan the COMPLETE story from start to finish\n"
        "- scene_outline must have exactly total_scenes entries\n"
        "- Each scene should be 1 sentence describing what happens\n"
        "- Story should have satisfying beginning and END\n"
    )


def _planner_user_prompt(premise: str, title_hint: str, opts: StoryOptions) -> str:
    hint = f"Title hint: {title_hint}\n" if title_hint.strip() else ""
    # Calculate recommended scene count based on max_scenes setting
    recommended_scenes = min(opts.max_scenes, 12)  # Default to reasonable length

    return (
        f"{hint}"
        f"Premise:\n{premise.strip()}\n\n"
        "Constraints:\n"
        f"- Visual style (global): {opts.visual_style}\n"
        f"- Aspect ratio: {opts.aspect_ratio}\n"
        "- Create 2-4 recurring characters with clear descriptions.\n"
        "- Create 2-4 recurring locations.\n"
        "- Add 3-5 do_not_change rules (for visual consistency).\n"
        f"- Plan a complete story with {recommended_scenes} scenes (set total_scenes to this).\n"
        "\n"
        "Story Structure Requirements:\n"
        "- story_arc: Write 1-2 sentences for EACH of: beginning, rising_action, climax, falling_action, resolution.\n"
        f"- scene_outline: Write EXACTLY {recommended_scenes} scene descriptions (1 sentence each).\n"
        "- The story MUST have a clear ending - no cliffhangers or 'to be continued'.\n"
        "- Scene 1 = hook/setup, middle scenes = development, final scene = resolution.\n"
    )


def _scene_system_prompt(allow_nsfw: bool, scene_index: int = 1) -> str:
    safety = "No graphic violence. No hate. No illegal instructions."
    if allow_nsfw:
        safety = "Keep it cinematic and safe."

    # Progressive word count guidelines for better pacing
    # Scene 1 = hook (short), later scenes progressively longer
    if scene_index == 1:
        length_guide = (
            "IMPORTANT: Scene 1 is the HOOK. Keep narration SHORT: 25-50 words ONLY.\n"
            "- Focus on a single striking visual moment or action.\n"
            "- NO internal monologue, NO backstory, NO conclusions.\n"
            "- Observable action only - what the camera sees.\n"
            "- End on intrigue, not resolution.\n"
        )
        narration_hint = "string (25-50 words, 1-2 sentences MAX)"
    elif scene_index == 2:
        length_guide = "Scene 2: Build on the hook. Narration: 40-70 words (2-3 sentences).\n"
        narration_hint = "string (40-70 words, 2-3 sentences)"
    elif scene_index == 3:
        length_guide = "Scene 3: Develop the story. Narration: 60-100 words (3-4 sentences).\n"
        narration_hint = "string (60-100 words, 3-4 sentences)"
    else:
        length_guide = f"Scene {scene_index}: Full narrative mode. Narration: 80-120 words (4-6 sentences).\n"
        narration_hint = "string (80-120 words, 4-6 sentences)"

    return (
        "You write ONE scene for a story that will be rendered as one image + narration.\n"
        "Output STRICT JSON ONLY (no markdown).\n"
        f"Safety rules: {safety}\n"
        f"\n{length_guide}\n"
        "JSON schema:\n"
        "{\n"
        f'  "narration": "{narration_hint}",\n'
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
    total_scenes = bible.total_scenes or 8
    scene_outline = bible.scene_outline or []
    story_arc = bible.story_arc or {}

    # Determine which part of the story arc we're in
    if idx == 1:
        arc_phase = "BEGINNING (Setup/Hook)"
        arc_context = story_arc.get("beginning", "Introduce the story")
    elif idx <= total_scenes * 0.3:
        arc_phase = "RISING ACTION"
        arc_context = story_arc.get("rising_action", "Build tension")
    elif idx <= total_scenes * 0.6:
        arc_phase = "APPROACHING CLIMAX"
        arc_context = story_arc.get("climax", "Major turning point")
    elif idx < total_scenes:
        arc_phase = "FALLING ACTION"
        arc_context = story_arc.get("falling_action", "Consequences")
    else:
        arc_phase = "RESOLUTION (FINAL SCENE)"
        arc_context = story_arc.get("resolution", "Conclusion")

    # Get the planned scene outline for this scene
    scene_plan = ""
    if scene_outline and 0 < idx <= len(scene_outline):
        scene_plan = f"\nPLANNED FOR THIS SCENE: {scene_outline[idx - 1]}\n"

    # Scene-specific pacing reminder (reinforces system prompt)
    if idx == 1:
        pacing_reminder = (
            "REMEMBER: This is Scene 1 - the HOOK.\n"
            "- Keep narration to 25-50 words ONLY (1-2 sentences).\n"
            "- Show a single striking moment. No backstory. No internal thoughts.\n"
            "- End on intrigue, not resolution.\n\n"
        )
    elif idx == total_scenes:
        pacing_reminder = (
            f"REMEMBER: This is the FINAL SCENE ({idx}/{total_scenes}) - RESOLUTION.\n"
            "- This MUST conclude the story satisfactorily.\n"
            "- Tie up loose ends. Provide closure.\n"
            "- 80-120 words narration.\n\n"
        )
    elif idx == 2:
        pacing_reminder = "Pacing: Scene 2 - build on the hook. 40-70 words.\n\n"
    elif idx == 3:
        pacing_reminder = "Pacing: Scene 3 - develop the story. 60-100 words.\n\n"
    else:
        pacing_reminder = f"Pacing: Scene {idx} - full narrative. 80-120 words.\n\n"

    return (
        f"Story title: {bible.title}\n"
        f"Logline: {bible.logline}\n"
        f"Setting: {bible.setting}\n\n"
        f"=== STORY PROGRESS: Scene {idx} of {total_scenes} ===\n"
        f"Story Phase: {arc_phase}\n"
        f"Arc Context: {arc_context}\n"
        f"{scene_plan}\n"
        + pacing_reminder
        + "Visual rules:\n"
        + "\n".join(f"- {x}" for x in (bible.visual_style_rules or []))
        + "\n\n"
        "Do not change:\n"
        + "\n".join(f"- {x}" for x in (bible.do_not_change or []))
        + "\n\n"
        "Recurring characters:\n"
        + "\n".join(f"- {c.get('name','?')}: {c.get('description','')}" for c in (bible.recurring_characters or []))
        + "\n\n"
        f"Summary so far:\n{state.summary_so_far}\n\n"
        f"Scene number: {idx} of {total_scenes}\n"
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

    base_url = ollama_base_url or OLLAMA_BASE_URL
    # Fallback chain for model: explicit param -> config -> hardcoded default
    # This prevents empty model string which causes Ollama to fail
    model = ollama_model or OLLAMA_MODEL or "llama3:8b"

    # First attempt with JSON mode and stop tokens for robustness
    print(f"[STORY] Generating story bible with model: {model}")
    text = await _ollama_chat(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        temperature=0.0,
        max_tokens=750,
        base_url=base_url,
        model=model,
        response_format="json",
        stop=_JSON_STOP_DEFAULT,
    )

    # Debug: Log what we got back
    if text.strip():
        print(f"[STORY] LLM response length: {len(text)} chars")
        print(f"[STORY] LLM response (first 300 chars): {text[:300]}")
    else:
        print(f"[STORY] WARNING: LLM returned empty response!")

    # Handle truncation with continuation, then use robust parsing
    text = await _continue_if_truncated(sys_msg=sys_msg, base_url=base_url, model=model, raw=text, max_tokens=260)
    obj = _extract_json_robust(text) if text.strip() else {}

    # Retry once if JSON is invalid/empty (truncation or model misbehavior)
    if not obj:
        print(f"[STORY] First attempt failed (empty or invalid JSON), retrying with repair prompt...")
        if text.strip():
            print(f"[STORY] Failed text (first 500 chars): {text[:500]}")

        repair_user = (
            "Your previous output was invalid JSON or incomplete.\n"
            "Return ONLY valid JSON matching this schema and NOTHING else.\n"
            "Must be parseable by json.loads(). Must end with a single '}'.\n"
            "Schema:\n"
            '{"title":"string","logline":"string","setting":"string",'
            '"visual_style_rules":["..."],'
            '"recurring_characters":[{"name":"...","description":"..."}],'
            '"recurring_locations":["..."],'
            '"do_not_change":["..."]}\n\n'
            f"Premise:\n{premise.strip()}\n"
        )

        text = await _ollama_chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": repair_user}],
            temperature=0.0,
            max_tokens=900,
            base_url=base_url,
            model=model,
            response_format="json",
            stop=_JSON_STOP_DEFAULT,
        )

        text = await _continue_if_truncated(sys_msg=sys_msg, base_url=base_url, model=model, raw=text, max_tokens=260)
        obj = _extract_json_robust(text) if text.strip() else {}

    # Final check for empty/invalid JSON
    if not obj:
        raise RuntimeError(
            f"LLM did not return valid JSON for story bible after retry. "
            f"Raw response (first 500 chars): {text[:500] if text else '(empty)'}"
        )

    # Normalize the JSON to handle different LLM output formats
    obj = _normalize_story_bible_json(obj)

    try:
        bible = StoryBible.model_validate(obj)
    except Exception as e:
        print(f"[STORY] WARNING: Failed to parse story bible, using fallback. Error: {e}")
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
    # Use the bible's planned total_scenes if available, otherwise fall back to opts.max_scenes
    total_planned_scenes = bible.total_scenes if bible.total_scenes > 0 else opts.max_scenes
    max_allowed = min(total_planned_scenes, opts.max_scenes)

    if idx > max_allowed:
        raise ValueError(f"Story complete! All {max_allowed} scenes have been generated.")

    sys_msg = _scene_system_prompt(allow_nsfw=opts.allow_nsfw, scene_index=idx)
    user_msg = _scene_user_prompt(bible=bible, state=state, idx=idx, opts=opts)

    base_url = ollama_base_url or OLLAMA_BASE_URL
    # Fallback chain for model: explicit param -> config -> hardcoded default
    model = ollama_model or OLLAMA_MODEL or "llama3:8b"

    print(f"[STORY] Generating scene {idx} with model: {model}")
    raw = await _ollama_chat(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        temperature=0.0,
        max_tokens=650,
        base_url=base_url,
        model=model,
        response_format="json",
        stop=_JSON_STOP_DEFAULT,
    )

    # Debug: Log what we got back
    if raw.strip():
        print(f"[STORY] Scene {idx} LLM response length: {len(raw)} chars")
    else:
        print(f"[STORY] WARNING: Scene {idx} LLM returned empty response!")

    # Handle truncation with continuation, then use robust parsing
    raw = await _continue_if_truncated(sys_msg=sys_msg, base_url=base_url, model=model, raw=raw, max_tokens=240)
    obj = _extract_json_robust(raw) if raw.strip() else {}

    # Retry once if JSON is invalid/empty
    if not obj:
        print(f"[STORY] Scene {idx} first attempt failed (empty or invalid JSON), retrying...")
        if raw.strip():
            print(f"[STORY] Failed raw (first 500 chars): {raw[:500]}")

        # Scene-specific word count hint for retry
        if idx == 1:
            word_hint = "25-50 words (SHORT hook only)"
        elif idx == 2:
            word_hint = "40-70 words"
        elif idx == 3:
            word_hint = "60-100 words"
        else:
            word_hint = "80-120 words"

        repair_user = (
            "Your previous output was invalid JSON or incomplete.\n"
            "Return ONLY valid JSON for ONE scene and NOTHING else.\n"
            f"IMPORTANT: Scene {idx} narration must be {word_hint}.\n"
            "Schema:\n"
            f'{{"narration":"string ({word_hint})",'
            '"image_prompt":"string (single prompt)",'
            '"negative_prompt":"string",'
            '"duration_s":7,'
            '"tags":{"location":"...","camera":"...","mood":"...","beat":"..."}}\n\n'
            f"Story: {bible.title}\n"
            f"Scene number: {idx}\n"
        )

        raw = await _ollama_chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": repair_user}],
            temperature=0.0,
            max_tokens=750,
            base_url=base_url,
            model=model,
            response_format="json",
            stop=_JSON_STOP_DEFAULT,
        )

        raw = await _continue_if_truncated(sys_msg=sys_msg, base_url=base_url, model=model, raw=raw, max_tokens=240)
        obj = _extract_json_robust(raw) if raw.strip() else {}

    # Final check for invalid/empty JSON
    if not obj:
        raise RuntimeError(
            f"LLM did not return valid JSON for scene generation after retry. "
            f"Raw response (first 500 chars): {raw[:500] if raw else '(empty)'}"
        )

    narration = _clamp_text(str(obj.get("narration") or ""), 2000)
    image_prompt = _clamp_text(str(obj.get("image_prompt") or ""), 2000)
    negative_prompt = _clamp_text(str(obj.get("negative_prompt") or ""), 800)
    duration_s = int(obj.get("duration_s") or 7)
    duration_s = max(3, min(30, duration_s))
    tags = obj.get("tags") if isinstance(obj.get("tags"), dict) else {}

    # Log warning if fallbacks are used but don't silently fail
    if not narration:
        print(f"[STORY] WARNING: No narration in LLM response, using fallback for scene {idx}")
        narration = f"Scene {idx}: The story continues."
    if not image_prompt:
        print(f"[STORY] WARNING: No image_prompt in LLM response, using fallback for scene {idx}")
        image_prompt = f"{bible.setting}. {opts.visual_style}. cinematic still."

    if opts.refine_image_prompt:
        ref_sys = _refine_system_prompt()
        ref_user = _refine_user_prompt(bible=bible, raw_prompt=image_prompt, raw_negative=negative_prompt, opts=opts)
        ref_raw = await _ollama_chat(
            [{"role": "system", "content": ref_sys}, {"role": "user", "content": ref_user}],
            temperature=0.0,
            max_tokens=280,
            base_url=(ollama_base_url or OLLAMA_BASE_URL),
            model=(ollama_model or OLLAMA_MODEL),
            response_format="json",
            stop=_JSON_STOP_DEFAULT,
        )
        ref_raw = await _continue_if_truncated(
            sys_msg=ref_sys,
            base_url=(ollama_base_url or OLLAMA_BASE_URL),
            model=(ollama_model or OLLAMA_MODEL),
            raw=ref_raw,
            max_tokens=140,
        )
        ref_obj = _extract_json_robust(ref_raw)
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
