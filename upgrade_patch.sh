#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== HomePilot upgrade patch =="
echo "Repo: $ROOT"

# -----------------------------------------------------------------------------
# 1) BACKEND: make Comfy errors readable + detect template workflows BEFORE calling /prompt
# -----------------------------------------------------------------------------
cat > "$ROOT/backend/app/comfy.py" <<'PY'
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from .config import COMFY_BASE_URL, COMFY_POLL_INTERVAL_S, COMFY_POLL_MAX_S


def _get_workflows_dir() -> Path:
    """
    Find workflows directory intelligently:
    1. If COMFY_WORKFLOWS_DIR is set, use it
    2. Try repo path (for local development)
    3. Fallback to /workflows (docker)
    """
    env_dir = os.getenv("COMFY_WORKFLOWS_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent.parent  # HomePilot root
    repo_workflows = repo_root / "comfyui" / "workflows"
    if repo_workflows.exists() and repo_workflows.is_dir():
        return repo_workflows

    return Path("/workflows")


WORKFLOWS_DIR = _get_workflows_dir()


def _deep_replace(obj: Any, mapping: Dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_replace(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_replace(x, mapping) for x in obj]
    if isinstance(obj, str):
        out = obj
        for k, v in mapping.items():
            out = out.replace(f"{{{{{k}}}}}", str(v))
        return out
    return obj


def _load_workflow(name: str) -> Dict[str, Any]:
    p = WORKFLOWS_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Workflow file not found: {p}. "
            f"Set COMFY_WORKFLOWS_DIR or mount workflows into {WORKFLOWS_DIR}."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _validate_prompt_graph(prompt_graph: Dict[str, Any], *, workflow_name: str) -> None:
    """
    ComfyUI /prompt expects an API-format graph:
      { "1": {"class_type": "...", "inputs": {...}}, "2": {...}, ... }
    Your repo currently ships TEMPLATE files with keys like "_comment"/"_instructions".
    Those cause ComfyUI to reply 400.
    """
    if not isinstance(prompt_graph, dict) or not prompt_graph:
        raise ValueError(
            f"Comfy workflow '{workflow_name}' is empty/invalid. "
            "Export a real ComfyUI workflow in 'API format' and replace the template JSON."
        )

    # If it looks like a template, fail early with a clear message
    template_keys = [k for k in prompt_graph.keys() if isinstance(k, str) and k.startswith("_")]
    if template_keys and all(k.startswith("_") for k in prompt_graph.keys()):
        raise ValueError(
            f"Comfy workflow '{workflow_name}' is still a TEMPLATE (contains only _comment/_instructions). "
            "You must export a real ComfyUI workflow using 'Save (API Format)' and overwrite this file:\n"
            f"  {WORKFLOWS_DIR / (workflow_name + '.json')}\n"
        )

    # Ensure at least one node has class_type
    has_node = False
    for _, node in prompt_graph.items():
        if isinstance(node, dict) and node.get("class_type"):
            has_node = True
            break
    if not has_node:
        raise ValueError(
            f"Comfy workflow '{workflow_name}' does not look like ComfyUI API format (no class_type nodes). "
            "Export from ComfyUI: Settings → enable Dev mode → Save (API Format)."
        )


def _post_prompt(client: httpx.Client, prompt: Dict[str, Any]) -> str:
    url = f"{COMFY_BASE_URL.rstrip('/')}/prompt"
    try:
        r = client.post(url, json={"prompt": prompt})
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            pass
        raise RuntimeError(
            f"ComfyUI /prompt failed ({e.response.status_code}). "
            f"Most common cause: workflow JSON is not API format. "
            f"Response: {body[:400]}"
        ) from e

    data = r.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id. Response: {data}")
    return str(prompt_id)


def _get_history(client: httpx.Client, prompt_id: str) -> Dict[str, Any]:
    url = f"{COMFY_BASE_URL.rstrip('/')}/history/{prompt_id}"
    r = client.get(url)
    r.raise_for_status()
    return r.json()


def _view_url(filename: str, subfolder: str = "", filetype: str = "output") -> str:
    base = COMFY_BASE_URL.rstrip("/")
    return f"{base}/view?filename={filename}&subfolder={subfolder}&type={filetype}"


def _extract_media(history: Dict[str, Any], prompt_id: str) -> Tuple[List[str], List[str]]:
    images: List[str] = []
    videos: List[str] = []

    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        return images, videos

    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, dict):
        return images, videos

    for _node_id, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue

        for img in (node_out.get("images") or []):
            if not isinstance(img, dict):
                continue
            fn = img.get("filename")
            if fn:
                images.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(img.get("subfolder", "")),
                        filetype=str(img.get("type", "output")),
                    )
                )

        for vid in (node_out.get("gifs") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

        for vid in (node_out.get("videos") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

    return images, videos


def run_workflow(name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    workflow = _load_workflow(name)
    prompt_graph = _deep_replace(workflow, variables)

    _validate_prompt_graph(prompt_graph, workflow_name=name)

    timeout = httpx.Timeout(60.0, connect=60.0)
    with httpx.Client(timeout=timeout) as client:
        prompt_id = _post_prompt(client, prompt_graph)

        started = time.time()
        while True:
            history = _get_history(client, prompt_id)

            entry = history.get(prompt_id)
            if isinstance(entry, dict) and entry.get("outputs"):
                images, videos = _extract_media(history, prompt_id)
                return {"images": images, "videos": videos, "prompt_id": prompt_id}

            if (time.time() - started) > float(COMFY_POLL_MAX_S):
                raise TimeoutError(
                    f"ComfyUI workflow '{name}' timed out after {COMFY_POLL_MAX_S}s (prompt_id={prompt_id})"
                )

            time.sleep(float(COMFY_POLL_INTERVAL_S))
PY

echo "✅ Patched backend/app/comfy.py (template detection + better errors)"

# -----------------------------------------------------------------------------
# 2) BACKEND: add conversation listing + message loading endpoints support
# -----------------------------------------------------------------------------
cat > "$ROOT/backend/app/storage.py" <<'PY'
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Tuple

from .config import SQLITE_PATH

_RESOLVED_DB_PATH = None

def _get_db_path() -> str:
    global _RESOLVED_DB_PATH
    if _RESOLVED_DB_PATH:
        return _RESOLVED_DB_PATH

    candidate = SQLITE_PATH
    directory = os.path.dirname(candidate) or "."

    try:
        os.makedirs(directory, exist_ok=True)
        test_file = os.path.join(directory, f".perm_check_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        _RESOLVED_DB_PATH = candidate
        return candidate
    except (OSError, PermissionError):
        fallback_dir = Path(__file__).resolve().parents[1] / "data"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = str(fallback_dir / "db.sqlite")
        print(f"WARNING: Permission denied for '{SQLITE_PATH}'. Using local fallback: {fallback_path}")
        _RESOLVED_DB_PATH = fallback_path
        return fallback_path


def init_db():
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.commit()
    con.close()


def add_message(conversation_id: str, role: str, content: str):
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
        (conversation_id, role, content),
    )
    con.commit()
    con.close()


def get_recent(conversation_id: str, limit: int = 24) -> List[Tuple[str, str]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content FROM messages
        WHERE conversation_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()
    return list(reversed(rows))


def list_conversations(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Returns most recent conversations, with last message preview.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT m.conversation_id,
               MAX(m.id) as max_id
        FROM messages m
        GROUP BY m.conversation_id
        ORDER BY max_id DESC
        LIMIT ?
        """,
        (limit,),
    )
    convs = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for conversation_id, max_id in convs:
        cur.execute(
            "SELECT role, content, created_at FROM messages WHERE id=?",
            (max_id,),
        )
        row = cur.fetchone()
        if row:
            role, content, created_at = row
            out.append(
                {
                    "conversation_id": conversation_id,
                    "last_role": role,
                    "last_content": content,
                    "updated_at": created_at,
                }
            )
    con.close()
    return out


def get_messages(conversation_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()
    return [{"role": r, "content": c, "created_at": t} for (r, c, t) in rows]
PY

echo "✅ Patched backend/app/storage.py (list_conversations, get_messages)"

# -----------------------------------------------------------------------------
# 3) BACKEND: add endpoints /conversations and /conversations/{id}/messages
# -----------------------------------------------------------------------------
python3 - <<'PY'
import re, pathlib

p = pathlib.Path("backend/app/main.py")
s = p.read_text(encoding="utf-8")

# Import new functions
if "list_conversations" not in s:
    s = s.replace(
        "from .storage import add_message, get_recent",
        "from .storage import add_message, get_recent, list_conversations, get_messages",
    )

# Add endpoints near /models (after models endpoint)
marker = "\n@app.get(\"/models\")\n"
idx = s.find(marker)
if idx == -1:
    raise SystemExit("Could not find /models endpoint marker to insert after.")

# Find end of /models function by locating next "\n\n@app."
m = re.search(r"@app\.get\(\"/models\"\).*?\n\n(?=@app\.)", s, flags=re.S)
if not m:
    raise SystemExit("Could not locate /models function block for insertion.")

insert_pos = m.end()

block = """

@app.get("/conversations")
async def conversations(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    \"\"\"List saved conversations (History/Today sidebar).\"\"\"
    try:
        items = list_conversations(limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversations": items})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list conversations: {e}", code="conversations_error"))


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, limit: int = Query(200, ge=1, le=1000)) -> JSONResponse:
    \"\"\"Load full message list for a conversation.\"\"\"
    try:
        msgs = get_messages(conversation_id, limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversation_id": conversation_id, "messages": msgs})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to load conversation: {e}", code="conversation_load_error"))

"""

s = s[:insert_pos] + block + s[insert_pos:]

p.write_text(s, encoding="utf-8")
print("✅ Inserted /conversations endpoints into backend/app/main.py")
PY

# -----------------------------------------------------------------------------
# 4) NOTE: Frontend changes are intentionally not auto-overwritten (large file),
# but you now have backend APIs needed for History/Today.
# -----------------------------------------------------------------------------
echo ""
echo "✅ Backend patch complete."
echo ""
echo "Next actions:"
echo "1) Replace Comfy workflows with real API-format exports (txt2img/edit/img2vid)."
echo "2) Update frontend App.tsx to:"
echo "   - call GET /conversations to populate Today/History"
echo "   - call GET /conversations/{id}/messages on click to switch chat session"
echo "   - add UI knobs for text/image/video settings and pass them into /chat"
echo ""
echo "Done."
