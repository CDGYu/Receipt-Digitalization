"""Ingest layer: dedupe, job creation, and blob storage, never parsing (§14.1).

The pipeline's front door. Validates and stores uploads and creates an in-memory
job (:mod:`receipts.ingest.ingest`); computes perceptual hashes and finds image
or semantic duplicates over injected candidate sets
(:mod:`receipts.ingest.dedupe`); and abstracts blob storage behind a
``StorageBackend`` with local-filesystem and S3 implementations
(:mod:`receipts.ingest.storage`).

Persistence does not exist yet (Phase 3): duplicate lookups operate on injected
candidates and jobs are returned in memory rather than written to a database.

**``ingest`` and ``storage`` are imported eagerly; ``dedupe`` is not** --
ADR-0009's pattern, applied one package over for the same reason it was applied
to :mod:`receipts.persist`. :mod:`receipts.ingest.dedupe` needs numpy and
Pillow, which live in the optional ``pipeline`` extra, while validating an
upload and writing its bytes to storage need neither. Because Python runs a
package's ``__init__`` even when a submodule is imported directly, an eager
``from .dedupe import ...`` here meant ``from receipts.ingest.ingest import
ingest_file`` -- and so ``import receipts.cli``, and so *every* ``receipts``
command, including ``users list`` -- required Pillow to be installed. The names
are resolved on first attribute access (:pep:`562`) instead:
``from receipts.ingest import compute_phash`` works exactly as before, and
imports the same module it always did, just later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .ingest import (
    ReceiptJob,
    UploadCheck,
    expand_pdf,
    ingest_bytes,
    ingest_file,
    validate_upload,
)
from .storage import (
    LocalStorage,
    S3Storage,
    StorageBackend,
    make_image_key,
    make_storage,
)

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .dedupe import (
        compute_phash,
        find_near_duplicate_image,
        find_semantic_duplicate,
        link_duplicate,
        phash_distance,
    )

#: Lazily re-exported name -> the submodule that defines it.
_LAZY: dict[str, str] = {
    "compute_phash": "dedupe",
    "find_near_duplicate_image": "dedupe",
    "find_semantic_duplicate": "dedupe",
    "link_duplicate": "dedupe",
    "phash_distance": "dedupe",
}

__all__ = [
    "LocalStorage",
    "ReceiptJob",
    "S3Storage",
    "StorageBackend",
    "UploadCheck",
    "compute_phash",
    "expand_pdf",
    "find_near_duplicate_image",
    "find_semantic_duplicate",
    "ingest_bytes",
    "ingest_file",
    "make_storage",
    "link_duplicate",
    "make_image_key",
    "phash_distance",
    "validate_upload",
]


def __getattr__(name: str) -> Any:
    """Resolve a ``dedupe`` name on first use (:pep:`562`)."""
    from importlib import import_module

    # ``receipts.ingest.dedupe`` as an *attribute* still resolves, so no caller
    # that relied on the previous eager import has to change.
    if name == "dedupe":
        return import_module(".dedupe", __name__)

    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value  # cache it: the lookup happens once per process
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
