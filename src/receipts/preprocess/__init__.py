"""Preprocessing layer: geometry and format only, never content (spec §14.2).

Opens supported image formats, normalizes orientation and colour mode, fits an
image to the model's window, splits over-tall receipts into overlapping strips,
and base64-encodes for transport (:mod:`receipts.preprocess.image_ops`); locates
and flattens the document quad (:mod:`receipts.preprocess.bounds`); and gates
images on cheap quality metrics before any model call
(:mod:`receipts.preprocess.quality`).
"""

from __future__ import annotations

from .bounds import (
    Quad,
    auto_crop,
    deskew_perspective,
    detect_document_bounds,
    estimate_rotation,
)
from .image_ops import (
    UnsupportedFormat,
    fix_orientation,
    load_image,
    resize_for_model,
    split_tall_receipt,
    to_base64,
    to_rgb,
)
from .quality import (
    QualityReport,
    assess_quality,
    is_processable,
)

__all__ = [
    "QualityReport",
    "Quad",
    "UnsupportedFormat",
    "assess_quality",
    "auto_crop",
    "deskew_perspective",
    "detect_document_bounds",
    "estimate_rotation",
    "fix_orientation",
    "is_processable",
    "load_image",
    "resize_for_model",
    "split_tall_receipt",
    "to_base64",
    "to_rgb",
]
