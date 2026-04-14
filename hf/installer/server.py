"""
HomePilot Installer — API backend.

Three endpoints:
  POST /api/verify   — validate HF token, return username
  POST /api/install  — create Space, clone template, push
  GET  /             — serve the installer HTML
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="HomePilot Installer")
TEMPLATE = os.environ.get("TEMPLATE_REPO", "ruslanmv/HomePilot")
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/{path:path}")
def static_files(path: str):
    f = STATIC_DIR / path
    if f.exists() and f.is_file():
        return FileResponse(f)
    return JSONResponse({"error": "not found"}, 404)


@app.post("/api/verify")
async def verify(request: Request):
    body = await request.json()
    token = body.get("token", "")
    if not token or len(token) < 8:
        return JSONResponse({"ok": False, "error": "Token vacío"})
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://huggingface.co/api/whoami-v2",
                            headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            name = r.json().get("name", "")
            return {"ok": True, "username": name}
        return JSONResponse({"ok": False, "error": f"HTTP {r.status_code}"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/install")
async def install(request: Request):
    body = await request.json()
    token = body.get("token", "")
    username = body.get("username", "")
    space_name = body.get("space_name", "HomePilot")
    private = body.get("private", True)
    model = body.get("model", "qwen2.5:1.5b")
    # Default True — mirrors the installer UI where the checkbox is
    # pre-ticked.  Callers that omit the field get the 14-persona
    # Starter + Retro pack auto-imported on first boot.  Set to
    # False (or untick the checkbox) for a clean HomePilot.
    include_personas = bool(body.get("include_personas", True))

    if not token or not username:
        return JSONResponse({"ok": False, "error": "Missing token/username"})

    repo_id = f"{username}/{space_name}"
    steps = []

    try:
        # 1. Create Space
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://huggingface.co/api/repos/create",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json"},
                             json={"type": "space", "name": space_name,
                                   "private": private, "sdk": "docker"})
        if r.status_code in (200, 201):
            steps.append("Space creado")
        elif r.status_code == 409:
            steps.append("Space existente — actualizando")
        else:
            return JSONResponse({"ok": False, "error": f"Create failed: {r.text[:200]}",
                                 "steps": steps})

        # 2. Clone template + push
        with tempfile.TemporaryDirectory() as tmp:
            remote = f"https://user:{token}@huggingface.co/spaces/{repo_id}"
            tpl_remote = f"https://user:{token}@huggingface.co/spaces/{TEMPLATE}"

            # Clone the template Space (preferred) OR fall back to the public
            # GitHub source.  HF Spaces 404 until ``sync-hf-spaces.yml`` has
            # successfully run at least once; in that window the installer
            # would previously silently fail later when the staged tpl/
            # directory didn't exist, producing the cryptic
            #   "[Errno 2] No such file or directory: '/tmp/.../tpl'"
            tpl_path = Path(f"{tmp}/tpl")
            tpl_source = None
            tpl_clone = subprocess.run(
                ["git", "-c", "credential.helper=", "clone", "--depth", "1",
                 tpl_remote, str(tpl_path)],
                capture_output=True, timeout=60,
            )
            if tpl_clone.returncode == 0 and tpl_path.exists():
                tpl_source = f"spaces/{TEMPLATE}"
            else:
                # Fallback: clone HomePilot from GitHub master.
                gh_fallback = os.environ.get(
                    "TEMPLATE_GITHUB",
                    f"https://github.com/{TEMPLATE}.git",
                )
                fb = subprocess.run(
                    ["git", "clone", "--depth", "1", gh_fallback, str(tpl_path)],
                    capture_output=True, timeout=120,
                )
                if fb.returncode == 0 and tpl_path.exists():
                    tpl_source = f"github.com/{TEMPLATE} (fallback)"
                else:
                    tpl_err = (
                        tpl_clone.stderr or tpl_clone.stdout or b""
                    ).decode("utf-8", errors="replace")[:300]
                    fb_err = (
                        fb.stderr or fb.stdout or b""
                    ).decode("utf-8", errors="replace")[:300]
                    return JSONResponse({
                        "ok": False,
                        "error": (
                            "HomePilot template is not yet available.  The "
                            "sync-hf-spaces.yml workflow must publish the "
                            f"template Space at {TEMPLATE} first.\n"
                            f"HF clone: {tpl_err.strip() or '<empty>'}\n"
                            f"GH clone: {fb_err.strip() or '<empty>'}"
                        ),
                        "steps": steps,
                    })

            steps.append(f"Template: {tpl_source}")

            clone = subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                                    remote, f"{tmp}/sp"], capture_output=True, timeout=30)
            sp = Path(f"{tmp}/sp")
            if clone.returncode != 0:
                sp.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", "-b", "main", str(sp)], capture_output=True)
                subprocess.run(["git", "-C", str(sp), "remote", "add", "origin", remote],
                               capture_output=True)

            for item in sp.iterdir():
                if item.name != ".git":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()

            tpl = Path(f"{tmp}/tpl")
            for item in tpl.iterdir():
                if item.name == ".git":
                    continue
                dest = sp / item.name
                shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)

            # Copy .gitattributes for LFS
            ga = tpl / ".gitattributes"
            if ga.exists():
                shutil.copy2(ga, sp / ".gitattributes")

            steps.append("Template clonado")

            # Patch model
            start = sp / "start.sh"
            if start.exists():
                start.write_text(start.read_text().replace(
                    "OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:1.5b}",
                    f"OLLAMA_MODEL=${{OLLAMA_MODEL:-{model}}}"))
            steps.append(f"Modelo: {model}")

            # Honor include_personas toggle.
            # - include_personas=True (default, UI checkbox pre-ticked):
            #   chata-personas bundle stays on disk and the in-container
            #   bootstrap auto-populates the 14-persona Starter + Retro
            #   pack as Projects on first boot.
            # - include_personas=False (user unchecked the box): clean
            #   HomePilot.  We inject ``export ENABLE_PROJECT_BOOTSTRAP=false``
            #   into start.sh AND delete the bundled chata-personas
            #   directory so no personas ship in the user's Space at all.
            if not include_personas and start.exists():
                st = start.read_text()
                if "ENABLE_PROJECT_BOOTSTRAP" not in st:
                    marker = "# ── Environment ──────────────────────────────────────────"
                    st = st.replace(
                        marker,
                        marker + "\nexport ENABLE_PROJECT_BOOTSTRAP=false",
                        1,
                    )
                    start.write_text(st)
                for cand in ("chata-personas",
                             "deploy/huggingface-space/chata-personas"):
                    d = sp / cand
                    if d.exists():
                        shutil.rmtree(d, ignore_errors=True)
                steps.append("Chata personas: omitted (clean install)")
            else:
                steps.append("Chata personas: included (auto-imported on first boot)")


            # Git push
            subprocess.run(["git", "lfs", "install", "--local"],
                           capture_output=True, cwd=str(sp))
            subprocess.run(["git", "lfs", "track", "*.hpersona", "*.png", "*.webp"],
                           capture_output=True, cwd=str(sp))
            subprocess.run(["git", "-C", str(sp), "-c", "user.email=i@hp.dev",
                            "-c", "user.name=HP", "add", "-A"],
                           capture_output=True, timeout=30)
            subprocess.run(["git", "-C", str(sp), "-c", "user.email=i@hp.dev",
                            "-c", "user.name=HP", "commit", "-m",
                            f"HomePilot installed ({model})"],
                           capture_output=True, timeout=30)
            push = subprocess.run(["git", "-C", str(sp), "push", "--force",
                                   remote, "HEAD:main"],
                                  capture_output=True, text=True, timeout=120)
            if push.returncode != 0:
                return JSONResponse({"ok": False, "error": push.stderr[:300], "steps": steps})

            steps.append("Desplegado")

        url = f"https://huggingface.co/spaces/{repo_id}"
        return {"ok": True, "repo_id": repo_id, "url": url, "steps": steps}

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "steps": steps})
