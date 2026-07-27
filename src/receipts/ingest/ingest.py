"""Upload entry point: validate, store, and create an in-memory job (§14.1).

Ingest is the pipeline's front door. It sniffs an upload to reject non-images
*before* they cost any storage, rasterises multi-page PDFs into per-page images,
stores the original bytes through an injected :class:`StorageBackend`, and hands
back a :class:`ReceiptJob` describing where the bytes landed. It never parses or
interprets the receipt -- that is Extract's job.

Persistence does not exist yet (Phase 3), so a :class:`ReceiptJob` is a plain
in-memory dataclass and nothing is written to a database here; the storage
backend is injected so tests (and dev) can use a local temp directory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pypdfium2

from .storage import StorageBackend, make_image_key

#: Default upload ceiling. Phone photos and multi-page PDF receipts fit well
#: under this; anything larger is far more likely to be a mis-upload than a
#: receipt, so it is refused before it touches storage.
_DEFAULT_MAX_MB = 25

#: Only these containers are accepted. The extension is a cheap first gate; the
#: magic-byte sniff below is what actually decides the type.
_ALLOWED_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic", ".heif"}
)

#: Enough leading bytes to cover every signature we sniff (the WEBP/HEIC markers
#: sit at byte offsets 8 and 4 respectively).
_HEADER_BYTES = 32

#: DPI used when rasterising PDF pages. 200 keeps small print legible for the
#: downstream VLM without producing needlessly huge bitmaps. pypdfium2 renders
#: at 72 DPI per unit of ``scale``.
_PDF_RENDER_DPI = 200


@dataclass
class UploadCheck:
    """Verdict from :func:`validate_upload`, computed before any storage write.

    ``content_type`` is the sniffed MIME type when ``ok`` is true, otherwise
    ``None``; ``reason`` explains the rejection when ``ok`` is false. ``size_bytes``
    is always populated so the caller can log it either way.
    """

    ok: bool
    reason: str | None
    content_type: str | None
    size_bytes: int


@dataclass
class ReceiptJob:
    """In-memory record of one ingested receipt (no DB row yet -- Phase 3).

    Captures the generated ``id``, the storage ``image_key`` the original bytes
    were written to, and provenance (``source``, ``original_filename``,
    ``content_type``) for the pipeline stages that follow.
    """

    id: uuid.UUID
    image_key: str
    source: str
    original_filename: str
    content_type: str


def _sniff_content_type(header: bytes) -> str | None:
    """Map leading file bytes to a supported MIME type, or ``None`` if unknown.

    Trusting the bytes rather than the extension stops a renamed ``.txt`` (or a
    truncated download) from reaching the model as if it were an image.
    """
    if header[:2] == b"\xff\xd8":
        return "image/jpeg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if header[:4] == b"%PDF":
        return "application/pdf"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF and other ISO-BMFF files carry an ``ftyp`` box at offset 4; the
    # specific brand varies (heic/heix/mif1/...), so the box marker is enough.
    if header[4:8] == b"ftyp":
        return "image/heic"
    return None


def _check_upload(
    suffix: str, size_bytes: int, header: bytes, max_mb: int
) -> UploadCheck:
    """Shared validation core for both the path and bytes entry points.

    Checks run cheapest-first (extension, then size, then a content sniff) and
    the first failure wins, so the ``reason`` names the most fundamental problem.
    """
    suffix = suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        return UploadCheck(
            ok=False,
            reason=f"unsupported file extension: {suffix!r}",
            content_type=None,
            size_bytes=size_bytes,
        )

    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        return UploadCheck(
            ok=False,
            reason=f"file too large: {size_bytes} bytes exceeds the {max_mb} MB limit",
            content_type=None,
            size_bytes=size_bytes,
        )
    if size_bytes == 0:
        return UploadCheck(
            ok=False, reason="file is empty", content_type=None, size_bytes=0
        )

    content_type = _sniff_content_type(header)
    if content_type is None:
        return UploadCheck(
            ok=False,
            reason="file contents do not match a supported image or PDF type",
            content_type=None,
            size_bytes=size_bytes,
        )

    return UploadCheck(
        ok=True, reason=None, content_type=content_type, size_bytes=size_bytes
    )


def validate_upload(path: Path, max_mb: int = _DEFAULT_MAX_MB) -> UploadCheck:
    """Gate an uploaded *file* before it is stored.

    Applies a size limit, an extension check, and a magic-byte sniff, returning
    an :class:`UploadCheck`. Rejections happen here, before storage, so a bad
    upload never consumes a blob or a downstream model call. A missing file is a
    (failed) verdict rather than an exception.
    """
    path = Path(path)
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return UploadCheck(
            ok=False, reason="file not found", content_type=None, size_bytes=0
        )
    with path.open("rb") as handle:
        header = handle.read(_HEADER_BYTES)
    return _check_upload(path.suffix, size_bytes, header, max_mb)


def expand_pdf(path: Path, out_dir: Path) -> list[Path]:
    """Rasterise each page of a PDF to a PNG in ``out_dir``; one receipt per page.

    Pages are written as ``page_{n:04d}.png`` (``n`` from 0) and returned in page
    order. This turns pages into pixels only -- it never reads the page text.
    ``out_dir`` is created if needed.
    """
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scale = _PDF_RENDER_DPI / 72.0
    pdf = pypdfium2.PdfDocument(path)
    try:
        out_paths: list[Path] = []
        for index in range(len(pdf)):
            page = pdf[index]
            image = page.render(scale=scale).to_pil()
            out_path = out_dir / f"page_{index:04d}.png"
            image.save(out_path, format="PNG")
            out_paths.append(out_path)
        return out_paths
    finally:
        pdf.close()


def ingest_file(
    path: Path, storage: StorageBackend, source: str = "upload"
) -> ReceiptJob:
    """Validate a file, store its original bytes, and return a :class:`ReceiptJob`.

    Raises ``ValueError`` with the validation reason when the upload is rejected
    (so callers cannot accidentally proceed on a bad file). On success the bytes
    are written under :func:`make_image_key` and a job describing them is returned.
    No database write happens (Phase 3).
    """
    path = Path(path)
    check = validate_upload(path)
    if not check.ok:
        raise ValueError(check.reason)
    return _store_original(
        data=path.read_bytes(),
        original_filename=path.name,
        content_type=check.content_type,
        storage=storage,
        source=source,
    )


def ingest_bytes(
    data: bytes,
    filename: str,
    storage: StorageBackend,
    source: str = "upload",
) -> ReceiptJob:
    """Byte-oriented twin of :func:`ingest_file` (e.g. an HTTP upload body).

    Validates the in-memory bytes with the same rules, then stores and returns a
    :class:`ReceiptJob`. Raises ``ValueError`` on a rejected upload.
    """
    check = _check_upload(
        Path(filename).suffix, len(data), data[:_HEADER_BYTES], _DEFAULT_MAX_MB
    )
    if not check.ok:
        raise ValueError(check.reason)
    return _store_original(
        data=data,
        original_filename=filename,
        content_type=check.content_type,
        storage=storage,
        source=source,
    )


def _store_original(
    data: bytes,
    original_filename: str,
    content_type: str | None,
    storage: StorageBackend,
    source: str,
) -> ReceiptJob:
    """Write validated original bytes to storage and build the job record.

    Factored out so the file and bytes entry points cannot drift apart in how
    they mint the id, choose the key, or populate the job.
    """
    # A validated upload always has a sniffed type; the fallback only guards the
    # type checker and never fires on the happy path.
    resolved_type = content_type or "application/octet-stream"
    receipt_id = uuid.uuid4()
    image_key = make_image_key(receipt_id, "original")
    storage.put(image_key, data, resolved_type)
    return ReceiptJob(
        id=receipt_id,
        image_key=image_key,
        source=source,
        original_filename=original_filename,
        content_type=resolved_type,
    )
