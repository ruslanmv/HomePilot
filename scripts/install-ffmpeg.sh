#!/usr/bin/env bash
###############################################################################
# install-ffmpeg.sh — make sure ffmpeg + ffprobe are on PATH.
#
# Run by `make install` and `make install-ffmpeg`. Creator Studio MP4 export,
# narration upload and meeting audio conversion need both binaries at runtime,
# and `make preflight` (which `make start` runs first) refuses to start
# without them — so install them here instead of leaving a hint behind.
#
# What happens per platform:
#   Debian / Ubuntu (incl. WSL)   apt-get install -y ffmpeg        (sudo if needed)
#   Fedora / RHEL                 dnf install -y ffmpeg-free (falls back to ffmpeg)
#   Arch                          pacman -S --noconfirm ffmpeg
#   Alpine                        apk add ffmpeg
#   macOS                         brew install ffmpeg              (no sudo)
#   Windows shell (Git Bash)      prints the winget command — not automated
#
# sudo is used only when we are not root: passwordless when available,
# interactive when a terminal is attached, never in a non-interactive shell
# (CI, editors) — there the manual command is printed instead, so this script
# cannot hang waiting for a password.
#
# Exit codes: 0 = present or installed; 2 = could not install (hint printed).
# HOMEPILOT_SKIP_FFMPEG=1 skips the install (exit 0).
###############################################################################
set -u

have() { command -v "$1" >/dev/null 2>&1; }

if have ffmpeg && have ffprobe; then
  echo "  ✓ ffmpeg + ffprobe already on PATH ($(ffmpeg -version 2>/dev/null | head -n1 | cut -d' ' -f1-3))"
  exit 0
fi
if [ "${HOMEPILOT_SKIP_FFMPEG:-0}" = "1" ]; then
  echo "  · ffmpeg install skipped (HOMEPILOT_SKIP_FFMPEG=1)"
  exit 0
fi

as_root() {
  if [ "$(id -u)" = "0" ]; then "$@"; return $?; fi
  if ! have sudo; then
    echo "  ⚠ Not root and sudo is not installed. Run as root:  $*"
    return 1
  fi
  if sudo -n true 2>/dev/null; then sudo "$@"; return $?; fi
  if [ -t 0 ]; then
    echo "  ↳ sudo password needed to install ffmpeg system-wide"
    sudo "$@"; return $?
  fi
  echo "  ⚠ Non-interactive shell and sudo needs a password. Run this yourself:"
  echo "      sudo $*"
  return 1
}

print_manual_hint() {
  echo "  ⚠ ffmpeg / ffprobe are still missing. Install them, then rerun: make install-ffmpeg"
  echo "      Ubuntu/Debian:  sudo apt-get install -y ffmpeg"
  echo "      Fedora:         sudo dnf install -y ffmpeg-free"
  echo "      macOS (brew):   brew install ffmpeg"
  echo "      Windows:        winget install Gyan.FFmpeg   (or download from ffmpeg.org)"
}

os="$(uname -s 2>/dev/null || echo unknown)"
distro=""
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  distro="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-${ID:-linux}}")"
fi

case "$os" in
  Linux)
    if have apt-get; then
      echo "  ↳ Installing ffmpeg with apt-get (${distro})..."
      as_root env DEBIAN_FRONTEND=noninteractive apt-get update -qq \
        && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
    elif have dnf; then
      echo "  ↳ Installing ffmpeg with dnf (${distro})..."
      as_root dnf install -y ffmpeg-free || as_root dnf install -y ffmpeg
    elif have pacman; then
      echo "  ↳ Installing ffmpeg with pacman (${distro})..."
      as_root pacman -S --noconfirm --needed ffmpeg
    elif have apk; then
      echo "  ↳ Installing ffmpeg with apk (${distro})..."
      as_root apk add ffmpeg
    else
      echo "  ⚠ No supported package manager found on this Linux (${distro})."
    fi
    ;;
  Darwin)
    if have brew; then
      echo "  ↳ Installing ffmpeg with Homebrew..."
      brew install ffmpeg
    else
      echo "  ⚠ Homebrew not found — install it from https://brew.sh, then rerun: make install-ffmpeg"
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "  ⚠ Windows shell detected. Install ffmpeg with:  winget install Gyan.FFmpeg"
    echo "    (If you use WSL, run make install inside the Ubuntu shell instead.)"
    ;;
  *)
    echo "  ⚠ Unrecognised OS '${os}' — cannot install ffmpeg automatically."
    ;;
esac

if have ffmpeg && have ffprobe; then
  echo "  ✓ ffmpeg + ffprobe installed ($(ffmpeg -version 2>/dev/null | head -n1 | cut -d' ' -f1-3))"
  exit 0
fi
print_manual_hint
exit 2
