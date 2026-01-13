#!/usr/bin/env bash
# =============================================================================
# fix-nvidia-docker-wsl.sh
# Fix "unknown or invalid runtime name: nvidia" + "--gpus all" not working on WSL
# by installing NVIDIA Container Toolkit + configuring Docker runtime.
#
# Works for native Docker Engine running inside WSL (Ubuntu/Debian family).
#
# Usage:
#   bash fix-nvidia-docker-wsl.sh
#
# After success:
#   docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
# =============================================================================

set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Please run as a normal user (it will use sudo when needed)."
  exit 1
fi

need_cmd() { command -v "$1" >/dev/null 2>&1; }

echo ""
echo "==> Checking environment..."

if ! need_cmd sudo; then
  echo "ERROR: sudo not found. Install sudo or run in a distro with sudo."
  exit 1
fi

if ! need_cmd docker; then
  echo "ERROR: docker not found. Install Docker Engine first."
  exit 1
fi

if ! need_cmd nvidia-smi; then
  echo "ERROR: nvidia-smi not found. GPU is not exposed to WSL."
  echo "Install NVIDIA Windows driver for WSL and ensure WSL GPU works."
  exit 1
fi

echo ""
echo "==> GPU in WSL:"
nvidia-smi || true

echo ""
echo "==> Docker runtimes (before):"
docker info 2>/dev/null | grep -i -E "runtimes|nvidia|wsl" || true

echo ""
echo "==> Installing prerequisites..."
sudo apt-get update -y
sudo apt-get install -y curl gpg ca-certificates

echo ""
echo "==> Detecting distribution..."
distribution=$(. /etc/os-release; echo "${ID}${VERSION_ID}")
echo "Detected: ${distribution}"
echo "OS release:"
cat /etc/os-release

echo ""
echo "==> Adding NVIDIA Container Toolkit repository + key..."
sudo mkdir -p /etc/apt/keyrings

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit.gpg

curl -fsSL "https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list" \
  | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

echo ""
echo "==> Updating apt indexes..."
sudo apt-get update -y

echo ""
echo "==> Installing nvidia-container-toolkit..."
sudo apt-get install -y nvidia-container-toolkit

if ! need_cmd nvidia-ctk; then
  echo "ERROR: nvidia-ctk not found after install. Something went wrong."
  exit 1
fi

echo ""
echo "==> Configuring Docker runtime for NVIDIA..."
sudo nvidia-ctk runtime configure --runtime=docker

echo ""
echo "==> Restarting Docker..."
# Try multiple restart methods because WSL setups differ
if sudo service docker status >/dev/null 2>&1; then
  sudo service docker restart
elif need_cmd systemctl && systemctl list-units --type=service | grep -q docker; then
  sudo systemctl restart docker
else
  echo "WARN: Could not restart docker via service/systemctl."
  echo "If Docker is managed by Docker Desktop, restart Docker Desktop now."
fi

echo ""
echo "==> Docker runtimes (after):"
docker info 2>/dev/null | grep -i -E "runtimes|nvidia|wsl" || true

echo ""
echo "==> Testing GPU in container..."
set +e
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
  echo ""
  echo "ERROR: GPU test still failed."
  echo ""
  echo "Common causes:"
  echo "  1) Docker Desktop is the real engine (not WSL docker service). Restart Docker Desktop."
  echo "  2) You are not using WSL integration in Docker Desktop."
  echo "  3) NVIDIA driver / WSL GPU stack mismatch."
  echo ""
  echo "Next diagnostics:"
  echo "  docker version"
  echo "  docker info | grep -i -E 'runtimes|nvidia|wsl'"
  echo "  docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi"
  exit $rc
fi

echo ""
echo "✅ SUCCESS: NVIDIA GPU works inside Docker containers."
echo ""
echo "Now you can run your stack:"
echo "  make run"
echo ""
