# ADR 0003 — Confidence as an additive penalty model

**Status:** Accepted (implements SPEC §12)

## Context

Every uncertainty signal (validation findings, legibility, handwriting, missing
critical fields, model-flagged ambiguity, self-consistency disagreement, triage
issues) must fold into one confidence score that routes a receipt to
auto-approve or review.

## Decision

`score/confidence.py`:

- `score_confidence(...)` starts at `Decimal("1.0")` and applies the SPEC §12
  penalty table: flat **−0.35** for *any* ERROR; bounded per-item penalties for
  warns / ambiguous fields / consistency disputes / triage issues; fixed
  penalties for fair/poor legibility, handwriting, and null total/date/merchant;
  a small **+0.05** bonus for a many-times-verified merchant. Clamp to `[0,1]`,
  quantize to 3 decimals, `Decimal` throughout (ADR-0001).
- `explain_confidence(...)` shares one private `_signals()` builder with the
  scorer, so the UI explanation can never drift from the number.
- `route(...)` maps score → `(ReceiptStatus, priority, reason)` with the §12
  thresholds and the **error + null-total ⇒ urgent (priority 0)** override.
- Penalty weights are **module constants for now**.

## Consequences

- Baseline auto-approval precision/rate become meaningful once a real provider
  runs (the eval adapter now scores instead of using a placeholder).
- **Deferred (M3/P3.T6 calibration):** move weights into `config/rules.yaml` so
  they are tunable against the golden set without a code change; consolidate the
  `0.85`/`0.60` thresholds (currently duplicated across `route()` defaults,
  `Settings`, and `eval.metrics`) onto `Settings`.
- **Deferred (safer per prime directive):** the handwriting penalty reads only
  `receipt.meta.is_handwritten`; consider OR-ing `triage.is_handwritten`.

## References

SPEC §12; ADR-0001; the final review of `feat/m1-pipeline`.
