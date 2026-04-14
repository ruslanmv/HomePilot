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
    # Additive: default True preserves current behavior exactly.
    # Set to False to ship a clean HomePilot without the Chata
    # persona pack pre-installed.
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

            subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                            tpl_remote, f"{tmp}/tpl"], capture_output=True, timeout=60)

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

            # Additive: honor include_personas toggle.
            # - include_personas=True (default): chata-personas bundle stays; the
            #   in-container bootstrap auto-populates Projects on first boot.
            # - include_personas=False: we inject an explicit disable into start.sh
            #   AND delete the bundled chata-personas directory so the user's
            #   HomePilot boots completely clean.
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
