"""Preprocessing layer: geometry and format only, never content (spec §14.2).

Opens supported image formats, normalizes orientation and colour mode, fits an
image to the model's window, splits over-tall receipts into overlapping strips,
and base64-encodes for transport. See :mod:`receipts.preprocess.image_ops`.
"""

from __future__ import annotations

from .image_ops import (
    UnsupportedFormat,
    fix_orientation,
    load_image,
    resize_for_model,
    split_tall_receipt,
    to_base64,
    to_rgb,
)

__all__ = [
    "UnsupportedFormat",
    "fix_orientation",
    "load_image",
    "resize_for_model",
    "split_tall_receipt",
    "to_base64",
    "to_rgb",
]
