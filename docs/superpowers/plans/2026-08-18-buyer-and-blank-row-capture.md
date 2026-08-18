# Buyer / Sold-To Capture and Blank-Row Transcription — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the receipt's buyer (Sold To), validate that a receipt was issued to the configured operator, and transcribe blank pre-printed rows without letting them into the arithmetic.

**Architecture:** A `Buyer` model parallel to `Merchant` on `ReceiptExtraction`, persisted as two `receipts` columns; two validation rules (`R014` presence, `R015` mismatch) whose severity splits on evidence strength; and an `is_template_row` flag on `LineItem` that every arithmetic and line-item-quality rule skips.

**Tech Stack:** Python 3.11/3.13, Pydantic v2, SQLAlchemy 2.0 + Alembic, pytest, React 19 + TypeScript (frontend), openpyxl (export).

**Spec:** `docs/superpowers/specs/2026-08-18-buyer-sold-to-capture-design.md`

## Global Constraints

- **Money is `Decimal`, never `float`** (ADR-0001, §18). Buyer fields are text; this constraint still governs any rule touching totals.
- **`null` over confident-wrong.** A field printed-but-blank is `None`, not `""`.
- **Stable rule IDs.** `R014` and `R015` are new; no existing ID changes meaning.
- **Nothing silently dropped** — the ruling this plan implements.
- **Explicit `Session` first, flush, never commit; `ValueError` at the boundary** (ADR-0006).
- **Alembic head is `a1c4d2f80b31`.** The new revision's `down_revision` is that string. Verified 2026-08-18: nothing else names it as a parent.
- **`tests/test_migrations.py` is a drift guard** — it runs `compare_metadata(context, Base.metadata)` and asserts no pending autogenerate diffs. **Adding an ORM column without a migration turns it red.** That is this plan's free RED proof, used in Task 2.
- **`_RECEIPT_FIELDS` and `_LINE_ITEM_FIELDS` in `persist/repository.py` are explicitly CLOSED** — its comment says "an unlisted path is a `ValueError`, never a silent no-op". A new field is not correctable by a reviewer until it is registered there.
- **Run the suite as bare `python -m pytest`.** `pyproject.toml` sets `addopts = "-q"`, so `-q` prints no pass count.
- **Stage by explicit path. Never `git add -A`.**

---

### Task 1: The schema — `Buyer`, and the template-row flag

**Files:**
- Modify: `src/receipts/extract/schema.py`
- Create: `tests/test_extract_schema.py` — **verified 2026-08-18 that no schema test module exists**; the nearest homes are `tests/test_models.py` (ORM) and `tests/test_extractor.py` (the extract path), and neither is about the Pydantic shapes.

**Interfaces:**
- Consumes: nothing.
- Produces: `Buyer(name: str | None, tax_id: str | None)`; `ReceiptExtraction.buyer: Buyer`; `LineItem.is_template_row: bool`.

- [ ] **Step 1: Write the failing tests**

```python
from receipts.extract.schema import Buyer, LineItem, ReceiptExtraction


def test_a_new_extraction_has_an_empty_buyer_rather_than_no_buyer() -> None:
    """The buyer is always present as a structure, even when unread.

    A missing `buyer` attribute and a `Buyer` with null fields are different
    states; downstream rules distinguish 'not read' from 'read and empty'.
    """
    extraction = ReceiptExtraction()
    assert extraction.buyer.name is None
    assert extraction.buyer.tax_id is None


def test_a_line_item_is_not_a_template_row_unless_it_says_so() -> None:
    assert LineItem().is_template_row is False


def test_a_template_row_round_trips_through_the_model() -> None:
    item = LineItem(description_raw="MaxiPower", is_template_row=True)
    assert LineItem.model_validate(item.model_dump()).is_template_row is True


def test_buyer_survives_a_round_trip() -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id=None))
    assert ReceiptExtraction.model_validate(extraction.model_dump()).buyer.name == "IDEAL SOURCE"
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

Run: `python -m pytest tests/test_extract_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'Buyer'`. **Not** an attribute error on `is_template_row`; if you see only that, the `Buyer` import silently resolved and something is wrong.

- [ ] **Step 3: Add the model and the field**

In `src/receipts/extract/schema.py`, directly after the `Merchant` class:

```python
class Buyer(BaseModel):
    """Who the receipt was issued TO -- the 'Sold To' / 'Registered Name' block.

    Distinct from :class:`Merchant`, which is who issued it, and from the
    printer's details in the footer. All three carry a TIN on a BIR sales
    invoice and they are three different numbers.

    No ``address``: the forms print a Business Address line for the buyer and
    it is blank on every receipt in the golden set, so the column would be
    empty and the match surface wider for no gain. Add it when a receipt
    carries one.
    """

    name: str | None = None
    tax_id: str | None = None
```

On `LineItem`, after `bbox`:

```python
    is_template_row: bool = Field(
        default=False,
        description=(
            "A pre-printed product row left blank on the form -- transcribed so "
            "nothing on the receipt is lost, but NOT a purchase. Every "
            "arithmetic and line-item-quality rule skips these. Set it for a row "
            "that is blank ON THE PAPER, never for a filled row the model could "
            "not read: that is meta.ambiguous_fields."
        ),
    )
```

On `ReceiptExtraction`, after `merchant`:

```python
    buyer: Buyer = Field(default_factory=Buyer)
```

- [ ] **Step 4: Run the tests and the suite**

Run: `python -m pytest tests/test_extract_schema.py -v` → PASS
Run: `python -m pytest` → **expect failures in eval scoring tests.** New schema paths change `flatten` output. Record which tests fail and their names; Task 7 fixes them by labelling. If anything *outside* eval/golden scoring fails, STOP and report.

- [ ] **Step 5: Commit**

```bash
git add src/receipts/extract/schema.py tests/test_extract_schema.py
git commit -m "feat(schema): a Buyer model, and a flag for blank pre-printed rows"
```

---

### Task 2: Persistence — two columns, one flag, one migration

**Files:**
- Modify: `src/receipts/persist/models.py`
- Create: `alembic/versions/<generated>_buyer_and_template_rows.py`
- Test: `tests/test_migrations.py` (existing — it is the guard, not a file you edit)

**Interfaces:**
- Consumes: Task 1's `Buyer`, `LineItem.is_template_row`.
- Produces: `Receipt.buyer_name_raw: str | None`, `Receipt.buyer_tax_id: str | None`, `LineItem.is_template_row: bool`.

- [ ] **Step 1: Add the ORM columns FIRST, so the drift guard goes red**

In `src/receipts/persist/models.py`, on the `Receipt` model beside `merchant_name_raw`:

```python
    buyer_name_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    buyer_tax_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
```

On the `LineItem` model, after `line_confidence`:

```python
    is_template_row: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
```

**Both `receipts` columns are nullable and the flag has a server default.** A NOT NULL buyer would turn an ordinary receipt — every one in the golden set has a blank buyer TIN — into a persist-stage failure. The `server_default` is what lets the migration add a NOT NULL column to a table that already has rows.

- [ ] **Step 2: Run the drift guard and watch it fail**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: FAIL on the no-pending-diffs test, naming `buyer_name_raw`, `buyer_tax_id` and `is_template_row` as columns the ORM has and the migration does not. **This is the RED proof for the migration.** If it passes, the columns did not land where you think — check you edited `Receipt` and not `Merchant`, which also has a `tax_id`.

- [ ] **Step 3: Generate the migration**

```bash
python -m alembic revision --autogenerate -m "buyer and template rows"
```

Open the generated file. Confirm:
- `down_revision = "a1c4d2f80b31"`
- three `op.add_column` calls, nothing else
- **delete any `op.drop_*` autogenerate invented.** Autogenerate compares the whole schema; anything it wants to drop is drift it misread, not your change.

- [ ] **Step 4: Run the drift guard again**

Run: `python -m pytest tests/test_migrations.py -v` → PASS
Run: `python -m pytest` → same eval failures as Task 1, no new ones.

- [ ] **Step 5: Commit**

```bash
git add src/receipts/persist/models.py alembic/versions/
git commit -m "feat(db): persist the buyer, and mark template rows"
```

---

### Task 3: The write path, and making the buyer correctable

**Files:**
- Modify: `src/receipts/persist/repository.py`
- Test: `tests/test_repository.py` (exists — verified 2026-08-18)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `save_extraction` persisting buyer + flag; `"buyer.name"` and `"buyer.tax_id"` accepted by `apply_corrections`.

- [ ] **Step 1: Write the failing tests**

```python
def test_save_extraction_persists_the_buyer(session, job) -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id=None))
    receipt = save_extraction(
        session, job, extraction, ValidationReport(), Decimal("0"),
        ReceiptStatus.NEEDS_REVIEW,
    )
    session.flush()
    assert receipt.buyer_name_raw == "IDEAL SOURCE"
    assert receipt.buyer_tax_id is None


def test_a_reviewer_can_correct_the_buyer_name(session, stored_receipt) -> None:
    """The mapping is closed: an unlisted path raises rather than no-oping."""
    apply_corrections(
        session, stored_receipt.id,
        [{"field_path": "buyer.name", "value": "IDEAL SOURCE"}],
        corrected_by="reviewer-1",
    )
    assert get_receipt(session, stored_receipt.id).buyer_name_raw == "IDEAL SOURCE"


def test_a_template_row_is_persisted_as_one(session, job) -> None:
    extraction = ReceiptExtraction(
        line_items=[LineItem(description_raw="MaxiPower", is_template_row=True)]
    )
    receipt = save_extraction(
        session, job, extraction, ValidationReport(), Decimal("0"),
        ReceiptStatus.NEEDS_REVIEW,
    )
    session.flush()
    assert receipt.line_items[0].is_template_row is True
```

Match the existing fixtures in that file rather than the names above — read the top of `tests/test_repository.py` first and reuse whatever it already provides.

- [ ] **Step 2: Run and confirm the failure reason**

Run: `python -m pytest tests/test_repository.py -k buyer -v`
Expected: FAIL — the correction test with `ValueError` naming `buyer.name` as unknown, and the save test with `buyer_name_raw` being `None`.

- [ ] **Step 3: Write the buyer on save**

In `save_extraction`, beside `merchant_name_raw=extraction.merchant.name,`:

```python
        buyer_name_raw=extraction.buyer.name,
        buyer_tax_id=extraction.buyer.tax_id,
```

Find where `LineItem` rows are constructed and pass `is_template_row=item.is_template_row`.

**`redact_pan` already covers this path** — the module docstring says it runs over "every free-text value on its way into a column". Confirm the buyer goes through the same helper the merchant name does; if it does not, that is a finding, so STOP and report rather than adding a second redaction site.

- [ ] **Step 4: Register the correctable paths**

In `_RECEIPT_FIELDS`, beside the merchant entry:

```python
    "buyer.name": ("buyer_name_raw", _coerce_optional_text),
    "buyer.tax_id": ("buyer_tax_id", _coerce_optional_text),
```

In `_LINE_ITEM_FIELDS`, add `is_template_row` with the boolean coercion that mapping already uses for booleans elsewhere — read the dict and reuse, do not invent a coercer.

- [ ] **Step 5: Run and commit**

Run: `python -m pytest tests/test_repository.py -v` → PASS
Run: `python -m pytest` → no new failures beyond Task 1's eval ones.

```bash
git add src/receipts/persist/repository.py tests/test_repository.py
git commit -m "feat(persist): store the buyer, and let a reviewer correct it"
```

---

### Task 4: `R014` and `R015`, and the config they read

**Files:**
- Modify: `config/settings.py`
- Modify: `src/receipts/validate/rules.py`
- Test: `tests/test_rules.py` (confirm with `ls tests/ | grep rule`)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: rules `R014`, `R015`; `Settings.expected_buyer_name`, `Settings.expected_buyer_tax_id`.

- [ ] **Step 1: Add the settings**

In `config/settings.py`, after the model-provider block:

```python
    # --- Who our receipts should be addressed to (§17) -------------------- #
    # Maps EXPECTED_BUYER_NAME / EXPECTED_BUYER_TAX_ID. The operator's own
    # registered identity, compared against the receipt's Sold To block by
    # R014/R015. A per-deployment constant like DEFAULT_CURRENCY, not a tuning
    # knob, which is why it lives here and not in rules.yaml.
    #
    # BOTH UNSET MEANS BOTH RULES ARE INERT. A deployment that has not declared
    # who it is gets no findings, rather than a finding on every receipt.
    expected_buyer_name: str | None = None
    expected_buyer_tax_id: str | None = None
```

- [ ] **Step 2: Write the failing tests — all five states, separately**

```python
from receipts.extract.schema import Buyer, ReceiptExtraction
from receipts.validate.report import Severity

# Build the ctx with whatever helper tests/test_rules.py already uses; read the
# file first. The rule reads the expected buyer off the ValidationContext, not
# off Settings directly -- see Step 4.


def test_r014_fires_when_the_buyer_name_was_not_read() -> None:
    findings = run_rule("R014", ReceiptExtraction(), expected_name="IDEAL SOURCE")
    assert [f.severity for f in findings] == [Severity.WARN]


def test_r014_does_not_fire_on_a_blank_tax_id_when_the_name_was_read() -> None:
    """The TIN line is printed and blank on every golden receipt.

    A rule that flagged it would fire on the whole corpus and be right about
    none of it.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id=None))
    assert run_rule("R014", extraction, expected_name="IDEAL SOURCE") == []


def test_r015_is_an_error_when_the_tax_ids_differ() -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id="111-111-111-000"))
    findings = run_rule("R015", extraction, expected_name="IDEAL SOURCE",
                        expected_tax_id="222-222-222-000")
    assert [f.severity for f in findings] == [Severity.ERROR]


def test_r015_is_only_a_warning_when_the_names_differ_and_there_is_no_tax_id() -> None:
    """The buyer name is handwritten on every golden receipt.

    An ERROR here would route the corpus to review on the least legible field
    on the page.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="SOMEONE ELSE", tax_id=None))
    findings = run_rule("R015", extraction, expected_name="IDEAL SOURCE")
    assert [f.severity for f in findings] == [Severity.WARN]


def test_r015_passes_on_a_matching_tax_id_even_when_the_name_differs() -> None:
    """TIN-first: a matching TIN settles identity and a name cannot override it."""
    extraction = ReceiptExtraction(buyer=Buyer(name="ldeal Sonrce", tax_id="222-222-222-000"))
    assert run_rule("R015", extraction, expected_name="IDEAL SOURCE",
                    expected_tax_id="222-222-222-000") == []


def test_r015_matches_names_through_the_normalizer() -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="Ideal source", tax_id=None))
    assert run_rule("R015", extraction, expected_name="IDEAL SOURCE") == []


def test_both_rules_are_inert_when_no_expected_buyer_is_configured() -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="ANYONE AT ALL", tax_id=None))
    assert run_rule("R014", extraction) == []
    assert run_rule("R015", extraction) == []
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `python -m pytest tests/test_rules.py -k "r014 or r015" -v`
Expected: FAIL — no rule with those IDs. `register` raises on duplicates, so a passing test here would mean the IDs already exist; if that happens STOP, the ID survey in the design is stale.

- [ ] **Step 4: Thread the expected buyer onto `ValidationContext`**

Read `src/receipts/validate/context.py` and add two optional fields mirroring how it already carries configuration. **Validation must stay pure** — the rule reads the context, never `Settings()`. Wire the context construction wherever the pipeline builds it.

- [ ] **Step 5: Implement both rules**

In `src/receipts/validate/rules.py`, in the PRESENCE section after `R013`:

```python
@register
class BuyerPresent(Rule):
    id = "R014"
    severity = Severity.WARN
    description = "buyer.name is not empty when an expected buyer is configured."

    def applies(self, r, ctx) -> bool:
        return ctx.expected_buyer_name is not None or ctx.expected_buyer_tax_id is not None

    def check(self, r, ctx) -> list[Finding]:
        if (r.buyer.name or "").strip():
            return []
        return [
            self.finding(
                "buyer.name is empty. The 'Sold To' / 'Registered Name' block "
                "names who the receipt was issued to. It is not the merchant in "
                "the header and not the printer in the footer. If the line is "
                "blank on the paper, leave it null.",
                field_paths=["buyer.name"],
            )
        ]


@register
class BuyerIsUs(Rule):
    id = "R015"
    severity = Severity.WARN
    description = "The buyer matches the configured operator."

    def applies(self, r, ctx) -> bool:
        return ctx.expected_buyer_name is not None or ctx.expected_buyer_tax_id is not None

    def check(self, r, ctx) -> list[Finding]:
        # TIN first: a printed identifier settles identity, and a name cannot
        # override it. Unexercised on the current corpus -- every golden buyer
        # TIN is blank -- and correct the moment a receipt carries one. Do not
        # "simplify" this branch away for being uncovered by the golden set.
        read_tin = (r.buyer.tax_id or "").strip()
        want_tin = (ctx.expected_buyer_tax_id or "").strip()
        if read_tin and want_tin:
            if _digits(read_tin) == _digits(want_tin):
                return []
            return [
                self.finding(
                    f"The receipt's buyer TIN {read_tin!r} is not this "
                    f"operator's TIN. A differing TIN is a different registered "
                    "entity, so this receipt may not be ours.",
                    field_paths=["buyer.tax_id"],
                    severity=Severity.ERROR,
                )
            ]

        read_name = (r.buyer.name or "").strip()
        want_name = (ctx.expected_buyer_name or "").strip()
        if not read_name or not want_name:
            return []  # 'not read' is R014's finding, not a mismatch.
        if normalize_merchant_name(read_name) == normalize_merchant_name(want_name):
            return []
        return [
            self.finding(
                f"The receipt's buyer {read_name!r} does not match this "
                "operator. The name is handwritten on these forms, so check the "
                "image before treating it as someone else's receipt.",
                field_paths=["buyer.name"],
            )
        ]
```

Import `normalize_merchant_name` from `..normalize.text`. Add a module-level `_digits` helper that strips everything but digits, or reuse one if `rules.py` already has it — grep before adding.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/test_rules.py -v` → PASS
Run: `python -m pytest` → no new failures.

```bash
git add config/settings.py src/receipts/validate/rules.py src/receipts/validate/context.py tests/test_rules.py
git commit -m "feat(validate): R014 and R015, the receipt-is-ours check"
```

---

### Task 5: Every arithmetic and quality rule skips template rows

**Files:**
- Modify: `src/receipts/validate/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 1's flag.
- Produces: no new names. Behaviour change to `R020`–`R025`, `R050`–`R053`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_template_row_does_not_break_the_line_item_arithmetic() -> None:
    """MaxiPower and MaxiGreen are printed and blank on r002.

    Counted as purchases they would drag the line-item sum away from the
    total and raise a reconciliation ERROR on a receipt that reconciles.
    """
    extraction = ReceiptExtraction(
        line_items=[
            LineItem(description_raw="MaxiPower", is_template_row=True),
            LineItem(description_raw="DieselPlus", qty=Decimal("17.39"),
                     unit_price=Decimal("115.00"), line_total=Decimal("2000.00")),
        ],
        totals=Totals(subtotal=Decimal("1785.71"), tax=Decimal("214.29"),
                      total=Decimal("2000.00")),
    )
    ids = {f.rule_id for f in validate(extraction, ctx()).findings}
    assert "R020" not in ids and "R021" not in ids


def test_r053_does_not_fire_on_a_template_row() -> None:
    """R053's complaint IS the definition of a template row."""
    extraction = ReceiptExtraction(
        line_items=[LineItem(description_raw="MaxiPower", is_template_row=True)]
    )
    assert "R053" not in {f.rule_id for f in validate(extraction, ctx()).findings}


def test_r053_still_fires_on_an_unflagged_empty_row() -> None:
    """The flag must not become a blanket amnesty for empty rows."""
    extraction = ReceiptExtraction(line_items=[LineItem(description_raw="")])
    assert "R053" in {f.rule_id for f in validate(extraction, ctx()).findings}


def test_a_wrongly_flagged_PURCHASE_is_silently_dropped_from_the_arithmetic() -> None:
    """The one way this feature can do real harm, pinned so it is a KNOWN cost.

    Nothing downstream can distinguish a genuinely blank pre-printed row from a
    filled row the model flagged by mistake -- both arrive as a description with
    null amounts. This test does not assert the harm is prevented, because it
    cannot be: it asserts the shape, so a later reader finds it documented
    rather than discovering it on a real ledger.

    A flagged row carrying a real amount is excluded from reconciliation, so a
    receipt whose totals DISAGREE with its purchases still validates clean.
    """
    extraction = ReceiptExtraction(
        line_items=[
            LineItem(description_raw="DieselPlus", line_total=Decimal("2000.00"),
                     is_template_row=True),  # wrongly flagged
        ],
        totals=Totals(total=Decimal("2000.00")),
    )
    ids = {f.rule_id for f in validate(extraction, ctx()).findings}
    assert "R020" not in ids, (
        "a wrongly flagged purchase is invisible to reconciliation -- this is a "
        "known, accepted cost of is_template_row and is why the prompt must be "
        "explicit that the flag describes the PAPER, not the model's confidence"
    )
```

- [ ] **Step 2: Run and confirm they fail**

Run: `python -m pytest tests/test_rules.py -k template -v`
Expected: the first two FAIL, the third PASSES already. **A third-test failure means you have misread `R053`** — stop and read it before changing anything.

- [ ] **Step 3: Add one helper and use it everywhere**

```python
def _purchased(r: ReceiptExtraction) -> list[LineItem]:
    """The line items that are purchases -- template rows excluded.

    One helper rather than a filter repeated per rule: the rules that must
    agree about what counts as a purchase are exactly the rules that will
    drift apart if each keeps its own predicate.
    """
    return [i for i in r.line_items if not i.is_template_row]
```

Then, in **every** rule that iterates `r.line_items` for arithmetic or item quality, swap to `_purchased(r)`. Find them with `grep -n "line_items" src/receipts/validate/rules.py` and change each deliberately — **do not blanket-replace**, because a rule that counts *rows on the form* legitimately wants all of them.

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/test_rules.py -v` → PASS
Run: `python -m pytest` → no new failures.

```bash
git add src/receipts/validate/rules.py tests/test_rules.py
git commit -m "fix(validate): a blank pre-printed row is not a purchase"
```

---

### Task 6: The prompt asks for the buyer and the blank rows

**Files:**
- Modify: `src/receipts/extract/prompts.py`
- Test: `tests/test_pipeline_merchant_hints.py` — **verified 2026-08-18: there is no `test_prompts.py`.** That module is the only one importing `build_extraction_prompt`, and it already asserts on prompt content, so the new assertions belong beside its existing ones rather than in a new file.

**Interfaces:**
- Consumes: Task 1's schema.
- Produces: no new names.

- [ ] **Step 1: Write the failing test**

```python
def test_the_extraction_prompt_asks_for_the_buyer_and_names_every_spelling() -> None:
    """Three golden receipts, three different labels for the same block."""
    prompt = build_extraction_prompt(TriageResult(), None, [])
    for spelling in ("SOLD TO", "Registered Name", "Sold to"):
        assert spelling.lower() in prompt.lower()


def test_the_extraction_prompt_distinguishes_the_three_tins() -> None:
    lowered = build_extraction_prompt(TriageResult(), None, []).lower()
    assert "printer" in lowered and "buyer" in lowered


def test_the_extraction_prompt_asks_for_blank_pre_printed_rows() -> None:
    assert "is_template_row" in build_extraction_prompt(TriageResult(), None, [])
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_prompts.py -k "buyer or tin or template" -v` → FAIL

- [ ] **Step 3: Extend the prompt**

Add to the extraction prompt body:

```
BUYER (the "SOLD TO", "Sold to:", or "Registered Name" block)
  This is who the receipt was issued TO. It is NOT the merchant printed at the
  top, and NOT the printing company in the footer. A BIR sales invoice carries
  THREE tax identification numbers -- the merchant's, the buyer's, and the
  printer's -- and they are different numbers. Put the buyer's in
  buyer.tax_id and nothing else. If the buyer's TIN line is printed but blank,
  leave buyer.tax_id null; do not fill it from the footer.

BLANK PRE-PRINTED ROWS
  These forms pre-print product names with empty quantity and amount columns.
  Emit every one you can see as a line item with is_template_row = true and
  its amounts left null, so the transcription is complete.
  Set is_template_row ONLY when the row is blank on the paper. A row that has
  handwriting you cannot read is a real purchase: emit it with
  is_template_row = false, leave the unreadable fields null, and name them in
  meta.ambiguous_fields.
```

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/test_prompts.py -v` → PASS

```bash
git add src/receipts/extract/prompts.py tests/test_prompts.py
git commit -m "feat(prompt): ask for the buyer, and for the rows left blank"
```

---

### Task 7: The golden labels

**Files:**
- Modify: `eval/golden/labels/r001.json`, `r002.json`, `r003.json`
- Test: whatever eval tests Task 1 turned red.

**Interfaces:**
- Consumes: Task 1's schema.
- Produces: labelled truth for the new paths.

**Values read from the images on 2026-08-18 — transcribe exactly, do not normalise:**

| receipt | `buyer.name` | `buyer.tax_id` | template rows |
|---|---|---|---|
| r001 | `IDEAL SOURCE` | `null` | `PREMIUM 97`, `PREMIUM 95`, `REGULAR 91`, `POWER DIESEL`, `MOTOR OIL` (**not** `CLEAN DIESEL` — it is the filled one) |
| r002 | `Ideal source` | `null` | `MaxiPower`, `MaxiGreen` |
| r003 | `IDEAL SOURCE` | `null` | none — the form prints no product rows |

- [ ] **Step 1: Add the `buyer` block to all three**

```json
  "buyer": { "name": "IDEAL SOURCE", "tax_id": null },
```

**r002's name is `Ideal source`, lowercase 's'.** The label records what the paper says, not what the operator is called. If you "correct" it, the normalizer test in Task 4 stops proving anything, because it will be comparing two identical strings.

- [ ] **Step 2: Add the template rows to r001 and r002**

Each as a line item with `"is_template_row": true`, `description_raw` exactly as pre-printed, every amount `null`, and `position` continuing the existing sequence.

- [ ] **Step 3: Update the notes rather than deleting them**

Each label's `meta.notes` says the blank rows "must NOT be emitted as line items". Rewrite that clause to say they are emitted **flagged** and excluded from arithmetic. **Keep the sentence naming which rows are blank** — it is the evidence for the flag.

- [ ] **Step 4: Run the eval tests**

Run: `python -m pytest` → the Task 1 failures clear. If field accuracy moves, that is expected: the new paths are now labelled truth.

- [ ] **Step 5: Commit**

```bash
git add eval/golden/labels/
git commit -m "test(golden): label the buyer, and the rows the forms leave blank"
```

---

### Task 8: The export

**Files:**
- Modify: `src/receipts/export/xlsx.py`
- Test: `tests/test_xlsx.py` — **verified 2026-08-18.** Note `tests/test_cli_reports.py` also imports `export_workbook`; if a header change breaks it, that is a real coupling to fix, not a test to loosen.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_review_sheet_carries_the_buyer() -> None:
    ws = _review_sheet_of(export_workbook([row_with(buyer_name="IDEAL SOURCE")]))
    assert "Buyer" in _header_row(ws)


def test_a_template_row_is_not_exported_as_a_purchase() -> None:
    """An accounting ledger listing something nobody bought is a defect."""
    book = export_workbook([row_with(line_items=[
        template("MaxiPower"), purchase("DieselPlus", Decimal("2000.00")),
    ])])
    assert _descriptions_in(book) == ["DieselPlus"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_export_xlsx.py -k "buyer or template" -v` → FAIL

- [ ] **Step 3: Implement**

Add `Buyer` and `Buyer TIN` headers and their cells via the existing `_text_cell`. Filter template rows where the sheet iterates line items. **Follow the file's own header-and-width machinery** — `_write_header`, `_autosize`, `_finalize` — rather than writing cells directly; `_finalize` takes a column index for confidence formatting and will be off by two if headers are added without it.

- [ ] **Step 4: Run and commit**

Run: `python -m pytest tests/test_export_xlsx.py -v` → PASS

```bash
git add src/receipts/export/xlsx.py tests/test_export_xlsx.py
git commit -m "feat(export): buyer columns, and no phantom ledger rows"
```

---

### Task 9: The reviewer can see and fix the buyer

**Files:**
- Modify: `frontend/src/review/ReceiptForm.tsx` and its `.module.css`
- Test: `frontend/tests/receipt-form.test.tsx`

**Interfaces:**
- Consumes: Task 3's `buyer.name` / `buyer.tax_id` correction paths.

- [ ] **Step 1: Write the failing test**

```tsx
it('shows the buyer and sends a correction for it', async () => {
  render(<ReceiptForm receipt={receiptWith({ buyer: { name: 'IDEAL SOURCE', tax_id: null } })} />)
  const field = screen.getByLabelText(/sold to|buyer/i)
  expect(field).toHaveValue('IDEAL SOURCE')
  await userEvent.clear(field)
  await userEvent.type(field, 'IDEAL SOURCE INC')
  await userEvent.click(screen.getByRole('button', { name: /approve/i }))
  expect(patchBody().corrections).toContainEqual(
    expect.objectContaining({ field_path: 'buyer.name' }),
  )
})
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npx vitest run receipt-form` → FAIL, no such field.

- [ ] **Step 3: Add the fields**

Two text inputs inside a `.fieldCell` wrapper at the call site (§0g: the wrapper is at the call site, never inside the input component). **`null` renders as the empty-value placeholder, not as `""` and never as `0`** — ADR-0027 decision 5. Not `MoneyInput`: these are text.

- [ ] **Step 4: Guard the class names**

Add any new class to whichever of `value.test.tsx`'s `COMPONENTS` or the stylesheet census covers this file. **Vitest sets `css: false`**, so a renamed class ships unpainted with every gate green — the census and the reference guard are the only things that catch it, and neither joins a class to the DOM.

- [ ] **Step 5: Run and commit**

Run: `cd frontend && npx vitest run && npm run typecheck` → PASS

```bash
git add frontend/src/review/ frontend/tests/
git commit -m "feat(review): show the buyer, and let a reviewer correct it"
```

---

## Close

- [ ] `python scripts/verify.py` — all five gates. **Background it**; it exceeds a 2-minute tool timeout.
- [ ] Re-run `scripts/try_one_receipt.py r002 --max-edge 2048` against `gemma4:cloud` and read the output. Expect the buyer populated, `MaxiPower`/`MaxiGreen` flagged, and **line-item precision up from 0.33** — the metric was penalising a correct reading.
- [ ] **Run it twice.** Cloud inference is not deterministic at `temperature=0` (ISSUE-001, 2026-08-18); one run is a sample.
- [ ] Whole-branch review on the strongest model, then one fix wave and one scoped re-review.

## Dated defect log

*(Append here as defects in this plan are found. Every milestone in this repo has found some, and every one has been the controller's — usually a claim about an existing artefact rather than an error of reasoning.)*
