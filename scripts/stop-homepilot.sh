#!/usr/bin/env bash
###############################################################################
# stop-homepilot.sh — stop HomePilot's processes, and nothing else.
#
# Other projects on the same machine may run their own uvicorn, Vite, a
# kubectl port-forward or containers on HomePilot's default ports. The old
# `make stop` killed "whatever listens on :8000" and "every uvicorn
# app.main:app", which took those down too. A process counts as HomePilot's
# only when it belongs to the current user AND its working directory, or a
# path on its command line, is inside this checkout.
#
# Usage: stop-homepilot.sh [--only REGEX] [--label NAME] [--dry-run]
#   --only REGEX  limit to processes whose command line matches REGEX
#   --label NAME  what to call them in the output
#   --dry-run     list what would be stopped, stop nothing
###############################################################################
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ONLY=""
LABEL="HomePilot services"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="${2:-}"; shift 2 ;;
    --label) LABEL="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "stop-homepilot: unknown option $1" >&2; exit 2 ;;
  esac
done

# The commands `make start` and the MCP targets launch — matched on the command itself,
# not on any word, so a terminal that merely sits in this folder is never a match:
# uvicorn (backend, edit-session, avatar, MCP and agentic servers) and its reload workers,
# Vite, ComfyUI, Context Forge, fastmcp servers, and the `make start` wrapper itself
# (recognisable by pick_ports.py in its script).
SERVICES='\.venv/bin/uvicorn|-m uvicorn|multiprocessing\.spawn|node_modules/\.bin/vite|vite/bin/vite\.js|main\.py --listen|start-comfyui\.sh|mcpgateway|server_fastmcp|agentic-start\.sh|mcp-start\.sh|pick_ports\.py'
PATTERN="${ONLY:-$SERVICES}"

# Never stop whoever is asking: this script, make, and the shell that ran it — even when
# that shell's working directory is this checkout.
ANCESTORS=" $$ "
_p=$$
while [ -n "$_p" ] && [ "$_p" != "0" ] && [ "$_p" != "1" ]; do
  _p="$(ps -o ppid= -p "$_p" 2>/dev/null | tr -d ' ')"
  [ -n "$_p" ] && ANCESTORS="$ANCESTORS$_p "
done

cwd_of() {
  if [ -e "/proc/$1" ]; then
    readlink "/proc/$1/cwd" 2>/dev/null
  elif command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n1
  fi
}

args_of() {
  if [ -r "/proc/$1/cmdline" ]; then
    tr '\0' ' ' < "/proc/$1/cmdline"
  else
    ps -o args= -p "$1" 2>/dev/null
  fi
}

ours() {
  local cwd args
  cwd="$(cwd_of "$1")"
  case "$cwd" in "$ROOT"|"$ROOT"/*) return 0 ;; esac
  args="$(args_of "$1")"
  case "$args" in *"$ROOT/"*) return 0 ;; esac
  return 1
}

targets=""
for pid in $(pgrep -u "$(id -u)" -f -- "$PATTERN" 2>/dev/null || true); do
  case "$ANCESTORS" in *" $pid "*) continue ;; esac
  ours "$pid" || continue
  targets="$targets $pid"
done

if [ -z "$targets" ]; then
  echo "  No $LABEL running."
  exit 0
fi

for pid in $targets; do
  # One line per process, even for the `make start` wrapper whose command is a whole script.
  echo "  Stopping $pid  $(args_of "$pid" | tr '\n\t\\' '   ' | tr -s ' ' | cut -c1-100)"
done
[ "$DRY" = "1" ] && exit 0

# shellcheck disable=SC2086
kill $targets 2>/dev/null || true
alive="$targets"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  alive=""
  for pid in $targets; do
    kill -0 "$pid" 2>/dev/null && alive="$alive $pid"
  done
  [ -z "$alive" ] && break
  sleep 0.5
done
if [ -n "$alive" ]; then
  # shellcheck disable=SC2086
  kill -9 $alive 2>/dev/null || true
fi
echo "  Stopped $LABEL."
