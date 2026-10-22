"""
S3Storage — media bytes in any S3-compatible object store, behind MediaStorage.

S3 is the protocol, not a vendor: MinIO or AIStor Free, Garage, SeaweedFS, RustFS, AWS, a
Hugging Face bucket's S3 layer — anything that answers SigV4 PUT/GET/HEAD/DELETE/COPY.
boto3 is imported only here, when this backend is selected, so a local HomePilot needs
neither the library nor a server.

Keys are the same relative paths as the local backend (an optional S3_PREFIX in front), so
the registries do not change when the backend does. A PUT is atomic on every S3 server — an
object appears only once its upload completed — which is the ``open_write`` contract: a
stream is spooled locally and uploaded when its block ends, dropped when it raises.
"""
from __future__ import annotations

import mimetypes
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterator, Mapping, Optional, Union

from .base import Bytes, MediaStorage, StoredObject, normalize_key

_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}
_SPOOL_MAX = 8 * 1024 * 1024


def normalize_prefix(prefix: str) -> str:
    """"media/" for "media", "/media//" and so on; "" for none."""
    clean = "/".join(p for p in (prefix or "").replace("\\", "/").split("/") if p and p != ".")
    return f"{clean}/" if clean else ""


@dataclass(frozen=True)
class S3Settings:
    bucket: str
    endpoint_url: Optional[str] = None       # None: AWS; "http://127.0.0.1:9400": a self-hosted server
    region: str = "us-east-1"
    access_key: Optional[str] = None         # None: boto3's own credential chain (env, profile, role)
    secret_key: Optional[str] = None
    addressing_style: str = "path"           # path for self-hosted servers; virtual for AWS-style hosts
    prefix: str = ""                         # key prefix inside the bucket, "" or "name/"
    create_bucket: bool = True               # make the bucket on first use when it is missing
    verify_tls: bool = True

    def __post_init__(self) -> None:
        # "media", "/media//" and "media/" are the same prefix; a frozen dataclass sets it so.
        object.__setattr__(self, "prefix", normalize_prefix(self.prefix))
        object.__setattr__(self, "bucket", (self.bucket or "").strip())

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "S3Settings":
        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()

        def flag(name: str, default: str = "1") -> bool:
            return get(name, default).lower() not in ("0", "false", "no", "off")

        return cls(
            bucket=get("S3_BUCKET", "homepilot-media"),
            endpoint_url=get("S3_ENDPOINT_URL") or None,
            region=get("S3_REGION", "us-east-1") or "us-east-1",
            access_key=get("S3_ACCESS_KEY_ID") or get("AWS_ACCESS_KEY_ID") or None,
            secret_key=get("S3_SECRET_ACCESS_KEY") or get("AWS_SECRET_ACCESS_KEY") or None,
            addressing_style=(get("S3_ADDRESSING_STYLE", "path").lower() or "path"),
            prefix=normalize_prefix(get("S3_PREFIX")),
            create_bucket=flag("S3_CREATE_BUCKET"),
            verify_tls=flag("S3_VERIFY_TLS"),
        )

    def signature(self) -> tuple:
        """What distinguishes one configured store from another (credentials excluded)."""
        return ("s3", self.endpoint_url or "", self.bucket, self.prefix, self.region, self.addressing_style)


def _is_missing(error: BaseException) -> bool:
    response = getattr(error, "response", None) or {}
    code = str((response.get("Error") or {}).get("Code") or "")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in _MISSING_CODES or status == 404


def _content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def _build_client(settings: S3Settings) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "MEDIA_STORAGE_BACKEND=s3 needs boto3: in backend/, `uv pip install -e '.[s3]'` "
            "(or `pip install 'boto3>=1.34'`)."
        ) from e
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": settings.addressing_style},
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
    )
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        config=config,
        verify=settings.verify_tls,
    )


class _Body:
    """A GET body as a plain binary stream (boto3's StreamingBody is not a context manager)."""

    def __init__(self, body: Any) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body.read() if size is None or size < 0 else self._body.read(size)

    def close(self) -> None:
        close = getattr(self._body, "close", None)
        if close:
            close()

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self.read(1024 * 1024)
            if not chunk:
                return
            yield chunk


class S3Storage(MediaStorage):
    name = "s3"

    def __init__(self, settings: S3Settings, *, client: Any = None) -> None:
        if not settings.bucket:
            raise ValueError("S3_BUCKET is required for MEDIA_STORAGE_BACKEND=s3")
        self.settings = settings
        self._client = client          # injected in tests; built lazily otherwise
        self._bucket_ready = False

    # ── plumbing ───────────────────────────────────────────────────────────────

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client(self.settings)
        return self._client

    @property
    def bucket(self) -> str:
        return self.settings.bucket

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as e:
            if not (_is_missing(e) and self.settings.create_bucket):
                raise
            kwargs: dict = {"Bucket": self.bucket}
            if not self.settings.endpoint_url and self.settings.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.settings.region}
            self.client.create_bucket(**kwargs)
        self._bucket_ready = True

    def _key(self, key: str) -> str:
        return self.settings.prefix + normalize_key(key)

    def _head(self, object_key: str) -> Optional[dict]:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception as e:
            if _is_missing(e):
                return None
            raise

    # ── writing ────────────────────────────────────────────────────────────────

    def put(self, key: str, data: Union[Bytes, BinaryIO], *, overwrite: bool = True) -> StoredObject:
        self._ensure_bucket()
        object_key = self._key(key)
        if not overwrite and self._head(object_key) is not None:
            raise FileExistsError(normalize_key(key))
        content_type = _content_type(key)
        if hasattr(data, "read"):
            self.client.upload_fileobj(data, self.bucket, object_key, ExtraArgs={"ContentType": content_type})
            size = int((self._head(object_key) or {}).get("ContentLength") or 0)
        else:
            payload = bytes(data)  # type: ignore[arg-type]
            self.client.put_object(Bucket=self.bucket, Key=object_key, Body=payload, ContentType=content_type)
            size = len(payload)
        return StoredObject(self.name, normalize_key(key), size)

    @contextmanager
    def open_write(self, key: str, *, overwrite: bool = True) -> Iterator[BinaryIO]:
        self._ensure_bucket()
        object_key = self._key(key)
        if not overwrite and self._head(object_key) is not None:
            raise FileExistsError(normalize_key(key))
        spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX)
        try:
            yield spool  # type: ignore[misc]
            spool.seek(0)
            self.client.upload_fileobj(spool, self.bucket, object_key, ExtraArgs={"ContentType": _content_type(key)})
        finally:
            spool.close()

    def copy(self, src_key: str, dst_key: str, *, overwrite: bool = True) -> StoredObject:
        self._ensure_bucket()
        src, dst = self._key(src_key), self._key(dst_key)
        if self._head(src) is None:
            raise FileNotFoundError(normalize_key(src_key))
        if not overwrite and self._head(dst) is not None:
            raise FileExistsError(normalize_key(dst_key))
        self.client.copy_object(
            Bucket=self.bucket, Key=dst, CopySource={"Bucket": self.bucket, "Key": src},
            ContentType=_content_type(dst_key), MetadataDirective="REPLACE",
        )
        return StoredObject(self.name, normalize_key(dst_key), int((self._head(dst) or {}).get("ContentLength") or 0))

    # ── reading ────────────────────────────────────────────────────────────────

    def open(self, key: str) -> BinaryIO:
        self._ensure_bucket()
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except Exception as e:
            if _is_missing(e):
                raise FileNotFoundError(normalize_key(key)) from None
            raise
        return _Body(response["Body"])  # type: ignore[return-value]

    def exists(self, key: str) -> bool:
        self._ensure_bucket()
        return self._head(self._key(key)) is not None

    def size(self, key: str) -> int:
        self._ensure_bucket()
        head = self._head(self._key(key))
        if head is None:
            raise FileNotFoundError(normalize_key(key))
        return int(head.get("ContentLength") or 0)

    # ── removing ───────────────────────────────────────────────────────────────

    def delete(self, key: str) -> bool:
        self._ensure_bucket()
        object_key = self._key(key)
        if self._head(object_key) is None:
            return False
        self.client.delete_object(Bucket=self.bucket, Key=object_key)
        return True
