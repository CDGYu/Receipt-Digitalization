"""Cheap, model-free image quality assessment and gating (spec §14.2).

Before spending an API call on a receipt we measure a handful of pixel
statistics -- sharpness, exposure, glare, resolution -- and decide whether the
image is even worth extracting. This is deliberately fast and content-blind:
it runs on every image and only ever *rejects* the obviously unusable ones, so
a wrong guess here costs a re-shoot prompt, never a silent drop.

:func:`assess_quality` reports the raw numbers; :func:`is_processable` applies
the thresholds below. The thresholds are intentionally lenient -- they exist to
catch black frames, thumbnails, and camera-shake blur, not to second-guess a
merely mediocre photo.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

from .image_ops import to_rgb

# --- is_processable thresholds (module constants so they are easy to tune) --- #

#: Variance-of-Laplacian below this reads as out-of-focus / motion-blurred. A
#: uniform or badly smeared frame sits near 0; an in-focus receipt is well into
#: the hundreds, so 100 cleanly separates "no detail" from "some detail".
_MIN_BLUR_SCORE = 100.0

#: Mean luma outside this band is a black frame or a blown-out white frame --
#: either way there is no legible text to extract.
_MIN_BRIGHTNESS = 25.0
_MAX_BRIGHTNESS = 240.0

#: If more than this fraction of the image is near-white blown-out pixels, glare
#: has likely swallowed the text.
_MAX_GLARE_RATIO = 0.55

#: Shortest edge (px) below which text is too small to read reliably. Receipt
#: photos are normally thousands of pixels; this only catches tiny thumbnails.
_MIN_SHORT_EDGE_PX = 640

#: Luma at/above this counts as "blown-out white" for the glare ratio.
_GLARE_LUMA = 250

#: Rough glyphs-along-the-long-edge assumption for the text-height estimate;
#: mirrors ``image_ops._ASSUMED_TEXT_LINES``. Informational only.
_ASSUMED_TEXT_LINES = 100


class QualityReport(BaseModel):
    """Pixel-level quality metrics for one image. None of this is money."""

    blur_score: float  # variance of the Laplacian (higher = sharper)
    brightness: float  # mean luma, 0-255
    contrast: float  # std of luma
    glare_ratio: float  # fraction of near-white blown pixels, 0-1
    resolution_ok: bool  # shortest edge >= _MIN_SHORT_EDGE_PX
    estimated_text_height: float  # rough px height of one text line


def assess_quality(img: Image.Image) -> QualityReport:
    """Compute cheap quality metrics for ``img`` (no model calls)."""
    gray = cv2.cvtColor(np.asarray(to_rgb(img)), cv2.COLOR_RGB2GRAY)
    height, width = gray.shape

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    glare_ratio = float(np.count_nonzero(gray >= _GLARE_LUMA) / gray.size)
    resolution_ok = min(height, width) >= _MIN_SHORT_EDGE_PX
    estimated_text_height = float(max(height, width) / _ASSUMED_TEXT_LINES)

    return QualityReport(
        blur_score=blur_score,
        brightness=brightness,
        contrast=contrast,
        glare_ratio=glare_ratio,
        resolution_ok=resolution_ok,
        estimated_text_height=estimated_text_height,
    )


def is_processable(report: QualityReport) -> tuple[bool, str | None]:
    """Gate an image before extraction.

    Returns ``(True, None)`` when the image is worth processing, or
    ``(False, reason)`` describing the first disqualifying condition found.
    Checks are ordered cheapest-signal-first; the reason string names the
    concrete measured value so the review UI can explain the rejection.
    """
    if not report.resolution_ok:
        return False, "resolution too low: shortest edge below minimum"
    if report.blur_score < _MIN_BLUR_SCORE:
        return False, (
            f"image too blurry: blur_score {report.blur_score:.1f} < {_MIN_BLUR_SCORE:.0f}"
        )
    if report.brightness < _MIN_BRIGHTNESS:
        return False, f"image too dark: brightness {report.brightness:.1f}"
    if report.brightness > _MAX_BRIGHTNESS:
        return False, f"image overexposed: brightness {report.brightness:.1f}"
    if report.glare_ratio > _MAX_GLARE_RATIO:
        return False, f"excessive glare: {report.glare_ratio:.0%} of pixels blown out"
    return True, None
