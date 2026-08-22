# ADR 0050 — A golden label is fully public or fully private

**Status:** Accepted
**Date:** 2026-08-22
**Advances, and does not close:** `docs/KNOWN_ISSUES.md` ISSUE-001 step 7. This
milestone builds the machinery that lets the golden set grow without publishing
more real businesses' details. **It grows the set by nothing.** Collecting and
labelling real receipts is the bottleneck, it needs a person and a camera, and
it did not run here.
**Rests on:** ADR-0040 (what `field_accuracy` counts), ADR-0049 (a baseline is a
spread over receipts).

---

## Context

ADR-0049 gave this project its first measured number and, in the same breath,
the reason not to read it as a summary: `transcription_accuracy` 60.00–61.43%
over five repeats, while **per receipt** those same runs give 60.71–64.29%,
91.67–95.83%, and **11.11% on every one of the five**. The spread across repeats
is ±1.4 points; across receipts it is 85. That is ISSUE-017, and what it points
at is not a better model but more receipts.

The golden set is three receipts. All three are handwritten, against a
documented target of 20% handwritten — five times its intended weight, in the
hardest category. The measured figure is therefore an average over the hardest
fifth of the intended mix, and collecting toward the documented targets should
move it substantially **with no model change at all**.

Growing the set means photographing real receipts. Those carry real third
parties' names, addresses and tax IDs, and this repository is public.

---

## Decision 1 — The unit of redaction is the whole receipt, because field-level redaction corrupts the metric

The obvious design — publish the label with its PII fields nulled — does not
merely shrink a denominator. It **inverts the metric's verdict**.

ADR-0040 reads *filled* from the truth side only. A nulled field in the truth
moves its path into the **absent** classes, where a prediction that fills it is
counted **hallucinated**. Re-derived 2026-08-22 against
`eval/golden/labels/r001.json`, with a prediction byte-identical to the truth:

```
truth intact           transcription 28/28   core 12/12   hallucinated=0
truth name NULLED      transcription 27/27   core 11/11   hallucinated=1
```

**A model that correctly read the real merchant name off the image would be
scored as having invented it**, and a public CI run would report hallucinations
that never happened.

Making field-level redaction safe would mean teaching `field_breakdown` to skip
declared-redacted paths in **every** class — and that is ADR-0040's published
metric surface, where narrowing one moves a published metric.

**So a label is committed whole or not at all.**

**That is a rule for labellers, and no gate holds it.** A tracked label with its
PII nulled passes every gate — measured. The reason it is hard rather than
merely undone: `eval/golden/README.md` also tells a labeller to use `null` for
anything the receipt does not show, so **a redacted field and an absent one are
indistinguishable in the label**, and any pin asserting "PII is filled" would
false-positive on a legitimate receipt with no printed tax ID. Closing it needs a
declared marker, which is a design decision this milestone does not take.
**ISSUE-019.**

**This is pinned, not merely argued.**
`tests/test_golden_privacy.py::test_nulling_a_pii_field_in_the_truth_scores_a_correct_read_as_invented`
asserts deltas rather than absolute counts, so re-labelling `r001` cannot rot
it. **One of the three discriminates and two are invariants:** the
`hallucinated` delta is what both mutations below redden, while the
`transcription_total` and `core_total` deltas record only that the nulled path
left the filled set, which holds however the absent branch classifies it.

Proven red two independent ways, each mutation parsed before it was believed:
counting a filled prediction over an empty truth as
`correctly_empty` instead of `hallucinated`, and having `field_breakdown` skip
empty-truth paths in every class — which is literally the change field-level
redaction would require. Both redden the central assertion; neither the
precondition.

**Why the pin had to be added at close is worth recording.** The design asked
for it in as many words — §7.4, "the §3 measurement, pinned, so nobody
reintroduces field-level redaction believing it only shrinks a denominator" —
and the milestone reached its final review without it. The measurement had been
re-derived three times by three different readers and written into a module
docstring that said, accurately, "not a property these tests pin". **A rationale
everyone agrees with and nothing checks is a rationale that can stop being true
silently.** How it was missed is itself checkable: the plan's spec-coverage
self-review maps §1 through §6, §7a and §8, and skips §7 — the section listing
the required tests.

---

## Decision 2 — Privacy is carried by the filename, and no module changed

`eval/golden/labels/p*.json` is gitignored; public labels keep the existing `r`
prefix. The images directory was already excluded.

**No reader needed changing, and that absence of work is the load-bearing
property.** Enumerated from the tree rather than argued — every glob over the
labels directory:

| reader | the symbol holding the glob |
|---|---|
| `eval/golden_set.py` | `_label_files` |
| `eval/harness.py` | `run_eval` |
| `src/receipts/cli.py` | `cmd_eval` |
| `tests/test_eval_floor.py` | `_labels` |

Cited by symbol rather than by line, because a line number rots silently and
nothing here would go red when it did (ADR-0028 decision 5).

Each globs one directory, so a private label sitting beside a public one is
scored here and is simply absent in a clone.

**What would fail if this were false:** the harness would need a second glob and
a precedence rule between two sources — the two-mechanisms-that-must-agree shape
this repository legislates against.

**A consequence that is free and easy to miss:** the suite parametrises over
every label present, so a label is validated the moment it lands and the local
suite runs more parametrised cases than CI does.

**And one that is not free.** `tests/test_rules.py` also loads the real labels
directory — transitively, through `eval/golden_set.py`'s glob, which is why it is
not a fifth row in the table above — and
`test_real_corpus_labels_produce_no_errors` scores them against a frozen
`GOLDEN_TODAY = date(2026, 7, 28)`. Rule `R031` is `Severity.ERROR` and the
future-date slack is one day, so **a label for any receipt dated after
2026-07-29 reddens the suite**, which is every receipt Task 3 will photograph.
The label is right and the frozen date is stale. **ISSUE-020.**

**Closed 2026-08-22**, on `feat/corpus-date-not-frozen`, before any receipt was
collected: the corpus check was the only caller overriding `today`, and every
production site already builds a bare `ValidationContext()`. The paragraph above
is kept as the record of what was found. **Neither option ISSUE-020 itself
proposed was taken** — that issue's resolution says why, including a claim in it
that turned out to be false about the tree.

**The rule is checked from both directions, within a stated bound.**
`git check-ignore --no-index` is asked
about a *name* rather than the index about a *file* — the index otherwise
refuses to call a tracked path ignored, which left a blanket
`eval/golden/labels/*.json` passing every test while destroying the public set.
Samples differing in the digit after the `p` rule out any literal-prefix
narrowing.

**What the tripwire does and does not cover.** `test_no_private_label_is_committed`
reads `git ls-files`, so it asserts that no `p` file is in the index **now**. A
label committed and then removed leaves the index clean and the tripwire green
while the PII stays retrievable from history — which is the direction
`eval/golden/README.md` itself calls permanent. Nothing here guards that, and
nothing cheaply can: the guard is the `.gitignore` rule and the habit of reading
`git diff --cached --stat` before committing.

---

## Decision 3 — The aggregate names the receipts it scored, and not a count

`aggregate.json` gains `scored_receipts`: a **sorted union of the `receipt_id`
values across every repeat**, accumulated from the in-memory reports as the loop
runs.

**Not the count this design originally specified.** §4 asked for "one top-level
count naming the public/private split, derived by comparing the scored ids
against the tracked label names". A count of how many labels were private
**restates the naming rule**, and a second copy of a rule is one that can drift —
this milestone had already paid for one derived count that did. A list of ids
restates nothing, is derived the way `spread_omitted` is, and answers the
question a reader actually has: *which receipts is this number over?* Recorded
as the design's §7b correction.

**A failed receipt is in the list.** One `except` in `run_eval` covers a label
that would not read or validate, a pipeline call that raised, and a scoring
error alike, and records an `EvalResult` carrying the id for every one of them.
So the key names **what the run was put over, not what succeeded**; `n_failed`
is the other question.

**Why it is accumulated rather than read off one repeat:** `run_eval` globs the
labels directory afresh on every repeat, so a label appearing or disappearing
mid-run leaves two repeats covering different receipts, and the union is what
the run as a whole reached.

**The pin discriminates in three directions**, which took two review rounds to
reach: an implementation keeping only the first repeat's ids, one keeping only
the last's, and one re-globbing the labels directory at the end. The fixture
makes the repeats **disjoint** rather than nested — a fixture that merely *grew*
the golden set leaves repeat 2's set equal to the union, and "keep the last
repeat" passes it.

---

## What this ADR does not decide

- **Whether the repository goes private, or history is rewritten.** Still the
  owner's call.
- **Whether the existing three labels are scrubbed.** Their values are fixtures
  in up to 16 other tracked files; that is a separate job.
- **How many receipts to collect, or which mix.** `eval/golden/README.md`
  targets 50–100 covering the real mix; nothing here narrows it.
- **Why `r003` scores 11.11% on every repeat.** ISSUE-017 records the fact; this
  design does not diagnose it.
- **Whether `field_breakdown` should learn about redacted paths.** Decision 1 is
  the argument that field-level redaction would require it; this design avoids
  needing it.

---

## Consequences

- **A number is only comparable to another number over the same
  `scored_receipts`.** A clone holds fewer labels than the machine that ran it,
  by design. A figure over a different set is a different measurement, not a
  better one.
- **A private label can be published later; a committed one cannot be
  un-committed.** `eval/golden/README.md`'s rule is "when in doubt, use `p`".
- **The bottleneck is unchanged, and is now the only thing in the way.** Nothing
  in this milestone collects a receipt.
- **What the close cost, and it is the argument for running every stage.** Each
  stage found real defects in the one before it. The plan's own central mutation
  could not be caught, and it was the mutation its task existed to prove. Its
  prescribed *remedy* for a weak test was itself a test that could not fail —
  and the closure for *that* was weak in the opposite direction, caught only by
  the review round after it. The final re-review then found two prose defects
  the fix round had introduced inside its own range, including a defect log
  citing a function that does not exist. **No gate caught any of them; all five
  were green throughout.**
