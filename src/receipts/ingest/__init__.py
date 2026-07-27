"""Ingest layer: dedupe, job creation, and blob storage, never parsing (§14.1).

The pipeline's front door. Validates and stores uploads and creates an in-memory
job (:mod:`receipts.ingest.ingest`); computes perceptual hashes and finds image
or semantic duplicates over injected candidate sets
(:mod:`receipts.ingest.dedupe`); and abstracts blob storage behind a
``StorageBackend`` with local-filesystem and S3 implementations
(:mod:`receipts.ingest.storage`).

Persistence does not exist yet (Phase 3): duplicate lookups operate on injected
candidates and jobs are returned in memory rather than written to a database.
"""

from __future__ import annotations

from .dedupe import (
    compute_phash,
    find_near_duplicate_image,
    find_semantic_duplicate,
    link_duplicate,
    phash_distance,
)
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
)

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
    "link_duplicate",
    "make_image_key",
    "phash_distance",
    "validate_upload",
]
