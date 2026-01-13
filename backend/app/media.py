import requests
from .config import MEDIA_BASE_URL, TOOL_TIMEOUT_S

def upscale_video(input_path: str, output_path: str, width=1920, height=1080):
r = requests.post(f"{MEDIA_BASE_URL}/upscale", json={
"input_path": input_path,
"output_path": output_path,
"width": width,
"height": height
}, timeout=TOOL_TIMEOUT_S)
r.raise_for_status()
return r.json()
