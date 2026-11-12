"""Canonical data survives a restart, and can be backed up and restored (Test M)."""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def data_root(monkeypatch, tmp_path):
    import app.config as config
    import app.storage as storage

    root = tmp_path / "persist"
    (root / "data").mkdir(parents=True)
    (root / "uploads").mkdir()
    (root / "outputs").mkdir()
    prev = storage._RESOLVED_DB_PATH, storage.SQLITE_PATH
    monkeypatch.setattr(storage, "SQLITE_PATH", str(root / "data" / "homepilot.db"), raising=False)
    storage._RESOLVED_DB_PATH = None
    monkeypatch.setattr(config, "UPLOAD_DIR", str(root / "uploads"), raising=False)
    monkeypatch.setattr(config, "OUTPUT_DIR", str(root / "outputs"), raising=False)
    monkeypatch.setenv("HOMEPILOT_DATA_ROOT", str(root))
    monkeypatch.delenv("HOMEPILOT_STORAGE_DURABLE", raising=False)
    yield root
    storage._RESOLVED_DB_PATH, storage.SQLITE_PATH = prev


def _write(root, text="hello from before the restart"):
    con = sqlite3.connect(root / "data" / "homepilot.db")
    con.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, content TEXT)")
    con.execute("INSERT INTO messages(content) VALUES (?)", (text,))
    con.commit()
    con.close()
    (root / "outputs" / "image.png").write_bytes(b"\x89PNG generated")


def _read(root):
    con = sqlite3.connect(root / "data" / "homepilot.db")
    try:
        return [r[0] for r in con.execute("SELECT content FROM messages")]
    finally:
        con.close()


def test_routing_state_survives_a_process_restart(data_root):
    """Per-user preferences and the spending ledger live in the durable database,
    not in process memory: a fresh process (new module state) reads them back."""
    import importlib
    from app.compute import routing

    routing.save_prefs("alice", {"strategy": "local_first", "monthly_budget_usd": 3})
    routing.record_usage("alice", {"provider": "openai", "billing": "paid",
                                   "cost": {"actual_usd": 0.25}})
    routing = importlib.reload(routing)            # what a restart does to module state
    assert routing.load_prefs("alice").strategy == "local_first"
    assert routing.spent("alice", "month") == pytest.approx(0.25)


def test_ephemeral_storage_is_reported_not_hidden(data_root, monkeypatch):
    from app import durable_storage as ds

    # pytest's tmp_path lives under the system temp dir, which is exactly the
    # case the path check exists to catch.
    info = ds.describe()
    assert info["durable"] is False and "erased" in info["warning"]
    assert ds._is_ephemeral(ds.Path("/tmp/homepilot/data/homepilot.db")) is True
    assert ds._is_ephemeral(ds.Path("/data/homepilot/data/homepilot.db")) is False
    monkeypatch.setenv("HOMEPILOT_STORAGE_DURABLE", "true")
    assert ds.describe()["durable"] is True and ds.describe()["warning"] is None


def test_backup_then_restore_brings_conversations_and_media_back(data_root):
    from app import durable_storage as ds

    _write(data_root)
    archive = ds.create_backup()
    assert archive.exists() and ds.describe()["backups"] == 1

    # Disaster: the database and the generated media are gone.
    os.remove(data_root / "data" / "homepilot.db")
    os.remove(data_root / "outputs" / "image.png")
    result = ds.restore_backup(archive)
    assert set(result["restored"]) >= {"database", "outputs"}
    assert _read(data_root) == ["hello from before the restart"]
    assert (data_root / "outputs" / "image.png").read_bytes() == b"\x89PNG generated"


def test_restore_never_silently_overwrites_live_data(data_root):
    from app import durable_storage as ds

    _write(data_root, "old")
    archive = ds.create_backup()
    _write(data_root, "newer message")
    with pytest.raises(FileExistsError):
        ds.restore_backup(archive)
    assert "newer message" in _read(data_root)

    ds.restore_backup(archive, force=True)
    assert _read(data_root) == ["old"]
    # ...and the replaced database is kept, so the restore can be undone.
    assert (data_root / "data" / "homepilot.db.pre-restore").exists()


def test_old_backups_are_pruned_and_cli_runs(data_root, capsys):
    from app import durable_storage as ds

    _write(data_root)
    for stamp in ("20200101T000000Z", "20200102T000000Z", "20200103T000000Z"):
        (ds.backup_dir()).mkdir(exist_ok=True)
        (ds.backup_dir() / f"{ds.ARCHIVE_PREFIX}{stamp}.tar.gz").write_bytes(b"x")
    ds.create_backup(keep=2)
    assert len(ds.list_backups()) == 2
    assert ds.main(["backup", "--if-older-than", "24"]) == 0
    assert "skip" in capsys.readouterr().out
    assert ds.main(["status"]) == 0


def test_a_malicious_archive_cannot_write_outside_the_data_root(data_root, tmp_path):
    import io
    import tarfile
    from app import durable_storage as ds

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../../escape.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"boom"))
    with pytest.raises(ValueError):
        ds.restore_backup(evil)
