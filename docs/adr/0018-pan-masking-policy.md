# ADR 0018 — The PAN masking policy

**Status:** Accepted (2026-07-31)

## Context

The Phase 5 whole-branch review parked a scoped follow-up: "PAN HARDENING." A
fresh pass against `main @ 446df20` — every claim reproduced by executing the
code, none recalled — found two residual leaks in `_PAN_RE`/`_mask_pan`, one
asymmetry between what a machine writes and what a reviewer writes, and three
prose claims the measurements themselves falsified, one of them in ADR-0007.
Full detail and every reproduction live in
`docs/superpowers/specs/2026-07-31-pan-hardening-design.md`; this ADR records
what the implementation actually does, per that design's §2.1, not the
abandoned design that preceded it.

**The constraint that shaped the decision:** this corpus's real merchant BIR
`VAT Reg. TIN` values are printed `3-3-3-N`, and three of the four are
**fourteen digits** — squarely inside the 13–19 digit window a PAN occupies
(`221 193 789 09013`, r001's merchant; `774-423-646-00011`, r002's merchant;
`103-969-951-00000`, the printer TIN in r002's notes; the fourth,
`205-741-640-162`, r003's merchant, is twelve). They are silent under
`_PAN_RE` **only** because it demands `4-4-4-N` or `4-6-5` grouping, and
`save_extraction_run` passes the entire extraction payload — `merchant.tax_id`
included, though it is not a correctable field — through `redact_pan`. Any
fail-closed rule as simple as "mask every run of 13+ digits" would mask every
merchant fingerprint this corpus prints. That constraint is why the fix below
widens one group instead of loosening the shape requirement, and it is what
`test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints` pins.

## Decision

**The whole detector change is one character.** In the `4-4-4-N` alternative,
the trailing group widens from `\d{1,4}` to `\d{1,7}`. That closes leak (a): a
four-group PAN with a 5–7 digit tail (17–19 digits total) used to fail the
match entirely and be stored **whole** — the invariant violation, "only ever
store the last four card digits," breached outright. `_mask_pan` is not
touched, and neither is anything else in `_PAN_RE` — the lookbehinds, the
`{2}` repetition, the Amex and unseparated alternatives, and the trailing
`(?!\d)` are all byte-identical to what shipped before this task.

**Leak (b) — a separated run of more than four groups leaves its remainder in
the clear — is accepted by the user's ruling (2026-07-31), not fixed.** In the
canonical case the pinned test asserts, `'CARD 4111 1111 1111 1111 111 OK'` →
`'CARD ************1111 111 OK'`: the leading four groups are masked, and
`111` is left over, however long a given remainder happens to be — the pinned
test also covers an 8-digit and a 4-digit leftover (`9999 9999`, `.1111`).
That is what the design doc counts as **seven** digits left visible outside
the asterisks in its canonical repro: seven consecutive card digits visible
where a compliant mask would show four — three in excess, under either
reading of the run. When the run is a single 19-digit card, the four digits
standing in the last-four position are mid-card digits, not the card's own
tail — measured, `redact_pan('4111 1111 1111 2345 678')` →
`'************2345 678'`: the visible `2345` is digits 13–16 of the run, not
its true last four (`5678`). Still a hardening gap, not an invariant
violation like leak (a)'s 17–19 digits in the clear. Two routes to closing it
were measured, and both were refused:

- **A greedy trailing group,** unbounded instead of capped at 7, closes (b)
  but leaks worse: `re.sub` never rescans inside a match it has already made,
  so the widened group swallowed a *second*, adjacent card number whole
  (`4111 1111 1111 1111 5555 5555 5555 4444` matched all 32 digits as one PAN)
  and, separately, ate an adjacent amount's integer part
  (`VISA 4111 1111 1111 1111 12.34` matched through to `12`, destroying the
  amount).
- **A scan loop controlling its own resume position** — re-examining a match
  that turns out to have swallowed too much, instead of trusting the greedy
  alternative's own end — closes (b) with neither regression, but is O(n²) on
  adversarial input: ~1715 ms for a 40 KB run of digits, against ~4 ms for the
  `\d{1,7}` pattern actually shipped.

Both were measured, both disclosed to the user together with their costs, and
the user ruled for the minimal `\d{1,7}` widening: leak (a) is the invariant
violation and is fully closed; leak (b) is a smaller, bounded gap, and neither
measured way of closing it was worth what it cost. Pinned by
`test_redact_pan_leaves_a_run_of_more_than_four_groups_partly_masked`.

**The group-shape requirement is load-bearing**, not incidental — see
Context. A future widening that relaxes `4-4-4-N`/`4-6-5` toward "any run of
13+ digits" must re-measure the four corpus TINs first, or it silently starts
masking merchant fingerprints instead of card numbers.

**`(?!\.\d)` stays scoped to the unseparated alternative alone.** It is what
keeps `1234567890123.45` a number rather than a masked PAN, and it must not
sit on the separated alternatives too: measured, with it applied everywhere,
`4111 1111 1111 1111.99` matched one group late and stored
`4111 **********1199` — the leading group left in the clear and the `.99`
amount destroyed. Scoped as shipped, the same input stores
`************1111.99`.

**`_mask_pan`'s length check is currently unreachable from `_PAN_RE`.** Every
alternative is bounded to 13–19 digits by construction — `4-4-4-N` tops out at
`4+4+4+7=19` and bottoms out at `4+4+4+1=13`, Amex is fixed at `4+6+5=15`, the
unseparated form is `\d{13,19}` outright — so the `return match.group(0)`
branch inside `_mask_pan` cannot currently fire from a real match. It is kept
anyway, as defence in depth on the project's hardest invariant: it costs
nothing, and removing a guard to satisfy today's coverage would be the wrong
trade the day a new alternative is added that *can* reach it.

**Redaction at the write boundary is default-on for extraction-sourced values
only — every scalar text column `save_extraction` builds, and the `modifiers`
JSON column.** `Modifier.label` is model text, and the prompts route
item-level promo/discount lines into it; a `String`-typed column walk cannot
see inside a JSON column, which is how `modifiers` stayed unredacted while
every scalar text column was covered. System-minted values — `image_key`,
`image_phash`, `status`, `confidence`, `merchant_id` — never pass through the
PAN heuristic at all, rather than being trusted to survive it: an all-digit
`image_phash` (the legal dHash of a uniform image, sixteen zero characters) is
indistinguishable from an unseparated PAN by shape, and routing it through
redaction turned it into invalid hex, breaking `phash_distance` and that
receipt's dedupe identity. The guarantee on the covered side is
`test_every_text_column_save_extraction_writes_is_redacted`, which walks
`Receipt.__table__` and `LineItem.__table__` rather than naming columns, so an
extraction-sourced column added later fails loudly instead of leaking
silently; the guarantee on the excluded side is
`test_save_extraction_never_corrupts_an_all_digit_image_phash`.

**Review reasons are redacted at the sink.** `enqueue_review` runs `reason`
through `redact_pan` on entry. Exception text interpolates raw model values —
`save_extraction`'s human-owned-status guard quotes `merchant.name`,
`_bounded_optional_text` quotes the overlong value that tripped it — and
`review_tasks.reason` is exactly where that text lands. Redacting at the one
sink covers every producer of a review reason, present and future, without
requiring each call site to remember to.

**The accepted false positives.** `_PAN_RE` masks by two independent routes,
and "13+ consecutive digits" characterizes only one of them. A *separated*
value masks when it is grouped exactly `4-4-4-N` or `4-6-5`, regardless of how
short any single run between separators is — measured, `4111 1111 1111 1111`
masks even though no run between its spaces is longer than 4. An *unseparated*
value masks when it holds a maximal run of 13-19 consecutive digits, capped —
measured, `41111111111111111111` (a 20-digit run) does **not** mask, because
the unseparated alternative is bounded `\d{13,19}` and no 13-19-digit span
inside a run that long can satisfy both boundary lookarounds at once. Grouping
decides the first route; run length decides the second — not "whenever it
looks like a card," which is a stronger claim than the regex actually
enforces either way. Four concrete false positives are accepted across these
two routes rather than fought, because a rule that must never miss a real PAN
cannot also never fire on something else:

- a 13–19 digit all-numeric identifier that is not a card number, indistinguishable
  from one by inspection;
- two column-scale amounts side by side in one free-text value (`1000.0000
  2000.0000` is four groups of four digits joined by dot, space, dot — a
  dotted PAN's shape exactly);
- roughly **1 in 200** random 16-character hex hashes (measured 2026-07-31) —
  not the ~1-in-1,845 an "all-digit-only" reading would suggest (`(10/16)**16`,
  since 10 of the 16 hex characters are digits), because a single non-digit
  character only protects a hash if it falls early enough to break every run
  of 13. This is why **no** hash is routed through
  `redact_pan`, not merely no all-digit one — `image_phash` is excluded
  structurally, per the redaction-boundary decision above, rather than by
  asking this function to tell a coincidence apart from a card number;
- a whole-number 13–19 digit `Modifier.amount`, serialized to string by
  `model_dump(mode="json")` before it reaches `redact_pan`. A quadrillion-scale
  modifier amount is not a real value, and anything with a fractional part
  (`"4111111111111111.00"`) is already protected by `(?!\.\d)`.

## Consequences

- **`docs/adr/0007-pan-redaction-and-money-integrity.md` is corrected, not
  rewritten** — a dated correction section points here for the current
  masking rule, and `frontend/src/review/ReceiptForm.tsx`'s own claim is
  bounded to the measured table it introduces rather than generalising past
  it. Both were false claims this milestone found; see that ADR's
  2026-07-31 correction for what exactly changed and when it stopped being
  true.
- **The rule for the next person who widens this regex: replay the committed
  battery in `tests/test_repository.py` in both directions before trusting a
  change, and always test a guard with two instances of what it guards inside
  one input.** Every battery in this task's history — a hand-picked one, the
  plan's own, and the project's committed one — held exactly one card number
  per case until the whole-branch review tried two, and that blind spot let a
  full second PAN through a green suite twice. It is not a coincidence unique
  to this function: a scanner's failure mode lives at the boundary *between*
  two hits, which a single-instance battery cannot see by construction. A
  separate 34-case hand-picked battery, built and passed in both directions
  during this same task, still missed a case the committed suite already
  had — `4111.1111.1111.1` — because a lexical fix tuned against invented
  cases is not the same thing as one checked against the committed ones.
- **Nothing about `_last4`, `_coerce_money`'s finiteness gate,
  `_bounded_optional_text`, `_plan_change`, or any API route changed.** The
  detector, the redaction boundary, and the review-reason sink are the entire
  surface this ADR covers.

## References

SPEC §18; ADR-0007 (superseded on the masking rule by this ADR; money
integrity and bounded text are unaffected and still governed there);
`docs/superpowers/specs/2026-07-31-pan-hardening-design.md` (§1.2 the TIN
constraint, §2.1 the ruling, §4 the full measured battery in both directions);
`src/receipts/persist/repository.py` (`_PAN_RE`, `_mask_pan`, `redact_pan`,
`save_extraction`, `_build_line_items`); `src/receipts/review/queue.py`
(`enqueue_review`); `tests/test_repository.py` (the `MUST_MASK`/
`MUST_STAY_SILENT` battery, and by name:
`test_redact_pan_leaves_a_run_of_more_than_four_groups_partly_masked`,
`test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints`,
`test_every_text_column_save_extraction_writes_is_redacted`,
`test_save_extraction_never_corrupts_an_all_digit_image_phash`);
`eval/golden/labels/r001.json`, `r002.json`, `r003.json` (the corpus TINs).
