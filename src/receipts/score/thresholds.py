"""The two confidence thresholds that decide routing (spec §12, §17).

Defined once, here, because they were previously written out in four places --
``route()``'s defaults, ``Settings``, ``eval.metrics``, and the export sheet's
colour scale -- and four copies of a number that calibration is meant to move
(P3.T6/P8.T1) is three chances to move three of them.

This module deliberately depends on nothing but ``decimal``: ``config.settings``
imports it, so the arrow runs config -> domain. Putting the constants in
``Settings`` instead would make a pure domain module depend on environment
configuration.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["AUTO_APPROVE_THRESHOLD", "REVIEW_THRESHOLD"]

#: At or above this, a receipt is auto-approved (§12).
AUTO_APPROVE_THRESHOLD = Decimal("0.85")

#: Between this and the auto-approve cut-off, a receipt gets a quick verify;
#: below it, a full re-key.
REVIEW_THRESHOLD = Decimal("0.60")
