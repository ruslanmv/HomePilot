from __future__ import annotations

import uuid
from pathlib import Path

from .models import WorkingFiles


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def studio_exports_root() -> Path:
    p = repo_root() / "backend" / "data" / "studio_exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def files_public_root() -> Path:
    p = repo_root() / "backend" / "data" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_working_files(project_id: str, export_id: str | None = None) -> WorkingFiles:
    export_id = export_id or uuid.uuid4().hex
    workdir = studio_exports_root() / project_id / export_id
    sources = workdir / "sources"
    renders = workdir / "renders"
    sources.mkdir(parents=True, exist_ok=True)
    renders.mkdir(parents=True, exist_ok=True)

    return WorkingFiles(
        workdir=workdir,
        sources_dir=sources,
        renders_dir=renders,
        concat_list_path=workdir / "concat.txt",
        subtitles_path=workdir / "subtitles.srt",
        final_output_path=workdir / "final.mp4",
        thumbnail_path=workdir / "thumbnail.jpg",
        manifest_path=workdir / "export_manifest.json",
    )
