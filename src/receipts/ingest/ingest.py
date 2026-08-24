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

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

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

#: The most pages one PDF may become. Each page becomes a receipt, a database
#: row and a queued job, so an unbounded expansion turns one upload into
#: unbounded work -- and the size ceiling above does not bound it, because a
#: few megabytes of PDF can hold hundreds of pages. Refusing past the bound is
#: loud; silently keeping the first N would be the drop this system forbids.
_MAX_PDF_PAGES = 50


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

    ``pypdfium2`` is imported here, not at module top, because it belongs to
    the optional ``pipeline`` extra and this is the only function in the module
    that touches it -- :func:`ingest_file`/:func:`ingest_bytes` store original
    bytes and never rasterise. A module-top import made *every* importer of
    this module (``receipts.cli``, and so ``receipts users list``) require the
    extra; the same defect as ``openpyxl``/``PIL`` one module over, and the
    pattern ``clients/factory.py`` and ``ingest/storage.py`` already use for
    their own optional dependencies.
    """
    import pypdfium2

    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scale = _PDF_RENDER_DPI / 72.0
    pdf = pypdfium2.PdfDocument(path)
    try:
        out_paths: list[Path] = []
        for index in range(len(pdf)):
            # Close the page and its render bitmap each iteration; leaving them
            # for the GC leaks per-page pdfium objects and triggers warnings.
            page = pdf[index]
            bitmap = page.render(scale=scale)
            try:
                image = bitmap.to_pil()
                out_path = out_dir / f"page_{index:04d}.png"
                image.save(out_path, format="PNG")
                out_paths.append(out_path)
            finally:
                bitmap.close()
                page.close()
        return out_paths
    finally:
        pdf.close()


def _pdf_pages(data: bytes, stem: str) -> list[tuple[bytes, str]]:
    """Rasterise PDF bytes into ``(png_bytes, filename)`` per page, in page order.

    A bytes-oriented wrapper over :func:`expand_pdf`, which works in files
    because ``pypdfium2`` does. The temporary directory is torn down before this
    returns, so nothing survives the call but the bytes.

    **The page count is checked before anything is rendered.** Counting opens the
    document a second time, which is the cost of not rasterising four hundred
    pages in order to discover there were four hundred.

    ``pypdfium2`` is imported in the body for the reason :func:`expand_pdf`
    documents: it belongs to the optional ``pipeline`` extra, and a module-top
    import would make every importer of this module -- ``receipts.cli``, and so
    ``receipts users list`` -- require it.
    """
    import pypdfium2

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf_path = root / "upload.pdf"
        pdf_path.write_bytes(data)

        document = pypdfium2.PdfDocument(pdf_path)
        try:
            page_count = len(document)
        finally:
            document.close()
        if page_count > _MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has {page_count} pages; the limit is {_MAX_PDF_PAGES}"
            )

        rendered = expand_pdf(pdf_path, root / "pages")
        if not rendered:
            raise ValueError("PDF has no pages to process")
        return [
            (page.read_bytes(), f"{stem}-page-{number}.png")
            for number, page in enumerate(rendered, start=1)
        ]


def ingest_file(
    path: Path,
    storage: StorageBackend,
    source: str = "upload",
    max_mb: int = _DEFAULT_MAX_MB,
) -> list[ReceiptJob]:
    """Validate a file, store its bytes, and return one job per receipt.

    **A list because one upload is not always one receipt.** A photograph is one
    job; a PDF is one job per page, because one job maps to one receipt id
    downstream and :func:`~receipts.pipeline.process_receipt` requires a blob
    holding a single image. Returning a scalar here is what left `expand_pdf`
    without a caller and every PDF dying at ``preprocess`` (ISSUE-027).

    Raises ``ValueError`` with the validation reason when the upload is rejected
    (so callers cannot accidentally proceed on a bad file), and never returns an
    empty list -- zero receipts from an accepted upload would be a silent drop.
    No database write happens here. ``max_mb`` defaults to
    :data:`_DEFAULT_MAX_MB`; the API passes ``settings.max_upload_mb`` so the
    ceiling is one configured value, not a literal duplicated at every call site.
    """
    path = Path(path)
    check = validate_upload(path, max_mb)
    if not check.ok:
        raise ValueError(check.reason)
    return _store_upload(
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
    max_mb: int = _DEFAULT_MAX_MB,
) -> list[ReceiptJob]:
    """Byte-oriented twin of :func:`ingest_file` (e.g. an HTTP upload body).

    Validates the in-memory bytes with the same rules, then stores and returns
    one :class:`ReceiptJob` per receipt -- one for an image, one per page for a
    PDF. Raises ``ValueError`` on a rejected upload. ``max_mb`` defaults to
    :data:`_DEFAULT_MAX_MB`; the API passes ``settings.max_upload_mb`` so the
    ceiling is one configured value, not a literal duplicated at every call
    site.
    """
    check = _check_upload(
        Path(filename).suffix, len(data), data[:_HEADER_BYTES], max_mb
    )
    if not check.ok:
        raise ValueError(check.reason)
    return _store_upload(
        data=data,
        original_filename=filename,
        content_type=check.content_type,
        storage=storage,
        source=source,
    )


def _store_upload(
    data: bytes,
    original_filename: str,
    content_type: str | None,
    storage: StorageBackend,
    source: str,
) -> list[ReceiptJob]:
    """Store one validated upload as one or more receipts.

    The single place that decides how many receipts an upload becomes, so the
    file and bytes entry points cannot drift apart on it. A PDF is rasterised
    here and its pages stored individually; the PDF itself is not kept, because
    every downstream stage wants an image and the page images are what the rest
    of the system reads. The source filename survives in each page's
    ``original_filename``, which is the only provenance a reviewer looking at
    twelve receipts has.
    """
    if content_type == "application/pdf":
        stem = Path(original_filename).stem
        return [
            _store_one(
                data=page,
                original_filename=name,
                content_type="image/png",
                storage=storage,
                source=source,
            )
            for page, name in _pdf_pages(data, stem)
        ]
    return [
        _store_one(
            data=data,
            original_filename=original_filename,
            content_type=content_type,
            storage=storage,
            source=source,
        )
    ]


def _store_one(
    data: bytes,
    original_filename: str,
    content_type: str | None,
    storage: StorageBackend,
    source: str,
) -> ReceiptJob:
    """Write one receipt's bytes to storage and build its job record.

    One receipt id, one blob key, one job. Every receipt in the system is minted
    here, whether it arrived as a photograph or as page nine of a PDF.
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
