"""
Compute registry (PR 2) — persisted sources, devices, manifests, routes, and
settings.

SQLite-backed and fully additive (new tables via ``CREATE TABLE IF NOT
EXISTS``). This is where PR 1's env-only global flags become *persisted user
settings*: ``load_settings()`` starts from ``ComputeSettings.from_env()`` (the
deployment defaults) and overlays whatever the user has saved, so an
unconfigured install behaves exactly as before while the UI can persist
per-model routing on top.

Everything degrades safely: read failures return empty/defaults rather than
raising, so a missing/locked DB can never take down an inference path — the
router just falls back to the legacy global-mode behaviour.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from ..storage import _get_db_path
from .schemas import (
    ComputeDevice,
    ComputeSettings,
    ComputeSource,
    ModelManifest,
    ModelRoute,
)

_SETTINGS_KEY = "settings"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def ensure_tables() -> None:
    con = _conn()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS compute_sources (
                id            TEXT PRIMARY KEY,
                data          TEXT NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compute_devices (
                id            TEXT PRIMARY KEY,
                source_id     TEXT NOT NULL,
                data          TEXT NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compute_manifests (
                id            TEXT PRIMARY KEY,
                data          TEXT NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compute_routes (
                modality      TEXT NOT NULL,
                model_id      TEXT NOT NULL,
                data          TEXT NOT NULL,
                updated_at    REAL NOT NULL,
                PRIMARY KEY (modality, model_id)
            );
            CREATE TABLE IF NOT EXISTS compute_kv (
                key           TEXT PRIMARY KEY,
                data          TEXT NOT NULL,
                updated_at    REAL NOT NULL
            );
            """
        )
        con.commit()
    finally:
        con.close()


def _write(table: str, columns: dict, pk_cols: tuple[str, ...], payload: dict) -> None:
    """Upsert a row. ``columns`` are the indexed/id columns to store; ``pk_cols``
    is the conflict target (must match the table's PRIMARY KEY)."""
    ensure_tables()
    col_names = list(columns.keys()) + ["data", "updated_at"]
    cols = ", ".join(col_names)
    placeholders = ", ".join(["?"] * len(col_names))
    conflict = ", ".join(pk_cols)
    values = (*columns.values(), json.dumps(payload), time.time())
    con = _conn()
    try:
        con.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET data=excluded.data, "
            f"updated_at=excluded.updated_at",
            values,
        )
        con.commit()
    finally:
        con.close()


def _read_all(table: str) -> list[dict]:
    try:
        ensure_tables()
        con = _conn()
        try:
            rows = con.execute(f"SELECT data FROM {table}").fetchall()
        finally:
            con.close()
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data"]))
        except Exception:
            continue
    return out


# ---- sources ----------------------------------------------------------------

def upsert_source(source: ComputeSource) -> ComputeSource:
    _write("compute_sources", {"id": source.id}, ("id",), source.to_dict())
    return source


def list_sources() -> list[ComputeSource]:
    return [ComputeSource.from_dict(d) for d in _read_all("compute_sources")]


def get_source(source_id: str) -> Optional[ComputeSource]:
    for s in list_sources():
        if s.id == source_id:
            return s
    return None


def delete_source(source_id: str) -> None:
    _delete("compute_sources", "id", source_id)


# ---- devices ----------------------------------------------------------------

def upsert_device(device: ComputeDevice) -> ComputeDevice:
    if device.last_heartbeat is None:
        device.last_heartbeat = time.time()
    _write("compute_devices", {"id": device.id, "source_id": device.source_id}, ("id",), device.to_dict())
    return device


def list_devices(source_id: Optional[str] = None) -> list[ComputeDevice]:
    devices = [ComputeDevice.from_dict(d) for d in _read_all("compute_devices")]
    if source_id is not None:
        devices = [d for d in devices if d.source_id == source_id]
    return devices


def get_device(device_id: str) -> Optional[ComputeDevice]:
    for d in list_devices():
        if d.id == device_id:
            return d
    return None


def delete_device(device_id: str) -> None:
    _delete("compute_devices", "id", device_id)


# ---- manifests --------------------------------------------------------------

def upsert_manifest(manifest: ModelManifest) -> ModelManifest:
    _write("compute_manifests", {"id": manifest.id}, ("id",), manifest.to_dict())
    return manifest


def list_manifests() -> list[ModelManifest]:
    return [ModelManifest.from_dict(d) for d in _read_all("compute_manifests")]


def get_manifest(model_id: str) -> Optional[ModelManifest]:
    for m in list_manifests():
        if m.id == model_id:
            return m
    return None


def delete_manifest(model_id: str) -> None:
    _delete("compute_manifests", "id", model_id)


# ---- routes -----------------------------------------------------------------

def upsert_route(route: ModelRoute) -> ModelRoute:
    _write(
        "compute_routes",
        {"modality": route.modality, "model_id": route.model_id},
        ("modality", "model_id"),
        route.to_dict(),
    )
    return route


def list_routes() -> list[ModelRoute]:
    return [ModelRoute.from_dict(d) for d in _read_all("compute_routes")]


def get_route(model_id: str, modality: Optional[str] = None) -> Optional[ModelRoute]:
    """Exact (modality, model_id) match preferred; otherwise the first route for
    the model regardless of modality (a name-only binding)."""
    routes = list_routes()
    if modality is not None:
        for r in routes:
            if r.model_id == model_id and r.modality == modality:
                return r
    for r in routes:
        if r.model_id == model_id:
            return r
    return None


def delete_route(model_id: str, modality: str) -> None:
    try:
        ensure_tables()
        con = _conn()
        try:
            con.execute(
                "DELETE FROM compute_routes WHERE model_id=? AND modality=?",
                (model_id, modality),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


# ---- settings ---------------------------------------------------------------

def load_settings() -> ComputeSettings:
    """Env/deployment defaults overlaid with any persisted overrides."""
    settings = ComputeSettings.from_env()
    try:
        ensure_tables()
        con = _conn()
        try:
            row = con.execute(
                "SELECT data FROM compute_kv WHERE key=?", (_SETTINGS_KEY,)
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return settings
    if not row:
        return settings
    try:
        stored = json.loads(row["data"])
    except Exception:
        return settings
    # Overlay: persisted values win, but unset keys keep env defaults.
    merged = settings.to_dict()
    merged.update({k: v for k, v in stored.items() if v is not None})
    if stored.get("modality_defaults"):
        merged["modality_defaults"] = stored["modality_defaults"]
    return ComputeSettings.from_dict(merged)


def save_settings(settings: ComputeSettings) -> ComputeSettings:
    _write("compute_kv", {"key": _SETTINGS_KEY}, ("key",), settings.to_dict())
    return settings


def _delete(table: str, col: str, value: str) -> None:
    try:
        ensure_tables()
        con = _conn()
        try:
            con.execute(f"DELETE FROM {table} WHERE {col}=?", (value,))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def is_empty() -> bool:
    """True when nothing has been persisted — the router then behaves exactly as
    PR 1 (pure env-driven global mode)."""
    try:
        ensure_tables()
        con = _conn()
        try:
            for table in ("compute_sources", "compute_routes", "compute_kv"):
                if con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    return False
        finally:
            con.close()
    except Exception:
        return True
    return True
