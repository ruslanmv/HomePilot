"""
Media storage (app/media_storage): the interface every persistent media write goes through,
its two backends, and the registries behind it — Phases 1 and 2 of docs/design/MEDIA_STORAGE.md.

The contract is one set of checks run against every backend: `local` (this disk) and `s3`
(any S3-compatible store; here boto3's client is replaced by a dict-backed fake, and the same
checks run against a real server when HOMEPILOT_TEST_S3_ENDPOINT is set). Nothing moves
between phases: keys are the relative paths the registries already hold, so files written
before any of this existed are served exactly as before.
"""
from __future__ import annotations

import io
import os
import uuid

import pytest


# ── a dict-backed stand-in for boto3's S3 client ────────────────────────────


class FakeS3Client:
    """Just enough of boto3's S3 client, over a dict, for the contract tests."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, tuple[bytes, str]]] = {}
        self.calls: list[str] = []

    def _error(self, code: str, op: str):
        from botocore.exceptions import ClientError

        status = 404 if code in ("404", "NoSuchKey", "NotFound", "NoSuchBucket") else 400
        return ClientError({"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, op)

    def _objects(self, bucket: str) -> dict:
        if bucket not in self.buckets:
            raise self._error("NoSuchBucket", "Op")
        return self.buckets[bucket]

    def head_bucket(self, Bucket):
        self.calls.append("head_bucket")
        if Bucket not in self.buckets:
            raise self._error("404", "HeadBucket")
        return {}

    def create_bucket(self, Bucket, **kwargs):
        self.calls.append("create_bucket")
        self.buckets.setdefault(Bucket, {})
        return {}

    def put_object(self, Bucket, Key, Body, ContentType=""):
        self._objects(Bucket)[Key] = (bytes(Body), ContentType)
        return {}

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None):
        self._objects(Bucket)[Key] = (Fileobj.read(), (ExtraArgs or {}).get("ContentType", ""))

    def head_object(self, Bucket, Key):
        objects = self._objects(Bucket)
        if Key not in objects:
            raise self._error("404", "HeadObject")
        return {"ContentLength": len(objects[Key][0]), "ContentType": objects[Key][1]}

    def get_object(self, Bucket, Key):
        objects = self._objects(Bucket)
        if Key not in objects:
            raise self._error("NoSuchKey", "GetObject")
        return {"Body": io.BytesIO(objects[Key][0]), "ContentLength": len(objects[Key][0])}

    def delete_object(self, Bucket, Key):
        self._objects(Bucket).pop(Key, None)
        return {}

    def copy_object(self, Bucket, Key, CopySource, **kwargs):
        src = self._objects(CopySource["Bucket"])[CopySource["Key"]]
        self._objects(Bucket)[Key] = (src[0], kwargs.get("ContentType", src[1]))
        return {}


def fake_s3(prefix: str = "unit"):
    from app.media_storage import S3Settings, S3Storage

    client = FakeS3Client()
    return S3Storage(S3Settings(bucket="hp-test", prefix=prefix), client=client), client


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path):
    from app.media_storage import LocalStorage

    if request.param == "local":
        return LocalStorage(tmp_path / "root")
    return fake_s3()[0]


# ── the contract, run against every backend ─────────────────────────────────


def contract_round_trip(storage):
    obj = storage.put("users/u1/images/a.png", b"png-bytes")
    assert (obj.backend, obj.key, obj.size_bytes) == (storage.name, "users/u1/images/a.png", 9)
    assert storage.exists("users/u1/images/a.png") and storage.size("users/u1/images/a.png") == 9
    assert storage.read("users/u1/images/a.png") == b"png-bytes"
    with storage.open("users/u1/images/a.png") as f:
        assert f.read(3) + f.read() == b"png-bytes"
    assert storage.delete("users/u1/images/a.png") is True
    assert storage.delete("users/u1/images/a.png") is False
    assert not storage.exists("users/u1/images/a.png")


def contract_streams(storage):
    storage.put("rooms/r1/docs/keep.txt", b"keep")
    storage.put("rooms/r1/docs/big.bin", io.BytesIO(b"x" * 3_000_000))
    assert storage.size("rooms/r1/docs/big.bin") == 3_000_000
    assert storage.delete("rooms/r1/docs/big.bin") is True
    assert storage.exists("rooms/r1/docs/keep.txt")
    storage.delete("rooms/r1/docs/keep.txt")


def contract_aborted_write_leaves_nothing(storage):
    storage.put("a/b.txt", b"old")
    with pytest.raises(RuntimeError):
        with storage.open_write("a/b.txt") as out:
            out.write(b"half")
            raise RuntimeError("connection dropped")
    assert storage.read("a/b.txt") == b"old"                     # the old object is intact
    with pytest.raises(RuntimeError):
        with storage.open_write("a/new.txt") as out:
            out.write(b"half")
            raise RuntimeError("connection dropped")
    assert not storage.exists("a/new.txt")                        # and nothing new appeared
    with storage.open_write("a/c.txt") as out:
        out.write(b"one ")
        out.write(b"two")
    assert storage.read("a/c.txt") == b"one two"
    with pytest.raises(FileNotFoundError):
        storage.open("missing.txt")
    with pytest.raises(FileNotFoundError):
        storage.size("missing.txt")
    for key in ("a/b.txt", "a/c.txt"):
        storage.delete(key)


def contract_overwrite_and_copy(storage):
    storage.put("x.txt", b"1")
    with pytest.raises(FileExistsError):
        storage.put("x.txt", b"2", overwrite=False)
    assert storage.read("x.txt") == b"1"
    storage.put("x.txt", b"2")
    assert storage.read("x.txt") == b"2"
    assert storage.copy("x.txt", "y/x.txt").key == "y/x.txt"
    assert storage.read("y/x.txt") == b"2" and storage.read("x.txt") == b"2"
    with pytest.raises(FileNotFoundError):
        storage.copy("nope.txt", "y/nope.txt")
    for key in ("x.txt", "y/x.txt"):
        storage.delete(key)


def contract_keys_cannot_leave_the_root(storage):
    from app.media_storage import StorageKeyError

    for key in ("../outside.txt", "a/../../outside.txt", "/etc/passwd", "C:/windows/x", "", "   ", "a\x00b", ".."):
        with pytest.raises(StorageKeyError):
            storage.put(key, b"x")
        with pytest.raises(StorageKeyError):
            storage.exists(key)


def contract_odd_slashes_name_the_same_object(storage):
    storage.put("users\\u1\\images\\a.png", b"x")
    assert storage.exists("users/u1/images/a.png")
    assert storage.read("users//u1/./images/a.png") == b"x"
    storage.delete("users/u1/images/a.png")


CONTRACT = [contract_round_trip, contract_streams, contract_aborted_write_leaves_nothing,
            contract_overwrite_and_copy, contract_keys_cannot_leave_the_root, contract_odd_slashes_name_the_same_object]


@pytest.mark.parametrize("check", CONTRACT, ids=lambda c: c.__name__.removeprefix("contract_"))
def test_contract(storage, check):
    check(storage)


# ── what only the local backend promises ────────────────────────────────────


def test_local_prunes_the_folders_it_empties_and_leaves_no_part_files(tmp_path):
    from app.media_storage import LocalStorage

    local = LocalStorage(tmp_path / "root")
    local.put("users/u1/images/a.png", b"x")
    assert local.local_path("users/u1/images/a.png") == local.root / "users" / "u1" / "images" / "a.png"
    with pytest.raises(RuntimeError):
        with local.open_write("users/u1/images/b.png") as out:
            out.write(b"half")
            raise RuntimeError("dropped")
    assert sorted(p.name for p in (local.root / "users" / "u1" / "images").iterdir()) == ["a.png"]
    local.delete("users/u1/images/a.png")
    assert not (local.root / "users").exists() and local.root.is_dir()
    assert not any(local.root.parent.glob("outside.txt"))


def test_normalize_key():
    from app.media_storage import normalize_key

    assert normalize_key("./users//u1/./images/a.png/") == "users/u1/images/a.png"
    assert normalize_key("users\\u1\\a.png") == "users/u1/a.png"


# ── what only the S3 backend promises ───────────────────────────────────────


def test_s3_prefixes_keys_sets_content_types_and_creates_the_bucket_once():
    storage, client = fake_s3(prefix="media")
    assert storage.local_path("anything") is None
    storage.put("users/u1/images/a.png", b"x")
    storage.put("notes/a.txt", io.BytesIO(b"text"))
    objects = client.buckets["hp-test"]
    assert objects["media/users/u1/images/a.png"] == (b"x", "image/png")
    assert objects["media/notes/a.txt"] == (b"text", "text/plain")
    storage.copy("notes/a.txt", "notes/b.md")
    assert objects["media/notes/b.md"][1] == "text/markdown"
    assert client.calls.count("create_bucket") == 1 and client.calls.count("head_bucket") == 1


def test_s3_without_bucket_creation_fails_loudly():
    from app.media_storage import S3Settings, S3Storage

    storage = S3Storage(S3Settings(bucket="absent", create_bucket=False), client=FakeS3Client())
    with pytest.raises(Exception, match="404|HeadBucket"):
        storage.exists("x")


def test_s3_settings_come_from_the_environment():
    from app.media_storage import S3Settings

    env = {"S3_BUCKET": " media ", "S3_ENDPOINT_URL": "http://127.0.0.1:9400", "S3_REGION": "eu-west-1",
           "S3_ACCESS_KEY_ID": "k", "S3_SECRET_ACCESS_KEY": "s", "S3_ADDRESSING_STYLE": "Virtual",
           "S3_PREFIX": "/tenant-a//", "S3_CREATE_BUCKET": "no", "S3_VERIFY_TLS": "0"}
    s = S3Settings.from_env(env)
    assert (s.bucket, s.endpoint_url, s.region, s.access_key, s.secret_key) == ("media", "http://127.0.0.1:9400", "eu-west-1", "k", "s")
    assert (s.addressing_style, s.prefix, s.create_bucket, s.verify_tls) == ("virtual", "tenant-a/", False, False)
    defaults = S3Settings.from_env({})
    assert (defaults.bucket, defaults.endpoint_url, defaults.region, defaults.prefix, defaults.create_bucket) == \
        ("homepilot-media", None, "us-east-1", "", True)
    assert "k" not in str(s.signature()) and "s" not in s.signature()   # credentials never in the signature


# ── the configured storage ──────────────────────────────────────────────────


def test_the_default_is_local_under_the_upload_dir(monkeypatch, tmp_path):
    from app import config
    from app.media_storage import LocalStorage, backend_name, get_storage, reset_storage, upload_root

    monkeypatch.delenv("MEDIA_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    reset_storage()
    storage = get_storage()
    assert backend_name() == "local" and isinstance(storage, LocalStorage)
    assert storage.root == (tmp_path / "uploads").resolve() == upload_root().resolve()
    assert get_storage() is storage                                        # built once…
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "elsewhere"))
    assert get_storage().root == (tmp_path / "elsewhere").resolve()        # …until the root moves
    reset_storage()


def test_s3_is_selected_by_the_environment_and_touches_no_network_until_used(monkeypatch):
    from app.media_storage import S3Storage, get_storage, reset_storage

    monkeypatch.setenv("MEDIA_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")      # nothing listens there
    monkeypatch.setenv("S3_BUCKET", "media")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "s")
    reset_storage()
    storage = get_storage()
    assert isinstance(storage, S3Storage) and storage.settings.bucket == "media"
    assert get_storage() is storage
    monkeypatch.setenv("S3_BUCKET", "other")
    assert get_storage().settings.bucket == "other"                     # settings changed: rebuilt
    reset_storage()


def test_an_unknown_backend_is_a_clear_error_not_a_silent_local_write(monkeypatch):
    from app.media_storage import get_storage, reset_storage

    monkeypatch.setenv("MEDIA_STORAGE_BACKEND", "gcs")
    reset_storage()
    with pytest.raises(RuntimeError, match="MEDIA_STORAGE_BACKEND='gcs'"):
        get_storage()
    reset_storage()


def test_reads_fall_back_to_the_disk_after_a_switch_to_s3(monkeypatch, tmp_path):
    """Media written before the switch is still on the disk: it is read from there, new media
    from S3, and a key in neither resolves to the configured backend (which then says 404)."""
    from app import config, media_storage
    from app.media_storage import LocalStorage, reset_storage, storage_for_read

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    reset_storage()
    remote, _ = fake_s3()
    monkeypatch.setattr(media_storage, "get_storage", lambda: remote)
    LocalStorage(tmp_path / "uploads").put("users/u1/images/old.png", b"old")
    remote.put("users/u1/images/new.png", b"new")

    assert storage_for_read("users/u1/images/old.png").name == "local"
    assert storage_for_read("users/u1/images/new.png") is remote
    assert storage_for_read("users/u1/images/none.png") is remote
    reset_storage()


# ── the registries ──────────────────────────────────────────────────────────


def test_the_registry_keeps_one_row_per_backend_and_key(client):
    from app import asset_registry as reg

    key = "users/u9/images/same.png"
    local_id = reg.register_asset(storage_key=key, kind="image", origin="test")
    assert reg.register_asset(storage_key=key, kind="image", origin="test") == local_id      # idempotent
    remote_id = reg.register_asset(storage_key=key, kind="image", origin="test", storage_backend="s3")
    assert remote_id != local_id
    assert reg.find_asset_id_by_storage_key(key) == local_id                                # the configured backend
    assert reg.find_asset_id_by_storage_key(key, storage_backend="s3") == remote_id
    assert reg.get_asset(local_id)["storage_backend"] == "local"
    assert reg.get_asset(remote_id)["storage_backend"] == "s3"


# ── file assets through the interface ───────────────────────────────────────


def _user(client, name):
    r = client.post("/v1/auth/register", json={"username": name, "password": "pw", "email": "", "display_name": name})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    token = body.get("token") or body.get("access_token") or (body.get("session") or {}).get("token")
    user = body.get("user") or body
    return str(user["id"]), {"Authorization": f"Bearer {token}"}


def test_generated_media_goes_through_storage_and_is_served_to_its_owner_only(client):
    from app import files
    from app.media_storage import get_storage

    owner, owner_h = _user(client, "ms_owner")
    _other, other_h = _user(client, "ms_other")

    out = files.save_generated_image_as_asset(owner, b"\x89PNG-fake", mime="image/png", conversation_id="c1")
    assert out["rel_path"].startswith(f"users/{owner}/images/") and out["rel_path"].endswith(".png")
    assert get_storage().read(out["rel_path"]) == b"\x89PNG-fake"
    assert files.get_asset(out["asset_id"])["rel_path"] == out["rel_path"]   # the key *is* the registered path

    r = client.get(out["url"], headers=owner_h)
    assert r.status_code == 200 and r.content == b"\x89PNG-fake"
    assert r.headers["content-type"].startswith("image/png")
    assert client.get(out["url"], headers=other_h).status_code == 404
    client.cookies.clear()          # registering set a session cookie; this request carries nothing
    assert client.get(out["url"]).status_code == 401

    # Deletion goes to the trash first: gone from every read, bytes kept until the purge.
    assert files.delete_asset_and_file(out["asset_id"]) is True
    assert client.get(out["url"], headers=owner_h).status_code == 404
    assert files.get_asset(out["asset_id"]) is None
    assert files.get_asset(out["asset_id"], include_deleted=True)["deleted_at"]
    assert get_storage().exists(out["rel_path"])
    from app import media_ops
    assert media_ops.purge_trash(retention_days=0)["purged"] >= 1
    assert not get_storage().exists(out["rel_path"])
    assert files.get_asset(out["asset_id"], include_deleted=True) is None


def test_a_video_keeps_its_type_and_a_conversation_delete_removes_its_media(client, monkeypatch):
    from app import files
    from app.media_storage import get_storage

    owner, owner_h = _user(client, "ms_video")
    out = files.save_generated_media_as_asset(owner, b"\x00\x00\x00 ftypmp42", "video/mp4", "video", conversation_id="c-del")
    assert out["rel_path"].endswith(".mp4")
    r = client.get(out["url"], headers=owner_h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("video/mp4")
    # With the trash on, a conversation delete trashes its media…
    assert files.delete_conversation_media("c-del") == 1
    assert files.get_asset(out["asset_id"]) is None and get_storage().exists(out["rel_path"])
    # …and with a retention of 0 (the pre-Phase-4 behaviour) the bytes go at once.
    monkeypatch.setenv("MEDIA_TRASH_RETENTION_DAYS", "0")
    again = files.save_generated_media_as_asset(owner, b"\x00\x00\x00 ftypmp42", "video/mp4", "video", conversation_id="c-del-2")
    assert files.delete_conversation_media("c-del-2") == 1
    assert not get_storage().exists(again["rel_path"])


def test_a_file_written_before_media_storage_existed_is_served_unchanged(client):
    """The legacy read path: a row whose bytes an older HomePilot put on disk directly —
    here even with the backslashes a Windows install recorded — resolves by the same key,
    and nothing is moved."""
    from app import files

    owner, owner_h = _user(client, "ms_legacy")
    folder = files._upload_root() / "users" / owner / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "old.txt").write_bytes(b"from before")
    asset_id = files.insert_asset(owner, "upload", f"users\\{owner}\\uploads\\old.txt", "text/plain", 11,
                                  original_name="old.txt")
    r = client.get(f"/files/{asset_id}", headers=owner_h)
    assert r.status_code == 200 and r.content == b"from before"
    assert (folder / "old.txt").exists()


def test_uploads_land_in_the_users_area(client):
    from app import files
    from app.media_storage import get_storage

    owner, owner_h = _user(client, "ms_upload")
    r = client.post("/v1/files/upload", files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")}, headers=owner_h)
    assert r.status_code == 200, r.text
    body = r.json()
    asset = files.get_asset(body["asset_id"])
    assert asset["rel_path"].startswith(f"users/{owner}/uploads/") and asset["rel_path"].endswith(".txt")
    assert get_storage().read(asset["rel_path"]) == b"hello"
    assert client.get(body["url"], headers=owner_h).content == b"hello"


def test_with_s3_configured_a_registered_object_streams_and_a_local_one_still_serves(client, monkeypatch):
    """The same /files/{id} route with S3 as the backend: a new object is streamed from S3
    (no local path), a file from before the switch is served from the disk, and a flat key
    such as an avatar is found in S3 by the path-based route."""
    from app import files, media_storage

    owner, owner_h = _user(client, "ms_s3")
    remote, client_fake = fake_s3()
    monkeypatch.setattr(media_storage, "get_storage", lambda: remote)
    monkeypatch.setattr(files, "get_storage", lambda: remote)

    out = files.save_generated_image_as_asset(owner, b"\x89PNG-remote", mime="image/png")
    assert client_fake.buckets["hp-test"][f"unit/{out['rel_path']}"][0] == b"\x89PNG-remote"
    r = client.get(out["url"], headers=owner_h)
    assert r.status_code == 200 and r.content == b"\x89PNG-remote"
    assert r.headers["content-type"].startswith("image/png")

    before = files._upload_root() / "users" / owner / "images"
    before.mkdir(parents=True, exist_ok=True)
    (before / "before.png").write_bytes(b"\x89PNG-disk")
    # A row from before the switch says `local` — that is where it was written (Phase 3a).
    old_id = files.insert_asset(owner, "image", f"users/{owner}/images/before.png", "image/png", 9, storage_backend="local")
    assert client.get(f"/files/{old_id}", headers=owner_h).content == b"\x89PNG-disk"

    remote.put("avatar_u1_1234.png", b"\x89PNG-avatar")
    assert client.get("/files/avatar_u1_1234.png").content == b"\x89PNG-avatar"        # public by prefix, from S3

    # A ComfyUI-bound read gets a local copy of the remote object, cached under the root.
    local = files.resolve_local_file(out["asset_id"])
    assert local is not None and local.read_bytes() == b"\x89PNG-remote"
    assert local == files.resolve_local_file(out["asset_id"])
    assert str(local).startswith(str(files._upload_root() / ".cache" / "media"))
    assert files.resolve_local_file("nothing-here.png") is None

    assert files.delete_asset_and_file(out["asset_id"], purge=True) is True
    assert not remote.exists(out["rel_path"])


# ── the backend on every row (Phase 3a) ─────────────────────────────────────


def test_an_older_database_gets_the_backend_column_with_local_for_its_rows(tmp_path):
    import sqlite3

    from app.storage import ensure_file_assets_backend_column

    con = sqlite3.connect(tmp_path / "old.db")
    con.execute("""CREATE TABLE file_assets(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
                   rel_path TEXT NOT NULL, mime TEXT DEFAULT '', size_bytes INTEGER DEFAULT 0,
                   original_name TEXT DEFAULT '', project_id TEXT DEFAULT '', conversation_id TEXT DEFAULT '',
                   created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("INSERT INTO file_assets(id, user_id, kind, rel_path) VALUES ('f_old', 'u', 'image', 'users/u/images/a.png')")
    con.commit()
    assert ensure_file_assets_backend_column(con) is True
    assert ensure_file_assets_backend_column(con) is False                      # idempotent
    assert con.execute("SELECT storage_backend FROM file_assets WHERE id = 'f_old'").fetchone()[0] == "local"
    con.close()


def test_each_row_records_the_backend_that_holds_its_bytes(client, monkeypatch):
    """Two rows, the same key in both stores: each is served from — and removed from — the
    backend its row names, never the first store that happens to have the key."""
    from app import files, media_storage

    owner, owner_h = _user(client, "ms_rows")
    on_disk = files.save_generated_image_as_asset(owner, b"disk", mime="image/png")
    assert files.get_asset(on_disk["asset_id"])["storage_backend"] == "local"

    remote, _ = fake_s3()
    monkeypatch.setattr(media_storage, "get_storage", lambda: remote)
    monkeypatch.setattr(files, "get_storage", lambda: remote)
    in_s3 = files.save_generated_image_as_asset(owner, b"remote", mime="image/png")
    assert files.get_asset(in_s3["asset_id"])["storage_backend"] == "s3"

    remote.put(on_disk["rel_path"], b"impostor")
    twin = files._upload_root() / in_s3["rel_path"]
    twin.parent.mkdir(parents=True, exist_ok=True)
    twin.write_bytes(b"impostor")
    assert client.get(on_disk["url"], headers=owner_h).content == b"disk"
    assert client.get(in_s3["url"], headers=owner_h).content == b"remote"
    assert files.resolve_local_file(on_disk["asset_id"]).read_bytes() == b"disk"
    assert files.resolve_local_file(in_s3["asset_id"]).read_bytes() == b"remote"

    assert files.delete_asset_and_file(in_s3["asset_id"], purge=True) is True
    assert not remote.exists(in_s3["rel_path"]) and twin.exists()            # S3 object gone, disk twin untouched
    assert files.delete_asset_and_file(on_disk["asset_id"], purge=True) is True
    assert remote.exists(on_disk["rel_path"])                                 # the S3 impostor was not this row's


def test_a_row_in_a_backend_this_homepilot_is_not_configured_for_is_a_clear_404(client, capsys):
    """Switched back to local after writing to S3: the row says s3, nothing reaches it."""
    from app import files

    owner, owner_h = _user(client, "ms_unconfigured")
    asset_id = files.insert_asset(owner, "image", f"users/{owner}/images/gone.png", "image/png", 4, storage_backend="s3")
    assert client.get(f"/files/{asset_id}", headers=owner_h).status_code == 404
    assert "media backend 's3'" in capsys.readouterr().out
    assert files.resolve_local_file(asset_id) is None
    assert files.delete_asset_and_file(asset_id) is True                      # the row goes; the object is left alone


# ── checksums, verify, migrate (Phase 3) ────────────────────────────────────


def test_writes_record_a_sha256_and_verify_notices_a_changed_object(client, capsys):
    from app import files, media_ops
    from app.media_storage import get_storage

    owner, _ = _user(client, "ms_hash")
    import hashlib
    out = files.save_generated_image_as_asset(owner, b"\x89PNG-hash", mime="image/png")
    assert files.get_asset(out["asset_id"])["sha256"] == hashlib.sha256(b"\x89PNG-hash").hexdigest()
    # The database is shared with every other test: count against the state before the edit.
    before = media_ops.verify(log=lambda s: None)
    get_storage().put(out["rel_path"], b"\x89PNG-changed")                      # bit rot, or a hand edit
    after = media_ops.verify(log=lambda s: None)
    assert after["mismatch"] == before["mismatch"] + 1
    files.delete_asset_and_file(out["asset_id"], purge=True)


def test_migrate_copies_verifies_and_flips_the_row_keeping_the_source(client, monkeypatch):
    from app import files, media_ops, media_storage

    owner, owner_h = _user(client, "ms_migrate")
    out = files.save_generated_image_as_asset(owner, b"\x89PNG-move", mime="image/png")
    local = media_storage.local_storage()
    remote, _ = fake_s3()
    monkeypatch.setattr(media_storage, "get_storage", lambda: remote)
    monkeypatch.setattr(files, "get_storage", lambda: remote)

    dry = media_ops.migrate(dry_run=True, log=lambda s: None)
    assert dry["moved"] >= 1 and not remote.exists(out["rel_path"])
    counts = media_ops.migrate(log=lambda s: None)
    assert counts["failed"] == 0 and counts["moved"] >= 1
    row = files.get_asset(out["asset_id"])
    assert row["storage_backend"] == "s3" and remote.read(out["rel_path"]) == b"\x89PNG-move"
    assert local.exists(out["rel_path"])                                        # the source is kept
    assert client.get(out["url"], headers=owner_h).content == b"\x89PNG-move"    # served from S3 now
    assert media_ops.migrate(log=lambda s: None)["moved"] == 0                   # nothing left to move
    assert media_ops.verify(log=lambda s: None)["mismatch"] == 0

    # --prune-source removes the disk copy, but only once the read-back verified.
    disk_only = files._upload_root() / "users" / owner / "images" / "prune.png"
    disk_only.parent.mkdir(parents=True, exist_ok=True)
    disk_only.write_bytes(b"\x89PNG-prune")
    prune_id = files.insert_asset(owner, "image", f"users/{owner}/images/prune.png", "image/png", 9, storage_backend="local")
    counts = media_ops.migrate(prune_source=True, log=lambda s: None)
    assert counts["moved"] == 1 and counts["failed"] == 0
    assert not disk_only.exists() and remote.read(f"users/{owner}/images/prune.png") == b"\x89PNG-prune"
    assert files.get_asset(prune_id)["storage_backend"] == "s3"


def test_backup_and_restore_round_trip(client, tmp_path, monkeypatch):
    """The restore drill, automated: back up, lose the files, restore, serve them again."""
    from app import files, media_ops
    from app.media_storage import get_storage

    owner, owner_h = _user(client, "ms_backup")
    a = files.save_generated_image_as_asset(owner, b"\x89PNG-a", mime="image/png")
    b = files.save_generated_media_as_asset(owner, b"\x00\x00\x00 ftypmp42-b", "video/mp4", "video")
    manifest = media_ops.backup(tmp_path / "bk", log=lambda s: None)
    ids = {e["id"] for e in manifest["assets"]}
    assert {a["asset_id"], b["asset_id"]} <= ids
    # Other tests leave rows in this shared database whose backend is no longer configured;
    # those are reported as skipped, never silently dropped — but ours are not among them.
    assert not [s for s in manifest["skipped"] if s["id"] in (a["asset_id"], b["asset_id"])]
    assert (tmp_path / "bk" / "homepilot.db").exists()
    assert (tmp_path / "bk" / "media" / a["rel_path"]).read_bytes() == b"\x89PNG-a"

    get_storage().delete(a["rel_path"])                                          # the disaster
    get_storage().delete(b["rel_path"])
    assert client.get(a["url"], headers=owner_h).status_code == 404

    counts = media_ops.restore(tmp_path / "bk", log=lambda s: None)
    assert counts["failed"] == 0 and counts["restored"] >= 2
    assert client.get(a["url"], headers=owner_h).content == b"\x89PNG-a"
    assert client.get(b["url"], headers=owner_h).content == b"\x00\x00\x00 ftypmp42-b"
    assert media_ops.verify(log=lambda s: None)["mismatch"] == 0


# ── multi-user hardening (Phase 4) ──────────────────────────────────────────


def test_the_trash_keeps_bytes_for_the_retention_then_purges(client):
    import time

    from app import files, media_ops
    from app.media_storage import get_storage

    owner, _ = _user(client, "ms_trash")
    out = files.save_generated_image_as_asset(owner, b"\x89PNG-trash", mime="image/png")
    assert files.delete_asset_and_file(out["asset_id"]) is True
    # Not old enough: the default retention is days, and the purge measures against now.
    assert media_ops.purge_trash(retention_days=7, log=lambda s: None)["purged"] == 0
    assert get_storage().exists(out["rel_path"])
    # Old enough: a purge run "in a month" removes bytes and row.
    counts = media_ops.purge_trash(retention_days=7, now=time.time() + 30 * 86400, log=lambda s: None)
    assert counts["purged"] >= 1 and not get_storage().exists(out["rel_path"])


def test_a_signed_link_serves_one_file_without_an_account_until_it_expires(client):
    from app import files, media_links

    owner, owner_h = _user(client, "ms_link")
    other, other_h = _user(client, "ms_link_other")
    out = files.save_generated_image_as_asset(owner, b"\x89PNG-link", mime="image/png")

    assert client.get(f"/v1/files/{out['asset_id']}/link", headers=other_h).status_code == 404   # not theirs
    link = client.get(f"/v1/files/{out['asset_id']}/link", headers=owner_h).json()
    assert link["url"].startswith(f"/files/{out['asset_id']}?exp=")
    client.cookies.clear()
    assert client.get(link["url"]).content == b"\x89PNG-link"                     # no account at all
    assert client.get(out["url"]).status_code == 401                               # the bare URL still needs one
    tampered = link["url"].replace("sig=", "sig=0")
    assert client.get(tampered).status_code == 401
    expired = media_links.sign(out["asset_id"], ttl_s=1, now=0)["url"]            # exp in 1970
    assert client.get(expired).status_code == 401
    # A link is for one asset: the same signature does not open another.
    second = files.save_generated_image_as_asset(owner, b"\x89PNG-second", mime="image/png")
    borrowed = link["url"].replace(out["asset_id"], second["asset_id"])
    assert client.get(borrowed).status_code == 401


def test_flat_files_are_public_only_as_avatars_or_persona_visuals(client):
    """avatar_*/outfit_*/thumb_* used to be public by name alone (audit A1)."""
    import sqlite3

    from app import files
    from app.storage import _get_db_path

    root = files._upload_root()
    (root / "avatar_loose.png").write_bytes(b"\x89PNG-loose")
    client.cookies.clear()
    assert client.get("/files/avatar_loose.png").status_code == 401                # a name is not a grant

    owner, owner_h = _user(client, "ms_public")
    con = sqlite3.connect(_get_db_path())
    con.execute("UPDATE users SET avatar_url = ? WHERE id = ?", ("/files/avatar_loose.png", owner))
    con.commit()
    con.close()
    client.cookies.clear()
    assert client.get("/files/avatar_loose.png").content == b"\x89PNG-loose"      # now someone's avatar: public

    visual = root / "projects" / "p-vis" / "persona" / "appearance"
    visual.mkdir(parents=True, exist_ok=True)
    (visual / "outfit_red.png").write_bytes(b"\x89PNG-outfit")
    assert client.get("/files/projects/p-vis/persona/appearance/outfit_red.png").content == b"\x89PNG-outfit"
    (root / "projects" / "p-vis" / "persona" / "appearance" / "notes.txt").write_bytes(b"private")
    assert client.get("/files/projects/p-vis/persona/appearance/notes.txt").status_code == 401


def test_a_users_folder_is_served_to_that_user_only_on_the_path_routes(client):
    """users/<other>/… through the legacy path route used to be readable by any account (audit A2)."""
    from app import files

    owner, owner_h = _user(client, "ms_own")
    other, other_h = _user(client, "ms_other_acc")
    folder = files._upload_root() / "users" / owner / "images"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "legacy.png").write_bytes(b"\x89PNG-legacy")
    path = f"/files/users/{owner}/images/legacy.png"
    assert client.get(path, headers=owner_h).content == b"\x89PNG-legacy"
    assert client.get(path, headers=other_h).status_code == 404
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_uploads_are_checked_before_they_are_stored(client, monkeypatch):
    from app import files

    owner, owner_h = _user(client, "ms_checks")
    # An image that is not one.
    r = client.post("/v1/files/upload", files={"file": ("fake.png", io.BytesIO(b"<html>not a png"), "image/png")}, headers=owner_h)
    assert r.status_code == 400 and "not the image" in r.json()["detail"]
    # The scanner has the last word (its exit code), and runs before anything is stored.
    monkeypatch.setenv("MEDIA_SCAN_COMMAND", "sh -c 'exit 1'")
    r = client.post("/v1/files/upload", files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")}, headers=owner_h)
    assert r.status_code == 400 and "scanner" in r.json()["detail"]
    monkeypatch.setenv("MEDIA_SCAN_COMMAND", "sh -c 'exit 0'")
    r = client.post("/v1/files/upload", files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")}, headers=owner_h)
    assert r.status_code == 200, r.text
    monkeypatch.delenv("MEDIA_SCAN_COMMAND")
    # A quota: 1 KB per user, and the usage endpoint says so.
    monkeypatch.setenv("MEDIA_QUOTA_MB_PER_USER", "0.001")
    r = client.post("/v1/files/upload", files={"file": ("big.bin", io.BytesIO(b"x" * 2000), "application/octet-stream")}, headers=owner_h)
    assert r.status_code == 413 and "quota" in r.json()["detail"].lower()
    usage = client.get("/v1/files/usage", headers=owner_h).json()
    assert usage["quota_bytes"] == 1048 and usage["used_bytes"] >= 5
    monkeypatch.delenv("MEDIA_QUOTA_MB_PER_USER")
    files.delete_conversation_media("")   # no-op; keeps the helper imported


# ── a real S3 server, when there is one ─────────────────────────────────────


@pytest.mark.skipif(not os.getenv("HOMEPILOT_TEST_S3_ENDPOINT"),
                    reason="set HOMEPILOT_TEST_S3_ENDPOINT (and S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY) to run the contract against a real S3 server")
def test_the_contract_holds_against_a_real_s3_server():
    from app.media_storage import S3Settings, S3Storage

    settings = S3Settings.from_env({
        **os.environ,
        "S3_ENDPOINT_URL": os.environ["HOMEPILOT_TEST_S3_ENDPOINT"],
        "S3_BUCKET": os.getenv("HOMEPILOT_TEST_S3_BUCKET", "homepilot-media-test"),
        "S3_PREFIX": f"contract-{uuid.uuid4().hex[:8]}",
    })
    storage = S3Storage(settings)
    for check in CONTRACT:
        check(storage)
