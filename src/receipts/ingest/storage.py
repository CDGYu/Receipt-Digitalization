"""Blob storage abstraction and image-key layout for ingest (spec §14.1).

Ingest owns *where the bytes live*, never what they say. A :class:`StorageBackend`
is a deliberately narrow put/get/url/delete contract so the rest of the pipeline
can stash an original upload and its derived variants without caring whether they
land on the local filesystem (dev) or an object store (prod). Keys are
content-blind, deterministic paths (:func:`make_image_key`), so the same receipt
variant always maps to the same place.

Persistence proper does not exist yet (Phase 3); these backends move bytes only
and never write to a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID


class StorageBackend(Protocol):
    """Narrow blob-storage contract: address bytes by an opaque string key.

    ``put`` returns the key it stored under (so callers need not reconstruct it),
    ``get`` reads the bytes back, ``url`` yields a locator a browser/reviewer can
    open, and ``delete`` removes the blob. Implementations must not interpret the
    payload.
    """

    def put(self, key: str, data: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def url(self, key: str, expires_in: int = 3600) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Filesystem-backed :class:`StorageBackend` rooted at a directory.

    Keys are treated as paths relative to ``root``; :meth:`put` creates parent
    directories as needed and writes the bytes verbatim. Intended for development
    and tests, so :meth:`url` returns a ``file://`` URI rather than a signed HTTP
    link, and ``content_type`` is accepted for contract parity but not persisted
    (the filesystem has nowhere to keep it).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def url(self, key: str, expires_in: int = 3600) -> str:
        # expires_in is irrelevant for a local file URI but kept for parity with
        # the Protocol so callers can swap backends without changing call sites.
        return self._path(key).resolve().as_uri()

    def delete(self, key: str) -> None:
        # Idempotent: ingest may retry cleanup, so a missing blob is not an error.
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """Object-store :class:`StorageBackend` (S3/MinIO) for production.

    ``boto3`` is a prod-only dependency that is not installed in the default or
    CI environments, so it is imported lazily inside each method and a missing
    install surfaces as a clear ``RuntimeError`` rather than an ``ImportError``
    at module import time. Only that missing-dependency path is unit-tested; the
    happy path needs live credentials and is out of scope for the offline suite.
    """

    def __init__(
        self,
        bucket: str,
        *,
        region: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url

    def _client(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 not installed") from exc
        return boto3.client(
            "s3", region_name=self.region, endpoint_url=self.endpoint_url
        )

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._client().put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    def get(self, key: str) -> bytes:
        response = self._client().get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def url(self, key: str, expires_in: int = 3600) -> str:
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, key: str) -> None:
        self._client().delete_object(Bucket=self.bucket, Key=key)


def make_image_key(
    receipt_id: UUID, variant: str, when: datetime | None = None
) -> str:
    """Deterministic blob key for one variant of a receipt image.

    Layout ``receipts/{yyyy}/{mm}/{id}/{variant}.jpg`` using the year and month
    of ``when`` (defaulting to the current UTC time). Partitioning by year/month
    keeps any single directory or object prefix from growing without bound, and
    keying by ``receipt_id`` keeps every variant of a receipt (original,
    deskewed, ...) together under one folder.

    Callers minting several variants of the *same* receipt should pass a single
    shared ``when`` so every variant lands in the same yyyy/mm folder -- relying
    on the wall clock could split them across a month rollover.
    """
    if when is None:
        when = datetime.now(UTC)
    return f"receipts/{when:%Y}/{when:%m}/{receipt_id}/{variant}.jpg"
