"""
Avatar Studio — additive feature module for persona avatar generation.

Provides endpoints for generating identity-consistent portraits via:
  - ComfyUI workflows (InstantID / PhotoMaker / FaceSwap)
  - Optional StyleGAN microservice (random faces)

Architecture:
  Backend stays a thin HTTP orchestrator.  ALL GPU/ML work runs inside
  ComfyUI or the optional avatar-service.  The backend never imports torch.
"""

from .router import router

__all__ = ["router"]
