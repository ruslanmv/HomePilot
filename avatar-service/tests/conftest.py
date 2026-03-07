"""Shared fixtures for avatar-service tests — CI-light, no GPU, no model weights."""

import os
import sys
import tempfile

import pytest

# Ensure the avatar-service app is importable
_svc_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)


@pytest.fixture()
def tmp_output_dir(tmp_path, monkeypatch):
    """Provide a temp output directory and patch the env var."""
    out = tmp_path / "uploads"
    out.mkdir()
    monkeypatch.setenv("AVATAR_OUTPUT_DIR", str(out))
    return out
