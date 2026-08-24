# Re-validating a corrected receipt — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer's correction is re-checked by every rule that can honestly
answer for corrected data, and the rules that cannot are named rather than
silently skipped.

**Architecture:** Three extraction fields become columns so the DB round-trip
stops changing the answer. Each rule declares whether its subject is the
receipt's **content** or the **extraction run**, bound to the code by a static
scan of what it reads off the `ValidationContext`. `receipt_detail` re-runs the
content rules on every read and returns them beside — never merged into — the
persisted extraction-run findings. Nothing is written, so the fresh findings
cannot go stale.

**Tech Stack:** Python 3.14, SQLAlchemy 2 + Alembic, FastAPI, Pydantic v2,
pytest; React 19 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-24-revalidating-a-corrected-receipt-design.md`

## Global Constraints

- **Money is `Decimal`, never `float`** (ADR-0001). `tests/test_no_float_in_money_path.py` enforces it.
- **Migrations must render as valid Postgres DDL** (ADR-0004). Boolean defaults use `sa.false()`, never `sa.text("0")` — Postgres rejects an integer default on a `BOOLEAN` column. `tests/test_migrations.py::test_the_revision_chain_renders_as_valid_postgres_ddl` enforces it.
- **The ORM and the migration chain must not drift.** `tests/test_migrations.py::test_migration_schema_matches_orm_metadata` enforces it.
- **Model text is redacted by default, not by an enumerated column list** (§18, ADR-0007). The blanket pass in `save_extraction` is `type(value) is str` over its `fields` dict, so it **cannot see inside a JSON column** — a JSON column of model text must be wrapped in `redact_pan(...)` explicitly, as `LineItem.modifiers` already is.
- **`validate()` is pure**: no network, no mutation, never raises. Rules never import `Settings`; the caller reads the environment and hands the answer in on the context.
- **Line length 100** (`ruff`). All five gates must pass: `python scripts/verify.py`.
- **Every new assertion gets its mutation run** (ADR-0051): apply it, watch *that named test* fail, revert with the **inverse edit** (never `git checkout -- <file>`, which also discards unrelated work in the file), confirm the mutant still compiled, re-run green.

---

## File Structure

| file | responsibility |
|---|---|
| `src/receipts/persist/models.py` | three new `Receipt` columns |
| `alembic/versions/<new>_revalidation_fields.py` | the migration, on head `f3ae0f86e0e6` |
| `src/receipts/persist/repository.py` | `save_extraction` writes the three, `tax_breakdown` through `redact_pan` |
| `src/receipts/review/serializers.py` | `_export_extraction` reads them; new `revalidate`; `receipt_detail` returns the new keys |
| `src/receipts/validate/context.py` | `REVIEW_RECONSTRUCTIBLE`, and the unsafe set derived as its complement |
| `src/receipts/validate/rules.py` | `Subject`, `Rule.subject`, five `RUN` declarations |
| `tests/test_rule_subjects.py` | **new** — the static scan that binds declaration to code |
| `tests/test_revalidate.py` | **new** — round-trip fidelity and `revalidate` behaviour |
| `frontend/src/api/types.ts` | `current_findings`, `not_rechecked` |
| `frontend/src/review/FindingsPanel.tsx` | two groups |

---

### Task 1: Persist the three fields validation needs

**Files:**
- Modify: `src/receipts/persist/models.py` (the `Receipt` meta columns, near `receipt_is_inconsistent` at :205)
- Create: `alembic/versions/<hash>_revalidation_fields.py`
- Modify: `src/receipts/persist/repository.py` (`save_extraction`'s `fields` dict, :538-571)
- Test: `tests/test_repository.py`, `tests/test_migrations.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Receipt.is_refund: bool`, `Receipt.prices_include_tax: bool | None`, `Receipt.tax_breakdown: Any | None` — read by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repository.py`, in the `save_extraction` section:

```python
def test_save_extraction_persists_the_fields_validation_needs(engine: sa.Engine) -> None:
    """Three fields that rules read and no column carried until 2026-08-24.

    Without them a rehydrated receipt validates DIFFERENTLY from the one that
    was extracted, with no edit involved: R040 reads ``meta.is_refund`` and
    inverts, R020/R024 read ``prices_include_tax`` and silently loosen, R025
    reads ``tax_breakdown`` and silently skips.
    """
    extraction = _extraction()
    extraction.meta.is_refund = True
    extraction.totals.prices_include_tax = True
    extraction.totals.tax_breakdown = [
        TaxBand(label="VATable", base=D("500.00"), rate=D("0.12"), amount=D("60.00"))
    ]
    with Session(engine) as session:
        receipt = save_extraction(
            session, _job(), extraction, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        assert receipt.is_refund is True
        assert receipt.prices_include_tax is True
        assert receipt.tax_breakdown == [
            {"label": "VATable", "base": "500.00", "rate": "0.12", "amount": "60.00"}
        ]


def test_save_extraction_redacts_a_pan_inside_tax_breakdown(engine: sa.Engine) -> None:
    """``tax_breakdown`` is model text in a JSON column, so the blanket pass misses it.

    ``save_extraction``'s redaction pass is ``type(value) is str`` over its
    ``fields`` dict; a list value is skipped whole, and ``TaxBand.label`` is
    model text. This is ``LineItem.modifiers``' hazard one column over, and it
    is invisible to the ``String``-typed-column walk in
    ``test_every_text_column_save_extraction_writes_is_redacted``.
    """
    pan = "4111111111111111"
    extraction = _extraction()
    extraction.totals.tax_breakdown = [TaxBand(label=f"VAT CARD {pan}", amount=D("60.00"))]
    with Session(engine) as session:
        receipt = save_extraction(
            session, _job(), extraction, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        assert pan not in str(receipt.tax_breakdown)
```

`TaxBand` must be added to the `receipts.extract.schema` import block at the top
of `tests/test_repository.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repository.py -k "fields_validation_needs or pan_inside_tax_breakdown" -v`
Expected: FAIL with `AttributeError: 'Receipt' object has no attribute 'is_refund'`.

- [ ] **Step 3: Add the columns**

In `src/receipts/persist/models.py`, immediately after `receipt_is_inconsistent`:

```python
    #: Whether the document is a refund / credit note. **R040 reads it**
    #: ("the total is positive unless the document is a refund"), and until
    #: 2026-08-24 it was a column on nothing -- so a receipt rebuilt from this
    #: table always looked like a sale, and a refund re-validated as an ERROR
    #: its extraction run never produced. Measured; see the design's section 1.
    #:
    #: NOT NULL with a server default, matching ``LineItem.is_template_row``:
    #: both engines refuse ``ADD COLUMN ... NOT NULL`` with no default once the
    #: table holds a row, and ``false`` is exactly what every existing row was
    #: already being rebuilt as, so no stored receipt changes behaviour.
    is_refund: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    #: The document's stated tax convention: ``True`` = the line amounts include
    #: tax, ``False`` = they exclude it, ``NULL`` = the document does not say.
    #: **R020/R024 read it** to choose what the line sum may equal; NULL accepts
    #: either reading, so a lost ``True`` does not fail loudly -- it silently
    #: LOOSENS the arithmetic check. Nullable because NULL is a real value here
    #: and the common one, not a placeholder.
    prices_include_tax: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    #: Per-band tax breakdown as the model emitted it, e.g.
    #: ``[{"label": "VATable", "base": "500.00", "rate": "0.12", "amount": "60.00"}]``.
    #: Amounts are strings so ``Decimal`` survives the round trip (ADR-0001).
    #: **R025 reads it** and skips on an empty list, so a lost breakdown
    #: disables that rule rather than failing it.
    #:
    #: Nullable on purpose, following ``confidence_reasons``: NULL means "not
    #: recorded" (a row written before this column existed), ``[]`` means "the
    #: model read no tax bands". Collapsing the two would claim a reading
    #: nothing made.
    tax_breakdown: Mapped[Any | None] = mapped_column(_jsonb(), nullable=True, default=None)
```

- [ ] **Step 4: Write them in `save_extraction`**

In `src/receipts/persist/repository.py`, inside the `fields: dict[str, Any] = dict(...)`
literal, after `receipt_is_inconsistent=extraction.meta.receipt_is_inconsistent,`:

```python
        is_refund=extraction.meta.is_refund,
        prices_include_tax=extraction.totals.prices_include_tax,
        # §18: wrapped in ``redact_pan`` for the same reason
        # ``LineItem.modifiers`` is -- ``TaxBand.label`` is model text, and the
        # blanket pass below is ``type(value) is str``, which skips a list value
        # whole. ``redact_pan`` recurses into lists and dicts, so one wrap
        # reaches every label. A ``String``-typed-column walk cannot see in here.
        tax_breakdown=redact_pan(
            [band.model_dump(mode="json") for band in extraction.totals.tax_breakdown]
        ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_repository.py -k "fields_validation_needs or pan_inside_tax_breakdown" -v`
Expected: PASS.

- [ ] **Step 6: Write the migration**

Create `alembic/versions/<hash>_revalidation_fields.py` — generate the hash with
`python -c "import uuid; print(uuid.uuid4().hex[:12])"`:

```python
"""fields the review-time re-validation needs

Revision ID: <hash>
Revises: f3ae0f86e0e6
Create Date: 2026-08-24 00:00:00.000000

Three ``receipts`` columns, each read by a validation rule and carried by no
column until now. Without them a receipt rebuilt from this table validates
DIFFERENTLY from the one that was extracted, with no reviewer edit involved:

* ``is_refund`` -- R040 ("the total is positive unless the document is a
  refund"). Measured 2026-08-24: a refund that validated clean at extraction
  produced ``R040/ERROR`` after a round trip, because the rebuild had no column
  to read and assumed a sale. NOT NULL with ``server_default=sa.false()``,
  matching ``line_items.is_template_row``: both engines refuse ``ADD COLUMN ...
  NOT NULL`` with no default once the table holds a row, and ``false`` is what
  every existing row was already rebuilt as, so nothing stored changes meaning.
* ``prices_include_tax`` -- R020/R024. NULL is a real value ("the document does
  not state a convention") and the common one, so the column is nullable and
  needs no default. A lost ``True`` does not fail loudly; it loosens the check.
* ``tax_breakdown`` -- R025. Nullable following ``receipts.confidence_reasons``:
  NULL means "not recorded" (a row written before this column existed), ``[]``
  means "the model read no bands".

Portability (ADR-0004): ``sa.false()``, never ``sa.text("0")`` -- SQLite's
spelling of false frozen into a migration, which Postgres rejects on a BOOLEAN
column. Same edit ``f3ae0f86e0e6`` documents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "<hash>"
down_revision: str | Sequence[str] | None = "f3ae0f86e0e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Add the three ``receipts`` columns the review-time re-validation reads."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_refund", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("prices_include_tax", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("tax_breakdown", _JSON, nullable=True))


def downgrade() -> None:
    """Drop the three columns."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("tax_breakdown")
        batch_op.drop_column("prices_include_tax")
        batch_op.drop_column("is_refund")
```

- [ ] **Step 7: Run the migration gates**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS — in particular `test_migration_schema_matches_orm_metadata`
(ORM and chain agree), `test_the_revision_chain_renders_as_valid_postgres_ddl`
(the `sa.false()` portability rule), and
`test_every_revision_applies_to_a_populated_database` (the NOT NULL default).

- [ ] **Step 8: Run the mutation**

Change `server_default=sa.false()` to `server_default=sa.text("0")` in the
migration only. Run `python -m pytest tests/test_migrations.py -v`.
Expected: `test_the_revision_chain_renders_as_valid_postgres_ddl` FAILS.
Revert with the inverse edit and re-run green. Confirm the mutant compiled.

- [ ] **Step 9: Commit**

```bash
git add src/receipts/persist/models.py src/receipts/persist/repository.py alembic/versions tests/test_repository.py
git commit -m "feat: persist is_refund, prices_include_tax and tax_breakdown"
```

---

### Task 2: Make the round-trip lossless, and pin that it is

**Files:**
- Modify: `src/receipts/review/serializers.py` (`_export_extraction`, :384-462, and its docstring)
- Test: `tests/test_revalidate.py` (**new**)

**Interfaces:**
- Consumes: `Receipt.is_refund`, `Receipt.prices_include_tax`, `Receipt.tax_breakdown` (Task 1).
- Produces: a faithful `_export_extraction`. Task 4 depends on it being faithful.

- [ ] **Step 1: Write the failing test**

Create `tests/test_revalidate.py`:

```python
"""Round-trip fidelity, and the re-validation built on it.

The property under test: **persisting a receipt and rebuilding it must not
change what ``validate()`` says about it.** Re-validating a reviewer's
correction is worthless otherwise -- the reviewer would be shown findings
caused by the database, attributed to their edit.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from eval.golden_set import DEFAULT_LABELS_DIR, load_labels
from receipts.extract.schema import ReceiptExtraction
from receipts.ingest.ingest import ReceiptJob
from receipts.persist.models import Base, ReceiptStatus
from receipts.persist.repository import save_extraction
from receipts.review.serializers import _export_extraction
from receipts.validate.report import ValidationReport
from receipts.validate.validator import validate

GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)


@pytest.fixture()
def engine() -> sa.Engine:
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _round_trip(engine: sa.Engine, extraction: ReceiptExtraction) -> ReceiptExtraction:
    """Persist through the real writer, rebuild through the real reader."""
    rid = uuid.uuid4()
    job = ReceiptJob(
        id=rid,
        image_key=f"receipts/2026/08/{rid}/original.jpg",
        source="upload",
        original_filename="receipt.jpg",
        content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, extraction, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        return _export_extraction(receipt)


def _finding_ids(extraction: ReceiptExtraction) -> list[str]:
    return sorted(f"{f.rule_id}/{f.severity.value}" for f in validate(extraction).findings)


def _refund() -> ReceiptExtraction:
    """r001 as a refund: every printed amount negated, ``is_refund`` set.

    This is the fixture that matters. Measured 2026-08-24, before the columns
    existed: it validated clean at extraction and produced ``R040/ERROR`` after
    a round trip, because ``meta.is_refund`` was a column on nothing and the
    rebuild assumed a sale. No reviewer touched it.
    """
    raw = json.loads((DEFAULT_LABELS_DIR / "r001.json").read_text(encoding="utf-8"))
    r = ReceiptExtraction.model_validate(raw)
    r.meta.is_refund = True
    r.totals.total = D("-1000.00")
    r.totals.subtotal = D("-892.86")
    r.totals.tax = D("-107.14")
    for item in r.line_items:
        if not item.is_template_row:
            item.line_total = D("-1000.00")
            item.unit_price = D("-102.00")
    return r


@pytest.mark.parametrize("case_id", [*sorted(GOLDEN_LABELS), "refund"])
def test_a_round_trip_does_not_change_what_validate_says(engine, case_id) -> None:
    """The standing guard. No edit is involved anywhere in this test."""
    original = _refund() if case_id == "refund" else GOLDEN_LABELS[case_id]
    rebuilt = _round_trip(engine, original)
    assert _finding_ids(rebuilt) == _finding_ids(original), (
        f"{case_id}: the database changed the answer. "
        f"extraction={_finding_ids(original)} rebuilt={_finding_ids(rebuilt)}"
    )


def test_a_round_trip_preserves_the_fields_no_rule_happens_to_read_today(engine) -> None:
    """Asserted on the VALUES, not only on the findings.

    Findings agreeing is a weaker claim than the fields surviving: r002 carries
    ``prices_include_tax=True`` and loses it to ``None`` without changing r002's
    findings at all, because ``None`` merely accepts both conventions. The
    silent loosening is the defect; this is what sees it.
    """
    original = GOLDEN_LABELS["r002"]
    original.totals.tax_breakdown = []
    rebuilt = _round_trip(engine, original)
    assert rebuilt.totals.prices_include_tax == original.totals.prices_include_tax
    assert rebuilt.meta.is_refund == original.meta.is_refund
    assert rebuilt.totals.tax_breakdown == original.totals.tax_breakdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_revalidate.py -v`
Expected: `test_a_round_trip_does_not_change_what_validate_says[refund]` FAILS with
`rebuilt=['R040/error'] extraction=[]`. The three golden cases PASS — that is
the trap this fixture exists to escape, and it is not evidence of anything.

- [ ] **Step 3: Read the columns in `_export_extraction`**

In `src/receipts/review/serializers.py`, add `TaxBand` to the schema imports,
then in the `Totals(...)` block add:

```python
            prices_include_tax=receipt.prices_include_tax,
            tax_breakdown=[
                TaxBand.model_validate(band) for band in (receipt.tax_breakdown or [])
            ],
```

and in the `ExtractionMeta(...)` block add:

```python
            is_refund=receipt.is_refund,
```

`receipt.tax_breakdown or []` folds NULL ("not recorded", a row older than the
column) into the schema default, which is exactly what the rebuild did for every
row before the column existed.

- [ ] **Step 4: Correct the docstring**

`_export_extraction`'s docstring opens with a list of what it cannot rebuild.
Three of its entries are now false, and `meta.is_refund` was missing from it
while being equally absent. Replace the "**Lossy against the full extraction
schema.**" paragraph with:

```
    **Lossy against the full extraction schema.** ``meta.ambiguous_fields``,
    ``meta.unreadable_regions``, ``meta.notes``, and the merchant's
    ``address``/``tax_id``/``phone``/``branch`` are not columns on ``receipts``
    -- they were never persisted past the extraction run that produced them, so
    there is nothing here to rebuild them from. They are left at their schema
    defaults (``[]``/``None``/``False``), never invented.

    **``tax_breakdown``, ``prices_include_tax`` and ``meta.is_refund`` used to
    be on that list and are not any more** (2026-08-24). They became columns
    because *rules read them*: R025, R020/R024 and R040 respectively. While they
    were missing, a receipt rebuilt here validated differently from the one that
    was extracted -- measured, a refund went from clean to ``R040/ERROR`` -- so
    re-validating a reviewer's correction would have blamed the database on the
    reviewer. Nothing else on the list above is read by any rule.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_revalidate.py -v`
Expected: PASS, all four cases.

- [ ] **Step 6: Run the mutations**

One at a time, each reverted by its inverse edit, each confirmed to compile:

1. Remove `is_refund=receipt.is_refund` from `_export_extraction`.
   Expected: `...[refund]` FAILS.
2. Remove `prices_include_tax=receipt.prices_include_tax`.
   Expected: `test_a_round_trip_preserves_the_fields_no_rule_happens_to_read_today` FAILS.
3. Remove the `tax_breakdown=[...]` line.
   Expected: the same test FAILS.

Read *which* assertion failed and with what message each time — a mutation that
reddens a different test than predicted changed more than one thing.

- [ ] **Step 7: Commit**

```bash
git add src/receipts/review/serializers.py tests/test_revalidate.py
git commit -m "fix: the DB round-trip no longer changes what validate() says"
```

---

### Task 3: Declare each rule's subject, and bind the declaration to the code

**Files:**
- Modify: `src/receipts/validate/context.py` (after `ValidationContext`)
- Modify: `src/receipts/validate/rules.py` (`Subject`, `Rule.subject`, five declarations)
- Test: `tests/test_rule_subjects.py` (**new**)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Subject.CONTENT` / `Subject.RUN`, `Rule.subject`, and
  `receipts.validate.context.REVIEW_RECONSTRUCTIBLE: frozenset[str]` plus
  `unreconstructible_context() -> frozenset[str]`. Task 4 filters `RULES` on
  `rule.subject is Subject.CONTENT`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rule_subjects.py`:

```python
"""Every rule's declared subject, checked against what it actually reads.

A rule may be re-run on a corrected receipt only if it can answer from the
persisted receipt alone. Rules that read the extraction RUN -- the raw OCR text,
the triage result, the repeated-run agreement, the JSON parse error -- cannot:
that evidence is not persisted and is gone by review time.

**Declared and then bound, never declared alone.** A hand-kept list of
"review-safe rules" drifts the moment a rule is added, which is the shape
ISSUE-006 names when it says nothing joins the editable set to
``_LINE_ITEM_FIELDS``. The scan below is what makes the declaration a property.

**Static, and therefore over-reporting.** It counts a ``ctx`` read on a branch
that may never execute. A dynamic recording proxy would under-report -- it sees
only the branches a fixture reaches -- and under-reporting means certifying a
rule that then lies to a reviewer. Over-reporting costs coverage and never lies.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap

import pytest

import receipts.validate.rules as rules_module
from receipts.validate.context import REVIEW_RECONSTRUCTIBLE, ValidationContext
from receipts.validate.rules import RULES, Subject

#: ``ctx`` attributes that are methods rather than fields, mapped to the fields
#: they read. Pinned below, so a new method reddens rather than sneaking past.
CTX_METHODS = {"tol": {"config"}}

FIELDS = {f.name for f in dataclasses.fields(ValidationContext)}


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _ctx_reads(fn, _seen: frozenset[str] = frozenset()) -> set[str]:
    """Every ``ValidationContext`` field ``fn`` can read.

    Follows the bare context into module-level helpers. **An unfollowable
    callable raises** rather than returning a partial answer: a helper this
    scan cannot see into is exactly the hole it exists to close, and a silent
    pass there would certify a rule nobody checked.
    """
    if fn.__qualname__ in _seen:
        return set()
    _seen = _seen | {fn.__qualname__}

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    ctx_name = list(inspect.signature(fn).parameters)[-1]
    reads: set[str] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == ctx_name
        ):
            if node.attr in FIELDS:
                reads.add(node.attr)
            elif node.attr in CTX_METHODS:
                reads |= CTX_METHODS[node.attr]
            else:
                raise AssertionError(
                    f"{fn.__qualname__} reads ctx.{node.attr}, which is neither a "
                    f"ValidationContext field nor a method in CTX_METHODS. Teach "
                    f"this scan what it reads, or the subject below is a guess."
                )
        if isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id == ctx_name:
                    helper = getattr(rules_module, _callee(node) or "", None)
                    if helper is None or not inspect.isfunction(helper):
                        raise AssertionError(
                            f"{fn.__qualname__} hands the bare context to "
                            f"{_callee(node)!r}, which this scan cannot follow. An "
                            f"unfollowable helper is how a RUN rule gets certified "
                            f"as CONTENT."
                        )
                    reads |= _ctx_reads(helper, _seen)
    return reads


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_a_content_rule_reads_no_unreconstructible_context(rule) -> None:
    """The binding. A CONTENT rule must answer from the persisted receipt alone."""
    if rule.subject is not Subject.CONTENT:
        return
    unsafe = (FIELDS - REVIEW_RECONSTRUCTIBLE) & (
        _ctx_reads(type(rule).applies) | _ctx_reads(type(rule).check)
    )
    assert not unsafe, (
        f"{rule.id} is declared CONTENT but reads {sorted(unsafe)}, which a review "
        f"route cannot reconstruct. Declare it Subject.RUN, or persist what it reads."
    )


def test_the_unsafe_set_is_the_complement_and_not_a_literal() -> None:
    """A context field added later must be unsafe by DEFAULT.

    Taking the complement is the whole mechanism: a field that nobody thought
    about is unreconstructible until somebody deliberately says otherwise. A
    written-out unsafe list would silently admit it instead.
    """
    from receipts.validate.context import unreconstructible_context

    assert unreconstructible_context() == FIELDS - REVIEW_RECONSTRUCTIBLE
    assert REVIEW_RECONSTRUCTIBLE <= FIELDS, (
        "the allow-list names a field ValidationContext does not have: "
        f"{sorted(REVIEW_RECONSTRUCTIBLE - FIELDS)}"
    )


def test_every_ctx_method_a_rule_calls_is_one_this_scan_knows() -> None:
    """``CTX_METHODS`` is small and must stay honest.

    ``ctx.tol(...)`` reads ``config`` and nothing else. A second method added to
    ValidationContext and called from a rule reddens the scan itself (it raises)
    rather than being counted as reading nothing.
    """
    method_names = {
        name
        for name, member in inspect.getmembers(ValidationContext, inspect.isfunction)
        if not name.startswith("_")
    }
    assert method_names == set(CTX_METHODS), (
        f"ValidationContext's public methods are {sorted(method_names)} but this "
        f"scan knows {sorted(CTX_METHODS)}. Map the new one to the fields it reads."
    )
    tol_src = textwrap.dedent(inspect.getsource(ValidationContext.tol))
    read = {
        node.attr
        for node in ast.walk(ast.parse(tol_src))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert read == CTX_METHODS["tol"], f"ctx.tol reads {sorted(read)}, not config alone"


def test_the_run_rules_are_exactly_those_reading_unreconstructible_context() -> None:
    """Stated both ways so neither side can drift alone.

    R013 is here and its subject is genuinely content -- "at least one line item
    was extracted". It reads ``ctx.triage`` only to suppress itself when triage
    expected zero items, and without triage it would fire on a receipt that
    legitimately has none. Marking it RUN loses a check; marking it CONTENT
    ships a rule that fires wrongly. The loss is deliberate and recorded here.
    """
    declared = {rule.id for rule in RULES if rule.subject is Subject.RUN}
    assert declared == {"R001", "R013", "R060", "R061", "R070"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rule_subjects.py -v`
Expected: FAIL at import with `ImportError: cannot import name 'REVIEW_RECONSTRUCTIBLE'`.

- [ ] **Step 3: Add the allow-list and its complement**

In `src/receipts/validate/context.py`, after the `ValidationContext` class:

```python
#: The context a review route can reconstruct after extraction has finished.
#:
#: ``config`` and ``today`` are process-local. The two ``expected_buyer_*``
#: fields come from ``Settings``, which a review route already holds. Everything
#: else on :class:`ValidationContext` is evidence produced by the extraction RUN
#: -- the raw OCR text, the triage result, the repeated-run agreement, the JSON
#: parse error -- and none of it is persisted, so it is gone by review time.
REVIEW_RECONSTRUCTIBLE: frozenset[str] = frozenset(
    {"config", "today", "expected_buyer_name", "expected_buyer_tax_id"}
)


def unreconstructible_context() -> frozenset[str]:
    """The context fields a review route CANNOT rebuild.

    The **complement** of :data:`REVIEW_RECONSTRUCTIBLE`, computed from the
    dataclass rather than written out, so a field added to
    :class:`ValidationContext` is unreconstructible by default. A written-out
    list would silently admit a new field to the safe set -- the failure this
    function exists to make impossible.
    """
    return frozenset(f.name for f in fields(ValidationContext)) - REVIEW_RECONSTRUCTIBLE
```

`fields` is already imported from `dataclasses` in this module (it is used for
`field(default_factory=...)`); confirm the import line reads
`from dataclasses import dataclass, field, fields` and extend it if not.

- [ ] **Step 4: Add `Subject` and declare it**

In `src/receipts/validate/rules.py`, extend the stdlib imports with
`from enum import Enum` (the module imports `ABC`, `date`, `Decimal` and
`ClassVar` but **not** `Enum` today), then above the registry:

```python
class Subject(str, Enum):
    """What a rule's finding is ABOUT, which decides whether it can be re-run.

    ``(str, Enum)`` matching :class:`~receipts.validate.report.Severity`, so it
    serialises as its token if it is ever persisted.
    """

    #: Answerable from the persisted receipt alone, so it can be re-run against
    #: a reviewer's corrections.
    CONTENT = "content"
    #: The evidence is the extraction run -- the OCR text, the triage estimate,
    #: the agreement between repeated runs, the parse error -- and none of it is
    #: persisted. Re-running it after a correction would not be a stricter
    #: check; it would be a different and quieter one.
    RUN = "run"
```

On `Rule`, beside `severity`:

```python
    #: Defaults to CONTENT: a new rule is re-runnable unless it says otherwise,
    #: and ``tests/test_rule_subjects.py`` reddens if it reads run-only context
    #: without declaring RUN. The default is the safe one BECAUSE it is bound --
    #: an unbound default this way round would be a silent lie.
    subject: ClassVar[Subject] = Subject.CONTENT
```

Then add `subject = Subject.RUN` to exactly five rules, each with the reason:

```python
# R001 SchemaParses:      reads ctx.parse_error -- the run's own JSON failure.
# R013 LineItemsPresent:  reads ctx.triage to suppress itself; without it, fires
#                         on a receipt that legitimately has no items. Content by
#                         subject, RUN by evidence -- the deliberate loss.
# R060 TotalAppearsInOcr: reads ctx.ocr_text -- the original scan.
# R061 MerchantAppearsInOcr: reads ctx.ocr_text.
# R070 ConsistencyAgreement: reads ctx.consistency -- agreement across runs.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_rule_subjects.py -v`
Expected: PASS — 31 parametrised cases plus four property tests.

- [ ] **Step 6: Run the mutations**

One at a time, inverse-edit revert, confirm each compiles:

1. Set `subject = Subject.CONTENT` on R060.
   Expected: `test_a_content_rule_reads_no_unreconstructible_context[R060]` FAILS
   naming `['ocr_text']`, **and** `test_the_run_rules_are_exactly_...` FAILS.
2. Change `unreconstructible_context()` to return a literal
   `frozenset({"triage", "ocr_text", "merchant", "consistency", "parse_error"})`.
   Expected: `test_the_unsafe_set_is_the_complement_and_not_a_literal` still
   passes — the sets are equal today. **Then add a field** `probe: str | None = None`
   to `ValidationContext` and re-run: the literal version FAILS, the computed
   version PASSES. Revert both edits. This two-step is the point: the mutation
   that matters is the one that only bites when the class grows.
3. In `_ctx_reads`, replace the `AssertionError` for an unfollowable callable
   with `continue`, and change `R014.applies` to call a new local helper.
   Expected: without the raise, R014 is certified CONTENT reading nothing.
   Revert both.

- [ ] **Step 7: Commit**

```bash
git add src/receipts/validate/context.py src/receipts/validate/rules.py tests/test_rule_subjects.py
git commit -m "feat: rules declare whether their subject is content or the extraction run"
```

---

### Task 4: Re-validate on read, and return it beside the history

**Files:**
- Modify: `src/receipts/review/serializers.py` (new `revalidate`; `receipt_detail` at :196-318)
- Modify: `src/receipts/review/api.py` (:362, :678 — pass the expected buyer)
- Test: `tests/test_revalidate.py`, `tests/test_api_read.py`, `tests/test_api_write.py`

**Interfaces:**
- Consumes: `_export_extraction` (Task 2), `Subject` / `Rule.subject` (Task 3).
- Produces:
  - `revalidate(receipt: Receipt, *, expected_buyer_name: str | None = None, expected_buyer_tax_id: str | None = None) -> ValidationReport`
  - `not_rechecked() -> list[str]`
  - `receipt_detail(receipt, findings, *, expected_buyer_name=None, expected_buyer_tax_id=None) -> dict[str, Any]`, whose payload gains `current_findings` and `not_rechecked`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_revalidate.py`:

```python
def test_revalidate_runs_the_content_rules_on_the_stored_receipt(engine) -> None:
    """A defect introduced after extraction is found, with no re-extraction."""
    from receipts.review.serializers import revalidate

    original = GOLDEN_LABELS["r001"]
    rid = uuid.uuid4()
    job = ReceiptJob(
        id=rid, image_key=f"receipts/2026/08/{rid}/original.jpg", source="upload",
        original_filename="receipt.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, original, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        assert revalidate(receipt).findings == []

        # What a reviewer does with the Template checkbox: flag the only row
        # that was actually bought. R026 exists for exactly this.
        for item in receipt.line_items:
            item.is_template_row = True
        session.commit()
        assert revalidate(receipt).fired("R026")


def test_revalidate_never_runs_a_rule_whose_subject_is_the_extraction_run(engine) -> None:
    """The RUN rules must be absent, not merely silent.

    Silence is what they would produce anyway with no context -- so asserting
    "no R060 finding" proves nothing. This asserts on the rule set that RAN.
    """
    from receipts.review.serializers import _CONTENT_RULES, not_rechecked

    assert {r.id for r in _CONTENT_RULES} & {"R001", "R013", "R060", "R061", "R070"} == set()
    assert not_rechecked() == ["R001", "R013", "R060", "R061", "R070"]
```

And to `tests/test_api_read.py`. **`client` there is the *unauthenticated*
fixture** -- `reviewer_client` plus the `receipt_id` fixture is what every other
detail test in that file uses:

```python
def test_the_detail_returns_current_findings_beside_the_extraction_run_ones(
    reviewer_client, receipt_id
):
    """Two lists, never merged. The whole point is that they mean different things.

    ``findings`` is what the extraction run recorded and is history.
    ``current_findings`` is recomputed from the receipt as it stands now.
    Merging them would destroy the distinction and re-create the defect.
    """
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    assert "current_findings" in body
    assert "not_rechecked" in body
    assert body["not_rechecked"] == ["R001", "R013", "R060", "R061", "R070"]
    assert isinstance(body["findings"], list)
```

*(`reviewer_client` and `receipt_id` are the pair
`test_money_is_serialized_as_a_string` and
`test_detail_returns_findings_and_the_reasons_that_made_the_score` already use.
Do not introduce a second seeding path.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_revalidate.py tests/test_api_read.py -k "revalidate or current_findings" -v`
Expected: FAIL with `ImportError: cannot import name 'revalidate'`.

- [ ] **Step 3: Write `revalidate` and `not_rechecked`**

`src/receipts/review/serializers.py` today imports only
`from ..validate.report import Severity` out of the validate package. Add:

```python
import logging

from ..validate.context import ValidationContext
from ..validate.report import Finding, Severity, ValidationReport
from ..validate.rules import RULES, Subject

log = logging.getLogger(__name__)
```

and extend `__all__` with `"not_rechecked"` and `"revalidate"`. Then, after
`_export_extraction`:

```python
#: The rules that can answer from a persisted receipt alone. Filtered from the
#: registry rather than listed, so a rule added later is included or excluded by
#: its own declaration and never by this module's memory of it.
_CONTENT_RULES = [rule for rule in RULES if rule.subject is Subject.CONTENT]


def not_rechecked() -> list[str]:
    """The rule ids a reviewer's screen must NOT claim were checked.

    Derived from the registry, never written out. Without this list an empty
    ``current_findings`` reads as "everything was checked and is fine", which is
    the confidently-wrong-answer shape this whole change exists to remove.
    """
    return sorted(rule.id for rule in RULES if rule.subject is Subject.RUN)


def revalidate(
    receipt: Receipt,
    *,
    expected_buyer_name: str | None = None,
    expected_buyer_tax_id: str | None = None,
) -> ValidationReport:
    """Run the content rules against the receipt AS IT NOW STANDS.

    Pure, and deliberately writes nothing. A stored copy would be stale the
    moment the next correction landed -- the defect this closes, re-created one
    table over -- whereas a report computed on read cannot be out of date.

    The context carries only what a review route can honestly rebuild
    (:data:`~receipts.validate.context.REVIEW_RECONSTRUCTIBLE`). The expected
    buyer is passed IN rather than read from ``Settings`` here, keeping
    validation reproducible from its inputs, exactly as ``pipeline`` does it.
    **Both blank makes R014/R015 inert**, so a caller that omits them silently
    loses two content rules; ``review/api.py`` supplies them from
    ``app.state.settings``.

    ``validate()`` never raises -- a rule that throws becomes an INFO
    ``{id}.crashed`` finding -- so this cannot break the detail response.
    :func:`_export_extraction` is not wrapped: if a receipt written by
    ``save_extraction`` cannot be rebuilt, that is a data-integrity defect and a
    loud failure is the correct signal. Swallowing it into an empty report would
    manufacture the exact silent wrong answer this function exists to remove.
    """
    ctx = ValidationContext(
        expected_buyer_name=expected_buyer_name,
        expected_buyer_tax_id=expected_buyer_tax_id,
    )
    extraction = _export_extraction(receipt)
    findings: list[Finding] = []
    for rule in _CONTENT_RULES:
        if rule.applies(extraction, ctx):
            findings.extend(rule.check(extraction, ctx))
    return ValidationReport(findings=findings)
```

**Note on the loop.** `validate()` runs the whole registry and cannot take a
subset, so the rule loop is repeated here rather than filtered afterwards —
filtering *after* would let a RUN rule read a context it should never have been
handed. It does lose `validate()`'s crash containment; add it back:

```python
        try:
            if not rule.applies(extraction, ctx):
                continue
            findings.extend(rule.check(extraction, ctx))
        except Exception:  # a broken rule must not take down the review screen
            log.exception("rule %s crashed during re-validation", rule.id)
```

- [ ] **Step 4: Return them from `receipt_detail`**

Change the signature and the payload tail:

```python
def receipt_detail(
    receipt: Receipt,
    findings: list[ValidationFinding],
    *,
    expected_buyer_name: str | None = None,
    expected_buyer_tax_id: str | None = None,
) -> dict[str, Any]:
```

and in the returned dict, after `"findings": [...]`:

```python
        # Beside `findings`, never merged into it. `findings` is what the
        # extraction run recorded and is history; these are recomputed from the
        # row as it now stands. One list holding both would destroy exactly the
        # distinction that made this defect visible.
        "current_findings": [
            _report_finding(finding)
            for finding in revalidate(
                receipt,
                expected_buyer_name=expected_buyer_name,
                expected_buyer_tax_id=expected_buyer_tax_id,
            ).findings
        ],
        "not_rechecked": not_rechecked(),
```

`_finding` takes a `ValidationFinding` ORM row; a fresh report yields
`validate.report.Finding` objects. Add the sibling:

```python
def _report_finding(finding: Finding) -> dict[str, Any]:
    """One in-memory finding in the same shape ``_finding`` gives an ORM row.

    Same keys deliberately, so the client's ``Finding`` type covers both lists.
    ``resolved_by_repair`` is always ``False`` here: repair is an extraction-run
    concept and a freshly computed finding has not been through one.
    """
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "message": finding.message,
        "context": finding.context,
        "resolved_by_repair": False,
    }
```

- [ ] **Step 5: Pass the expected buyer at both call sites**

In `src/receipts/review/api.py`, at :362 and :678:

```python
            settings: Settings = request.app.state.settings
            return receipt_detail(
                receipt,
                findings,
                expected_buyer_name=settings.expected_buyer_name,
                expected_buyer_tax_id=settings.expected_buyer_tax_id,
            )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_revalidate.py tests/test_api_read.py tests/test_api_write.py -v`
Expected: PASS.

- [ ] **Step 7: Run the mutations**

1. Change `_CONTENT_RULES` to `list(RULES)`.
   Expected: `test_revalidate_never_runs_a_rule_whose_subject_is_the_extraction_run` FAILS.
2. Make `not_rechecked()` return the hard-coded list
   `["R001", "R013", "R060", "R061", "R070"]`, then flip R060 to `CONTENT`.
   Expected: the derived version FAILS (the list shrinks); the hard-coded one
   passes while lying. Revert both.
3. Drop `expected_buyer_name=...` from `api.py:362`.
   Expected: add a test asserting an R014 finding on a receipt with no buyer and
   a configured expected buyer; it FAILS. If no such fixture exists, write it —
   without it, this silent loss has no guard.

- [ ] **Step 8: Commit**

```bash
git add src/receipts/review/serializers.py src/receipts/review/api.py tests/
git commit -m "feat: the detail response re-checks the receipt as it now stands"
```

---

### Task 5: Show both, and say what was not checked

**Files:**
- Modify: `frontend/src/api/types.ts` (`ReceiptDetail`, :133-141)
- Modify: `frontend/src/review/FindingsPanel.tsx`
- Modify: `frontend/src/review/FindingsPanel.module.css`
- Modify: `frontend/src/review/ReviewScreen.tsx:565`
- Test: `frontend/src/review/FindingsPanel.test.tsx` (**new** if absent), `review-screen.test.tsx`

**Interfaces:**
- Consumes: the payload from Task 4.
- Produces: `FindingsPanelProps { findings, currentFindings, notRechecked }`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { FindingsPanel } from './FindingsPanel'

const finding = (rule_id: string) => ({
  rule_id, severity: 'error', message: `${rule_id} message`,
  context: null, resolved_by_repair: false,
})

test('a freshly computed finding is not presented as extraction history', () => {
  render(
    <FindingsPanel
      findings={[finding('R022')]}
      currentFindings={[finding('R026')]}
      notRechecked={['R001', 'R060']}
    />,
  )
  // Both are shown, and they are in different groups.
  const current = screen.getByRole('region', { name: /checked now/i })
  const history = screen.getByRole('region', { name: /extraction/i })
  expect(current).toHaveTextContent('R026')
  expect(current).not.toHaveTextContent('R022')
  expect(history).toHaveTextContent('R022')
  expect(history).not.toHaveTextContent('R026')
})

test('an empty current list says what was NOT checked rather than "all clear"', () => {
  render(
    <FindingsPanel findings={[]} currentFindings={[]} notRechecked={['R001', 'R060']} />,
  )
  const current = screen.getByRole('region', { name: /checked now/i })
  // The count is rendered, so a reader cannot mistake silence for coverage.
  expect(current).toHaveTextContent('2')
  expect(current).toHaveTextContent(/not re-checked|original scan/i)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/review/FindingsPanel.test.tsx`
Expected: FAIL — `FindingsPanel` takes only `findings`.

- [ ] **Step 3: Extend the client type**

In `frontend/src/api/types.ts`, in `ReceiptDetail` after `findings: Finding[]`:

```ts
  /** Recomputed from the receipt as it now stands, on every read. Same shape as
   *  `findings` and deliberately a SEPARATE list: `findings` is the extraction
   *  run's record and is history, these are current. */
  current_findings: Finding[]
  /** Rule ids that could not be re-checked, because their evidence is the
   *  extraction run (the OCR text, the triage estimate, agreement across
   *  repeated runs) and is not persisted. Rendered, not swallowed: an empty
   *  `current_findings` with this hidden reads as "all checked and fine". */
  not_rechecked: string[]
```

- [ ] **Step 4: Split the panel**

`FindingsPanel` takes the two new props and renders two `<section>`s, each with
an accessible name (`aria-labelledby` on its heading, which is what
`getByRole('region', {name})` matches). Extract the existing `<li>` body into a
local `FindingList({ findings })` so both groups render identically — the list
markup, the `<details>` disclosure and the severity classes are unchanged.

The first group is headed **"Checked now"**. The second keeps the existing
heading "What the machine found at extraction time" **and keeps the existing
note** — *"Not re-checked when you edit -- this is the receipt as it was
extracted"* — which stays true of that group and only that group. Move it, do
not delete it: that note is the honest label that made this defect findable.

Under the first group, when `notRechecked.length > 0`:

```tsx
      <p className={styles.note}>
        {notRechecked.length} rule{notRechecked.length === 1 ? '' : 's'} can only
        be checked against the original scan and {notRechecked.length === 1 ? 'is' : 'are'}{' '}
        not re-run here: {notRechecked.join(', ')}.
      </p>
```

Update the module docstring: its current text says these findings are "history,
not current state", which stops being true of the first group.

- [ ] **Step 5: Pass them from `ReviewScreen`**

`frontend/src/review/ReviewScreen.tsx:565`:

```tsx
      <FindingsPanel
        findings={receipt.findings}
        currentFindings={receipt.current_findings}
        notRechecked={receipt.not_rechecked}
      />
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/review && npm run typecheck`
Expected: PASS. Fix any `ReceiptDetail` fixture in existing tests that now lacks
the two required keys — **add the keys to the fixtures**, do not make the fields
optional. Optional fields would let a route that forgets them render a panel
claiming everything was checked.

- [ ] **Step 7: Run the mutations**

1. Render `currentFindings` and `findings` into one list.
   Expected: the first panel test FAILS on `not.toHaveTextContent`.
2. Return `null` instead of the `notRechecked` paragraph.
   Expected: the second panel test FAILS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat: the review screen separates what was just checked from history"
```

---

### Task 6: Close the issue, end to end

**Files:**
- Test: `tests/test_api_write.py`
- Modify: `docs/KNOWN_ISSUES.md`, `RECEIPT_SYSTEM_SPEC.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing further.

- [ ] **Step 1: Write the acceptance test**

In `tests/test_api_write.py`:

**The `receipt_id` fixture in that file seeds NO line items**, so it cannot be
used here -- R026's `applies()` requires `bool(r.line_items)` and would skip.
Seed locally, in the shape
`test_the_rebuilt_extraction_carries_the_buyer_and_the_template_flag` already
uses (one template row plus one purchase, at :1240). Like that test, this needs
`session_factory` only -- `storage` matters for the image route, and neither
`GET /receipts/{id}` nor `PATCH` reads the blob:

```python
def test_a_reviewer_who_empties_the_purchase_set_is_told(reviewer_client, session_factory):
    """ISSUE-006's headline, closed through the API a reviewer actually uses.

    Flagging the only purchased row takes the line-item arithmetic offline:
    ``sum_line_nets`` returns None, R020 and R024 both skip, and before R026 the
    receipt produced zero findings at any severity while its row silently left
    the export. R026 catches it, and this asserts the REVIEWER is the one told --
    which needs the PATCH response to re-check, not merely the rule to exist.
    """
    rid = uuid.uuid4()
    with session_factory() as session:
        session.add(
            Receipt(
                id=rid,
                status=ReceiptStatus.NEEDS_REVIEW,
                confidence=Decimal("0.700"),
                merchant_name_raw="FUEL CO",
                txn_date=date(2026, 7, 1),
                currency="PHP",
                subtotal=Decimal("2000.00"),
                total=Decimal("2000.00"),
                image_key=make_image_key(rid, "original"),
                image_phash="",
                line_items=[
                    LineItem(position=0, description_raw="MaxiPower", is_template_row=True),
                    LineItem(
                        position=1,
                        description_raw="DieselPlus",
                        line_total=Decimal("2000.00"),
                    ),
                ],
            )
        )
        session.commit()

    detail = reviewer_client.get(f"/receipts/{rid}").json()
    assert detail["current_findings"] != [], (
        "the pre-PATCH assertion below is only meaningful if this key is "
        "populated at all -- an absent or always-empty key makes it vacuous"
    )
    assert "R026" not in [f["rule_id"] for f in detail["current_findings"]]

    response = reviewer_client.patch(
        f"/receipts/{rid}", json={"line_items[1].is_template_row": "true"}
    )
    assert response.status_code == 200
    body = response.json()

    assert "R026" in [f["rule_id"] for f in body["current_findings"]]
    # And the extraction run's record is untouched by the reviewer's edit.
    assert body["findings"] == detail["findings"]
```

**On that first assertion.** A seeded row with no `validation_findings` and a
clean shape yields an empty `current_findings`, which would make
`"R026" not in []` true for the wrong reason. Seed the receipt so at least one
content rule fires (the shape above has no `receipt_number` and no `tax`, so
R022 or a presence rule will) -- or, if it genuinely validates clean, replace
the guard with an explicit `assert "current_findings" in detail`. Do not leave
a vacuous assertion in place.

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m pytest tests/test_api_write.py -k empties_the_purchase_set -v`
It should FAIL only if something above is incomplete. If it passes on the first
run, check that the pre-PATCH assertion is real — a `current_findings` key that
is absent rather than empty would make the first assertion vacuously true.

- [ ] **Step 3: Run every gate**

Run: `python scripts/verify.py`
Expected: all five PASS.

- [ ] **Step 4: Close the issue**

In `docs/KNOWN_ISSUES.md`, change ISSUE-033's status to
`**RESOLVED 2026-08-24** at <sha>` and add a "Resolution" section recording:
the three columns and why each was needed; the measured refund case that
reframed the fix; that R013 was lost deliberately; and that §8's deferred scope
(the export gate, `/metrics`, re-routing, confidence) is **still open** and must
not read as closed. Follow ADR-0032: delete the "How to resume" steps rather
than keeping them with a caveat.

In `RECEIPT_SYSTEM_SPEC.md`, add the three columns to the §6 `receipts` table
and note the rule `subject` in §10.3.

- [ ] **Step 5: Commit**

```bash
git add docs/KNOWN_ISSUES.md RECEIPT_SYSTEM_SPEC.md tests/test_api_write.py
git commit -m "docs: ISSUE-033 resolved -- a correction is re-checked and says what was not"
```

---

## Self-review notes

- **Spec coverage.** §3 → Task 3. §4 → Task 1. §5 → Tasks 2 and 4. §6 → Task 5.
  §7 → Task 4 step 3's docstring and the deliberate absence of a `try` around
  `_export_extraction`. §8 → Task 6 step 4. §9's seven pins map to Tasks 1-6.
- **The `revalidate` loop duplicates `validator.validate`.** That is deliberate
  and called out in Task 4: `validate()` takes no rule subset, and filtering
  after the fact would hand a RUN rule a context it must never see. If the
  duplication grows, the right fix is a `rules=` parameter on `validate()` —
  not a filter at the call site.
- **`not_rechecked` is asserted as an exact list in three places** (Tasks 3, 4
  and the API test). That is intentional over-specification: this list is the
  only thing standing between a reviewer and reading silence as coverage, so it
  should be hard to change by accident.
