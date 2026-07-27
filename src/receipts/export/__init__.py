"""Output/export formats. Excel is a display format, never the source of truth."""

from __future__ import annotations

from receipts.export.xlsx import export_workbook

__all__ = ["export_workbook"]
