import json
import time
import uuid
import requests
from pathlib import Path
from .config import COMFY_BASE_URL, WORKFLOWS_DIR, TOOL_TIMEOUT_S, COMFY_POLL_INTERVAL_S, COMFY_POLL_MAX_S

def _deep_replace(obj, mapping: dict):
# Recursively replace {{key}} placeholders in ANY string value in the workflow graph.
if isinstance(obj, dict):
return {k: _deep_replace(v, mapping) for k, v in obj.items()}
if isinstance(obj, list):
return [_deep_replace(v, mapping) for v in obj]
if isinstance(obj, str):
out = obj
for k, v in mapping.items():
out = out.replace("{{" + k + "}}", str(v))
return out
return obj

def load_workflow(name: str) -> dict:
p = Path(WORKFLOWS_DIR) / f"{name}.json"
if not p.exists():
raise FileNotFoundError(f"Workflow not found: {p}")
return json.loads(p.read_text(encoding="utf-8"))

def submit_workflow(workflow: dict) -> str:
# ComfyUI /prompt expects {"prompt": <graph>, "client_id": "..."} for many setups.
# Exported ComfyUI workflow JSON is often a dict with node IDs as keys.
client_id = str(uuid.uuid4())
payload = {"prompt": workflow, "client_id": client_id}
r = requests.post(f"{COMFY_BASE_URL}/prompt", json=payload, timeout=TOOL_TIMEOUT_S)
r.raise_for_status()
j = r.json()
# Typically returns {"prompt_id": "...", "number": ...}
return j.get("prompt_id") or j.get("promptId") or j.get("id")

def poll_history(prompt_id: str) -> dict:
# Poll /history/{prompt_id} until outputs appear
deadline = time.time() + COMFY_POLL_MAX_S
last = None
while time.time() < deadline:
r = requests.get(f"{COMFY_BASE_URL}/history/{prompt_id}", timeout=TOOL_TIMEOUT_S)
r.raise_for_status()
j = r.json()
last = j
# When finished, ComfyUI history usually includes "outputs"
if j and isinstance(j, dict):
# Some builds nest under prompt_id key; normalize
if prompt_id in j:
entry = j[prompt_id]
else:
entry = j
if isinstance(entry, dict) and entry.get("outputs"):
return entry
time.sleep(COMFY_POLL_INTERVAL_S)
return last or {}

def extract_media_urls(history_entry: dict):
# Extract filenames from outputs and convert to /view URLs
images = []
videos = []
outputs = history_entry.get("outputs", {}) if isinstance(history_entry, dict) else {}
for _, out in outputs.items():
if not isinstance(out, dict):
continue
# images
if "images" in out and isinstance(out["images"], list):
for img in out["images"]:
fn = img.get("filename")
sub = img.get("subfolder", "")
typ = img.get("type", "output")
if fn:
url = f"{COMFY_BASE_URL}/view?filename={fn}&subfolder={sub}&type={typ}"
images.append(url)
# videos (ComfyUI often stores gifs/mp4s under "gifs" or "videos" or images w/ extension)
for key in ("gifs", "videos"):
if key in out and isinstance(out[key], list):
for v in out[key]:
fn = v.get("filename")
sub = v.get("subfolder", "")
typ = v.get("type", "output")
if fn:
url = f"{COMFY_BASE_URL}/view?filename={fn}&subfolder={sub}&type={typ}"
videos.append(url)

```
# Fallback: if no explicit videos, detect mp4 in images list
if not videos:
    for u in images:
        if ".mp4" in u.lower() or ".webm" in u.lower() or ".gif" in u.lower():
            videos.append(u)

return images, videos
```

def run_workflow(name: str, inputs: dict):
wf = load_workflow(name)
wf = _deep_replace(wf, inputs)
pid = submit_workflow(wf)
if not pid:
raise RuntimeError("ComfyUI did not return prompt_id")
hist = poll_history(pid)
images, videos = extract_media_urls(hist)
return {"prompt_id": pid, "images": images, "videos": videos, "raw": hist}
