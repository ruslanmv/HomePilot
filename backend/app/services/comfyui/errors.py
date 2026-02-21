"""
ComfyUI service errors.
"""

from __future__ import annotations


class ComfyUIUnavailable(Exception):
    """ComfyUI is offline or unreachable."""


class ComfyUITimeout(Exception):
    """Workflow execution timed out."""


class ComfyUIWorkflowError(Exception):
    """Workflow returned an error from ComfyUI."""
