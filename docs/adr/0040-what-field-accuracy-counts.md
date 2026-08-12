# ADR 0040 — What eval field accuracy counts, and the three things it used to average

**Status:** Accepted (2026-08-12)
**Relates to:** ISSUE-001 (`docs/KNOWN_ISSUES.md`), ADR-0028 (claims about the
tree are re-derived), ADR-0030 (a finding is a claim), ADR-0032 (a document
cannot certify itself), ADR-0033 (a correction goes to every copy), ADR-0039
(the local path is a liveness check), `RECEIPT_SYSTEM_SPEC.md` §16 (the metric
set)

Derived 2026-08-12 on `feat/eval-field-accuracy` by running the probe below
against the tracked golden labels. **Re-derive rather than quote** (ADR-0028
rule 1): the design document this implements was written before the code, and
some of its figures did not reproduce. *What was corrected on the way in* lists
the ones that were checked — it is that measurement, not a complete audit of the
document. Nothing here is inherited from it.

The probe. It prints both definitions side by side, so every floor in this ADR
comes out of one command:

```bash
python - <<'PY'
import json, pathlib
from eval.metrics import field_accuracy, field_breakdown
from receipts.extract.schema import ReceiptExtraction
for p in sorted(pathlib.Path("eval/golden/labels").glob("*.json")):
    truth = ReceiptExtraction.model_validate(json.loads(p.read_text(encoding="utf-8")))
    acc = field_accuracy(ReceiptExtraction(), truth)
    bd = field_breakdown(ReceiptExtraction(), truth)
    print(p.stem,
          "old", f"{sum(acc.values())}/{len(acc)}",
          "new", f"{bd.transcription_correct}/{bd.transcription_total}",
          "core", f"{bd.core_correct}/{bd.core_total}",
          "line_items", f"{bd.line_items_correct}/{bd.line_items_total}",
          "self_report", f"{bd.self_report_correct}/{bd.self_report_total}",
          "hallucinated", bd.hallucinated,
          "correctly_empty", bd.correctly_empty,
          "structural_mismatch", bd.structural_mismatch)
PY
```

## Context

`eval.metrics.field_accuracy` returns `{dotted_path: bool}` over the union of
the paths on both sides. The harness folded that map into one scalar — correct
paths over all paths — and printed it as §16's metric 4.

That scalar averaged three unlike quantities: what the model **read**, what it
**correctly left empty**, and what it **said about itself** (`meta.*`, whose
`meta.notes` on r001 is 161 words of human verification prose, scored as one
path at equal weight to `totals.total`). The last two are earned by producing
nothing at all.

**Measured, not argued.** Score `ReceiptExtraction()` — every field at its
default, nothing read — against each golden label under the old definition:

| label | floor a model that read nothing reached |
|---|---|
| r001 | **42.50%** (17 / 40) |
| r002 | **37.50%** (15 / 40) |
| r003 | **36.59%** (15 / 41) |

Where r001's seventeen free points came from, classified by the same
`_is_filled` rule the shipped code uses (`None` is not filled, and neither is an
empty container):

| contributor | count |
|---|---|
| **non-`meta`** paths where neither side is filled — the receipt has no such field | 12 |
| `meta.*` self-reports resting at their schema defaults | 4 |
| a filled truth value a schema default happens to match (`receipt.decimal_convention`) | 1 |

**The `meta` qualifier on row 1 is load-bearing, and a re-deriver who drops it
will get a different number.** Neither-side-filled *without* it is 14, because
`meta.ambiguous_fields` and `meta.unreadable_regions` are `[]` on both sides and
so satisfy both predicates. Row 2 is where they are counted. With the qualifier
the three rows partition the 17; without it, rows 1 and 2 overlap by exactly
those two paths.

ADR-0039 records a local run scoring 45.00% field accuracy on r001 from a model
whose confidence was `0.000`, whose critical fields were all wrong, and which
found no line item. Against a 42.50% floor, that run beat silence by one path.
**That measurement is not re-derived here and is not restated as a defect of the
run** — it is an accurate record of what the old metric printed. ADR-0039 **§1**
is the section that reads it, and calls that figure "the trap"; §3 is scoped to
the *timing* and is why the run is not repeated to obtain a fresher one.

Second defect, same metric: `_report_to_dict` collapsed each receipt's per-path
map to two integers. §16 assigns metric 4 the purpose "where to focus prompt
work", and two integers cannot answer that. The map was computed, summed once,
and thrown away.

## Decision

### 1. Two axes, and *filled* is read from the truth side only

Every path is classified on two axes, and neither is ever read from the
prediction's value.

**Group** comes from the path string alone: `meta.` prefix, `line_items` or a
`line_items[` prefix, else core. A prefix test, not a list of field names — a
`meta` field added to the schema next year is classified without anybody
deciding it should be (review standard 19).

**Filled** is read from the **truth** side: a value is filled when it is not
`None` and not an empty container.

Reading *filled* from the prediction would let a model **enlarge its own
denominator**. A path the prediction invents has no truth value, so it can never
become a transcription point; a model cannot dilute its error rate by
hallucinating. This is the property the whole design rests on, and it is why the
rule is stated as a side rather than as a comparison.

### 2. Five numbers, and three of them are counts

`transcription_accuracy` (truth filled, group core or line items) and
`self_report_agreement` (truth filled, group meta) are ratios — `None`, never
`0.0`, on an empty denominator. `hallucinated_fields`,
`correctly_empty_fields` and `structural_mismatch_fields` are **counts**.

Counts on purpose, but not for the reason first written here. Their would-be
denominator is "fields this receipt does not have", which is a property of the
**schema**, not of the receipt: adding an optional field to `ReceiptExtraction`
would move that percentage on every receipt with nothing about the model having
changed.

A count is **not** immune to that, and the sentence that used to close the
paragraph above — "a count moves only when behaviour moves" — was false in
exactly the way that paragraph argues against. Re-derived: subclassing
`ReceiptExtraction` with one extra optional scalar field and scoring an empty
extraction against r001 moves `correctly_empty_fields` from 14 to 15, with the
model unchanged. The counts are also micro-summed across receipts, so growing
the golden set (P8.T2, in *What this ADR does not decide*) moves them too.

What a count avoids is **rescaling**. A ratio's denominator is the whole absent
set, so schema growth shifts every value it has ever produced; a count shifts by
a bounded amount per receipt — how much depends on how many leaves the new field
flattens to — and its earlier value stays readable as the same quantity. So the
comparability rule, stated rather than implied: **two runs' counts are
comparable over the same schema and the same corpus, and not otherwise.** They
are read beside the `prompt_version` and receipt count in their own results
file, never across a schema or golden-set change.

`hallucinated_fields` exists because "null over confident-wrong" is a project
non-negotiable that was measured by nothing. Under the old scalar, a model that
invents a cashier name and one that correctly leaves it null differed by a
single path in forty.

**`correctly_empty_fields` is bounded by the per-path map**, and
`structural_mismatch_fields` is where the residue of that bound goes. The rule
is one property: *no class named for agreement may contain a path
`field_accuracy` scores as disagreement.* It was not always so. Measured on
r001 against an empty extraction, 4 of the 18 paths the first implementation
counted as `correctly_empty` were scored `False` by the same map the harness
commits to the artefact — `line_items` among them, because the prediction's
empty list and truth's absent leaf both read as "not filled" while the map
scored the pair wrong. Inventing three line-item rows moved the number printed
as `Correctly empty fields:` from 18 to 25: a hallucinating model scoring better
on a count named for agreement.

A path reaches `structural_mismatch` when neither side is filled and the map
still scores it wrong, which is what a path present on one side only looks like.
It does not say the model misread a value — values read wrong are in
`transcription`, values invented are in `hallucinated` — it says the two sides
disagree about *which paths exist*. Under the shipped rule, r001/r002/r003
against an empty extraction split as `correctly_empty` 14/12/12 and
`structural_mismatch` 4/5/6; the probe at the top of this ADR prints both.

**The bound does not stop the count moving when a model invents rows, and is not
claimed to.** Re-measured on r001 with three invented line-item rows,
`correctly_empty` goes 14 → 17, and the three paths gained are
`line_items[0].bbox`, `.modifiers` and `.sku`: producing *a* row zero gives
truth's own empty sub-paths something to be compared against, and
`field_accuracy` scores those pairs `True`. So the count still rises, but every
path it now rises by is a path the map calls agreement — which is the whole of
what the bound guarantees, and it is checkable. A stronger notion of agreement
would have to change `field_accuracy` itself, which decision 3 keeps as it is.
What no longer happens is the count rising on paths the same map scores wrong.

The classes tile the path set — `field_breakdown` assigns every path exactly
once, and the totals it returns add back to the old denominator. Nothing is
dropped; the free points are only stopped from inflating a percentage. The
tiling and the bound are pinned separately in `tests/test_eval_metrics.py`,
because the bound is only safe if the paths it sheds have somewhere to go.

### 3. Rename, never redefine

`EvalReport.field_accuracy` does not survive. Neither does the `field_accuracy`
key in the results JSON or the `Field accuracy:` line in the printed table.

The pure function `eval.metrics.field_accuracy` keeps its name **and** its
meaning — it still returns per-path correctness — so §16's declared signature
stays literally true.

A name that keeps its spelling and changes its meaning is the rot ADR-0032
legislates against: every sentence ever written about the old number stays
readable and silently becomes false. A rename makes them fail loudly instead.

### 4. `flatten` is not touched

`receipts.extract.paths.flatten` emits empty containers as leaves deliberately,
so that "had three line items" versus "had none" is a visible difference rather
than a silently absent key. It also **has callers outside `eval/`**, which is
the reason this decision exists at all. No set of them is named here: `git grep
-n "flatten(" -- src eval scripts` is the list, and it is to be read rather than
trusted to any count — including one written here, which would begin rotting the
day it was correct. Read it literally, and read what comes back as *matches*
rather than as callers: a string search cannot tell a consumer from anything
else that shares the spelling, and some of what it returns is not a consumer at
all. Sorting those out is the reading this sentence refuses to do for you — as
is any list of them, which would be this decision's own warning in miniature.

The rule that treats an empty container as *absent* is an **eval** rule and
lives only in `eval/`.

**`paths.py`'s own module docstring undercounts what depends on `flatten`, and
that is recorded rather than fixed.** It says the function is "used in three
places" and names self-consistency diffing, the corrections log and eval field
accuracy; it omits `count_nulls`, defined in the same file, which depends on
`flatten`'s leaf enumeration and feeds attempt tie-breaking in
`extractor.py`. So the docstring a maintainer would consult before changing
`flatten` understates the blast radius — in the file this decision is about not
touching. It is left alone because this decision is not to touch that file, and
because the milestone that found it was documentation-only. **The fix, when
someone has licence, is to state the property and hand over the grep — not to
replace "three" with a larger number**, which reproduces the same defect one
size up (review standard 19).

### 5. A behaviour change outruns a token grep, because the sentences about it sit in files the fix does not touch

This milestone found a corrected claim still standing after successive passes
had swept for it, and the reason is structural rather than careless. It is
recorded here because the ledger is gitignored and a ruling nobody can find is
not a ruling (ADR-0019).

The claim: several docstrings said `_build_report` "defines
`auto_approval_precision` as `1.0`" when nothing was auto-approved. P8.T3
changed it to `None`. The correction did not reach every copy — and the number
of live copies each pass found **rose at every pass**, the last of them found by
a reviewer *inside the paragraph that had just been corrected*, contradicting a
sentence four lines above it, in a commit titled "every copy of the precision
claim".

That last copy survived every search because it shared no token with the change:
it said "the stored float", and contained neither `1.0` nor
`auto_approval_precision`.

**The structural part, verified rather than reasoned:**

```bash
git show --stat 4a46c46          # P8.T3: harness.py, metrics.py, test_eval_metrics.py
git show --stat 9fe93a0          # the commit that wrote the sentence, into run_baseline.py
git merge-base --is-ancestor 9fe93a0 4a46c46 && echo ancestor
```

The sentence entered at `9fe93a0`, which **is** an ancestor of the fixing commit
`4a46c46`. `4a46c46` touched three files and `eval/run_baseline.py` was not one
of them. The surviving copy was therefore not an oversight inside the sweep: it
was a file **outside the fixing commit's blast radius, carrying a sentence about
the fixed behaviour**.

So the rule:

> When a behaviour changes, grepping for the token you changed is
> **structurally** insufficient. Some sentences describing that behaviour live
> in files the fixing commit never opens, and those are exactly the ones a
> change-scoped search cannot reach. Sweep the claim's **vocabulary** — the ways
> a person would paraphrase the behaviour — not the identifier. And read the
> fixing commit's own file list as evidence about **where** the holdouts are:
> the files that discuss the behaviour, minus the files the fix touched.

Two honest limits on that rule, because it would otherwise overreach.

**First, copies live inside the touched files too** — several of this claim's
were found there. The file-boundary observation narrows where the *residue*
hides; it does not relocate the whole problem, and a reader who took it for the
whole rule would stop searching the files the fix opened.

**Second, "sweep the vocabulary" cannot converge, and must not be mistaken for a
procedure that can.** You cannot enumerate every paraphrase of a behaviour; an
enumerated defence never does converge (review standard 19), and a rule that
promised otherwise would be this repo's recurring failure wearing a new hat. The
honest statement of what happened is narrower and more useful: **the surviving
copy would not have been found by any query — it was found by reading.** The
grep is what shortens the list of files to read. Reading is what finds the
claim.

## Consequences

- **The floor an empty extraction reaches is now around 5.9%**, measured with
  the probe above: `1 / 17`, `1 / 18`, `1 / 17` on r001/r002/r003 — 5.88%,
  5.56%, 5.88%. Down from 42.50% / 37.50% / 36.59%.
- **The residual is one path, and it is a real field.** On all three labels the
  only transcription path an empty extraction gets right is
  `receipt.decimal_convention`, whose schema default `'point'` happens to be
  correct for these receipts. It stays in: a comma-convention receipt would get
  it wrong, so it is a genuine point, not an artefact.
- **`tests/test_eval_floor.py` is the pin**, and it states its bound as a
  literal rather than deriving it from the code under test — a bound computed by
  the thing it checks moves with the defect. The test was written *after* the
  attribute existed, so being green proved nothing on its own (review standard
  14); what makes it a pin is that restoring the old every-path denominator
  behind the new name breaches the bound, which the floors in *Context* already
  show — every one of them is far above it.
- **Line items stay in the headline denominator.** They are the paths an empty
  extraction reliably fails — measured, **zero** free line-item points on all
  three labels (`0/6`, `0/5`, `0/5`). Removing them raises the floor rather than
  lowering it: the core-only figures are 9.09%, 7.69%, 8.33%. Excluding the
  hardest-earned paths would make the metric easier to score well on without
  reading anything. They are additionally reported **split out**, because all
  three current labels carry one line item and line-item paths are already
  `6/17`, `5/18` and `5/17` of each transcription denominator — 35%, 28%, 29%. A
  six-row receipt would push that past half and the headline would quietly
  become a line-item metric.
- **The per-path map now reaches the committed artefact**, sorted, alongside the
  per-class counts. A prompt change that fixes `merchant.tax_id` and breaks
  `receipt.date` is invisible in a scalar and obvious in a diff of the map. This
  is what §16 commits results *for*.
- **One renderer serves the batch table and the single-receipt script.**
  `scripts/try_one_receipt.py` used to compute its own `correct / len(acc)`
  scalar — the same average of unlike quantities reached by a different route,
  printed by the tool an operator actually reaches for during a liveness check
  (ADR-0039). `cmd_eval`'s docstring claims "what counts as correct" never has
  two definitions to keep in sync; it now does not.
- **ISSUE-001's proposed remedy is refuted, and the refutation is recorded with
  its measurement** (ADR-0030). The side-finding proposed excluding `meta.*`, or
  at least `meta.notes`, from the denominator. Excluding `meta.*` moves r001's
  floor from 42.50% to 39.39% and r003's from 36.59% to 36.36% — about 0.22
  points. Excluding only `meta.notes` **raises** every floor (43.59% / 38.46% /
  37.50%), because `notes` is a path an empty extraction *fails*, so dropping it
  removes a penalty rather than a gift. The diagnosis was right; the remedy was
  not the fix.
- **`eval/results/` was empty when this landed** — the directory does not exist
  and nothing is tracked under it — so no committed artefact was invalidated.
  Once a real baseline is committed, redefining the metric makes that first file
  non-comparable with every later one, which is the thing §16 commits results to
  prevent. This was the last free moment.
- **Micro-averaging across receipts is unchanged** — correct paths summed over
  total paths — so a receipt with more line items carries more weight. Left as
  it was, and named in *What this ADR does not decide* rather than settled.

## What this ADR does not decide

**Micro versus macro averaging.** Left at micro, unexamined. Worth revisiting
when receipts differ substantially in row count, which the current three do not.

**`meta.notes` will always fail**, and that is accepted rather than fixed. It
lands in `self_report_agreement`, labelled as self-description, instead of being
special-cased out by name. `self_report_agreement` will read low permanently;
that is the honest reading.

**Whether three receipts can support any of these numbers.** They cannot support
the ≥99% auto-approval precision claim — §16 says so, ADR-0039 says so, and
growing the held-out set is P8.T2. A better-defined metric over three receipts
is still three receipts.

**The "roughly 70–85%" field-accuracy expectation, in `README.md` and
`RECEIPT_SYSTEM_SPEC.md` §15.** Both carry it and both have since `d0ea79f`
(2026-07-27) — `git grep -n "70–85"` finds them, and that is the whole of what
is claimed about its provenance here. It predates this ADR's redefinition, so it
was set when the only field-accuracy number in the project was the old scalar.
`transcription_accuracy` is a strictly harder number, and the floors above show
how much harder: the old scalar started a model that read *nothing* at 42.50%.

**It is left standing deliberately, and this is the record of that.** The
question was put to the project owner during this milestone and the ruling was
to leave both sentences until a real baseline exists. The reasoning is worth
keeping with the ruling: the figure is meaningless under the new definition, but
*replacing* it means choosing a different number, and that is a judgement about
what to expect from a model nobody has run — which is exactly what ISSUE-001
blocks. So it waits on the same thing every other accuracy figure in this project
waits on. **Revisit it when ISSUE-001 closes, not before.**

If you have arrived here from `README.md` or the spec wondering whether that
70–85% still means anything: it does not, it is known not to, and nothing is to
be done about it yet.

It is also an instance of decision 5's own rule — a sentence about the changed
behaviour, sitting in a file no commit in this milestone touched. It was found by
sweeping the claim's vocabulary past the milestone's own file set, which is the
only reason it is in this ADR rather than still unnoticed.

## What was corrected on the way in

The design document
(`docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md`) was
written before the code. It does not self-amend, so the corrections are recorded
here and the numbers above are the measured ones.

- Its §9 states that excluding `meta.*` moves r003's floor by **0.23** points.
  The unrounded delta is **0.2217** points; 0.23 is what you get by subtracting
  two figures that were each already rounded to two decimals (36.59 − 36.36).
- Its §3.5 states that line-item paths are "24–25% of each denominator". That
  holds for the **whole path set** (25.00% / 25.00% / 24.39%), but the
  denominator that now matters is the transcription one, where they are 35.29% /
  27.78% / 29.41%.
- Its §3.5 states that excluding line items raises the floor to "31.6% / 28.6% /
  25.0%". Neither of the two readings measured here reproduces that: the old
  scalar with line-item paths dropped gives 56.67% / 50.00% / 48.39%, and the
  shipped core-only ratio gives 9.09% / 7.69% / 8.33%. What the figures were
  computed from is not recovered here. The claim's *direction* — that removing
  line items raises the floor — holds under both.
- Its §1.2 splits r001's seventeen free points as 11 / 4 / 2. Under the shipped
  `_is_filled` rule the split is 12 / 4 / 1 — with row 1 read as **non-`meta`**
  paths where neither side is filled, the qualifier the Context table carries and
  the one that keeps these rows a partition. `totals.tax_breakdown` is an empty
  list and an empty container is *not filled*, so it moves out of the schema
  defaults and in beside the other paths the receipt does not have. Both splits
  sum to 17; only the bucketing differed.

## References

`docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md` — the
approved design, with the caveats above; `docs/KNOWN_ISSUES.md` — ISSUE-001 and
its dated correction; `docs/adr/0039-the-local-path-is-a-liveness-check.md` —
what a local run does and does not license, and the measurement not to
re-derive; `docs/adr/0032-a-document-cannot-certify-itself.md` and
`docs/adr/0033-the-handoff-pair-goes-last-and-alone.md` — the correction-goes-
to-every-copy rule decision 5 extends; `RECEIPT_SYSTEM_SPEC.md` §16 — the metric
set and the commit-the-results rule; `eval/metrics.py`, `eval/harness.py`,
`eval/run_baseline.py`, `tests/test_eval_floor.py` — what shipped.
