"""Tests for the ingest layer: storage, dedupe, and upload validation (spec §14.1).

Ingest owns *where the bytes live* and *whether we have seen them before* --
never what the receipt says. Every fixture here is built in-memory (Pillow) or
under ``tmp_path``; nothing touches a network or a database, which do not exist
yet (Phase 3). Duplicate lookups take injected candidate iterables and storage
is injected, so the whole layer is exercised offline.

The module is skipped when the optional "pipeline" extras (Pillow + pypdfium2)
are absent, mirroring the preprocess tests; CI installs the extras but the plain
dev environment does not.
"""

from __future__ import annotations

import importlib.util
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import mock

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")

import pypdfium2  # noqa: E402
from PIL import Image  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.ingest import (  # noqa: E402
    LocalStorage,
    ReceiptJob,
    S3Storage,
    UploadCheck,
    compute_phash,
    expand_pdf,
    find_near_duplicate_image,
    find_semantic_duplicate,
    ingest_bytes,
    ingest_file,
    link_duplicate,
    make_image_key,
    make_storage,
    phash_distance,
    validate_upload,
)

# --------------------------------------------------------------------------- #
# helpers -- synthetic images with known horizontal structure so dHash bits are
# predictable. A vertical gradient has constant rows (no horizontal change); its
# 90-degree rotation has strong horizontal change, so the two hashes differ a lot.
# --------------------------------------------------------------------------- #


def _vertical_gradient() -> Image.Image:
    """256x256 gradient that varies top-to-bottom (rows are constant)."""
    return Image.linear_gradient("L").convert("RGB")


def _horizontal_gradient() -> Image.Image:
    """The same gradient rotated 90 degrees: now it varies left-to-right."""
    return _vertical_gradient().rotate(90, expand=True)


def _png_bytes(color: tuple[int, int, int] = (5, 6, 7)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 10), color).save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# storage: LocalStorage
# --------------------------------------------------------------------------- #


def test_localstorage_put_get_roundtrips_bytes(tmp_path):
    storage = LocalStorage(tmp_path)
    key = storage.put("a/b/c.bin", b"hello world", "application/octet-stream")
    assert key == "a/b/c.bin"
    assert storage.get("a/b/c.bin") == b"hello world"


def test_localstorage_url_returns_file_uri(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.put("x.bin", b"data", "application/octet-stream")
    url = storage.url("x.bin")
    assert url.startswith("file://")


def test_localstorage_delete_removes_blob(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.put("y.bin", b"data", "application/octet-stream")
    storage.delete("y.bin")
    with pytest.raises(FileNotFoundError):
        storage.get("y.bin")


def test_localstorage_delete_is_idempotent(tmp_path):
    # Deleting a missing key must not raise -- ingest may retry cleanup.
    LocalStorage(tmp_path).delete("never-existed.bin")


# --------------------------------------------------------------------------- #
# storage: S3Storage (only the missing-dependency path is exercised offline)
# --------------------------------------------------------------------------- #


def test_s3storage_raises_clear_error_without_boto3():
    if importlib.util.find_spec("boto3") is not None:
        pytest.skip("boto3 is installed; the missing-dependency path is not applicable")
    s3 = S3Storage("my-bucket")
    with pytest.raises(RuntimeError, match="boto3 not installed"):
        s3.put("k", b"data", "image/png")


# --------------------------------------------------------------------------- #
# storage: make_storage (the backend-selection policy)
# --------------------------------------------------------------------------- #
#
# This policy shipped untested. It lived as ``_make_storage``, private in
# ``cli.py``, and no test referenced it under either name -- so when ADR-0035
# moved it here for the ASGI entry point to share, nothing proved the move
# preserved its behaviour. These three cases are that proof.


def test_make_storage_builds_a_local_backend_rooted_at_the_setting(tmp_path):
    settings = Settings(
        _env_file=None, storage_backend="local", storage_root=str(tmp_path / "blobs")
    )

    storage = make_storage(settings)

    assert isinstance(storage, LocalStorage)
    assert storage.root == tmp_path / "blobs"


def test_make_storage_builds_an_s3_backend_for_the_configured_bucket():
    settings = Settings(_env_file=None, storage_backend="s3", s3_bucket="some-bucket")

    storage = make_storage(settings)

    assert isinstance(storage, S3Storage)


def test_make_storage_refuses_a_non_local_backend_with_no_bucket():
    """The one branch that is a refusal rather than a construction.

    Any non-``local`` backend needs a bucket, so an operator who sets
    ``STORAGE_BACKEND`` and forgets ``S3_BUCKET`` is told which one is missing
    rather than getting an ``S3Storage`` bound to ``None``.
    """
    settings = Settings(_env_file=None, storage_backend="s3", s3_bucket=None)

    with pytest.raises(ValueError, match="S3_BUCKET"):
        make_storage(settings)


# --------------------------------------------------------------------------- #
# storage: make_image_key
# --------------------------------------------------------------------------- #


def test_make_image_key_layout():
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original")
    parts = key.split("/")
    assert parts[0] == "receipts"
    assert len(parts[1]) == 4 and parts[1].isdigit()  # yyyy
    assert len(parts[2]) == 2 and parts[2].isdigit()  # mm
    assert parts[3] == str(receipt_id)
    assert parts[4] == "original.jpg"


def test_make_image_key_uses_injected_when_for_partition():
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original", when=datetime(2023, 5, 9, tzinfo=UTC))
    parts = key.split("/")
    assert parts[1] == "2023"  # yyyy taken from `when`, not the wall clock
    assert parts[2] == "05"    # mm taken from `when`


def test_make_image_key_same_when_keeps_variants_in_one_folder():
    # Two variants of one receipt minted with the same `when` share a folder,
    # even across a month rollover a wall-clock read could straddle.
    receipt_id = uuid.uuid4()
    when = datetime(2023, 5, 31, 23, 59, tzinfo=UTC)
    original = make_image_key(receipt_id, "original", when=when)
    deskewed = make_image_key(receipt_id, "deskewed", when=when)
    assert original.rsplit("/", 1)[0] == deskewed.rsplit("/", 1)[0]


# --------------------------------------------------------------------------- #
# dedupe: compute_phash / phash_distance
# --------------------------------------------------------------------------- #


def test_compute_phash_is_16_hex_chars():
    phash = compute_phash(_vertical_gradient())
    assert len(phash) == 16
    int(phash, 16)  # parses as hex


def test_compute_phash_is_stable_for_same_image():
    img = _vertical_gradient()
    assert compute_phash(img) == compute_phash(img)


def test_phash_distance_zero_for_identical_images():
    phash = compute_phash(_vertical_gradient())
    assert phash_distance(phash, phash) == 0


def test_phash_distance_positive_for_very_different_images():
    a = compute_phash(_vertical_gradient())
    b = compute_phash(_horizontal_gradient())
    assert phash_distance(a, b) > 0


# --------------------------------------------------------------------------- #
# dedupe: find_near_duplicate_image
# --------------------------------------------------------------------------- #


def test_find_near_duplicate_returns_first_within_threshold():
    target = compute_phash(_vertical_gradient())
    far = compute_phash(_horizontal_gradient())
    candidates = [("far-id", far), ("near-id", target)]
    assert find_near_duplicate_image(target, candidates, threshold=5) == "near-id"


def test_find_near_duplicate_returns_none_when_all_far():
    target = compute_phash(_vertical_gradient())
    far = compute_phash(_horizontal_gradient())
    assert find_near_duplicate_image(target, [("far-id", far)], threshold=5) is None


# --------------------------------------------------------------------------- #
# dedupe: find_semantic_duplicate
# --------------------------------------------------------------------------- #


def test_find_semantic_duplicate_matches_merchant_date_total():
    candidates = [
        {"id": "a", "merchant_id": "m1", "txn_date": date(2024, 1, 1), "total": Decimal("10.00")},
        {"id": "b", "merchant_id": "m2", "txn_date": date(2024, 1, 2), "total": Decimal("20.00")},
    ]
    match = find_semantic_duplicate("m2", date(2024, 1, 2), Decimal("20.00"), candidates)
    assert match == "b"


def test_find_semantic_duplicate_returns_none_when_no_match():
    candidates = [
        {"id": "a", "merchant_id": "m1", "txn_date": date(2024, 1, 1), "total": Decimal("10.00")},
    ]
    assert find_semantic_duplicate("m9", date(2024, 1, 1), Decimal("10.00"), candidates) is None


# --------------------------------------------------------------------------- #
# dedupe: link_duplicate
# --------------------------------------------------------------------------- #


def test_link_duplicate_returns_pair():
    new_id, existing_id = uuid.uuid4(), uuid.uuid4()
    assert link_duplicate(new_id, existing_id) == (new_id, existing_id)


# --------------------------------------------------------------------------- #
# ingest: validate_upload
# --------------------------------------------------------------------------- #


def test_validate_upload_accepts_real_png(tmp_path):
    png_path = tmp_path / "receipt.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(png_path)

    check = validate_upload(png_path)
    assert isinstance(check, UploadCheck)
    assert check.ok is True
    assert check.reason is None
    assert check.content_type == "image/png"
    assert check.size_bytes > 0


def test_validate_upload_rejects_txt_extension(tmp_path):
    txt_path = tmp_path / "note.txt"
    txt_path.write_text("plainly not an image")

    check = validate_upload(txt_path)
    assert check.ok is False
    assert check.reason  # non-empty reason


def test_validate_upload_rejects_oversized_file(tmp_path):
    # Valid PNG magic bytes but padded past the limit; the size gate fires.
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024))

    check = validate_upload(big, max_mb=1)
    assert check.ok is False
    assert "large" in check.reason.lower()


def test_validate_upload_rejects_extension_content_mismatch(tmp_path):
    # A .png extension over non-image bytes must be caught by the magic sniff.
    fake = tmp_path / "liar.png"
    fake.write_bytes(b"this is not a real png payload at all")

    check = validate_upload(fake)
    assert check.ok is False
    assert check.reason


# --------------------------------------------------------------------------- #
# ingest: expand_pdf
# --------------------------------------------------------------------------- #


def test_expand_pdf_returns_one_png_per_page(tmp_path):
    page1 = Image.new("RGB", (200, 300), (255, 0, 0))
    page2 = Image.new("RGB", (200, 300), (0, 0, 255))
    pdf_path = tmp_path / "two_pages.pdf"
    page1.save(pdf_path, "PDF", save_all=True, append_images=[page2])

    out_dir = tmp_path / "pages"
    pages = expand_pdf(pdf_path, out_dir)

    assert len(pages) == 2
    for page_path in pages:
        assert page_path.exists()
        with Image.open(page_path) as opened:
            opened.load()
            assert opened.size[0] > 0 and opened.size[1] > 0


def test_expand_pdf_closes_per_page_render_bitmaps(tmp_path):
    # Regression: each page's render bitmap must be closed inside the loop, not
    # left for the GC -- otherwise pypdfium2 leaks per-page objects and warns.
    page1 = Image.new("RGB", (200, 300), (255, 0, 0))
    page2 = Image.new("RGB", (200, 300), (0, 0, 255))
    pdf_path = tmp_path / "two_pages.pdf"
    page1.save(pdf_path, "PDF", save_all=True, append_images=[page2])

    with mock.patch.object(
        pypdfium2.PdfBitmap,
        "close",
        autospec=True,
        side_effect=pypdfium2.PdfBitmap.close,
    ) as bitmap_close:
        pages = expand_pdf(pdf_path, tmp_path / "pages")

    assert len(pages) == 2
    assert bitmap_close.call_count == 2  # one render bitmap explicitly closed per page


# --------------------------------------------------------------------------- #
# ingest: ingest_bytes / ingest_file
# --------------------------------------------------------------------------- #


def test_ingest_bytes_stores_original_and_returns_job(tmp_path):
    storage = LocalStorage(tmp_path)
    data = _png_bytes()

    job = ingest_bytes(data, "receipt.png", storage)

    assert isinstance(job, ReceiptJob)
    assert isinstance(job.id, uuid.UUID)
    assert job.original_filename == "receipt.png"
    assert job.content_type == "image/png"
    assert job.source == "upload"
    assert storage.get(job.image_key) == data


def test_ingest_file_stores_original_and_returns_job(tmp_path):
    storage = LocalStorage(tmp_path)
    src = tmp_path / "receipt.png"
    Image.new("RGB", (12, 10), (5, 6, 7)).save(src)

    job = ingest_file(src, storage, source="folder-watch")

    assert job.source == "folder-watch"
    assert job.content_type == "image/png"
    assert storage.get(job.image_key) == src.read_bytes()


def test_ingest_bytes_rejects_invalid_upload(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        ingest_bytes(b"not an image", "note.txt", storage)


def test_ingest_bytes_honours_an_explicit_max_mb(tmp_path):
    storage = LocalStorage(tmp_path)
    data = b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024)  # a 2 MB "JPEG"
    with pytest.raises(ValueError, match="too large"):
        ingest_bytes(data, "r.jpg", storage, max_mb=1)
