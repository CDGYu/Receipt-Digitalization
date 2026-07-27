"""Document geometry: find the receipt in the frame and flatten it (spec §14.2).

This module handles *where the page is*, never *what it says*. It locates the
largest document-like quadrilateral via edge detection, warps it to a flat
axis-aligned rectangle, and estimates residual skew. Everything is pure pixel
geometry -- no content is interpreted and inputs are never mutated (OpenCV
operates on copies obtained from ``numpy.asarray``).

All public functions take and return :class:`PIL.Image.Image`; OpenCV works in
BGR/ndarray internally, so we convert at the boundaries.
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np
from PIL import Image

from .image_ops import to_rgb

logger = logging.getLogger(__name__)

#: Four ``(x, y)`` integer corner points, always ordered top-left, top-right,
#: bottom-right, bottom-left. This is the shape returned by
#: :func:`detect_document_bounds` and consumed by :func:`deskew_perspective`.
Quad = list[tuple[int, int]]

#: A detected quad must cover at least this fraction of the frame to count as a
#: document. Below it we are almost certainly latching onto a logo, a label, or
#: image noise rather than the page, so we return ``None`` and let the caller
#: fall back to the uncropped image instead of confidently cropping garbage.
_MIN_AREA_FRACTION = 0.25

#: Polygon-approximation tolerance as a fraction of the contour perimeter.
#: 2% is the conventional value that collapses a rectangle's slightly ragged
#: edge contour down to exactly four vertices without over-simplifying.
_APPROX_EPS_FRACTION = 0.02


def _to_gray(img: Image.Image) -> np.ndarray:
    """Return a single-channel uint8 array (grayscale) for OpenCV."""
    rgb = np.asarray(to_rgb(img))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _order_corners(pts: np.ndarray) -> Quad:
    """Order four points as top-left, top-right, bottom-right, bottom-left.

    Uses the standard sum/difference trick: the top-left corner has the
    smallest ``x + y`` and the bottom-right the largest; the top-right has the
    smallest ``y - x`` and the bottom-left the largest.
    """
    pts = pts.reshape(4, 2).astype(np.float64)
    s = pts.sum(axis=1)
    diff = pts[:, 1] - pts[:, 0]
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmin(diff))]
    bl = pts[int(np.argmax(diff))]
    return [
        (int(round(tl[0])), int(round(tl[1]))),
        (int(round(tr[0])), int(round(tr[1]))),
        (int(round(br[0])), int(round(br[1]))),
        (int(round(bl[0])), int(round(bl[1]))),
    ]


def detect_document_bounds(img: Image.Image) -> Quad | None:
    """Find the largest confident 4-sided contour (the document edges).

    Pipeline: grayscale -> Gaussian blur -> Canny -> external contours ->
    ``approxPolyDP``. Among convex 4-vertex approximations we keep the one with
    the greatest area; if that area covers less than :data:`_MIN_AREA_FRACTION`
    of the frame (or nothing 4-sided is found), we are not confident and return
    ``None``. The returned corners are ordered ``(tl, tr, br, bl)``.
    """
    gray = _to_gray(img)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    frame_area = float(gray.shape[0] * gray.shape[1])
    best_quad: Quad | None = None
    best_area = 0.0
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, _APPROX_EPS_FRACTION * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        area = float(cv2.contourArea(approx))
        if area > best_area:
            best_area = area
            best_quad = _order_corners(approx)

    if best_quad is None or best_area < _MIN_AREA_FRACTION * frame_area:
        return None
    return best_quad


def deskew_perspective(img: Image.Image, quad: Quad) -> Image.Image:
    """Warp the ``quad`` region to a flat, axis-aligned rectangle.

    The output size is taken from the quad's own edge lengths (the longer of
    each opposing pair), so a perspective-distorted page comes out roughly its
    true proportions. Returns a new RGB PIL image; the input is untouched.
    """
    src = np.array(quad, dtype=np.float32)
    tl, tr, br, bl = src

    width = max(np.hypot(*(br - bl)), np.hypot(*(tr - tl)))
    height = max(np.hypot(*(tr - br)), np.hypot(*(tl - bl)))
    out_w = max(1, int(round(width)))
    out_h = max(1, int(round(height)))

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)

    bgr = cv2.cvtColor(np.asarray(to_rgb(img)), cv2.COLOR_RGB2BGR)
    warped = cv2.warpPerspective(bgr, matrix, (out_w, out_h))
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


def auto_crop(img: Image.Image) -> tuple[Image.Image, bool]:
    """Detect the document and deskew it if found.

    Returns ``(cropped, True)`` when a confident quad is detected, otherwise the
    original image unchanged as ``(img, False)`` -- we never guess-crop.
    """
    quad = detect_document_bounds(img)
    if quad is None:
        return img, False
    return deskew_perspective(img, quad), True


def estimate_rotation(img: Image.Image) -> float:
    """Estimate small-angle skew in degrees from near-horizontal edges.

    Runs a probabilistic Hough transform over Canny edges, folds every segment
    angle into ``[-90, 90]``, keeps the near-horizontal ones (``|angle| <= 45``,
    i.e. text baselines rather than vertical rules), and averages them. Returns
    ``0.0`` when nothing measurable is found, and clamps the result to
    ``[-45, 45]``.
    """
    gray = _to_gray(img)
    edges = cv2.Canny(gray, 50, 150)
    min_len = max(20, min(gray.shape) // 4)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=80, minLineLength=min_len, maxLineGap=20
    )
    if lines is None:
        return 0.0

    angles: list[float] = []
    # HoughLinesP returns (N, 1, 4) on some builds and (N, 4) on others; flatten
    # to (N, 4) so the unpacking is version-independent.
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
        # Fold to [-90, 90] so direction of travel along the line is irrelevant.
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        if abs(angle) <= 45:  # near-horizontal only
            angles.append(angle)

    if not angles:
        return 0.0
    return max(-45.0, min(45.0, float(np.mean(angles))))
