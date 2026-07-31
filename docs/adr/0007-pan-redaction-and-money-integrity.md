# ADR 0007 — PAN redaction and money integrity at the persistence boundary

**Status:** Accepted (implements SPEC §18; hardened after the `feat/db-layer` review)

## Context

Two hard rules meet at the moment data is written:

- **Only ever store the last four card digits.** A full PAN must never reach
  `extraction_runs.raw_response`, which stores a verbatim model response.
- **Money is an exact amount or nothing** (ADR-0001).

Both were implemented and both had real holes that a pre-merge review found by
*executing* the code. The holes are recorded here because they are the kind that
silently reappear.

## Decision

**Two independent defences for card data.** `_last4()` on the way into
`receipts.card_last4` (so a model that puts a PAN in `payment.card_last4` loses
all but the tail, and so does a reviewer pasting one), and `redact_pan()` over
everything written to `raw_response`.

`redact_pan` is pure and recursive: it walks dict **keys and values**, list /
tuple / set / frozenset members (preserving container type), strings, and numeric
scalars (an `int`, or a whole-valued `float`, whose digits look like a PAN). One
regex covers unseparated `\d{13,19}`, grouped `4-4-4-N`, and Amex `4-6-5`, with
separators being any mix of spaces and hyphens; `_mask_pan` re-checks the 13–19
digit total and keeps only the last four.

**The lookbehind is `(?<!\d)(?<!\d\.)`, not `(?<![\d.])`.** This is the
load-bearing detail. The original form rejected any match preceded by a period,
which meant `CARD NO.4111111111111111` — exactly what a thermal receipt prints —
passed through **unredacted**. A period only means "decimal point" when a digit
precedes it; otherwise it is label punctuation. The trailing `(?!\d)(?!\.\d)`
still stops a match that continues into more digits or a fraction, so
`1234567890123.45` stays a number.

**Money coercion rejects non-finite values.** `float` was already refused; the
review found `Decimal("nan")` slipping through (it is a *legal* Decimal), landing
as NULL on SQLite while the `corrections` row recorded `NaN` — the amount
destroyed with no error and the audit trail disagreeing with the column it
describes. On Postgres `numeric` accepts `NaN` and it poisons every later sum.
`_coerce_money` now gates on `is_finite()`.

**Bounded text is validated against the model column.** Over-long `currency`
(`String(3)`) was silently stored by SQLite but is a `DataError` on Postgres;
`_bounded_optional_text` reads the limit from
`Receipt.__table__.c[...].type.length` and raises `ValueError`.

## Correction (2026-07-31)

**"separators being any mix of spaces and hyphens" (above) is stale.** The class
has been `[ .\-_/,]` — space, period, hyphen, underscore, slash, comma — since
the Phase 5 fix wave. Three further defects were found after this ADR was
written and are addressed in ADR-0018: a four-group run with a 5–7 digit tail
was stored **whole** (fixed); `save_extraction` redacted two of its text columns
while copying the rest verbatim (fixed); and the "silent on … a 16-character
hash" consequence above is false as stated — a value masks whenever it contains
a run of **13+ consecutive digits**, which roughly 1 in 200 random 16-character
hex hashes do (measured 2026-07-31), so **no hash may be routed through
`redact_pan` at all**; `save_extraction` keeps system-minted values such as
`image_phash` out of the redaction pass entirely. One documented residual is
**accepted by user ruling** rather than fixed: a separated run of more than
four groups keeps its remainder in the clear. **ADR-0018 supersedes this ADR's
description of the masking rule.** Everything here about money integrity and
bounded text still stands.

## Consequences

- **The silent-case tests are as important as the firing ones.** A redaction rule
  that fires on money, a hash, a 4-digit last4, a date, or `555-1234` is worse
  than no rule. Never touch `redact_pan` without keeping
  `test_redact_pan_is_silent_on_money_hashes_and_last4` green.
- The accepted false positive is a 13–19 digit all-numeric identifier, which is
  indistinguishable from a PAN by inspection.
- `redact_pan` is a public export, so it cannot rely on `_json_safe` upstream to
  normalise its input — it handles the scalar and container types itself.

## References

SPEC §18; ADR-0001; ADR-0006; `semantic-review/2026-07-28-111510-pr-feat-db-layer.md`.
