"""Geometry-and-format-only image preparation (spec §14.2).

This module handles the *pixels*, never the *content*: it opens supported
formats, normalizes orientation and colour mode, fits an image to the model's
window, splits an over-tall receipt into overlapping strips, and base64-encodes
for transport. Nothing here interprets what the receipt says.

Functions return new images and do not mutate their inputs -- the one
exception is :func:`to_rgb`, which returns the input unchanged when it is
already ``RGB``. HEIF/HEIC support is registered with Pillow at import time.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

logger = logging.getLogger(__name__)

#: Extensions accepted by :func:`load_image`. Anything else is refused up front
#: rather than handed to Pillow, so an unknown container fails as a clear
#: ``UnsupportedFormat`` instead of a late, confusing decode error.
_SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"})

#: Crude legibility heuristic for :func:`resize_for_model`. We assume a receipt
#: stacks on the order of this many text lines along its longer edge, so one
#: glyph is roughly ``longer_edge / _ASSUMED_TEXT_LINES`` pixels tall. This is
#: intentionally rough -- it only ever drives a warning, never a decision, so a
#: wrong guess costs a log line, not a dropped receipt. At the default
#: ``max_edge`` of 2048 it yields ~20px, comfortably above the 12px default.
_ASSUMED_TEXT_LINES = 100


class UnsupportedFormat(Exception):
    """Raised when a file is not an image Pillow can open."""


def load_image(path: Path) -> Image.Image:
    """Open a JPEG/PNG/WEBP/HEIC file.

    Raises :class:`UnsupportedFormat` for an unknown extension or for a file
    Pillow cannot identify as an image.
    """
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise UnsupportedFormat(f"Unsupported file extension: {path.suffix!r}")
    try:
        img = Image.open(path)
        img.load()
    except UnidentifiedImageError as exc:
        raise UnsupportedFormat(f"Not a recognized image: {path}") from exc
    return img


def fix_orientation(img: Image.Image) -> Image.Image:
    """Apply the EXIF orientation tag, then strip EXIF.

    Returns a new image whose ``info`` carries no ``exif`` payload, so a later
    save cannot re-apply an orientation that has already been baked into the
    pixels. The input image is left untouched.
    """
    fixed = ImageOps.exif_transpose(img)
    fixed.info.pop("exif", None)
    return fixed


def to_rgb(img: Image.Image) -> Image.Image:
    """Return an ``RGB`` image.

    Alpha (``RGBA``/``LA``/transparent ``P``) is flattened onto a white
    background; ``CMYK``/``L``/``P`` are converted. An image already in ``RGB``
    is returned unchanged.
    """
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def resize_for_model(
    img: Image.Image, max_edge: int = 2048, min_text_height_px: int = 12
) -> Image.Image:
    """Downscale so the longest edge is ``<= max_edge``; never upscale.

    Aspect ratio is preserved. When the post-resize image is small enough that
    the estimated glyph height (``max(size) / _ASSUMED_TEXT_LINES``) drops below
    ``min_text_height_px``, a warning is logged -- it never fails or alters the
    result. Always returns a distinct image (a copy when no resize is needed).
    """
    width, height = img.size
    longest = max(width, height)
    if longest <= max_edge:
        resized = img.copy()
    else:
        scale = max_edge / longest
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)

    estimated_text_height = max(resized.size) / _ASSUMED_TEXT_LINES
    if estimated_text_height < min_text_height_px:
        logger.warning(
            "Post-resize estimated text height %.1fpx is below %dpx; text may "
            "be illegible (size=%s, max_edge=%d).",
            estimated_text_height,
            min_text_height_px,
            resized.size,
            max_edge,
        )
    return resized


def split_tall_receipt(
    img: Image.Image, max_aspect: float = 3.0, overlap_px: int = 120
) -> list[Image.Image]:
    """Split a receipt taller than ``max_aspect`` into overlapping strips.

    Returns ``[img]`` unchanged when ``height / width <= max_aspect``. Otherwise
    it cuts full-width horizontal strips, each about ``width * max_aspect`` tall,
    with consecutive strips overlapping by at least ``overlap_px`` so a line item
    straddling a cut survives whole in one strip. The strips cover the full
    height and the last one ends exactly at the bottom edge.
    """
    width, height = img.size
    if width <= 0 or height <= 0 or height <= width * max_aspect:
        return [img]

    strip_height = max(1, round(width * max_aspect))
    step = max(1, strip_height - overlap_px)

    strips: list[Image.Image] = []
    top = 0
    while True:
        bottom = top + strip_height
        if bottom >= height:
            # Snap the final strip to the bottom so it ends at the edge; this
            # can only widen the overlap with the previous strip, never shrink
            # it below overlap_px.
            top = max(0, height - strip_height)
            strips.append(img.crop((0, top, width, height)))
            return strips
        strips.append(img.crop((0, top, width, bottom)))
        top += step


def to_base64(img: Image.Image, fmt: str = "JPEG", quality: int = 90) -> str:
    """Encode ``img`` to base64 (no data-URI prefix).

    JPEG cannot store alpha, so an alpha or palette image is flattened to
    ``RGB`` via :func:`to_rgb` before encoding. ``quality`` applies to JPEG.
    """
    fmt_name = "JPEG" if fmt.upper() in ("JPG", "JPEG") else fmt.upper()

    out_img = img
    if fmt_name == "JPEG" and img.mode not in ("RGB", "L", "CMYK"):
        out_img = to_rgb(img)

    buffer = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if fmt_name == "JPEG":
        save_kwargs["quality"] = quality
    out_img.save(buffer, format=fmt_name, **save_kwargs)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
