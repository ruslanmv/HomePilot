"""Machine resource metrics endpoint — additive, non-destructive.

Provides GET /v1/system/resources returning GPU, RAM, CPU, and disk
usage.  GPU info comes from nvidia-smi (graceful fallback if missing).
RAM/CPU from psutil, disk from shutil.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

try:
    import psutil  # optional dependency
except ImportError:
    psutil = None  # type: ignore[assignment]

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/system", tags=["system-resources"])


def _status_from_percent(
    percent: float, warn: float, critical: float, good_label: str = "healthy",
) -> str:
    if percent >= critical:
        return "critical"
    if percent >= warn:
        return "warning"
    return good_label


def _get_gpu_info() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, check=True, timeout=2.5,
        )
        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]

        name = parts[0]
        total_mb = int(parts[1])
        used_mb = int(parts[2])
        free_mb = int(parts[3])
        util = int(parts[4])
        temp = int(parts[5])

        free_ratio = free_mb / max(total_mb, 1)
        if free_ratio < 0.15:
            status = "tight"
        elif free_ratio < 0.30:
            status = "warning"
        else:
            status = "good"

        return {
            "available": True,
            "name": name,
            "vram_total_mb": total_mb,
            "vram_used_mb": used_mb,
            "vram_free_mb": free_mb,
            "used_percent": round((used_mb / total_mb) * 100) if total_mb else 0,
            "utilization_percent": util,
            "temperature_c": temp,
            "status": status,
        }
    except Exception:
        return {
            "available": False,
            "name": None,
            "vram_total_mb": None,
            "vram_used_mb": None,
            "vram_free_mb": None,
            "used_percent": None,
            "utilization_percent": None,
            "temperature_c": None,
            "status": "unavailable",
        }


def _get_ram_info() -> Dict[str, Any]:
    if psutil is None:
        return {"total_mb": 0, "used_mb": 0, "available_mb": 0, "percent": 0, "status": "unavailable"}
    vm = psutil.virtual_memory()
    return {
        "total_mb": round(vm.total / 1024 / 1024),
        "used_mb": round(vm.used / 1024 / 1024),
        "available_mb": round(vm.available / 1024 / 1024),
        "percent": round(vm.percent),
        "status": _status_from_percent(vm.percent, 75, 90),
    }


def _get_cpu_info() -> Dict[str, Any]:
    if psutil is None:
        return {
            "name": platform.processor() or platform.machine(),
            "physical_cores": os.cpu_count() or 1,
            "logical_cores": os.cpu_count() or 1,
            "percent": 0,
            "status": "unavailable",
        }
    cpu_pct = psutil.cpu_percent(interval=0.3)
    return {
        "name": platform.processor() or platform.machine(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "percent": round(cpu_pct),
        "status": _status_from_percent(cpu_pct, 60, 85, good_label="normal"),
    }


def _get_disk_info() -> Dict[str, Any]:
    root_path = os.getenv("HOMEPILOT_ROOT", str(Path.cwd()))
    usage = shutil.disk_usage(root_path)
    pct = round((usage.used / usage.total) * 100) if usage.total else 0

    if pct >= 90:
        status = "critical"
    elif pct >= 80:
        status = "warning"
    else:
        status = "healthy"

    return {
        "path": root_path,
        "total_gb": round(usage.total / 1024 / 1024 / 1024),
        "used_gb": round(usage.used / 1024 / 1024 / 1024),
        "free_gb": round(usage.free / 1024 / 1024 / 1024),
        "percent": pct,
        "status": status,
    }


@router.get("/resources")
async def system_resources() -> JSONResponse:
    """Machine capacity: GPU, RAM, CPU, disk."""
    return JSONResponse({
        "gpu": _get_gpu_info(),
        "ram": _get_ram_info(),
        "cpu": _get_cpu_info(),
        "disk": _get_disk_info(),
    })
