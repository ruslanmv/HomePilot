from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .composer import compose_project_export
from .paths import studio_exports_root

router = APIRouter(prefix="/studio/video-export", tags=["studio-video-export"])


class StudioVideoExportIn(BaseModel):
    project_id: str = Field(..., description="Creator Studio project id")
    project: dict[str, Any] = Field(..., description="Project payload including scenes")
    kind: Literal["video_mp4", "youtube_mp4", "shorts_mp4"] = "youtube_mp4"
    public_base_url: str = Field("http://localhost:8000", description="Public backend base URL")


@router.post("")
def export_studio_project_video(inp: StudioVideoExportIn) -> dict[str, Any]:
    try:
        result = compose_project_export(
            project_id=inp.project_id,
            project=inp.project,
            export_kind=inp.kind,
            public_base_url=inp.public_base_url,
        )
        return {"ok": True, "export": result.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Studio export failed: {e}")


@router.get("/files/{project_id}/{export_id}/final.mp4")
def get_exported_video(project_id: str, export_id: str):
    path = studio_exports_root() / project_id / export_id / "final.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Exported video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"{project_id}-{export_id}.mp4")


@router.get("/files/{project_id}/{export_id}/thumbnail.jpg")
def get_exported_thumbnail(project_id: str, export_id: str):
    path = studio_exports_root() / project_id / export_id / "thumbnail.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Exported thumbnail not found")
    return FileResponse(path, media_type="image/jpeg", filename=f"{project_id}-{export_id}.jpg")
