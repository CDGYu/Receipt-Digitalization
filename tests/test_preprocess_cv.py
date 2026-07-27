"""Tests for the CV-based preprocessing layers: bounds + quality (spec §14.2).

These layers touch only *pixels* -- document geometry (crop/deskew) and image
quality gating -- never the receipt's content. Every fixture here is a
synthetic image built in-memory from numpy arrays, so the tests are
deterministic and never depend on a real photo or a model call.

The whole module is skipped when the optional "pipeline" extras (OpenCV +
Pillow) are absent, mirroring ``test_image_ops.py``; CI installs only ".[dev]".
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")
pytest.importorskip("PIL")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from receipts.preprocess import (  # noqa: E402
    QualityReport,
    assess_quality,
    auto_crop,
    deskew_perspective,
    detect_document_bounds,
    estimate_rotation,
    is_processable,
)

# --------------------------------------------------------------------------- #
# helpers -- all fixtures are synthetic uint8 arrays wrapped as RGB PIL images
# --------------------------------------------------------------------------- #


def _rgb(arr: np.ndarray) -> Image.Image:
    """Wrap a single-channel uint8 array as an RGB PIL image."""
    return Image.fromarray(arr, mode="L").convert("RGB")


def _doc_on_canvas() -> tuple[Image.Image, tuple[int, int, int, int]]:
    """A light rectangle centered on a larger dark canvas.

    Returns the image and the rectangle's expected ``(x0, y0, x1, y1)`` box.
    Canvas 400x500 (WxH) = 200000 px; rectangle 200x300 = 60000 px -> 30% of
    area, comfortably above the detector's ~25% confidence floor.
    """
    h, w = 500, 400
    arr = np.full((h, w), 40, dtype=np.uint8)  # dark background
    rh, rw = 300, 200
    y0, x0 = (h - rh) // 2, (w - rw) // 2  # (100, 100)
    arr[y0 : y0 + rh, x0 : x0 + rw] = 200  # light document
    return _rgb(arr), (x0, y0, x0 + rw, y0 + rh)


def _blank() -> Image.Image:
    """A uniform mid-gray image: no edges, no contrast, maximally unhelpful."""
    return _rgb(np.full((500, 400), 128, dtype=np.uint8))


def _checkerboard(size: int = 800, cell: int = 40) -> Image.Image:
    """A sharp, high-contrast checkerboard (light 200 / dark 40, no blown white).

    Values stay below the near-white glare threshold on purpose so the board
    reads as sharp-and-clean, not glary.
    """
    arr = np.empty((size, size), dtype=np.uint8)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            arr[y : y + cell, x : x + cell] = 200 if ((x // cell + y // cell) % 2 == 0) else 40
    return _rgb(arr)


def _horizontal_bars() -> Image.Image:
    """A white image with several full-width black horizontal bars (0 skew)."""
    h, w = 400, 400
    arr = np.full((h, w), 255, dtype=np.uint8)
    for y in range(40, h, 60):
        arr[y : y + 10, :] = 0
    return _rgb(arr)


def _gradient(h: int = 420, w: int = 420) -> Image.Image:
    """A horizontal gray ramp -- arbitrary content for warp-size checks."""
    row = np.linspace(0, 255, w, dtype=np.uint8)
    return _rgb(np.tile(row, (h, 1)))


def _quad_bbox(quad) -> tuple[int, int, int, int]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def _quad_area(quad) -> float:
    """Shoelace area of a 4-point polygon."""
    n = len(quad)
    acc = 0.0
    for i in range(n):
        x0, y0 = quad[i]
        x1, y1 = quad[(i + 1) % n]
        acc += x0 * y1 - x1 * y0
    return abs(acc) / 2.0


# --------------------------------------------------------------------------- #
# detect_document_bounds
# --------------------------------------------------------------------------- #


def test_detect_bounds_finds_rectangle_on_canvas():
    img, (ex0, ey0, ex1, ey1) = _doc_on_canvas()
    quad = detect_document_bounds(img)

    assert quad is not None
    assert len(quad) == 4
    for point in quad:
        assert len(point) == 2
        assert all(isinstance(c, int) for c in point)

    bx0, by0, bx1, by1 = _quad_bbox(quad)
    # The detected box should hug the true rectangle to within a few pixels
    # (edge thickness + polygon approximation).
    assert abs(bx0 - ex0) <= 12
    assert abs(by0 - ey0) <= 12
    assert abs(bx1 - ex1) <= 12
    assert abs(by1 - ey1) <= 12

    expected_area = (ex1 - ex0) * (ey1 - ey0)
    assert _quad_area(quad) == pytest.approx(expected_area, rel=0.15)


def test_detect_bounds_returns_none_for_blank():
    assert detect_document_bounds(_blank()) is None


def test_detect_bounds_orders_corners_tl_tr_br_bl():
    img, _ = _doc_on_canvas()
    quad = detect_document_bounds(img)
    assert quad is not None
    tl, tr, br, bl = quad
    # top corners sit above bottom corners; left corners left of right corners.
    assert tl[1] < bl[1] and tr[1] < br[1]
    assert tl[0] < tr[0] and bl[0] < br[0]


# --------------------------------------------------------------------------- #
# deskew_perspective
# --------------------------------------------------------------------------- #


def test_deskew_perspective_returns_expected_size():
    img = _gradient(420, 420)
    # A mildly skewed quad whose edge lengths are all ~300px.
    quad = [(60, 45), (360, 55), (355, 350), (65, 345)]
    warped = deskew_perspective(img, quad)

    assert isinstance(warped, Image.Image)
    w, h = warped.size
    assert 290 <= w <= 310
    assert 290 <= h <= 310


def test_deskew_perspective_does_not_mutate_input():
    img = _gradient(420, 420)
    before = img.size
    deskew_perspective(img, [(60, 45), (360, 55), (355, 350), (65, 345)])
    assert img.size == before


# --------------------------------------------------------------------------- #
# auto_crop
# --------------------------------------------------------------------------- #


def test_auto_crop_crops_when_document_found():
    img, _ = _doc_on_canvas()
    cropped, was_cropped = auto_crop(img)
    assert was_cropped is True
    assert isinstance(cropped, Image.Image)
    # cropped output should be smaller than the full canvas it came from.
    assert cropped.size[0] <= img.size[0] and cropped.size[1] <= img.size[1]


def test_auto_crop_passthrough_when_no_document():
    img = _blank()
    result, was_cropped = auto_crop(img)
    assert was_cropped is False
    assert result is img


# --------------------------------------------------------------------------- #
# estimate_rotation
# --------------------------------------------------------------------------- #


def test_estimate_rotation_near_zero_for_horizontal_bars():
    angle = estimate_rotation(_horizontal_bars())
    assert abs(angle) < 1.0


def test_estimate_rotation_zero_when_undetectable():
    # A blank image has no lines to measure, so the estimate must be exactly 0.
    assert estimate_rotation(_blank()) == 0.0


# --------------------------------------------------------------------------- #
# assess_quality / is_processable
# --------------------------------------------------------------------------- #


def test_assess_quality_returns_report_with_sane_fields():
    report = assess_quality(_checkerboard())
    assert isinstance(report, QualityReport)
    assert report.blur_score >= 0.0
    assert 0.0 <= report.brightness <= 255.0
    assert report.contrast >= 0.0
    assert 0.0 <= report.glare_ratio <= 1.0
    assert isinstance(report.resolution_ok, bool)
    assert report.estimated_text_height >= 0.0


def test_sharp_image_has_higher_blur_score_than_uniform():
    sharp = assess_quality(_checkerboard()).blur_score
    flat = assess_quality(_blank()).blur_score
    assert sharp > flat


def test_is_processable_rejects_uniform_blank():
    ok, reason = is_processable(assess_quality(_blank()))
    assert ok is False
    assert isinstance(reason, str) and reason


def test_is_processable_accepts_sharp_high_contrast_image():
    ok, reason = is_processable(assess_quality(_checkerboard()))
    assert ok is True
    assert reason is None
