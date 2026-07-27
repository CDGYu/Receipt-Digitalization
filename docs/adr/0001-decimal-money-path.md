# ADR 0001 — `Decimal` everywhere on the money path

**Status:** Accepted (foundational; restates and operationalizes SPEC §18)

## Context

This is an accounting-grade pipeline. A single `float` in the money path
produces tolerance failures that look like model errors and cost hours to trace
(SPEC §18, README §6). The value comes from trusting auto-approved receipts, so
representation drift is unacceptable.

## Decision

Money is **`Decimal`** end to end. `float` is allowed only at genuine
non-money or terminal-display boundaries:

- Excel cell values in `export/xlsx.py` (display only; DB is source of truth).
- Non-money fields: `LineItem.bbox` (pixel coords), `quality` metrics, the
  sampling `temperature` knob.
- `line_item_f1`/rate metrics in `eval/` (statistical ratios, not amounts).

Confidence scores **and their thresholds** are `Decimal` too (see ADR-0003).

## Enforcement (already in place)

- `tests/test_no_float_in_money_path.py` walks the Pydantic schema; fails on any
  `float` money field (allowlists `bbox`, asserts money fields are actually
  reached so it can't pass vacuously).
- `tests/test_models.py` walks `Base.metadata` and fails on any SQLAlchemy
  `Float` column; ORM money is `Numeric(…, asdecimal=True)`.
- Money comparisons use `within_tolerance` (cents-bounded), never `==` or float.
- Golden labels store money as JSON **strings** (`"761.60"`) so the `Decimal`
  scale survives parsing; `Settings` money fields are `Decimal`.

## Consequences

- Every new money field must be `Decimal`/`Numeric`; the guard tests will catch
  regressions on a dependency upgrade.
- `quantize_money` is display-only and must never run before validation.

## References

SPEC §10.2 (tolerance), §18 (traps); README §5–6; `.kiro/steering/receipt-system.md`.
