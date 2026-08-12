# Eval field accuracy — what it counts (2026-08-12)

**Status:** approved 2026-08-12 by the user. Decision to be recorded in an ADR.

Derived against `main` at `871f1aa`, working tree clean, five gates PASS.
**Re-derive rather than quote** (ADR-0028 rule 1). Every number below states the
command or probe that produced it; none is inherited from `docs/KNOWN_ISSUES.md`
or from `docs/NEXT_SESSION_PROMPT.md`.

## 1. The gap

`eval.metrics.field_accuracy` returns `{dotted_path: bool}` over the union of
paths in the predicted and truth extractions. `eval.harness` folds that map into
one scalar by summing correct paths over total paths across the golden set.

The scalar averages **three unlike quantities**:

1. what the model **read** — `merchant.name`, `totals.total`, line-item rows;
2. what it **correctly left empty** — fields this receipt does not have;
3. what it **said about itself** — `meta.*`, which is self-description and, in
   `meta.notes`, human annotator prose.

Terms 2 and 3 dominate. They are earned by producing nothing at all.

### 1.1 The measurement

Method: construct `ReceiptExtraction()` — every field at its default, nothing
read — and score it with the current `field_accuracy` against each golden label.
This is the metric's **floor**: the number a model that reads nothing achieves.

| label | floor | paths |
|---|---|---|
| r001 | **42.50%** | 17 / 40 |
| r002 | **37.50%** | 15 / 40 |
| r003 | **36.59%** | 15 / 41 |

`docs/KNOWN_ISSUES.md` records a local run scoring **45.00%** field accuracy on
r001 from a model whose confidence was `0.000`, whose critical fields were all
wrong and which found no line item. Against a floor of 42.50%, that run beat
silence by **one path**.

### 1.2 Where the floor comes from

r001's 17 free points, itemised by the same probe:

| contributor | count | examples |
|---|---|---|
| both sides null — the receipt does not have this field | 11 | `merchant.branch`, `merchant.phone`, `payment.card_last4`, `payment.method`, `receipt.cashier`, `receipt.terminal`, `receipt.time`, `totals.change`, `totals.discount`, `totals.prices_include_tax`, `totals.tender` |
| `meta.*` self-reports resting at their defaults | 4 | `meta.ambiguous_fields=[]`, `meta.is_refund=False`, `meta.receipt_is_inconsistent=False`, `meta.unreadable_regions=[]` |
| schema defaults that agree by construction | 2 | `receipt.decimal_convention='point'`, `totals.tax_breakdown=[]` |

`meta.*` is the **smaller** contributor. This matters because it refutes the
remedy that was on file — see §9.

`meta.notes` deserves naming on its own. r001's is roughly 200 words of human
verification prose ("USER-VERIFIED 2026-07-28: qty is 9.8 (the glyph can read as
98/78)…"). It is scored as **one path, at equal weight to `totals.total`**, and
no model will ever match it.

### 1.3 The second defect: the artefact discards the useful half

Spec §16 lists metric 4 as "**Per-field accuracy** — where to focus prompt work."

`eval/harness.py`'s `_report_to_dict` collapses each receipt's per-path map to
two integers, `fields_correct` and `fields_total`. The committed results file
therefore cannot answer the question §16 assigns the metric its purpose for.
The map is computed, used for one sum, and thrown away.

## 2. Scope

**In:** `eval/metrics.py` (a new pure classifier and the report dataclass),
`eval/harness.py` (aggregation and the JSON view), `eval/run_baseline.py`
(the printed table), `scripts/try_one_receipt.py` (§2.1), their tests, an ADR,
and a dated correction to ISSUE-001 recording §9.

**Out, deliberately:**

- **`receipts.extract.paths.flatten` is not touched.** Its docstring states that
  empty containers are emitted as leaves *"so that 'had 3 line items' versus 'had
  none' is a visible difference rather than silently absent"*, and it is shared
  by self-consistency diffing and the corrections log. The rule in §3.1 that
  treats an empty container as absent is an **eval** rule and lives only in
  `eval/`.
- **`field_accuracy()`'s signature is not changed.** Spec §16 declares it as
  `-> dict[str, bool]`. The defect is in aggregation, not in scoring; the
  per-path map it returns is already the right artefact.
- **No new golden receipts.** Growing the held-out set is P8.T2.
- **No provider work.** This milestone is deliberately runnable with no key
  (ISSUE-001, backlog item 1).

### 2.1 The second definition of "correct"

`cmd_eval`'s docstring states that the command "owns no scoring logic of its own,
only argument plumbing, so 'what counts as correct' never has two definitions to
keep in sync."

It has two. `scripts/try_one_receipt.py`'s scoring block calls `field_accuracy`
and then computes its own scalar — `correct / len(acc)` — printing it on the line
that begins `field accuracy :`. That is the same average of unlike quantities
described in §1, reached by a different route, and it is printed by the tool an
operator reaches for during a liveness check (ADR-0039).

It is in scope. Fixing only the harness would leave the misleading number in the
place it is most often read.

## 3. The design

### 3.1 Two orthogonal axes

Every path is classified on two axes. **Group** comes from the path string
itself; **filled** is read from the **truth** side. Neither is ever read from the
prediction — see the second note in §3.2 for why that matters.

**Group** — structural, from the path prefix alone:

| group | rule |
|---|---|
| `meta` | the path starts with `meta.` |
| `line_items` | the path is `line_items` or starts with `line_items[` |
| `core` | anything else |

The rule is a prefix test, not a list of field names. A `meta` field added to the
schema later is classified without anybody deciding it should be — which is the
property review standard 19 asks for, and the reason this is not an enumeration
of "which meta fields are facts".

**Filled** — a value `v` is *filled* iff:

```python
v is not None and not (isinstance(v, (list, dict)) and len(v) == 0)
```

Written with `isinstance` and `len`, not `v not in (None, [], {})`: the latter
compares with `==`, and equality against a container is not a test this rule
should depend on.

### 3.2 The classes

| class | condition | scored how |
|---|---|---|
| `transcription` | truth filled, group is `core` or `line_items` | ratio |
| `self_report` | truth filled, group is `meta` | ratio, reported separately |
| `absent` | truth not filled, any group | **counted**, never a ratio |

The three tile the path set. Nothing is dropped.

**A path missing from a side counts as not filled on that side.** The path set is
the union of the two flattened dicts, so a path can be absent from either. Both
"present with value `None`" and "not present at all" are *not filled*; the
classifier reads `flat.get(path)` and applies §3.1's rule to the result. This is
what makes a hallucinated fourth line item count: truth has no `line_items[3].*`
paths at all, so they are `absent`, and a prediction that fills them is
hallucination rather than a silent miss.

**The class is always read from the truth side.** A path the prediction invents
has no truth value; it is `absent` by the rule above, never `transcription`. So
inventing fields can never enlarge the denominator the model is scored against —
which would otherwise let a model dilute its own error rate by hallucinating.

### 3.3 The numbers that replace the scalar

1. **`transcription_accuracy`** — correct `transcription` paths over all
   `transcription` paths. The headline. `None` when the denominator is zero,
   never `0.0` (the `auto_approval_precision` rule from P8.T3, applied to a
   second metric before it can bite).
2. **`self_report_agreement`** — the same ratio over `self_report` paths.
   Reported beside the headline, never averaged into it. It will read low
   permanently, because `meta.notes` is unmatchable; that is the honest reading
   and not a defect to fix.
3. **`hallucinated_fields`** — a **count**: `absent` paths where the *prediction*
   is filled. The model invented a value for a field the receipt does not have.
4. **`correctly_empty_fields`** — a **count**: `absent` paths where the
   prediction is also not filled.

**3 and 4 are counts, not ratios, on purpose.** Their would-be denominator is
"fields this receipt does not have", which is a property of the *schema*, not of
the receipt: adding an optional field to `ReceiptExtraction` would move the
percentage on every receipt without anything about the model changing. A count
moves only when behaviour moves.

**Why hallucination gets a number at all.** "Null over confident-wrong" is a
project non-negotiable and is currently measured by nothing. Under the old
scalar a model that invents a cashier name and a model that correctly leaves it
null differ by one path in forty. Splitting the classes is what makes the
difference legible.

**Why `correctly_empty_fields` exists.** It is where the 11 free points of §1.2
go. They are not deleted from the accounting, only stopped from inflating a
percentage — a reader can still see that the model correctly left 11 fields
empty. Nothing silently dropped.

### 3.4 The resulting floor

Same probe as §1.1, under the new definition:

| label | old floor | `transcription_accuracy` floor |
|---|---|---|
| r001 | 42.50% | **5.9%** (1 / 17) |
| r002 | 37.50% | **5.6%** (1 / 18) |
| r003 | 36.59% | **5.9%** (1 / 17) |

The residual single path is `receipt.decimal_convention`, whose schema default
`'point'` is correct for all three of these receipts. It is left in: it is a
genuine field a comma-convention receipt would get wrong, not an artefact.

### 3.5 Per-group breakdown

`transcription_accuracy` is additionally reported split by group — `core` and
`line_items` — so composition stays visible.

This matters as the held-out set grows. All three current labels carry exactly
**one** line item, so line-item paths are 24–25% of each denominator. A six-row
receipt would push that past half, and the headline would silently become a
line-item metric. The breakdown makes that visible instead of surprising.

Line items stay **in** the headline denominator. Measured: excluding them raises
the floor to 31.6% / 28.6% / 25.0%, because line-item paths are the ones an
empty extraction reliably fails — 0 free across all three labels. Removing the
hardest-earned paths would make the metric easier to score well on without
reading anything.

### 3.6 Aggregation across receipts

Micro-averaged — correct paths summed over total paths across the golden set —
which is the existing behaviour and is unchanged. A receipt with more line items
therefore carries more weight. The per-path map (§4) is what serves §16's "where
to focus prompt work", so the aggregate is not asked to do that job.

### 3.7 Naming: rename, never redefine

The key `field_accuracy` **does not survive** in the report dataclass, the JSON,
or the printed table. A name that keeps its spelling and changes its meaning is
the exact rot ADR-0032 legislates against: every sentence written about the old
number stays readable and becomes false.

`EvalReport.field_accuracy` becomes `EvalReport.transcription_accuracy`. The pure
function `eval.metrics.field_accuracy` keeps its name **and** its meaning — it
still returns per-path correctness — so §16's declared signature stays literally
true.

## 4. The artefact

`_report_to_dict` retains the per-path result map rather than collapsing it to
counts. §16 commits results so regressions are visible in a diff, and a diff of
per-path booleans is precisely what shows one: a prompt change that fixes
`merchant.tax_id` and breaks `receipt.date` is invisible in a scalar and obvious
in the map.

Per receipt, the JSON carries the class counts and the map. Three receipts at
~40 paths is ~120 entries.

**Accepted residual:** at 20 receipts this is ~800 entries. That is tolerable for
a diffable artefact and is recorded here rather than pre-solved; revisit it when
the golden set actually reaches that size, not before.

## 5. The printed table

`run_baseline.format_report` prints §16's six metrics. Metric 4's single line
becomes a small block: the headline, its two group figures, self-report
agreement, and the two counts.

**One in-scope correction.** `format_report`'s docstring states that
`_build_report` *"defines it as ``1.0``"* when nothing is auto-approved. That was
true before P8.T3 and is false at `871f1aa`: `_build_report` now resolves
`auto_approval_precision` to `None` when nothing was approved. The P8.T3 fix
reached `_build_report` itself and `EvalReport`'s field comment and missed this
third copy (ADR-0033 §2: a correction goes to every copy). It is corrected
because this design edits that function; it is not otherwise this milestone's
business.

## 6. Blast radius

Re-derive rather than trust this table. The command that produced it:

```
git grep -n "\.field_accuracy\|\"field_accuracy\"\|fields_correct\|fields_total"
```

plus a grep for the eval symbols across `src`, `eval`, `scripts` and `tests`.
**No line numbers are cited below** — ADR-0028 §5 and review standard 21: a
citation is a claim, and this repo is already carrying an unaudited residual of
them. Symbols and quoted text are given instead, so a moved line does not
falsify a sentence.

| consumer | affected? | why |
|---|---|---|
| `receipts.cli.cmd_calibrate` | **no** | reads `results[].confidence` and `results[].critical_correct` only, and sets `field_acc={}` explicitly when it rebuilds `EvalResult` |
| `receipts.pipeline` | **no** | matched only on `build_eval_pipeline`; touches no metric |
| `eval/results/*.json` | **no** | the directory does not exist at `871f1aa`; nothing committed is invalidated |
| `eval/harness.py` | yes | `_report_to_dict`'s `field_accuracy` key, and its `fields_correct`/`fields_total` pair |
| `eval/run_baseline.py` | yes | `format_report`'s `Field accuracy:` line |
| `scripts/try_one_receipt.py` | yes | §2.1, the second definition |
| `tests/test_eval_metrics.py` | yes | contains `assert report.field_accuracy == 1.0` |
| `tests/test_run_baseline.py` | yes | asserts on the table text |
| `tests/test_cli_reports.py` | yes | synthetic results-file fixtures carrying `fields_correct`/`fields_total`. `calibrate` ignores those keys, so these keep passing while encoding a shape that no longer exists — a green test asserting a dead contract |

**Historical records quote the old shape and are left alone.**
`docs/KNOWN_ISSUES.md` and `docs/adr/0039-the-local-path-is-a-liveness-check.md`
each record `fields_correct 18 / 40` from the 2026-08-11 liveness run. Those are
accurate reports of what that run printed. Rewriting them would falsify a record
of the past to match the present, and ADR-0039 §3 says that measurement is not to
be re-derived. The same applies to `docs/superpowers/plans/2026-07-29-cli.md`,
which does not self-amend.

**`eval/results/` being empty is why this is worth doing now.** Once a real
baseline is committed, redefining the metric makes that first artefact
non-comparable with every later one — which defeats the purpose §16 commits
results for. This is the last point at which the change costs nothing.

## 7. Testing

The load-bearing test is the **floor test**, and it is the one that would have
caught the original defect: score `ReceiptExtraction()` — nothing read — against
each real golden label and assert the headline number is below a stated bound.

**Its RED phase needs care, and the plan must say so.** Written against
`transcription_accuracy`, it fails on today's code with `AttributeError` — the
attribute does not exist yet. That is failure for the wrong reason and proves
nothing (review standard 15). The proof this test is a pin is a **mutation after
the attribute exists**: restore the old "every path counts" denominator behind
the new name and confirm the bound is breached. A test never proven red for the
right reason is not a pin (standard 14).

The bound itself is stated as a number in the test, not derived at runtime from
the thing under test — a floor computed by the code it is checking would move
with the defect.

Also pinned: each class's membership rule as a property rather than an example
(a `meta.` path added to the schema lands in `self_report` without a test
change); hallucination counted when the prediction fills a path the truth leaves
empty; both counts present in the JSON; the per-path map present in the JSON; and
`None` rather than `0.0` on an empty denominator.

## 8. Open, and deliberately not decided here

- **Micro versus macro averaging** across receipts (§3.6). Left at micro. Worth
  revisiting when receipts differ substantially in row count, which the current
  three do not.
- **`meta.notes` will always fail.** Accepted: it lands in `self_report_agreement`
  where it is labelled as self-description, rather than being special-cased out
  by name.
- **P8.T2**, growing the held-out set, is the thing that makes any of these
  numbers statistically meaningful. §16 already says a ≥99% precision claim
  cannot rest on three receipts.

## 9. A finding that was on file, verified, and refuted

`docs/KNOWN_ISSUES.md` ISSUE-001's side-finding proposes: *"Consider excluding
`meta.*` (or at least `meta.notes`) from the field-accuracy denominator so the
number reflects transcription, not annotation."*

The diagnosis is right. **The remedy does not achieve what it says**, and its
weaker half moves the number the wrong way. Measured with the §1.1 probe:

| definition | r001 | r002 | r003 |
|---|---|---|---|
| current | 42.50% | 37.50% | 36.59% |
| exclude `meta.*` | 39.39% | 33.33% | 36.36% |
| exclude only `meta.notes` | **43.59%** | **38.46%** | **37.50%** |

Excluding `meta.*` entirely moves r003's floor by **0.23 percentage points**.
Excluding only `meta.notes` **raises** every floor, because `notes` is a path the
empty extraction *fails* — dropping it removes a penalty, not a gift.

Recorded under ADR-0030: a finding is a claim, "this finding is wrong" is a valid
resolution, and it is recorded with its measurement rather than dropped. The
diagnosis in ISSUE-001 stands and is cited in §1; the proposed remedy is
superseded by §3.
