# ADR 0010 — Export stays decoupled from persistence (`ReceiptExportRow`)

**Status:** Accepted (implements SPEC §13)

## Context

The §13.1/§13.2 sheets need only a `ReceiptExtraction`. The §13.3 `Needs Review`
and §13.4 `Summary` sheets additionally need facts that live *outside* the
extraction: the receipt id, the routed status and confidence (§12), the review
reason/priority, whether an ERROR finding is still unresolved, and an image link.

The obvious move — take ORM rows — would couple the exporter to the database and
a live session, and break the existing offline tests.

## Decision

- `export_workbook` keeps taking `list[ReceiptExtraction]`. The extra facts arrive
  through an optional **frozen dataclass `ReceiptExportRow`** in a `rows=` list
  running parallel to `receipts` (length-checked like `ids`, `ValueError` before
  anything is written). Every field is optional: what the caller does not know
  stays an empty cell rather than being invented.
- `has_unresolved_error` is the caller's to compute (typically
  `any(f.severity is Severity.ERROR and not f.resolved_by_repair …)`), so export
  never needs a `ValidationReport`.
- New params `include_review_sheet` / `include_summary` default to `True` per the
  §13 signature. New Receipts columns were **appended** so existing column-letter
  assertions still hold.
- **Excel is display-only** (steering rule): `Decimal` stays on the internal path
  and every Summary aggregate is summed/divided in `Decimal`, converted to
  `float` once, at the cell. §13.5 formatting is applied: autofilter, currency
  `#,##0.00` right-aligned, a `ColorScaleRule` on confidence with its amber
  midpoint at the §12 `0.60` floor, light-red fill on unresolved-ERROR rows,
  `receipt_no`/`card_last4` as text (`@`) so Excel cannot eat leading zeros,
  content-sized widths capped at 50, no sheet protection.
- An undefined rate/average renders **empty**, never a fabricated `0%`; an empty
  receipt list cannot divide by zero.

## Consequences

- The exporter is still unit-testable with no DB, and a caller with ORM rows
  builds `ReceiptExportRow`s in one comprehension.
- **Deferred:** `write_only` streaming above 5000 receipts (SPEC §13) — it forbids
  the random cell access the whole formatting pass relies on, so it needs its own
  pass that formats while appending rather than being half-implemented.

## References

SPEC §13 (esp. §13.3–13.5); ADR-0001; `.kiro/steering/receipt-system.md`.
