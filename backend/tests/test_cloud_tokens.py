"""Tests for the server-side cloud token store (Batch 7 — BFF session)."""
import os
import sys
import tempfile

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _fresh_store():
    os.environ["SQLITE_PATH"] = tempfile.mktemp(suffix=".db")
    os.environ.pop("HOMEPILOT_CLOUD_TOKEN_KEY", None)
    # Re-import fresh so the fernet cache + db path are clean.
    for m in ("app.cloud_tokens",):
        sys.modules.pop(m, None)
    from app import cloud_tokens as ct
    ct._fernet_cache = None  # reset tri-state cache
    return ct


def test_roundtrip_upsert_clear():
    ct = _fresh_store()
    assert ct.get_cloud_token("u1") is None
    ct.set_cloud_token("u1", "tok-abc")
    assert ct.get_cloud_token("u1") == "tok-abc"
    ct.set_cloud_token("u1", "tok-xyz")   # upsert
    assert ct.get_cloud_token("u1") == "tok-xyz"
    ct.clear_cloud_token("u1")
    assert ct.get_cloud_token("u1") is None


def test_plaintext_prefixed_when_no_key():
    ct = _fresh_store()
    ct.set_cloud_token("u2", "plain-secret")
    # Stored value carries the 'p:' prefix (server-side plaintext), never raw.
    import sqlite3
    con = sqlite3.connect(ct._get_db_path())
    raw = con.execute("SELECT token_enc FROM user_cloud_tokens WHERE user_id='u2'").fetchone()[0]
    con.close()
    assert raw.startswith("p:") and raw.endswith("plain-secret")
    assert ct.get_cloud_token("u2") == "plain-secret"


def test_empty_inputs_are_noops():
    ct = _fresh_store()
    ct.set_cloud_token("", "x")      # no user
    ct.set_cloud_token("u3", "")     # no token
    assert ct.get_cloud_token("u3") is None
    assert ct.get_cloud_token("") is None


def test_legacy_unprefixed_read_as_plaintext():
    ct = _fresh_store()
    ct.ensure_table()
    import sqlite3, time
    con = sqlite3.connect(ct._get_db_path())
    con.execute("INSERT INTO user_cloud_tokens(user_id, token_enc, updated_at) VALUES (?,?,?)",
                ("u4", "legacy-raw", time.time()))
    con.commit(); con.close()
    assert ct.get_cloud_token("u4") == "legacy-raw"
