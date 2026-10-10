#!/usr/bin/env python3
"""Refresh the FitLab snapshots bundled with HomePilot (backend/app/model_advisor/data/).

Every HomePilot release ships these, so the Model Advisor has current suggestions even on a
machine that never goes online. Run it before a release; users get newer definitions with
"Fetch definitions" or the optional daily check.

Only what HomePilot reads is kept: chat and vision models HomePilot can install (an Ollama
tag), their sizing fields, FitLab's measured benchmarks and calibration; the media lane as
published; and name/memory/bandwidth for each GPU profile.

Usage:
  python backend/scripts/update_fitlab_snapshot.py                 # from FitLab on GitHub
  python backend/scripts/update_fitlab_snapshot.py --from-dir ../fitlab   # from a local checkout
  python backend/scripts/update_fitlab_snapshot.py --check          # exit 1 if a snapshot is older than 21 days
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "model_advisor" / "data"
RAW = "https://raw.githubusercontent.com/ruslanmv/fitlab/{ref}/data/{name}"
SOURCES = {
    "registry.json": ("registry-latest", "master"),
    "media_registry.json": ("registry-latest", "master"),
    "gpu_catalog.json": ("master",),
}
LLM_CATEGORIES = {"text-generation", "image-text-to-text"}
LLM_FIELDS = ("id", "hf_id", "category", "capabilities", "params_b", "active_params_b", "license",
              "ollama_tag", "status")
GPU_FIELDS = ("id", "name", "model", "aliases", "vram_gb", "bandwidth_gbs", "form_factor", "vendor")


def _get(name: str, from_dir: Path | None) -> dict:
    if from_dir:
        return json.loads((from_dir / "data" / name).read_text(encoding="utf-8"))
    errors = []
    for ref in SOURCES[name]:
        url = RAW.format(ref=ref, name=name)
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise SystemExit(f"could not fetch {name}:\n  " + "\n  ".join(errors))


def trim_registry(reg: dict) -> dict:
    models = {}
    for mid, m in reg["models"].items():
        if m.get("category") not in LLM_CATEGORIES or m.get("status") == "stale":
            continue
        if not m.get("ollama_tag") or not m.get("arch") or not m.get("params_b"):
            continue
        slim = {k: m[k] for k in LLM_FIELDS if m.get(k) is not None}
        slim["arch"] = {k: m["arch"][k] for k in ("n_layers", "n_kv_heads", "head_dim") if k in m["arch"]}
        slim["hf_stats"] = {"downloads_30d": int((m.get("hf_stats") or {}).get("downloads_30d") or 0)}
        models[mid] = slim
    return {
        "schema_version": reg["schema_version"],
        "ranking_version": reg.get("ranking_version"),
        "generated_at": reg["generated_at"],
        "calibration": reg.get("calibration") or {},
        "benchmarks_latest": {k: {"gen_tps": v.get("gen_tps"), "date": v.get("date")}
                              for k, v in (reg.get("benchmarks_latest") or {}).items()},
        "compat": {k: {"ok": bool(v.get("ok"))} for k, v in (reg.get("compat") or {}).items()
                   if isinstance(v, dict)},
        "models": models,
    }


def trim_gpus(cat: dict) -> dict:
    return {"schema_version": cat.get("schema_version"), "updated_at": cat.get("updated_at"),
            "gpus": [{k: g[k] for k in GPU_FIELDS if k in g} for g in cat["gpus"]]}


def _write(path: Path, doc: dict) -> bool:
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def check(max_age_days: int) -> int:
    today = datetime.date.today()
    stale = 0
    for name in ("fitlab_registry.snapshot.json", "fitlab_media.snapshot.json"):
        doc = json.loads((OUT / name).read_text(encoding="utf-8"))
        age = (today - datetime.date.fromisoformat(doc["generated_at"])).days
        print(f"{name}: generated {doc['generated_at']} ({age} days ago)")
        stale += age > max_age_days
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-dir", type=Path, help="a local FitLab checkout instead of GitHub")
    ap.add_argument("--check", action="store_true", help="only report the snapshots' age")
    ap.add_argument("--max-age-days", type=int, default=21)
    args = ap.parse_args(argv)
    if args.check:
        return check(args.max_age_days)

    OUT.mkdir(parents=True, exist_ok=True)
    reg = trim_registry(_get("registry.json", args.from_dir))
    media = _get("media_registry.json", args.from_dir)
    gpus = trim_gpus(_get("gpu_catalog.json", args.from_dir))
    if not reg["models"] or not media.get("models") or not gpus["gpus"]:
        raise SystemExit("refusing to write an empty snapshot")
    changed = [name for name, doc in (("fitlab_registry.snapshot.json", reg),
                                      ("fitlab_media.snapshot.json", media),
                                      ("fitlab_gpus.json", gpus)) if _write(OUT / name, doc)]
    print(f"registry {reg['generated_at']}: {len(reg['models'])} installable chat/vision models · "
          f"media {media['generated_at']}: {len(media['models'])} models · {len(gpus['gpus'])} GPU profiles")
    print("changed: " + (", ".join(changed) if changed else "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
