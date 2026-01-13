#!/usr/bin/env bash
set -euo pipefail

echo "This helper requires huggingface-cli installed on your host."
echo "Install: pip install -U 'huggingface_hub[cli]'"
echo ""
echo "It will download into ./models. Adjust repos/paths as you prefer."
echo ""

mkdir -p models/llm models/comfy

read -p "Proceed? [y/N] " yn
if [[ "${yn:-}" != "y" && "${yn:-}" != "Y" ]]; then
echo "Cancelled."
exit 0
fi

# NOTE: choose models that fit your hardware. These are examples.

# LLM example (you may use a quantized model directory compatible with vLLM):

echo "Downloading LLM example (you should pick a vLLM-compatible model)..."
echo "TIP: For home GPUs, consider smaller 7B-14B instruct models or quantized 32B if available."
echo ""

# Placeholder command (user edits):

echo "SKIP: Not downloading LLM automatically by default."
echo "Place your model in ./models/llm so vLLM can load it."

echo ""
echo "ComfyUI models are NOT auto-downloaded here."
echo "Place FLUX/SDXL/SVD/etc into ./models/comfy according to your ComfyUI setup."
echo "Done."
