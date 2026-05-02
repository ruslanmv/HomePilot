"""
Tests for runtime_config — the shell-sourceable env persistence
that makes ComfyUI launcher flags survive a backend restart.

Contract:
* Only keys in ``ALLOWED_KEYS`` are written; anything else silently
  dropped so a stale or malicious frontend can't leak arbitrary env
  into ComfyUI.
* Values that look like shell meta-chars (``$()``, backticks, ``;``,
  etc.) are rejected — the resulting file is always safe to
  ``source`` in bash.
* Atomic write: a crash mid-write never leaves a half-file.
* Read tolerates missing file / malformed lines cleanly.
"""
from __future__ import annotations

import os
import pathlib

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a throwaway tmp path so the test never
    touches a real install's runtime.env."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_read_missing_file_returns_empty_dict(tmp_data_dir):
    from app.runtime_config import read_runtime_config
    assert read_runtime_config() == {}


def test_write_and_read_roundtrip(tmp_data_dir):
    from app.runtime_config import read_runtime_config, write_runtime_config
    written = write_runtime_config({"COMFY_VRAM_MODE": "high"})
    assert written == {"COMFY_VRAM_MODE": "high"}
    assert read_runtime_config() == {"COMFY_VRAM_MODE": "high"}
    # File exists and is shell-sourceable format.
    path = pathlib.Path(tmp_data_dir) / "runtime.env"
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "COMFY_VRAM_MODE=high" in body


def test_write_rejects_unknown_keys(tmp_data_dir):
    from app.runtime_config import write_runtime_config, read_runtime_config
    written = write_runtime_config({
        "COMFY_VRAM_MODE": "normal",
        "PATH": "/tmp",  # sneaky — must be dropped
        "arbitrary_key": "no",
    })
    assert written == {"COMFY_VRAM_MODE": "normal"}
    stored = read_runtime_config()
    assert "PATH" not in stored
    assert "arbitrary_key" not in stored


def test_write_rejects_shell_metacharacters(tmp_data_dir):
    """Defence-in-depth: even allow-listed keys reject values with
    backticks / $() / ;. The file is ``source``-d by bash, so a
    malicious value would otherwise execute."""
    from app.runtime_config import write_runtime_config, read_runtime_config
    for evil in [
        "value; rm -rf /",
        "$(whoami)",
        "`id`",
        "value && evil",
        "value | evil",
    ]:
        written = write_runtime_config({"COMFY_VRAM_MODE": evil})
        assert written == {}, f"{evil!r} should have been rejected"
    # File may exist but should not contain the evil value.
    stored = read_runtime_config()
    assert "COMFY_VRAM_MODE" not in stored


def test_write_is_atomic(tmp_data_dir, monkeypatch):
    """Confirm we don't leave a partial file behind on crash — the
    write goes through tmp + os.replace, so either the new file is
    fully there or the old one is untouched."""
    from app.runtime_config import write_runtime_config
    write_runtime_config({"COMFY_VRAM_MODE": "high"})
    path = pathlib.Path(tmp_data_dir) / "runtime.env"
    before = path.read_text(encoding="utf-8")

    # Simulate a failure partway through the write by monkeypatching
    # os.replace to raise. The old content must survive intact.
    real_replace = os.replace

    def boom(src, dst):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(RuntimeError):
        write_runtime_config({"COMFY_VRAM_MODE": "low"})
    # Restore real behaviour; verify the old file wasn't corrupted.
    monkeypatch.setattr(os, "replace", real_replace)
    assert path.read_text(encoding="utf-8") == before


def test_read_tolerates_malformed_lines(tmp_data_dir):
    """A hand-edited file with comments, blank lines, or garbage
    lines should parse the good entries and ignore the rest."""
    from app.runtime_config import read_runtime_config
    path = pathlib.Path(tmp_data_dir) / "runtime.env"
    path.write_text(
        "# leading comment\n"
        "\n"
        "COMFY_VRAM_MODE=normal\n"
        "NOT_IN_ALLOWLIST=whatever\n"
        "junk-without-equals\n"
        "  # indented comment\n",
        encoding="utf-8",
    )
    assert read_runtime_config() == {"COMFY_VRAM_MODE": "normal"}
