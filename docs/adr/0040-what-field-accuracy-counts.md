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
          "correctly_empty", bd.correctly_empty)
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
| truth not filled and prediction not filled — the receipt has no such field | 12 |
| `meta.*` self-reports resting at their schema defaults | 4 |
| a filled truth value a schema default happens to match (`receipt.decimal_convention`) | 1 |

`meta.*` is the **smaller** contributor. That is what refutes the remedy that
was on file — see *Consequences*.

ADR-0039 records a local run scoring 45.00% field accuracy on r001 from a model
whose confidence was `0.000`, whose critical fields were all wrong, and which
found no line item. Against a 42.50% floor, that run beat silence by one path.
**That measurement is not re-derived here and is not restated as a defect of the
run** — it is an accurate record of what the old metric printed, and ADR-0039 §3
is the ruling that keeps it.

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

### 2. Four numbers, and two of them are counts

`transcription_accuracy` (truth filled, group core or line items) and
`self_report_agreement` (truth filled, group meta) are ratios — `None`, never
`0.0`, on an empty denominator. `hallucinated_fields` and
`correctly_empty_fields` are **counts**.

Counts on purpose. Their would-be denominator is "fields this receipt does not
have", which is a property of the **schema**, not of the receipt: adding an
optional field to `ReceiptExtraction` would move that percentage on every
receipt with nothing about the model having changed. A count moves only when
behaviour moves.

`hallucinated_fields` exists because "null over confident-wrong" is a project
non-negotiable that was measured by nothing. Under the old scalar, a model that
invents a cashier name and one that correctly leaves it null differed by a
single path in forty.

The classes tile the path set — `field_breakdown` assigns every path exactly
once, and the totals it returns add back to the old denominator. Nothing is
dropped; the free points are only stopped from inflating a percentage.

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
than a silently absent key — and it is shared beyond eval, by self-consistency
diffing and the corrections log. The rule that treats an empty container as
*absent* is an **eval** rule and lives only in `eval/`.

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

Two honest limits on that rule, because it would otherwise overreach. Copies
live **inside** the touched files too — several were found there — so this
narrows where the *residue* hides, it does not relocate the whole problem. And
the file-list query is a starting filter, not an answer: it tells you which
files to read, and only reading them tells you what they claim.

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

**The "roughly 70–85%" expectation** — `git grep -n "70–85"` finds it in
`README.md` and `RECEIPT_SYSTEM_SPEC.md` §15 — predates this split and is not
re-baselined here. It was written against the
old scalar; `transcription_accuracy` is a strictly harder number. Re-stating it
needs a real baseline, which is ISSUE-001's business, not this ADR's. It is
named here as an instance of decision 5's own rule: a sentence about the changed
behaviour, sitting in a file no commit in this milestone touched.

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
  `_is_filled` rule the split is 12 / 4 / 1, because `totals.tax_breakdown` is
  an empty list and an empty container is *not filled* — so it belongs with the
  both-sides-empty group rather than with the schema defaults. Both sum to 17;
  only the bucketing differed.

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
