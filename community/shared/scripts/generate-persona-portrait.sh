#!/usr/bin/env bash
#
# generate-persona-portrait.sh — create the STANDARD community-persona portrait.
#
# Wrapper around generate_persona_portrait.py that (a) bootstraps Pillow, and
# (b) documents how to create images inside the Claude Code / CI sandbox where
# there is no GPU and no image tooling preinstalled.
#
# ── The standard (see docs/PERSONA_PORTRAIT_STANDARD.md) ─────────────────────
#   assets/avatar_<prefix>.png         512x512  PNG   square, synthetic face
#   assets/thumb_avatar_<prefix>.webp  256x256  WebP  gallery thumbnail
#
# ── Source priority ──────────────────────────────────────────────────────────
#   PRIMARY  : our custom local StyleGAN2 generator (offline, deterministic).
#   FALLBACK : thispersondoesnotexist.com (keyless; works in the sandbox).
#
# ── Sandbox notes for AI coders (Claude Code) ────────────────────────────────
#   * No image libs are preinstalled. pypi.org is directly reachable through
#     the agent proxy, so `pip install Pillow` works. This script does it.
#   * There is no GPU and StyleGAN2 weights are ~360 MB, so the LOCAL path is
#     usually unavailable in-sandbox → it transparently falls back to the web
#     source. That is expected and fine; the faces are still fully synthetic.
#   * To PICK a face visually: pass --candidates N --contact-sheet PATH, then
#     open/Read the sheet PNG, then re-run with --use-file on the winner.
#
# Usage:
#   community/shared/scripts/generate-persona-portrait.sh \
#       community/shared/bundles/nexus_secretary nexus [extra args...]
#
# Examples:
#   # 6 candidates → contact sheet (then Read it and choose)
#   ... nexus_secretary nexus --candidates 6 --contact-sheet /tmp/sheet.png
#   # commit the chosen candidate into the bundle + repack .hpersona
#   ... nexus_secretary nexus --use-file /tmp/persona_faces/candidate_1.jpg
#   # maintainer, deterministic local StyleGAN2
#   ... nexus_secretary nexus --source local --seed 42
#
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <bundle-dir> <prefix> [extra args passed to the python tool]" >&2
  echo "  e.g. $0 community/shared/bundles/nexus_secretary nexus --candidates 6 --contact-sheet /tmp/sheet.png" >&2
  exit 2
fi

BUNDLE="$1"; PREFIX="$2"; shift 2
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${SCRIPT_DIR}/generate_persona_portrait.py"

# Prefer python3; ensure pip is present.
PYBIN="$(command -v python3 || command -v python)"
if [[ -z "${PYBIN}" ]]; then echo "[error] python not found" >&2; exit 1; fi

# Bootstrap Pillow up-front (idempotent; pypi is reachable in the sandbox).
if ! "${PYBIN}" -c "import PIL" >/dev/null 2>&1; then
  echo "[setup] installing Pillow ..."
  "${PYBIN}" -m pip install --quiet Pillow
fi

echo "[run] ${PY} --bundle ${BUNDLE} --prefix ${PREFIX} $*"
exec "${PYBIN}" "${PY}" --bundle "${BUNDLE}" --prefix "${PREFIX}" "$@"
