# backend/app/studio/exports_repo.py
"""
Export artifacts repository.
Stores export metadata in-memory (can be swapped for DB later).
"""
import time
import threading
from typing import Dict, List, Optional

from .models import ExportArtifact, ExportKind

_LOCK = threading.Lock()
_EXPORTS: Dict[str, ExportArtifact] = {}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def add_export(project_id: str, kind: ExportKind, url: str, filename: str, bytes_: int = 0) -> ExportArtifact:
    now = time.time()
    art = ExportArtifact(
        id=_new_id("exp"),
        projectId=project_id,
        kind=kind,
        url=url,
        filename=filename,
        bytes=bytes_,
        createdAt=now,
    )
    with _LOCK:
        _EXPORTS[art.id] = art
    return art


def list_exports(project_id: str) -> List[ExportArtifact]:
    with _LOCK:
        return [e for e in _EXPORTS.values() if e.projectId == project_id]


def latest_export(project_id: str, kind: ExportKind) -> Optional[ExportArtifact]:
    items = [e for e in list_exports(project_id) if e.kind == kind]
    if not items:
        return None
    return sorted(items, key=lambda x: x.createdAt, reverse=True)[0]
