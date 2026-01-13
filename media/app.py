from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import os

app = FastAPI(title="HomePilot Media", version="1.0.0")

class UpscaleIn(BaseModel):
input_path: str
output_path: str
width: int = 1920
height: int = 1080

@app.get("/health")
def health():
return {"ok": True}

@app.post("/upscale")
def upscale(inp: UpscaleIn):
os.makedirs(os.path.dirname(inp.output_path), exist_ok=True)
cmd = [
"ffmpeg", "-y",
"-i", inp.input_path,
"-vf", f"scale={inp.width}:{inp.height}:flags=lanczos",
"-c:v", "libx264", "-crf", "18", "-preset", "slow",
"-pix_fmt", "yuv420p",
inp.output_path
]
subprocess.run(cmd, check=True)
return {"output_path": inp.output_path}
