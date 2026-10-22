# Media storage

Where HomePilot keeps media bytes — uploads, generated images and videos, avatars, room
documents — and how that becomes S3-ready without moving a file or changing a URL.

**Status:** Phases 1–4 implemented, 21 October 2026 — the interface and local backend, the
S3 backend, the backend recorded on every asset, checksums with verify/migrate/backup/restore,
and the multi-user hardening. A fifth phase (PostgreSQL, a shared queue, several app replicas,
storage HA) was dropped: one HomePilot instance serving a household or a small team never
needs it, and nothing here assumes it. Its triggers would be concrete — more than one backend
process writing the same data, or visible SQLite write contention — not "more users".

## Decisions

1. **Local HomePilot works completely offline.** `local` is the default backend and needs
   no service, credential or network. A self-hosted S3-compatible server is opt-in.
2. **S3 is a protocol, not a vendor.** The next backend speaks plain S3 against any
   endpoint (MinIO/AIStor Free, Garage, SeaweedFS, RustFS, a Hugging Face bucket's S3
   layer). The original open-source MinIO repository was archived in April 2026 and AIStor
   Free is single-node only, so no storage product is a dependency of the application.
3. **SQLite, the existing asset IDs and the existing files stay.** `file_assets` (owner,
   kind, rel_path, mime, size, project, conversation) and `assets` (storage_backend,
   storage_key, sha256, …) remain the two registries; a third canonical table is not
   introduced. PostgreSQL is reassessed only with multiple independently writing
   application replicas or sustained write contention.

## The interface

`backend/app/media_storage/` — `MediaStorage` (base.py), `LocalStorage` (local.py), and
`get_storage()` (`__init__.py`), the single way to obtain the configured backend.

```python
from .media_storage import get_storage

storage = get_storage()
storage.put("users/<id>/images/<file>.png", data)      # atomic; bytes or a stream
with storage.open_write(key) as out: ...               # chunked; discarded entirely on error
storage.open(key) / read(key) / exists(key) / size(key)
storage.delete(key)                                     # True when something was removed
storage.copy(src, dst)
storage.local_path(key)                                 # a Path for local, None for remote
```

**Keys** are relative POSIX paths under the storage root — the very strings
`file_assets.rel_path` and `assets.storage_key` already hold (`users/<user>/images/<f>`,
`avatar_<user>_<hex>.png`). That is why nothing moves: an asset registered before this
existed resolves by the same key. `normalize_key()` treats backslashes as separators (keys
recorded on Windows), collapses odd slashes, and refuses anything that could leave the
root: absolute paths, drive letters, `..`, NUL (`StorageKeyError`).

**Writes are atomic** in `LocalStorage`: a temp file in the target's directory, `fsync`,
then `os.replace`. A reader never sees a half-written object, and an aborted write leaves
nothing — no object, no `.part` file.

**The backend is a deployment setting.** `MEDIA_STORAGE_BACKEND=local` (default) or `s3`.
A name this HomePilot does not have is a clear `RuntimeError` at first use, never a silent
local write. `get_storage()` builds the backend once, touching no network, and rebuilds it
when the backend or its settings change (tests, `DATA_DIR`).

## The S3 backend (Phase 2)

`S3Storage` (s3.py) speaks plain S3 through boto3 — imported only when this backend is
selected, so a local HomePilot needs neither the library nor a server. Any S3-compatible
store works: a self-hosted MinIO/AIStor Free, Garage, RustFS or SeaweedFS, AWS, or a
Hugging Face bucket's S3 layer. Keys are the same relative paths, with an optional prefix in
front, so the registries do not change when the backend does. A PUT is atomic on every S3
server (an object appears only once its upload completed), which is the `open_write`
contract: a stream is spooled locally and uploaded when its block ends, dropped when it
raises. Content types come from the key's extension.

```env
MEDIA_STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://127.0.0.1:9400     # unset for AWS
S3_BUCKET=homepilot-media
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=…                        # or boto3's own credential chain when unset
S3_SECRET_ACCESS_KEY=…
S3_ADDRESSING_STYLE=path                  # virtual for AWS-style hosts
S3_PREFIX=                                # optional key prefix inside the bucket
S3_CREATE_BUCKET=1                        # make the bucket on first use when missing
```

**A self-hosted server in one command:** `make start-media-s3` runs an S3 server in Docker on
`127.0.0.1:9400` (console `:9401`) from `agentic/ops/compose/media-s3.compose.yml`, with its
objects in `backend/data/media-s3/` (git-ignored; back it up like the database) and
credentials generated once into `backend/data/media-s3.env` (mode 600, never printed).
`MEDIA_S3_PORT` / `MEDIA_S3_CONSOLE_PORT` move the ports; `MEDIA_S3_IMAGE` picks another
server than the default community MinIO image, which is frozen (its repository was archived
in April 2026) — the profile only asks for the two usual credentials. The container gets its
own Docker network on `MEDIA_S3_SUBNET` (default `10.251.9.0/24`): Docker's own pick from
172.17–172.31/16 collided with a VPN route on a laptop and left the published port
unreachable. `make stop-media-s3` stops it. The target prints the four lines to give the
backend.

**Switching a `make start` HomePilot:** `make use-media-s3` writes
`backend/data/media-storage.env` (the backend's `MEDIA_STORAGE_BACKEND=s3` and `S3_*` lines,
credentials copied from the server's env file; mode 600) and `make start` sources that file
for the backend process — so the choice survives restarts and lives with the data, not in the
shell. `make use-media-local` removes it. Both take effect on the next `make start`.

**Every row names its backend (Phase 3a).** `file_assets.storage_backend` (`local` for every
row from before the column existed — they were written to this disk — and the configured
backend for new rows, set by `insert_asset`). `/files/{id}`, deletion and
`resolve_local_file` go to the backend the row names, so two stores holding the same key
can never be confused, and switching backends is safe in both directions: a row whose
backend this HomePilot is not configured for (switched back to `local` after writing to S3)
answers 404 with a log line naming it, until that backend is configured again. The column
is added idempotently at startup (`storage.ensure_file_assets_backend_column`) and lazily by
`files.py` for a database opened without it.

Only keys **without a row** — path-based legacy URLs, public-by-prefix avatars — still use
`storage_for_read(key)`: the configured backend when it has the object, else this machine's
disk, so an avatar uploaded after the switch and a background from before it are both served.

**Code that needs a file on this disk** — ComfyUI inputs (`comfy.py`), the persona avatar
commit (`main.py`) — calls `files.resolve_local_file(ref)`: the object itself when it is on
the disk, else a copy fetched from the configured storage into `<upload root>/.cache/media/`
(kept, re-fetched when the size differs; `reconcile()` skips dot-folders).

**Verification.** The contract tests run against both backends — `local` on a temp dir and
`s3` on a dict-backed stand-in for boto3's client — and, when `HOMEPILOT_TEST_S3_ENDPOINT`
(with `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`) is set, against that real server under a
throw-away prefix: `backend/tests/test_media_storage.py`.

**AIStor Free, if chosen as the server:** its license is single-node and, per MinIO's
licensing documentation, does not allow server-side encryption at rest — use encrypted host
storage — and it should be confirmed to run fully disconnected before being bundled.

## What goes through it (Phase 1)

| Write | Module | Key |
|---|---|---|
| Uploads (`POST /v1/files/upload`) | `files.py` | `users/<id>/{uploads,images,projects/<p>}/<f>` |
| Uploads (`POST /upload`, chunked) | `main.py` | `users/<id>/uploads/<f>`, or flat without a user |
| Generated chat images and videos | `files.py` (`save_generated_*_as_asset`) | `users/<id>/images/<f>`, `users/<id>/misc/<f>` |
| Item uploads (`/projects/{id}/items/upload`) | `main.py` | `users/<id>/projects/<p>/<f>`, or flat without a user |
| Downloaded ComfyUI outputs | `main.py` (`_download_comfy_image`) | `<filename>` (flat) |
| User avatars | `users.py` | `avatar_<id>_<hex>.<ext>` (flat) |
| Background-tool results | `background.py` | `bg_<hex>.png` (flat) |

Reads of registered assets (`GET /files/{asset_id}` with a `file_assets` row) go through
`_serve_object`: a `FileResponse` when the backend has a local path, a 1 MB-chunk stream
otherwise. Deletes (`delete_asset_and_file`, `delete_conversation_media`) go through
`storage.delete`, with the same immediate semantics as before.

The registry functions are backend-aware: `register_asset(..., storage_backend=)` and
`find_asset_id_by_storage_key(key, storage_backend=)` default to the configured backend and
no longer hard-code `'local'`. `reconcile()` and `register_comfy_output()` scan this disk and
say `local` explicitly.

**Deliberately left on the filesystem:** ComfyUI input copies (`comfy.py`), render working
files (`studio/render_mp4.py`), crop and persona-appearance temp copies (`main.py`), the
knowledge-base ingestion file of `/projects/{id}/upload`, Creator Studio's own file area
(`studio/routes.py`) and Teams room documents (`teams/rooms.py`, under `<data>/teams/`).
Temporary working files are not forced into object storage; the last three are persistent
and are Phase 2 candidates once their URL schemes are reviewed.

## Checksums, verify, migrate, backup, restore (Phase 3)

Every writer records the SHA-256 of the bytes it stored in `file_assets.sha256` (rows from
before carry `''`). `backend/app/media_ops.py` is both a library and a CLI
(`python -m app.media_ops …`, or the `make media-*` targets, which run with the same
`backend/data/media-storage.env` that `make start` gives the backend):

| Command | What it does |
|---|---|
| `make media-verify` | every live asset: its backend configured, the object there, the hash as recorded; exits 1 on a missing or changed object |
| `make media-migrate` (`MEDIA_MIGRATE_ARGS=--dry-run` / `--prune-source`) | copies each asset that is not in the configured backend into it, reads it back, compares hashes, then flips the row (and the `assets` registry row); **the source is kept** unless `--prune-source`; idempotent |
| `make media-backup` (`MEDIA_BACKUP_DIR=…`) | a portable backup: a consistent copy of the database, every live asset's bytes under `media/<key>`, and `manifest.json` with the rows and hashes — independent of any backend's on-disk format |
| `make media-restore MEDIA_BACKUP_DIR=…` | puts the backup's assets into the configured backend, verifies each against the manifest and by reading it back, and makes sure each has its row naming that backend; the database file itself is restored by copying `homepilot.db` back while HomePilot is stopped |
| `make media-gc` | purges the trash (below); the backend also runs this itself |

The restore drill is a test, not a document: `test_backup_and_restore_round_trip` backs up,
removes the objects, restores, and serves them again.

## Multi-user hardening (Phase 4)

Defaults keep a local, single-person HomePilot exactly as it was; each control is a setting.

- **Soft deletion.** Deleting an asset marks it (`deleted_at`) and it disappears from every
  read; its bytes stay for `MEDIA_TRASH_RETENTION_DAYS` (7) and are then purged by a
  background thread (and `make media-gc`). `0` restores immediate removal.
- **Public is a property, not a filename** (audit A1). A flat file is served without an
  account only when it is some user's current avatar (the login screen shows those) or a
  persona visual that also lives under a project's appearance folder; a registered asset,
  when its `visibility` is `public`. Other `avatar_*`/`outfit_*`/`thumb_*` files now need an
  account, a signed link or the API key. New profile pictures get a random name — the
  account id is no longer in it.
- **Ownership on the path routes** (A2). `/files/users/<id>/…` is served to that account
  only; a persona's own pictures (`projects/<id>/persona/appearance/…`) stay public; other
  legacy paths need an account, as before.
- **Signed links instead of account tokens** (A3). `GET /v1/files/{id}/link?ttl=` returns
  `/files/{id}?exp=…&sig=…` — valid for that one asset until `exp`, nothing else
  (`media_links.py`, HMAC with `MEDIA_SIGNING_KEY` or a key generated once into the data
  dir, mode 600). In the packaged container the frontend and backend share an origin, so
  `<img>` tags are authorised by the HttpOnly session cookie and carry no token; the
  `?token=` form remains for the cross-origin dev setup and the API key for OllaBridge's
  media proxy.
- **Quotas** (`MEDIA_QUOTA_MB_PER_USER`, 0 = none). An upload that would take its owner
  past the limit is refused with 413 before any byte is stored; the trash does not count;
  `GET /v1/files/usage` reports both numbers.
- **Validation and quarantine.** A file presented as an image must start like one (PNG,
  JPEG, GIF, WebP, BMP) or it is refused. `MEDIA_SCAN_COMMAND` (e.g. `clamdscan
  --no-summary`) runs on a temporary copy with the path appended; a non-zero exit refuses
  the upload — nothing is stored until the scanner has said yes.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 — Foundation | `MediaStorage`, `LocalStorage`, backend-aware registry, contract tests | done |
| 2 — Local S3 | `S3Storage`, `make start-media-s3` / `use-media-s3`, read fallback for keys with no row, local copies for ComfyUI | done |
| 3a — Backend per row | `file_assets.storage_backend`, reads and deletes by the row's backend | done |
| 3 — Reliability | SHA-256 on write; `verify`, `migrate`, `backup`, `restore`; the restore drill as a test | done |
| 4 — Multi-user hardening | soft deletion, public as a property, ownership on path routes, signed links, quotas, validation and a scanner hook | done |
| ~~5 — Scale-out~~ | dropped; see the status note at the top | — |

Phase 1 acceptance, as agreed: existing assets keep IDs, paths, URLs and content; uploads
and generated media work as before; the selected persistent writes use `MediaStorage`;
temp files may stay on disk; the registry takes an explicit backend; local storage rejects
traversal and writes atomically; tests cover registration, retrieval, ownership, missing
files, failure recovery and the legacy read path; the default configuration needs no MinIO,
PostgreSQL, network or cloud credential; no existing file is moved or deleted.

## Audit of the file-access and deletion paths (`backend/app/files.py`)

Found while designing the interface. A1–A4 and A6 are addressed by Phase 4 above (public as
a property, ownership on path routes, signed links, soft deletion, random avatar names); A5
stays as recorded — the gallery URL shape depends on it — and is harmless now that the path
routes enforce ownership.

| # | Finding | Where | Risk |
|---|---|---|---|
| A1 | **Public by filename prefix.** Any file named `avatar_*`, `outfit_*` or `thumb_*` is served without authentication, by both `/files/{asset_id}` and `/files/{subpath}`. User profile pictures are written as `avatar_<user_id>_<hex>` (`users.py`), so every user's avatar is public, and the name exposes the user id. | `_is_public_file`, `download_file`, `download_file_legacy` | Information disclosure |
| A2 | **Authenticated path fallback without ownership.** When an id is not a `file_assets` row, `/files/{asset_id}` serves `<root>/<name>` and `/files/{subpath}` serves any `<root>/<subpath>` to *any* authenticated user — including `users/<other>/images/<file>`. Traversal is blocked; cross-user reads by path are not. | `download_file` (fallback), `download_file_legacy` | Cross-user read |
| A3 | **Account credentials in URLs.** `?token=` accepts a session token or the compat API key, so `<img>` URLs carry long-lived account credentials into logs, history and referrers. | `_resolve_user`, both routes | Credential leakage |
| A4 | **Immediate physical deletion.** `delete_asset_and_file` and `delete_conversation_media` remove the row and the bytes at once; there is no soft-delete window. | `_remove_object` and callers | Non-recoverable |
| A5 | **Inconsistent registry key for chat images.** `persist_chat_images` registers the `assets` row with `storage_key=<file_assets id>` instead of the path, because the gallery builds `/files/{storage_key}`; a path key would route through A2. Fix together with A2. | `persist_chat_images`, `main.py` gallery routes | Data quality |
| A6 | **Avatar replacement deletes the previous file immediately** and the legacy `/upload` endpoint writes to the flat root under a random name served by A2. | `users.py`, `main.py` | Same class as A2/A4 |

Proposed direction for the ticket: an explicit `public` flag on the asset instead of the
name prefix; ownership for every private legacy path (or a one-time registration of flat
files to their owners); short-lived, media-specific signed URLs for `<img>` instead of
account tokens; soft deletion with deferred removal through `MediaStorage`; and the same
compatibility rule as this phase — existing links keep working through tested fallbacks.
