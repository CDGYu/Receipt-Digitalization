# Re-validating a corrected receipt — design

**Date:** 2026-08-24
**Status:** Draft, for review
**Closes:** ISSUE-033 (a reviewer's correction is never re-validated).
**Extends:** ISSUE-006's close (R026), whose reviewer-facing half this is.
**Deliberately does not close:** the export gate, `/metrics`, and re-routing —
see §8.

Every measurement below was taken on 2026-08-24 against
`feat/arithmetic-went-offline` at `13a254d`. `main` is at `b7ef275` and is an
ancestor of that commit (`git merge-base --is-ancestor main HEAD`), so the
branch is `main` plus R026 and its documentation.

---

## §0. What this is

A reviewer corrects a total from 949.20 to 1000.00. The findings panel beside
them still shows the findings the receipt arrived with. Nothing recomputes —
not the findings, not the confidence, not the status.

ISSUE-033 states that as a wiring gap. **It is not.** The measurements in §1
show that re-running `validate()` on a corrected receipt today would *invent*
findings and *destroy* findings for reasons that have nothing to do with the
reviewer's edit. Today's honest label — "what the machine found at extraction
time" — is better than a naive fix. This design is about what can *truthfully*
be recomputed.

---

## §1. What the tree already dictates

Facts, measured, that bound everything after this.

**`validate()` has exactly one call site.** `src/receipts/extract/extractor.py`
line 319. Established by grepping every import of the validate package across
`src/` (`from ..validate`, `from .validate`, `from receipts.validate`): `report`,
`context` and `rules` are imported in several modules; `validator.validate` in
exactly one. `PATCH /receipts/{id}` calls `apply_corrections` and then
`get_findings` — the rows persisted at extraction — and `POST
/review/{task_id}/complete` re-reads nothing at all.

**A rehydration function already exists and is explicitly lossy.**
`review/serializers.py::_export_extraction(receipt: Receipt) ->
ReceiptExtraction`, built for the export path. Its own docstring lists what it
cannot rebuild: `tax_breakdown`, `prices_include_tax`, `meta.ambiguous_fields`,
`meta.unreadable_regions`, `meta.notes`, and the merchant's
`address`/`tax_id`/`phone`/`branch`. **`meta.is_refund` is missing from that
list and is equally absent** — it is a column on no model.

**The round-trip changes the answer, with no edit at all.** Each golden label
was persisted through the real `save_extraction` into in-memory SQLite,
rehydrated with `_export_extraction`, and both sides validated:

| receipt | at extraction | after round-trip |
|---|---|---|
| r001, r002, r003 | `[]` | `[]` — same |
| a refund (r001 negated, `meta.is_refund = True`) | `[]` | **`R040/ERROR`** |

`meta.is_refund` rebuilds as `False`, so R040 ("the total is positive unless the
document is a refund") fires on a receipt that was correct. r002 additionally
loses `prices_include_tax: True -> None` silently — it does not change r002's
findings, but it changes what R020 is permitted to compare against, from one
declared convention to either.

**The three clean labels agreeing is the trap.** A shallower check would have
stopped there and concluded the round-trip is faithful.

**The `ValidationContext` is not persisted at all.** No model carries
`ocr_text`, `triage`, or `consistency` (the two hits for those words in
`persist/models.py` are `PassName` enum tokens for `extraction_runs`, not stored
context). Measured on a receipt crafted to fire the context rules, with a full
extraction-time context versus the bare one a review route could build today:

```
extraction-time context: ['R001', 'R010', 'R020', 'R061', 'R070']
review-time context:     ['R010', 'R020']
VANISH: ['R001', 'R061', 'R070']      APPEAR: []
```

**`ctx.merchant` is read by no rule.** Grepped across `validate/rules.py`: zero
hits. It is a dead context field. Recorded, not fixed here.

---

## §2. The property

> A finding shown to a reviewer is either **current** — recomputed from the
> receipt as it stands now — or **labelled as the extraction run's**. Never a
> stale copy presented as current.

Both halves matter. The second is what the system does correctly today and must
keep doing; the first is what is missing.

---

## §3. Rule subjects, declared and bound

`Rule` gains a declared subject:

```python
class Subject(str, Enum):
    CONTENT = "content"   # answerable from the persisted receipt alone
    RUN = "run"           # the evidence is the extraction run, and it is gone
```

`Rule.subject: Subject = Subject.CONTENT` by default.

**The classification is derived, not enumerated.** An enumerated list of
"review-safe rules" would drift the moment a rule is added — the shape recorded
in `enumerated-defence-never-converges`, and the same hazard ISSUE-006 names
when it says nothing joins the editable set to `_LINE_ITEM_FIELDS`. Instead
`ValidationContext` declares what a review route can rebuild:

```python
#: Context a review route can reconstruct. Everything else is extraction-run
#: evidence: a rule that reads it cannot be re-run after a correction.
REVIEW_RECONSTRUCTIBLE = frozenset({
    "config", "today", "expected_buyer_name", "expected_buyer_tax_id",
})
```

The unsafe set is the **complement**, computed from
`dataclasses.fields(ValidationContext)` rather than written out. `ValidationContext`
has exactly nine fields today (`triage`, `ocr_text`, `merchant`, `consistency`,
`parse_error`, `expected_buyer_name`, `expected_buyer_tax_id`, `config`,
`today`), so the unsafe set is `{triage, ocr_text, merchant, consistency,
parse_error}`.

**A new context field is unsafe by default.** That is the whole point of taking
the complement: a field added without a deliberate entry in the allow-list makes
every `CONTENT` rule that reads it red, rather than silently joining the safe
set.

### §3.1 Which direction the binding fails

The declaration is bound to the code by a static scan of each rule's `applies`
and `check` source for `ctx.<name>` reads.

**Static rather than dynamic, on purpose.** A recording-proxy context would only
observe the fields a rule reads on the branches a fixture happens to reach, so
it *under*-reports: a rule that reads `ctx.ocr_text` in an unexercised branch
would be certified `CONTENT` and would then lie. Static analysis
*over*-reports — it counts a read that never happens — which costs coverage and
never lies. Fail in the safe direction.

### §3.2 The helper hole, closed

`R014.applies` and `R015.applies` are both `return expects_a_buyer(ctx)`. A
naive scan sees no `ctx.<name>` read in either and waves them through — for the
wrong reason, since the helper reads `expected_buyer_name` and
`expected_buyer_tax_id`, which happen to be reconstructible.

The scan therefore follows `ctx` into module-level helpers, and **an
unrecognised callable receiving bare `ctx` is an error, not a pass.** There is
exactly one such helper today (`expects_a_buyer`); `ctx.tol(...)` is a method
call reading `config` and is reconstructible. A second helper added later
reddens rather than opening a hole.

### §3.3 What falls out, including one deliberate loss

`RUN`: **R001** (`parse_error`), **R060** and **R061** (`ocr_text`), **R070**
(`consistency`).

**R013 is `RUN` too, and this is a real coverage loss rather than an
oversight.** Its subject — "at least one line item was extracted" — is content.
It reads `ctx.triage` only to suppress itself when triage said zero items were
expected. Without triage it would fire on a receipt that legitimately has no
items. Marking it `RUN` loses a check; marking it `CONTENT` ships a rule that
fires wrongly. §3.1's principle decides it, and this paragraph is the record
that the cost was seen and accepted.

R014 and R015 are `CONTENT`, so the review route supplies the expected buyer
from `Settings` exactly as the pipeline does.

---

## §4. Making the round-trip lossless

One migration on `receipts`, on top of head `f3ae0f86e0e6`:

| column | type | why |
|---|---|---|
| `is_refund` | `BOOLEAN NOT NULL DEFAULT false` | R040 inverts without it (§1, measured) |
| `prices_include_tax` | `BOOLEAN NULL` | R020/R024 silently loosen without it |
| `tax_breakdown` | `_jsonb() NOT NULL DEFAULT '[]'` | R025 silently skips without it |

`_jsonb()` is `models.py`'s own helper -- `JSONB` on Postgres, `JSON` on
SQLite -- so the migration works under the test engine as well as production.
`Subject` follows `Severity`'s `(str, Enum)` shape, which is what `_token_enum`
expects if it is ever persisted.

`save_extraction` writes all three; `_export_extraction` reads them.

**`_export_extraction`'s docstring shrinks by three entries.** Its "Lossy
against the full extraction schema" list is a load-bearing claim that other
readers rely on; leaving it as-is would make it false. `meta.is_refund` is added
to that list at the same time — it belonged there before this change and was
missing.

Backfill is deliberately not attempted. Existing rows get the defaults, which is
correct for `prices_include_tax` (null already means "either convention") and
for `tax_breakdown` (an empty list makes R025 skip, which is what it does today).
For `is_refund` the default `false` matches what `_export_extraction` already
assumes, so no existing receipt's behaviour changes.

---

## §5. Where it runs, and what it returns

A new pure function in `review/serializers.py`:

```python
def revalidate(receipt: Receipt) -> ValidationReport
```

It rehydrates via `_export_extraction`, builds a `ValidationContext` with only
the reconstructible fields, and runs the `CONTENT` rules. `receipt_detail` calls
it, so `GET /receipts/{id}` and `PATCH /receipts/{id}` both get it with no route
change and no second query. **Nothing is written.**

The payload gains two sibling keys rather than merging into `findings` — merging
would destroy the distinction the property in §2 exists to preserve:

```json
"findings":         [...],
"current_findings": [...],
"not_rechecked":    ["R001", "R013", "R060", "R061", "R070"]
```

`current_findings` reuses the existing `_finding` serializer, so the frontend's
`Finding` type is unchanged.

**`not_rechecked` is load-bearing, not decoration.** Without it an empty
`current_findings` reads as "everything was checked and is fine", which is the
silent-wrong-answer shape this project keeps producing. It is derived from the
registry, never written out, so a rule that changes subject changes this list.

### §5.1 Why nothing is persisted

The alternative — writing a review-time generation of findings — recreates the
bug it fixes: generation *N-1* is stale the moment edit *N* lands, so it needs a
"current generation" concept to defend against staleness it introduced. It also
grows `validation_findings` per edit and moves `save_findings` ownership out of
the extraction pipeline, which is one of the four rulings ISSUE-033 flags.

Computed-on-read **cannot go stale, by construction.** There is no stored copy
to fall behind. Its one cost — the export gate and `/metrics` cannot see these
findings — is precisely the deferred scope in §8, and it is not a blocker: if
that scope is taken later, persistence is an additive change on top of this.

---

## §6. The review screen

`FindingsPanel` currently renders one list under the heading "What the machine
found at extraction time", with the note "Not re-checked when you edit -- this
is the receipt as it was extracted."

It splits into two groups:

- **Checked now** — `current_findings`. Recomputed on load and after every save.
- **From the extraction run** — `findings`, keeping the existing heading and
  keeping that note, which stays true of this group and only this group. It
  states how many rules could not be re-checked and why: their evidence is the
  original scan.

The existing note must **move**, not be deleted. It is the honest label that
made this defect discoverable, and it is still correct about the second group.

---

## §7. Error handling

`validate()` never raises — a rule that throws is recorded as an INFO
`{rule}.crashed` finding, and `tests/test_rules.py::test_crashing_rule_is_contained`
pins it. So `revalidate` cannot break the detail response through a rule.

`_export_extraction` is straight-line construction from typed columns.
**No catch is added.** If a receipt written by `save_extraction` cannot be
rehydrated, that is a data-integrity defect and a loud failure is the correct
signal; swallowing it into an empty `current_findings` would manufacture exactly
the silent wrong answer this design exists to remove. A pin asserts the
round-trip holds for everything `save_extraction` writes.

---

## §8. What this deliberately leaves open

Stated here so no reader takes it as closed:

- **The export's `has_unresolved_error`** is computed by `build_export_rows`
  from persisted findings, so a corrected receipt still exports against its
  extraction-time errors.
- **`/metrics` and the review queue** likewise read persisted findings.
- **Confidence and status are not recomputed.** A corrected receipt keeps its
  routed status. Changing that needs a ruling nothing in the system has today:
  what it means for a receipt a human has already reviewed to be re-scored, and
  whether it may reach `auto_approved` afterwards.

These are one decision, not three, and it is the option deferred when this
design's scope was set on 2026-08-24.

---

## §9. Testing

Every pin below names the mutation that makes it red. Mutations go where the
subject computes its answer (ADR-0051), one at a time, each confirmed to still
compile, each reverted by its inverse edit rather than by `git checkout`.

| pin | proven red by |
|---|---|
| **round-trip fidelity**: `validate(original) == validate(rehydrated)` over the golden labels **and a refund fixture** | reverting any one of the three new columns |
| every `CONTENT` rule reads no unreconstructible context field | declaring R060 as `CONTENT` |
| the unsafe set is derived from `dataclasses.fields(ValidationContext)`, not a literal | adding a context field without touching the allow-list |
| an unrecognised callable receiving bare `ctx` is an error | adding a second `expects_a_buyer`-shaped helper |
| no `RUN` rule ever appears in `current_findings` | dropping the subject filter in `revalidate` |
| `not_rechecked` is derived from the registry | hard-coding the list |
| **acceptance**: `PATCH` flipping `is_template_row` on the sole purchase returns `current_findings` containing **R026** | the whole chain |

**The refund fixture is the most important one.** It is the case that currently
goes clean -> `R040/ERROR` on a round-trip with no edit, and it is the only pin
here that would have caught the defect that reframed this design.

**A note on which pins can go red in the TDD RED phase.** The negative pins —
"no `RUN` rule appears", "the scan rejects an unknown helper" — will pass before
any of this is written, because a subject that does not exist filters nothing.
They are pins only once their mutation is run
(`a-new-rules-negative-tests-pass-vacuously`).

---

## §10. Files

| file | change |
|---|---|
| `alembic/versions/` | one new revision on `f3ae0f86e0e6` |
| `src/receipts/persist/models.py` | three columns on `Receipt` |
| `src/receipts/persist/repository.py` | `save_extraction` writes them |
| `src/receipts/validate/context.py` | `REVIEW_RECONSTRUCTIBLE`, the derived complement |
| `src/receipts/validate/rules.py` | `Subject`, `Rule.subject`, five `RUN` declarations |
| `src/receipts/review/serializers.py` | `revalidate`, `_export_extraction` reads the three columns and its docstring shrinks, `receipt_detail` returns the two new keys |
| `frontend/src/api/types.ts` | `current_findings`, `not_rechecked` |
| `frontend/src/review/FindingsPanel.tsx` | two groups |
| `tests/`, `frontend/src/review/*.test.tsx` | §9 |
| `docs/KNOWN_ISSUES.md` | ISSUE-033 resolution |
| `RECEIPT_SYSTEM_SPEC.md` | the three columns in §6, the subject in §10.3 |
