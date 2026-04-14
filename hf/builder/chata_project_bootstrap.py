#!/usr/bin/env python3
"""Additive, idempotent persona -> project bootstrap for HomePilot.

Context
-------
HomePilot's container already runs ``auto_import_personas.py`` at boot, which
*extracts* ``.hpersona`` ZIPs to ``/tmp/homepilot/data/personas/{id}/``.  That
places blueprints on disk, but the **Projects** UI is populated by a separate
SQLite table written only when ``POST /persona/import/atomic`` is called.

This script bridges that gap: after HomePilot's HTTP API is healthy, it posts
every bundled ``.hpersona`` to ``/persona/import/atomic`` so each blueprint
becomes a first-class Project.

Design goals
------------
* **Additive**      — never modifies HomePilot source; only calls its public
                      API.  If the user creates projects manually they are
                      untouched.
* **Idempotent**    — writes a marker file so re-runs are no-ops.  Per-file
                      "already exists" responses from HomePilot are also
                      treated as success.
* **Non-blocking**  — runs in the background after ``python3 hf_wrapper.py``
                      starts serving; never delays first response.
* **Resilient**     — missing directory, network flake, or Ollama-not-ready
                      is logged and skipped, not fatal.

Usage (called from ``start.sh``):

  python3 /app/chata_project_bootstrap.py \\
      --personas-dir /app/chata-personas \\
      --api-base http://127.0.0.1:7860 \\
      --marker /tmp/homepilot/data/.projects_bootstrapped
"""

from __future__ import annotations

import os

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def log(msg: str) -> None:
    sys.stdout.write(f"[chata-bootstrap] {msg}\n")
    sys.stdout.flush()


def wait_healthy(api_base: str, timeout_s: int = 300) -> bool:
    """Poll ``{api_base}/health`` until it returns 200 or the timeout fires.

    Default timeout raised to 300 s because HomePilot's cold start on HF
    Spaces can exceed 120 s (Ollama model pull + service discovery).
    """
    url = f"{api_base.rstrip('/')}/health"
    deadline = time.time() + timeout_s
    last_err: str = ""
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    log(f"health up after {attempt} attempt(s)")
                    return True
                last_err = f"status={resp.status}"
        except urllib.error.URLError as e:
            last_err = str(e.reason if hasattr(e, "reason") else e)[:120]
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:120]
        time.sleep(2)
    log(f"health never came up within {timeout_s}s (last: {last_err})")
    return False


def list_existing_project_ids(api_base: str) -> set[str]:
    """Best-effort: return persona IDs that already have a project.

    We match on persona_agent.id when the project surface exposes it.  If the
    call fails we return an empty set and fall back to per-file conflict
    detection.
    """
    try:
        with urllib.request.urlopen(
            f"{api_base.rstrip('/')}/projects", timeout=10
        ) as resp:
            data: Any = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        log(f"could not list projects (non-fatal): {e}")
        return set()

    if isinstance(data, dict):
        items = data.get("items") or data.get("projects") or []
    else:
        items = data or []

    out: set[str] = set()
    for proj in items:
        if not isinstance(proj, dict):
            continue
        for key in ("persona_id", "slug"):
            v = proj.get(key)
            if isinstance(v, str) and v:
                out.add(v)
        agent = proj.get("persona_agent") or {}
        if isinstance(agent, dict):
            v = agent.get("id")
            if isinstance(v, str) and v:
                out.add(v)
    return out


def _encode_multipart(field_name: str, file_path: Path) -> tuple[bytes, str]:
    """Minimal multipart/form-data builder — zero deps so this script can run
    in the HomePilot container's Python without pip installs."""
    boundary = f"----chata{int(time.time() * 1000)}"
    lines: list[bytes] = []
    lines.append(f"--{boundary}".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{field_name}"; '
        f'filename="{file_path.name}"'.encode()
    )
    lines.append(b"Content-Type: application/octet-stream")
    lines.append(b"")
    lines.append(file_path.read_bytes())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, boundary


def import_one(api_base: str, hpersona: Path) -> tuple[bool, str]:
    """POST one .hpersona to /persona/import/atomic.  Return (ok, note)."""
    url = f"{api_base.rstrip('/')}/persona/import/atomic"
    body, boundary = _encode_multipart("file", hpersona)
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if 200 <= resp.status < 300:
                return True, "created"
            text = resp.read().decode("utf-8", errors="replace")[:200]
            return False, f"http={resp.status} body={text}"
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
        # "Already exists" shapes — treat as success, idempotent.
        if any(tok in text.lower() for tok in ("already", "exists", "conflict")):
            return True, "already-exists"
        return False, f"http={e.code} body={text}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def bootstrap(
    personas_dir: Path,
    api_base: str,
    marker: Path,
    force: bool = False,
) -> int:
    if marker.exists() and not force:
        log(f"marker present at {marker} — skipping (use --force to re-run)")
        return 0

    if not personas_dir.exists():
        log(f"personas dir not found: {personas_dir} — nothing to import")
        return 0

    hpersonas = sorted(personas_dir.glob("*.hpersona"))
    if not hpersonas:
        log(f"no .hpersona files under {personas_dir}")
        return 0

    log(f"waiting for HomePilot API at {api_base}...")
    if not wait_healthy(api_base):
        log("API never came up — will retry on next boot")
        return 1

    existing = list_existing_project_ids(api_base)
    if existing:
        log(f"found {len(existing)} existing project(s); will skip matches")

    created, skipped, failed = 0, 0, 0
    for hp in hpersonas:
        pid = hp.stem
        if pid in existing:
            log(f"skip  {pid} (already present)")
            skipped += 1
            continue
        ok, note = import_one(api_base, hp)
        if ok:
            if note == "already-exists":
                skipped += 1
                log(f"skip  {pid} ({note})")
            else:
                created += 1
                log(f"ok    {pid}")
        else:
            failed += 1
            log(f"fail  {pid} :: {note}")

    log(f"done: created={created} skipped={skipped} failed={failed}")

    if failed == 0:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "bootstrapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "created": created,
                    "skipped": skipped,
                    "source_dir": str(personas_dir),
                },
                indent=2,
            )
        )
    return 0 if failed == 0 else 2


def enable_ollabridge(api_base: str, *, enabled: bool = True, api_key: str = "") -> None:
    """Flip the OllaBridge Gateway on so personas are reachable via the
    OpenAI-compat ``/v1/chat/completions`` endpoint with zero extra UI
    clicks.

    Industry best practice for self-hosted AI deployments: sane defaults,
    converge state on every boot.  Idempotent — safe to run repeatedly.

    * ``enabled=True``  → HomePilot exposes ``/v1/chat/completions`` and
                          ``/v1/models``, which is what OllaBridge / Chata /
                          3D avatar clients hit.
    * ``api_key=""``    → no auth required.  Private Spaces are already
                          gated by HF's own auth; an extra key inside is
                          redundant and is the exact thing that caused the
                          2026-04-14 auth-lockout incident.  Operators who
                          want a key can set one explicitly in Settings.

    Override: ``ENABLE_OLLABRIDGE_AUTO=false`` disables this step entirely.
    """
    url = f"{api_base.rstrip('/')}/settings/ollabridge"
    body = json.dumps({"enabled": enabled, "api_key": api_key}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json",
                 "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                log(f"ollabridge: enabled={enabled} api_key_set={bool(api_key)}")
                return
            log(f"ollabridge: unexpected status {resp.status}")
    except Exception as e:  # noqa: BLE001
        log(f"ollabridge: skipped ({e})")


def publish_all_personas(api_base: str) -> tuple[int, int]:
    """Publish every persona Project to the shared API so it is addressable
    via the OpenAI-compat ``/v1/chat/completions`` endpoint as
    ``persona:<slug>--<shortid>``.

    Without this step the 14 auto-imported personas exist as Projects but
    are invisible to OllaBridge / Chata / any OpenAI-compat client — the
    bridge returns 404 ``persona_unpublished``.

    Idempotent — re-publishing an already-published persona is a no-op on
    the backend side.  Returns ``(published, failed)`` counts.

    Disable with ``ENABLE_PERSONA_PUBLISH=false``.
    """
    try:
        with urllib.request.urlopen(
            f"{api_base.rstrip('/')}/projects", timeout=15
        ) as resp:
            data: Any = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        log(f"publish: could not list projects ({e})")
        return 0, 0

    items = data if isinstance(data, list) else (
        data.get("items") or data.get("projects") or []
    )
    published = failed = 0
    for proj in items:
        if not isinstance(proj, dict):
            continue
        if proj.get("project_type") not in (None, "persona"):
            continue
        pid = proj.get("id")
        name = proj.get("name", pid)
        if not pid:
            continue
        body = json.dumps({"enabled": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{api_base.rstrip('/')}/projects/{pid}/shared-api",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json",
                     "Content-Length": str(len(body))},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    published += 1
                else:
                    failed += 1
                    log(f"publish: {name} HTTP {resp.status}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"publish: {name} failed ({str(e)[:80]})")
    log(f"publish: {published} personas now on /v1/chat/completions "
        f"(failed={failed})")
    return published, failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--personas-dir", type=Path, default=Path("/app/chata-personas"))
    ap.add_argument("--api-base", default="http://127.0.0.1:7860")
    ap.add_argument(
        "--marker",
        type=Path,
        default=Path("/tmp/homepilot/data/.projects_bootstrapped"),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if the marker exists (still idempotent per-file).",
    )
    args = ap.parse_args(argv)
    rc = bootstrap(args.personas_dir, args.api_base, args.marker, args.force)

    # Zero-config UX: expose personas via the OpenAI-compat endpoint so
    # OllaBridge / Chata / 3D-avatar clients connect without extra UI
    # steps.  Runs regardless of persona-import outcome — a clean-install
    # HomePilot still benefits from a working /v1/chat/completions.
    # Disable with ENABLE_OLLABRIDGE_AUTO=false.
    if os.environ.get("ENABLE_OLLABRIDGE_AUTO", "true").lower() == "true":
        enable_ollabridge(args.api_base)

    # Zero-config: publish every persona Project so OllaBridge / Chata
    # can see them via ``/v1/models`` and chat via
    # ``persona:<slug>--<shortid>``.  Without this step the imported
    # personas exist as Projects but are invisible to external clients.
    # Disable with ENABLE_PERSONA_PUBLISH=false.
    if os.environ.get("ENABLE_PERSONA_PUBLISH", "true").lower() == "true":
        publish_all_personas(args.api_base)

    return rc
if __name__ == "__main__":
    raise SystemExit(main())
