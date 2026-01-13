# homepilot/media/app.py
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="HomePilot Media", version="1.0.0")


class UpscaleIn(BaseModel):
    input_path: str = Field(..., description="Path to input video/image on disk")
    output_path: str = Field(..., description="Path to output file on disk")
    width: int = Field(1920, ge=1, le=8192, description="Target width")
    height: int = Field(1080, ge=1, le=8192, description="Target height")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "homepilot-media", "version": app.version}


@app.post("/upscale")
def upscale(inp: UpscaleIn) -> Dict[str, Any]:
    # Basic validation
    if not os.path.exists(inp.input_path):
        raise HTTPException(status_code=404, detail=f"Input not found: {inp.input_path}")

    out_dir = os.path.dirname(inp.output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        inp.input_path,
        "-vf",
        f"scale={inp.width}:{inp.height}:flags=lanczos",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "slow",
        "-pix_fmt",
        "yuv420p",
        inp.output_path,
    ]

    try:
        # Capture output so errors are returned as a clean HTTP error
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg not found in PATH")
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"ffmpeg failed (code {e.returncode}): {e.stderr.strip() or e.stdout.strip()}",
        )

    return {"ok": True, "output_path": inp.output_path}
