"""Tests for the preprocessing image_ops layer (spec §14.2).

Preprocessing touches only the *pixels* -- format, orientation, colour mode,
size, and transport encoding -- never the receipt's content. Every fixture here
is a synthetic image built in-memory; no real files are read.
"""

from __future__ import annotations

import base64
import io
import logging

import pytest

# The preprocess layer needs the optional "pipeline" extras (Pillow + HEIF).
# CI installs only ".[dev]", so skip the whole module rather than erroring at
# collection when those libraries are absent.
pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image, ImageDraw  # noqa: E402

from receipts.preprocess import (  # noqa: E402
    UnsupportedFormat,
    fix_orientation,
    load_image,
    resize_for_model,
    split_tall_receipt,
    to_base64,
    to_rgb,
)

LOGGER_NAME = "receipts.preprocess.image_ops"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _row_coded_image(width: int, height: int) -> Image.Image:
    """An RGB image where every row encodes its own y in (R, G).

    ``R = y % 256`` and ``G = y // 256`` so a cropped strip's original vertical
    position can be recovered exactly (crop is lossless), which lets the split
    tests verify coverage and overlap by pixel content alone.
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        draw.line([(0, y), (width - 1, y)], fill=(y % 256, y // 256, 0))
    return img


def _decode_row(color: tuple[int, ...]) -> int:
    r, g = color[0], color[1]
    return r + 256 * g


# --------------------------------------------------------------------------- #
# load_image
# --------------------------------------------------------------------------- #


def test_load_image_opens_png(tmp_path):
    png_path = tmp_path / "receipt.png"
    Image.new("RGB", (32, 48), (200, 100, 50)).save(png_path)

    img = load_image(png_path)
    assert img.size == (32, 48)


def test_load_image_rejects_unknown_extension(tmp_path):
    txt_path = tmp_path / "not_an_image.txt"
    txt_path.write_text("this is plainly not an image")

    with pytest.raises(UnsupportedFormat):
        load_image(txt_path)


def test_load_image_rejects_unidentifiable_bytes(tmp_path):
    # A supported extension but garbage content: Pillow cannot identify it, so
    # it must still surface as UnsupportedFormat, not a raw decode error.
    fake_png = tmp_path / "broken.png"
    fake_png.write_bytes(b"definitely not a PNG")

    with pytest.raises(UnsupportedFormat):
        load_image(fake_png)


# --------------------------------------------------------------------------- #
# to_rgb
# --------------------------------------------------------------------------- #


def test_to_rgb_flattens_rgba():
    img = Image.new("RGBA", (10, 12), (255, 0, 0, 128))
    result = to_rgb(img)
    assert result.mode == "RGB"
    assert result.size == (10, 12)


def test_to_rgb_converts_grayscale():
    img = Image.new("L", (10, 12), 128)
    result = to_rgb(img)
    assert result.mode == "RGB"
    assert result.size == (10, 12)


def test_to_rgb_returns_rgb_unchanged():
    img = Image.new("RGB", (10, 12), (1, 2, 3))
    assert to_rgb(img) is img


# --------------------------------------------------------------------------- #
# fix_orientation
# --------------------------------------------------------------------------- #


def test_fix_orientation_applies_tag_and_strips_exif():
    # A 40x20 landscape image tagged orientation 6 (rotate 90 CW on display)
    # should come back as 20x40 portrait with no EXIF left in info.
    base = Image.new("RGB", (40, 20), (120, 130, 140))
    exif = base.getexif()
    exif[0x0112] = 6  # Orientation
    buffer = io.BytesIO()
    base.save(buffer, format="JPEG", exif=exif.tobytes())
    buffer.seek(0)
    loaded = Image.open(buffer)
    loaded.load()
    assert "exif" in loaded.info  # precondition: the fixture really has EXIF

    result = fix_orientation(loaded)
    assert result.size == (20, 40)
    assert "exif" not in result.info


# --------------------------------------------------------------------------- #
# resize_for_model
# --------------------------------------------------------------------------- #


def test_resize_downscales_and_preserves_aspect():
    img = Image.new("RGB", (4000, 3000))
    result = resize_for_model(img)
    assert max(result.size) == 2048
    assert result.size == (2048, 1536)  # 4:3 preserved


def test_resize_never_upscales():
    img = Image.new("RGB", (500, 400))
    result = resize_for_model(img)
    assert result.size == (500, 400)


def test_resize_warns_when_text_would_be_illegible(caplog):
    img = Image.new("RGB", (4000, 3000))
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        resize_for_model(img, max_edge=300)
    assert any("text" in record.message.lower() for record in caplog.records)


def test_resize_does_not_warn_for_reasonable_size(caplog):
    img = Image.new("RGB", (4000, 3000))
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        resize_for_model(img)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


# --------------------------------------------------------------------------- #
# split_tall_receipt
# --------------------------------------------------------------------------- #


def test_split_short_receipt_returns_single_image():
    img = Image.new("RGB", (300, 300))
    result = split_tall_receipt(img)
    assert result == [img]
    assert result[0] is img


def test_split_tall_receipt_covers_full_height_with_overlap():
    height = 1500
    img = _row_coded_image(300, height)  # aspect 5 > default max_aspect 3

    strips = split_tall_receipt(img)
    assert len(strips) > 1

    tops = [_decode_row(strip.getpixel((0, 0))) for strip in strips]
    bottoms = [_decode_row(strip.getpixel((0, strip.height - 1))) for strip in strips]

    # Coverage: first strip starts at the very top, last ends at the very bottom.
    assert tops[0] == 0
    assert bottoms[-1] == height - 1

    # Consecutive strips overlap (next strip's top row lies within the previous
    # strip), which also rules out any uncovered gap between them.
    for i in range(len(strips) - 1):
        assert tops[i + 1] <= bottoms[i]


# --------------------------------------------------------------------------- #
# to_base64
# --------------------------------------------------------------------------- #


def test_to_base64_roundtrips_to_expected_size():
    img = Image.new("RGB", (64, 48), (10, 20, 30))
    encoded = to_base64(img)

    assert isinstance(encoded, str)
    assert encoded  # non-empty
    assert not encoded.startswith("data:")  # no data-URI prefix

    reopened = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert reopened.size == (64, 48)


def test_to_base64_flattens_rgba_for_jpeg():
    img = Image.new("RGBA", (24, 16), (0, 128, 255, 100))
    encoded = to_base64(img)  # must not raise despite alpha + JPEG

    reopened = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert reopened.size == (24, 16)
    assert reopened.mode == "RGB"
