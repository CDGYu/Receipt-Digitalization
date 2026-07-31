# PAN Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two PAN leaks in the redaction regex, one whole-PAN leak in
`save_extraction`, and three false prose claims — without masking the merchant
TINs this corpus depends on.

**Architecture:** `_PAN_RE`'s four-group alternative becomes a greedy run and
stops trying to decide anything by shape alone; every ambiguity (amount tail,
over-long run, length window) moves into `_mask_pan`, which is the only place
the digit count is visible. Separately, `save_extraction` stops redacting an
enumerated list of columns and redacts every `str` it is about to store, with a
test that enumerates the columns from the SQLAlchemy table so a new one fails
RED instead of leaking.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x ORM, pytest (+ `pytest-randomly`),
ruff, FastAPI/Starlette `TestClient`, React 19 + Vite + TypeScript, Vitest.

**Design doc:** `docs/superpowers/specs/2026-07-31-pan-hardening-design.md` —
read §1.2 and §4 before writing any code.

## Global Constraints

- **`Decimal` on the money path, never `float`** (ADR-0001).
- **A full PAN is never persisted** (SPEC §18, ADR-0007). This is the invariant
  the whole plan serves.
- **The group-shape requirement in `_PAN_RE` is load-bearing.** Real merchant
  TINs on this corpus are 12–14 digits printed `3-3-3-N`
  (`221 193 789 09013`, `774-423-646-00011`, `205-741-640-162`,
  `103-969-951-00000`). They are silent only because the pattern demands
  `4-4-4-N` or `4-6-5`. **Never relax the grouping to "any run of 13+ digits."**
- **`(?!\.\d)` stays on the unseparated alternative alone.** Relocating it onto
  the separated alternatives is a measured regression: it makes
  `4111 1111 1111 1111.99` store as `4111 **********1199`.
- **Repository conventions (ADR-0006):** the session is injected, **the caller
  commits**, and invalid input raises `ValueError`. No function in
  `repository.py` calls `session.commit()`.
- **`python -m pytest` stays offline and Node-free.** No test may need a
  network, a provider, or `node`.
- **No module-top import of an optional extra** on any path reachable from an
  entry point (ADR-0014).
- Lint is `python -m ruff check .` — bare `ruff` is not on `PATH`.
- Gate runner is `python scripts/verify.py` (ADR-0017): pytest, ruff, typecheck,
  vitest, build. **`npm test` does not type-check** — `npm run typecheck` is a
  separate gate.
- Conventional commit messages (`feat(scope): …`, `fix(scope): …`, `docs: …`,
  `test(scope): …`).
- Baseline on `main` before this work: **844 Python tests, 170 Vitest.**
- **Never stage anything under `var/`** — it holds real receipt images.

---

## Working branch

All tasks land on `feat/pan-hardening`, branched from `main`. Pushing `feat/*`
is authorised; **do not push `main`.**

```bash
git checkout -b feat/pan-hardening main
```

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/receipts/persist/repository.py` | `_PAN_RE` (the detector), `_mask_pan` (every masking decision), `save_extraction` / `_build_line_items` (the write boundary) | 2, 3, 4 |
| `tests/test_repository.py` | The PAN battery — two parametrised tables plus the write-boundary tests | 2, 3, 4, 5 |
| `tests/test_api_write.py` | The skip-recoverability regression test | 1 |
| `frontend/src/review/ReceiptForm.tsx` | The doc comment bounding what the browser may assume about masking | 6 |
| `docs/adr/0018-pan-masking-policy.md` | The measured policy, so the next widening starts from measurements | 6 |
| `docs/adr/0007-pan-redaction-and-money-integrity.md` | Dated correction to the stale separator sentence | 6 |
| `docs/adr/README.md` | Index entry for 0018 | 6 |

**Task order matters.** Task 1 pins queue behaviour that must not move while the
writer changes. Task 2 makes the detector greedy and would leak *more* if
`_mask_pan` were not fixed in the same task — so 2 covers both, and 3 and 4 build
on it.

---

### Task 1: Bind the recoverability the "Skip this receipt" button spends

The review UI's skip button **completes** the held task, leaving the receipt
`needs_review` with a `DONE` review task. Three properties make that recoverable
rather than a black hole. All three are true today and **none would go red if
they stopped being.** This task lands first so the queue's behaviour is pinned
before anything else moves.

**Files:**
- Modify: `tests/test_api_write.py`

**Interfaces:**
- Consumes, all existing in `tests/test_api_write.py` — **verified against the
  file on 2026-07-31, not guessed:**
  - `reviewer_client` (fixture) — a `TestClient` logged in as `alice`.
  - `session_factory` (fixture) — a session factory over a temp SQLite DB.
  - `receipt_id` (fixture) — a seeded `needs_review` receipt.
  - `task_id` (fixture) — that receipt's review task, **already claimed by
    alice**, which is exactly the state the skip button acts from.
  - `enqueue_review` and `next_task`, imported at `tests/test_api_write.py:61`.
  - `ReviewTaskState`, imported from `receipts.persist.models` at `:50-57` —
    confirm the exact name in that import block before using it.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Confirm the three route contracts still hold**

The plan's route facts were measured, but measure them again — a plan's claims
about existing APIs are the part that has been wrong eleven times in this repo.

Run: `python -m pytest tests/test_api_write.py -q --junitxml=/dev/null`

Then confirm by reading:
- `GET /receipts` returns `{"items": [...]}` — **the key is `items`, not
  `receipts`.** A Phase 5 reviewer lost a whole measurement to that.
- `PATCH /receipts/{id}` takes a **domain-nested** body — `{"totals": {...}}`,
  `{"payment": {...}}`, `{"receipt": {...}}` — parsed into a `CorrectionPatch`
  with `exclude_unset=True`. It is **not** `{"fields": {...}}`.
- `POST /review/{task_id}/complete` is what the UI's skip button calls.

- [ ] **Step 2: Write the test**

```python
def test_a_skipped_receipt_stays_recoverable(
    reviewer_client, session_factory, receipt_id, task_id
) -> None:
    """The three properties the review UI's "Skip this receipt" button spends.

    Skip **completes** the held task, leaving the receipt ``needs_review`` with
    a ``DONE`` task. That is survivable only because of the asymmetry measured
    during the Phase 5 review:

        IN_PROGRESS --enqueue_review--> in_progress   claimable by another: False
        DONE        --enqueue_review--> open          claimable by another: True

    So skip converts the one genuinely unrecoverable queue state into a
    recoverable one. All three properties below are true today and **none would
    go red if they stopped being** -- which is the entire reason this test
    exists.
    """
    assert reviewer_client.post(f"/review/{task_id}/complete").status_code == 200

    # (i) still listed as needing review
    listed = reviewer_client.get("/receipts", params={"status": "needs_review"})
    assert listed.status_code == 200
    assert str(receipt_id) in [item["id"] for item in listed.json()["items"]]

    # (ii) still PATCH-able to `reviewed` -- the route never consults ReviewTask,
    #      so even a patch that changes nothing drives the status.
    patched = reviewer_client.patch(f"/receipts/{receipt_id}", json={})
    assert patched.status_code == 200
    assert patched.json()["status"] == "reviewed"

    # (iii) still re-openable, and re-opened OPEN -- claimable by someone else,
    #       not just by alice.
    with session_factory() as session:
        task = enqueue_review(session, receipt_id, reason="reopened")
        session.commit()
        assert task.state is ReviewTaskState.OPEN
```

> If `PATCH` with `json={}` does not return `200`, do **not** paper over it by
> sending a field. Report it: the ledger records the empty patch as measured
> behaviour, and a disagreement is a finding.

- [ ] **Step 3: Run it and confirm it passes**

Run: `python -m pytest tests/test_api_write.py::test_a_skipped_receipt_stays_recoverable -v`
Expected: **PASS.** All three properties hold today — this test documents them,
it does not fix anything. A RED run here means the test is wrong, not the code.

- [ ] **Step 4: Prove each guarantee separately**

A test asserting the absence of breakage **cannot be proven by one RED run.**
Revert each guarantee on its own and confirm the test goes red naming *that*
one, restoring the code fully between mutations. One variable per mutation, or
the result names the wrong cause.

| # | Mutation | Expected failure |
|---|---|---|
| (i) | In the `GET /receipts` route, filter out receipts whose review task is `DONE` | the `listed` assertion |
| (ii) | In `apply_corrections`, refuse a patch when the receipt's task is `DONE` | the `patched` assertion |
| (iii) | In `enqueue_review`, return an `IN_PROGRESS` task instead of re-opening to `OPEN` | the `task.state` assertion |

Record the three observed failure messages in the commit body. Then:

Run: `git diff --exit-code` — must print nothing, proving every mutation was
reverted before committing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_write.py
git commit -m "test(review): bind the recoverability a skipped receipt depends on"
```

---

### Task 2: Make the detector greedy and move every decision into `_mask_pan`

Closes leak **(a)** — a four-group PAN with a 5+ digit tail stored whole — and
leak **(b)** — more than four groups leaving seven digits clear.

**Files:**
- Modify: `src/receipts/persist/repository.py:131-146` (`_PAN_RE` and `_mask_pan`)
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_mask_pan(match: re.Match[str]) -> str` — signature unchanged.
  `redact_pan(value: Any) -> Any` — signature and recursion unchanged. Tasks 3
  and 4 rely on both keeping their current names and shapes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repository.py`, beside the existing PAN battery:

```python
@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        # (a) A four-group PAN with a 5+ digit tail was stored WHOLE, because
        #     the trailing group was \d{1,4} and the match simply did not cover
        #     the run. 17, 18 and 19 digits in the clear -- the worst leak in
        #     the module, and the only one its comments did not record.
        ("4111 1111 1111 11111", "*************1111"),
        ("4111 1111 1111 111111", "**************1111"),
        ("4111 1111 1111 1111111", "***************1111"),
        ("4111-1111-1111-11111", "*************1111"),
        ("4111.1111.1111.11111", "*************1111"),
        # (b) More than four groups left seven digits clear.
        ("4111 1111 1111 1111 111", "***************1111"),
        ("4111-1111-1111-1111-111", "***************1111"),
    ],
    ids=["4x5", "4x6", "4x7", "4x5-hyphen", "4x5-dot", "five-groups", "five-hyphen"],
)
def test_redact_pan_masks_a_separated_run_longer_than_four_full_groups(
    printed: str, expected: str
) -> None:
    """The two residuals the Phase 5 whole-branch review surfaced.

    Both had one root cause: ``_mask_pan`` returned the match unchanged when the
    digit total fell outside 13-19, so a pattern that under-matched leaked
    everything it failed to cover.
    """
    assert redact_pan(f"CARD {printed} OK") == f"CARD {expected} OK"


def test_redact_pan_keeps_an_amount_that_follows_a_card_number() -> None:
    """A trailing ``.NN`` is an amount when a whole PAN precedes it.

    The greedy pattern deliberately over-matches and swallows the amount; the
    decision is made in ``_mask_pan``, where the digit count is visible. A
    *lexical* guard cannot do this job: it also blocks ``4111.1111.1111.1``, a
    13-digit PAN whose last group is one digit -- measured, and a committed
    expectation of this module.
    """
    assert redact_pan("CARD 4111 1111 1111 1111.99") == "CARD ************1111.99"
    assert redact_pan("CARD 4111.1111.1111.1111.99") == "CARD ************1111.99"
    assert redact_pan("CARD 4111.1111.1111.1 OK") == "CARD *********1111 OK"
    assert redact_pan("SUBTOTAL 1234567890123.45") == "SUBTOTAL 1234567890123.45"


def test_redact_pan_masks_the_leading_card_number_of_an_over_long_run() -> None:
    """Over 19 digits is not a PAN, so the leading valid window is masked.

    Kept and documented rather than widened a third time: a 24-digit run is not
    a card number, and every previous widening of this pattern produced a
    surprise. ADR-0018.
    """
    assert redact_pan("4111 1111 1111 1111 9999 9999") == "************1111 9999 9999"
    assert redact_pan("4111.1111.1111.1111.1111") == "************1111.1111"
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

Run: `python -m pytest tests/test_repository.py -k "longer_than_four_full_groups or keeps_an_amount or over_long_run" -v`

Expected: the seven `longer_than_four_full_groups` cases **FAIL**, each showing
the card number returned *verbatim* rather than masked — that is leak (a)/(b) in
the failure output. `keeps_an_amount` and `over_long_run` should **PASS**
already; they pin behaviour that must survive Step 3.

- [ ] **Step 3: Make the detector greedy**

In `src/receipts/persist/repository.py`, change **only** the first alternative
of `_PAN_RE`. Leave the lookbehinds, the Amex alternative, the unseparated
alternative, its `(?!\.\d)`, and the trailing `(?!\d)` exactly as they are.

```python
_PAN_RE = re.compile(
    r"""
    (?<!\d)(?<!\d\.)                                # not mid-number, not a decimal fraction
    (?:
        \d{4}(?:[ .\-_/,]\d{4})+(?:[ .\-_/,]\d{1,7})?  # 4-4-4-... any number of groups
      | \d{4}[ .\-_/,]\d{6}[ .\-_/,]\d{5}           # 4-6-5 (Amex)
      | \d{13,19}(?!\.\d)                           # unseparated, and not an integer part
    )
    (?!\d)
    """,
    re.VERBOSE,
)
```

- [ ] **Step 4: Move every decision into `_mask_pan`**

Replace `_mask_pan` entirely. **Rule order is load-bearing** — the amount tail
must be tested before the 13–19 window, or `4111 1111 1111 1111.99` masks 18
digits and destroys the amount.

```python
#: A trailing decimal fraction: one or two digits after a period, at the end.
_AMOUNT_TAIL_RE = re.compile(r"\.\d{1,2}$")


def _mask_all_but_last_four(text: str) -> str:
    """Stars for every digit of ``text`` but the last four, separators dropped."""
    digits = re.sub(r"\D", "", text)
    return "*" * (len(digits) - 4) + digits[-4:]


def _mask_pan(match: re.Match[str]) -> str:
    """Decide what a matched run is, then mask it. Never fails open.

    The pattern deliberately over-matches: it cannot see a digit *count*, and
    every question worth asking about a card number is a question about counts.
    So it matches the longest plausible run and this function resolves it.

    The rules, in the order they must be applied:

    1. **A trailing ``.NN`` is an amount** when the text before it already holds
       a whole PAN. Checked first, or ``4111 1111 1111 1111.99`` masks eighteen
       digits and the amount is destroyed. The length check is not optional
       either: without it ``4111.1111.1111.1`` -- a 13-digit card number whose
       last group is a single digit -- stops being masked.
    2. **13-19 digits is a PAN.** Mask all but the last four.
    3. **Under 13 digits is not a PAN.** Return it untouched.
    4. **Over 19 digits is not a PAN either**, but it may *contain* one: mask
       the longest 13-19 digit prefix that ends on a group boundary and leave
       the rest. Returning the whole run untouched here -- which is what this
       function used to do -- is what leaked the card numbers in cases (a) and
       (b): a pattern that under-matched leaked everything it failed to cover.
    """
    text = match.group(0)
    tail = _AMOUNT_TAIL_RE.search(text)
    if tail is not None:
        head = text[: tail.start()]
        if _PAN_MIN_DIGITS <= len(re.sub(r"\D", "", head)) <= _PAN_MAX_DIGITS:
            return _mask_all_but_last_four(head) + tail.group(0)

    digits = re.sub(r"\D", "", text)
    if _PAN_MIN_DIGITS <= len(digits) <= _PAN_MAX_DIGITS:
        return _mask_all_but_last_four(text)
    if len(digits) < _PAN_MIN_DIGITS:
        return text

    for length in range(_PAN_MAX_DIGITS, _PAN_MIN_DIGITS - 1, -1):
        seen = 0
        for index, char in enumerate(text):
            if not char.isdigit():
                continue
            seen += 1
            if seen < length:
                continue
            head, rest = text[: index + 1], text[index + 1 :]
            if not rest or not rest[0].isdigit():
                return _mask_all_but_last_four(head) + rest
            break
    return text
```

- [ ] **Step 5: Run the new tests**

Run: `python -m pytest tests/test_repository.py -k "longer_than_four_full_groups or keeps_an_amount or over_long_run" -v`
Expected: **PASS**, all of them.

- [ ] **Step 6: Replay the committed battery — the required check**

This is the step that catches what a hand-picked battery misses. A lexical
fraction guard passed 34 hand-written cases in both directions and still broke
`CARD 4111.1111.1111.1 OK`, a committed expectation. **A battery you write
agrees with you.**

Run: `python -m pytest tests/test_repository.py -v`
Expected: **PASS**, every test in the module, with **no expectation edited**. If
any committed case now fails, the design is wrong — stop and report it rather
than adjusting the expectation to match the code.

- [ ] **Step 7: Run the full Python suite**

Run: `python -m pytest -q --junitxml=results.xml` then read `results.xml` for
the counts — PowerShell clips piped Python output and the summary line is the
first thing lost.
Expected: **PASS**, and the total is 844 + the tests added here. Delete
`results.xml` before staging.

- [ ] **Step 8: Lint**

Run: `python -m ruff check .`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add src/receipts/persist/repository.py tests/test_repository.py
git commit -m "fix(persist): mask a separated card number however many groups it is printed in"
```

---

### Task 3: Redact every text value `save_extraction` is about to store

Closes leak **(d)**: `save_extraction` redacts two of its text columns and
copies the rest verbatim, so a model that reads the card line into
`receipt.number` or `receipt.date_raw` lands a **whole PAN** in `receipts` —
while a reviewer typing the same string gets it masked, because `_plan_change`
redacts every coerced text value.

**Files:**
- Modify: `src/receipts/persist/repository.py` — `save_extraction` (the `fields`
  dict around `:368-394`) and `_build_line_items` (`:459-484`)
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `redact_pan` and `_last4` from Task 2's module — both unchanged.
- Produces: `save_extraction(...) -> Receipt` and
  `_build_line_items(extraction: ReceiptExtraction) -> list[LineItem]` — both
  signatures unchanged. Task 4's test consumes `save_extraction`.

- [ ] **Step 1: Write the failing test**

```python
def test_save_extraction_redacts_every_text_column_not_just_two(engine: sa.Engine) -> None:
    """§18 on the machine side, for the columns nobody enumerated.

    ``merchant_name_raw`` and ``payment_method`` were redacted; ``receipt_number``,
    ``date_raw``, ``currency`` and every line-item text field were copied
    verbatim. So a model that read the card line into the receipt number stored
    a full card number in the plainest spelling there is -- while a reviewer
    typing the same string got it masked, because ``_plan_change`` redacts every
    coerced text value. The two sides now agree.
    """
    job = _job()
    with Session(engine) as session:
        receipt = save_extraction(
            session,
            job,
            ReceiptExtraction(
                merchant=ExtractedMerchant(name="M"),
                receipt=ReceiptMeta(
                    number="4111111111111111",
                    date_raw="CARD 4111-1111-1111-1111",
                ),
                line_items=[
                    ExtractedLineItem(
                        position=1,
                        description_raw="CARD 4111 1111 1111 1111",
                        sku="378282246310005",
                        unit="4111.1111.1111.1111",
                        qty=Decimal("1"),
                        unit_price=Decimal("1.00"),
                        line_total=Decimal("1.00"),
                    )
                ],
            ),
            ValidationReport(),
            Decimal("0.5"),
            ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()

        assert receipt.receipt_number == "************1111"
        assert receipt.date_raw == "CARD ************1111"
        item = receipt.line_items[0]
        assert item.description_raw == "CARD ************1111"
        assert item.sku == "***********0005"
        assert item.unit == "************1111"
```

> Confirm `ReceiptMeta`'s real field names and `ExtractedLineItem`'s required
> arguments against `src/receipts/extract/schema.py` before running this.
> `ExtractedLineItem` is `receipts.extract.schema.LineItem`, imported under an
> alias at `tests/test_repository.py:43`. Access to `receipt.line_items` may
> need a `session.refresh(receipt)` — check how neighbouring tests read child
> rows.

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_repository.py::test_save_extraction_redacts_every_text_column_not_just_two -v`
Expected: **FAIL** on `receipt.receipt_number`, showing `'4111111111111111'` —
the whole card number, verbatim.

- [ ] **Step 3: Redact by default in `save_extraction`**

After the `fields` dict is fully built and **before** the `Receipt(...)`
construction, add:

```python
    # §18: redaction is default-on rather than an enumerated column list. That
    # list has been found short twice -- ``receipt_number`` and ``date_raw``
    # stored whole card numbers while ``merchant_name_raw`` and
    # ``payment_method`` were masked, so the machine leaked what a reviewer
    # could not. Money is ``Decimal`` and dates are ``date``/``time``, so the
    # gate leaves them structurally out of reach. The gate is ``type(...) is
    # str``, not ``isinstance``: ``Legibility`` and ``ReceiptStatus`` are
    # *str-enums*, and ``redact_pan`` hands a str subclass back as plain
    # ``str`` -- measured: ``redact_pan(ReceiptStatus.NEEDS_REVIEW)`` returns
    # ``'needs_review'``, and although the value-based Enum columns bind it,
    # the instance attribute then holds a plain string until the next refresh.
    # Every value the correction path coerces is an exact ``str``, so the two
    # sides still agree.
    fields = {
        key: redact_pan(value) if type(value) is str else value
        for key, value in fields.items()
    }
    # ``card_last4`` keeps the *stronger* guarantee, applied after: four digits
    # at most, not "all but the last four".
    fields["card_last4"] = _last4(extraction.payment.card_last4)
```

Then delete the now-redundant `redact_pan(...)` wrappers on
`merchant_name_raw` and `payment_method` in the dict literal, replacing them
with the bare values, and leave a short comment pointing at the block above so
the next reader does not think redaction was removed.

- [ ] **Step 4: Redact the line-item text columns**

In `_build_line_items`, wrap the three text fields:

```python
            description_raw=redact_pan(item.description_raw),
            sku=redact_pan(item.sku),
            unit=redact_pan(item.unit),
```

`position`, `qty`, `unit_price`, `line_total`, `modifiers` and `bbox` are
untouched: they are not text. `redact_pan` returns `None` unchanged, so the
optional columns keep their NULLs.

- [ ] **Step 5: Run the test**

Run: `python -m pytest tests/test_repository.py::test_save_extraction_redacts_every_text_column_not_just_two -v`
Expected: **PASS**.

- [ ] **Step 6: Run the full Python suite and expect fixtures to move**

Run: `python -m pytest -q --junitxml=results.xml`, then read `results.xml`.

This step **changes what is stored**, so a fixture carrying a long digit run may
now come back masked. That is the intended behaviour, not a regression — but
each failure must be inspected individually and fixed by correcting the
*expectation*, never by narrowing the redaction. If a failure shows a value that
should not have been masked, stop: that is a false positive and a finding, not a
fixture update. Delete `results.xml` before staging.

- [ ] **Step 7: Lint and commit**

```bash
python -m ruff check .
git add src/receipts/persist/repository.py tests/test_repository.py
git commit -m "fix(persist): redact every text value save_extraction stores, not two of them"
```

---

### Task 4: Make a new text column fail RED instead of leaking

Task 3 fixed the columns that exist. This makes the guarantee survive the
*next* column, which is what the enumerated list failed to do twice.

**Files:**
- Modify: `tests/test_repository.py`

**Interfaces:**
- Consumes: `save_extraction` from Task 3; `Receipt` and `LineItem` from
  `receipts.persist.models`.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the test**

```python
def test_every_text_column_save_extraction_writes_is_redacted(engine: sa.Engine) -> None:
    """The guarantee, enumerated from the table rather than from memory.

    The redaction column list was hand-maintained and was found short twice. A
    column added later must fail *here* rather than leak silently, so this walks
    ``Receipt.__table__`` and ``LineItem.__table__`` instead of naming columns.

    ``card_last4`` is excluded because it carries a stronger guarantee
    (:func:`_last4`, four digits at most). ``Enum`` columns are excluded by
    *type*: ``sa.Enum`` subclasses ``sa.String``, and ``Legibility`` is a
    ``str`` enum, so both would otherwise be swept in and neither can hold free
    text. ``JSON`` columns are walked separately -- a ``String`` walk is
    structurally blind to them, which is exactly how ``modifiers`` stored a
    whole PAN while every scalar text column was covered.
    """
    pan = "4111111111111111"

    def text_columns(table: sa.Table, *, exclude: frozenset[str] = frozenset()) -> list[str]:
        return [
            column.name
            for column in table.columns
            if isinstance(column.type, sa.String)
            and not isinstance(column.type, sa.Enum)
            and column.name not in exclude
        ]

    receipt_text = text_columns(Receipt.__table__, exclude=frozenset({"card_last4"}))
    item_text = text_columns(LineItem.__table__)
    item_json = [c.name for c in LineItem.__table__.columns if isinstance(c.type, sa.JSON)]
    # The walk is the guarantee, so a filter that quietly matched nothing would
    # make this test pass forever. Measured contents on 2026-07-31:
    # receipts -> merchant_name_raw, receipt_number, date_raw, currency,
    # payment_method, image_key, processed_image_key, image_phash;
    # line_items -> description_raw, sku, unit; JSON -> modifiers, bbox.
    assert {"receipt_number", "date_raw", "merchant_name_raw"} <= set(receipt_text)
    assert {"description_raw", "sku", "unit"} <= set(item_text)
    assert "modifiers" in item_json

    job = _job()
    with Session(engine) as session:
        receipt = save_extraction(
            session,
            job,
            ReceiptExtraction(
                merchant=ExtractedMerchant(name=pan),
                receipt=ReceiptMeta(number=pan, date_raw=pan),
                payment=Payment(method=pan),
                line_items=[
                    ExtractedLineItem(
                        position=1,
                        description_raw=pan,
                        sku=pan,
                        unit=pan,
                        modifiers=[Modifier(label=f"PROMO CARD {pan}")],
                    )
                ],
            ),
            ValidationReport(),
            Decimal("0.5"),
            ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()

        leaked = [
            name
            for name in receipt_text
            if isinstance(getattr(receipt, name, None), str)
            and pan in getattr(receipt, name)
        ]
        item = receipt.line_items[0]
        leaked += [
            f"line_items.{name}"
            for name in item_text
            if isinstance(getattr(item, name, None), str)
            and pan in getattr(item, name)
        ]
        leaked += [
            f"line_items.{name}"
            for name in item_json
            if pan in json.dumps(getattr(item, name, None) or [])
        ]
        assert leaked == [], f"columns storing a full PAN: {leaked}"
```

Check `Modifier`'s real constructor at `src/receipts/extract/schema.py:53` and
whether `json` is already imported in the test module before writing this.

> `image_key` and any column `save_extraction` fills from `job` will not contain
> the PAN, so they pass trivially — the test asserts *absence of the PAN*, not
> that every column was touched. Check what `Receipt.__table__.columns` actually
> yields before trusting the filter.
>
> **Correction (measured 2026-07-31):** an earlier draft of this note claimed
> `currency` was protected because `_bounded_optional_text` "raises first". That
> is false on this path. `_bounded_optional_text` is wired only into
> `_RECEIPT_FIELDS`, the **correction** path; `save_extraction` writes
> `currency=receipt_meta.currency` directly, and `ReceiptMeta.currency` is an
> unconstrained `str | None`. A 16-digit PAN in `currency` therefore reaches a
> `String(3)` column unguarded — SQLite stores it, Postgres raises `DataError`.
> That is a **separate pre-existing defect of the same shape as leak (d)** — a
> guard the human path has and the machine path lacks — and it is **out of scope
> here**: it is recorded in the ledger, not fixed by this task. For the purposes
> of this test, do not special-case `currency`; let the walk cover it.

- [ ] **Step 2: Run it and confirm it passes**

Run: `python -m pytest tests/test_repository.py::test_every_text_column_save_extraction_writes_is_redacted -v`
Expected: **PASS** — Task 3 already made it true.

- [ ] **Step 3: Prove the test can fail, then undo the proof — once per guarantee**

This asserts the absence of breakage, so a passing run proves nothing on its
own, and it binds TWO distinct guarantees, so two separate single-variable
reverts:

1. Temporarily remove the `fields = {…redact_pan…}` comprehension added in
   Task 3. Expected: **FAIL** listing at minimum `receipt_number` and
   `date_raw`. Restore; `git diff src/ --exit-code` must print nothing.
2. Temporarily remove the `redact_pan(...)` wrap around the dumped modifiers in
   `_build_line_items` (Task 3 fix round 2). Expected: **FAIL** listing
   `line_items.modifiers` — proving the JSON walk is live, not decorative.
   Restore; `git diff src/ --exit-code` must print nothing.

- [ ] **Step 4: Prove it catches a *new* column**

The point of the test is the column nobody has added yet. Temporarily add a
`String` column to `Receipt` and write it unredacted in `save_extraction`, then:

Run: `python -m pytest tests/test_repository.py::test_every_text_column_save_extraction_writes_is_redacted -v`
Expected: **FAIL**, naming the new column. Remove both edits and confirm with
`git diff src/ --exit-code`.

Do **not** commit the throwaway column, and do **not** generate a migration
for it.

- [ ] **Step 5: Commit**

```bash
git add tests/test_repository.py
git commit -m "test(persist): make a new text column fail red instead of leaking a PAN"
```

---

### Task 5: Pin the corpus TINs as silent cases

The group-shape requirement is the only thing keeping real merchant TINs out of
the mask, and nothing records that. This makes the constraint executable.

**Files:**
- Modify: `tests/test_repository.py`

**Interfaces:**
- Consumes: `redact_pan` from Task 2.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Confirm the values against the corpus**

Run: `grep -n "tax_id" eval/golden/labels/*.json`

Use what that prints. If a value differs from the plan, **the label file wins** —
these are real documents, and the plan is quoting a measurement taken on
2026-07-31.

- [ ] **Step 2: Write the test**

```python
@pytest.mark.parametrize(
    "tax_id",
    [
        "221 193 789 09013",   # eval/golden/labels/r001.json, Metro Oil Subic
        "774-423-646-00011",   # eval/golden/labels/r002.json, Summit Fuel OPC
        "205-741-640-162",     # eval/golden/labels/r003.json, Serv Central
        "103-969-951-00000",   # r001's notes: RJ Printing Press, the printer TIN
    ],
)
def test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints(tax_id: str) -> None:
    """The false positive that would cost the most, pinned to real documents.

    These are Philippine BIR ``VAT Reg. TIN`` values, printed 3-3-3-N, and three
    of the four hold **fourteen** digits -- inside the 13-19 window a PAN
    occupies. They are silent only because ``_PAN_RE`` requires 4-4-4-N or
    4-6-5 grouping. **The grouping requirement is what protects them**, so a
    future widening to "any run of 13+ digits" would mask every merchant
    fingerprint in the corpus. ``save_extraction_run`` passes the whole
    extraction payload through ``redact_pan``, so ``merchant.tax_id`` reaches
    this rule even though it is not a correctable field.
    """
    assert redact_pan(tax_id) == tax_id
    assert redact_pan(f"VAT Reg. TIN {tax_id}") == f"VAT Reg. TIN {tax_id}"
```

- [ ] **Step 3: Run it**

Run: `python -m pytest tests/test_repository.py -k merchant_tax_ids -v`
Expected: **PASS**.

- [ ] **Step 4: Prove the grouping requirement is what makes it pass**

Absence-of-breakage again, so revert the guarantee rather than trusting GREEN.
Temporarily replace `_PAN_RE`'s first alternative with a grouping-agnostic run —
`\d{3,4}(?:[ .\-_/,]\d{3,7})+` — which is the "obvious" widening this test
exists to forbid.

Run: `python -m pytest tests/test_repository.py -k merchant_tax_ids -v`
Expected: **FAIL** on at least the three 14-digit values, showing them masked.

Restore `_PAN_RE`. Run: `git diff src/ --exit-code` — must print nothing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_repository.py
git commit -m "test(persist): pin the merchant TINs the grouping requirement protects"
```

---

### Task 6: Correct the three false sentences and record the policy

Three prose claims are falsified by the measurements, and one of them is in the
governing ADR. Per the project's rule: **a claim about what your own artefacts
say is itself a claim requiring a command** — grep for each, do not recall it.

**Files:**
- Modify: `frontend/src/review/ReceiptForm.tsx:33-38`
- Modify: `docs/adr/0007-pan-redaction-and-money-integrity.md:27-28`
- Modify: `src/receipts/persist/repository.py:124-130` (the `_PAN_RE` docstring)
- Create: `docs/adr/0018-pan-masking-policy.md`
- Modify: `docs/adr/README.md`

**Interfaces:**
- Consumes: the behaviour Tasks 2 and 3 shipped. Every sentence written here
  must describe what the tests from Tasks 2–5 assert.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Locate each claim rather than recalling it**

Run:
```bash
grep -n "any mix of" frontend/src/review/ReceiptForm.tsx docs/adr/0007-pan-redaction-and-money-integrity.md
grep -n "spaces and hyphens" docs/adr/0007-pan-redaction-and-money-integrity.md
grep -n "more than four" src/receipts/persist/repository.py
```

- [ ] **Step 2: Fix `ReceiptForm.tsx`**

The current sentence claims a 13–19 digit PAN in four-group or Amex grouping
with any of six separators is masked. Leak (a) falsified that, and the sentence
was written *in the commit whose purpose was removing false sentences*. Bound it
by the table it already introduces, the way `serializers.py:172` does — the
comment should say what was measured, not generalise from it:

```
 * stored.** `_plan_change` runs `redact_pan` over every coerced text value, so
 * a card number in any spelling the table below records is masked before it
 * reaches the column, and the `corrections` row records only the masked form,
 * so the original is not recoverable from the audit trail either. One spelling
 * is deliberately NOT fully masked: a run of MORE than four separated groups
 * keeps everything after its leading four groups in the clear -- never a full
 * card number on its own. Accepted by ruling rather than closed, because every
 * measured attempt to close it leaked something worse (ADR-0018).
 *
 * **What is masked is exactly the table below, and nothing is generalised from
 * it.** This claim has been wrong twice. The first version was measured on the
 * unseparated form alone and generalised to every separator; at the time, a
 * PAN separated by anything but a space or a hyphen was stored whole. The
 * second was measured on four-group forms with a 1-4 digit tail and
 * generalised to "13-19 digits"; at the time, `4111 1111 1111 11111` and
 * every longer tail was stored whole. Both were found by executing the code,
 * not by reading it. `tests/test_repository.py` is the binding measurement.
```

Keep the existing measured table below it, and **extend the table** with the
rows this branch changed, re-measured through the real `PATCH` route the way
the existing rows were (one fresh receipt per row, read back with
`GET /receipts/{id}`): a 4-4-4-5 spelling now masks; a five-group spelling
stores `'************1111 111'`. **Do not add a digit count or a test count to
this comment** — a number that can change without its sentence changing does
not go in a comment. One citation in this repo drifted `61 → 81 → 94 → 101`,
once inside the commit documenting the drift.

- [ ] **Step 3: Fix ADR-0007 with a dated correction**

Do not rewrite history — append a correction, matching how ADR-0013 records its
own dated correction:

```markdown
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
```

- [ ] **Step 4: Write ADR-0018**

Create `docs/adr/0018-pan-masking-policy.md`. Match the house format — read
`docs/adr/0016-review-next-resumes-the-callers-task.md` for the shape first.
**The authoritative source is the design doc's §2.1
(`docs/superpowers/specs/2026-07-31-pan-hardening-design.md`) — the ruling that
replaced the original greedy design. Do not describe the greedy design as
current anywhere.** The ADR must record, because each is a decision someone
will otherwise re-litigate:

1. **The whole detector change is one character:** the 4-4-4-N alternative's
   trailing group `\d{1,4}` → `\d{1,7}`, closing leak (a) — a four-group PAN
   with a 5–7 digit tail stored whole, 17–19 digits in the clear, the invariant
   violation. `_mask_pan` is unchanged.
2. **Leak (b) — more than four groups leaving the remainder clear — is ACCEPTED
   by user ruling (2026-07-31), not fixed.** Record both measured routes that
   were on the table and why each was refused: a greedy alternative swallowed a
   *second, adjacent card number* into one match (`re.sub` never rescans inside
   a match) and ate an adjacent amount's integer part; a scan loop controlling
   its own resume position closed (b) with neither regression but is O(n²) —
   ~1715 ms on a 40 KB adversarial run against ~4 ms. Seven digits of remainder
   is not a card number. Pinned by
   `test_redact_pan_leaves_a_run_of_more_than_four_groups_partly_masked`.
3. **The group-shape requirement is load-bearing** — the four corpus TINs, why
   they sit inside the 13–19 window, and that relaxing the grouping masks every
   merchant fingerprint. Name
   `test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints` as
   the guard.
4. **`(?!\.\d)` stays on the unseparated alternative alone**, with the measured
   consequence of moving it (`4111 **********1199`).
5. **`_mask_pan`'s length check is currently unreachable from `_PAN_RE`** —
   every alternative is bounded to 13–19 digits by construction — and is kept
   anyway as defence in depth on the hardest invariant.
6. **Redaction at the write boundary is default-on for extraction-sourced
   values only — scalar text columns AND the `modifiers` JSON** (`Modifier.label`
   is model text and the prompts route item-level promo lines into it; a JSON
   column is invisible to a String-typed column walk, which is how it stayed
   unredacted while every scalar was covered). System-minted values
   (`image_key`, `image_phash`, `status`, `confidence`, `merchant_id`) never
   pass through the PAN heuristic: an all-digit `image_phash` — the legal dHash
   of a uniform image — was masked into invalid hex, breaking `phash_distance`
   and the receipt's dedupe identity. The two-table column walk is the
   guarantee on the covered side;
   `test_save_extraction_never_corrupts_an_all_digit_image_phash` on the
   excluded side.
7. **Review reasons are redacted at the sink.** Exception text interpolates raw
   model values (`save_extraction`'s human-owned guard quotes `merchant.name`;
   `_bounded_optional_text` quotes the overlong value), and the pipeline
   persists `str(failure)` into `review_tasks.reason`. `enqueue_review` redacts
   `reason` on entry, covering every producer, present and future.
8. **The accepted false positives:** a value masks whenever it contains a run
   of 13+ consecutive digits. Concretely: a 13–19 digit all-numeric identifier;
   two column-scale amounts in one free-text value; roughly 1 in 200 random
   16-character hex hashes (measured 2026-07-31) — which is why NO hash is
   routed through `redact_pan`, not merely no all-digit one; and a whole-number
   13–19 digit modifier `amount` serialized to string by `model_dump` (a
   quadrillion-scale modifier amount is not a real value; anything with a
   fractional part is protected by `(?!\.\d)`).
9. **The rule for the next person:** widen nothing without replaying the
   committed battery in both directions, and always test the guard with **two
   instances of what it guards in one input** — every battery in this task's
   history held one card number per case, and that blind spot let a full PAN
   through a green suite twice. A hand-picked 34-case battery also missed
   `4111.1111.1111.1`.

- [ ] **Step 5: Index it**

Add the ADR-0018 row to `docs/adr/README.md`, matching the existing row format
exactly.

- [ ] **Step 6: Re-point the `_PAN_RE` comment at ADR-0018**

The `_PAN_RE` comment block was already rewritten during Task 2's fix rounds —
it now records the widening, both measured routes, and the attributed ruling.
**Do not rewrite it.** Two small edits only: (1) the ruling sentence points at
`docs/superpowers/specs/2026-07-31-pan-hardening-design.md` section 2.1 because
ADR-0018 did not exist yet — re-point it to ADR-0018 now that it does (find it
with `grep -n "2026-07-31-pan-hardening-design" src/receipts/persist/repository.py`);
(2) read the block end to end against the shipped behaviour and fix any
sentence a measurement falsifies — expected: none, it was re-reviewed twice.

- [ ] **Step 7: Verify every claim you just wrote**

For each sentence asserting behaviour, there must be a test that asserts it.

Run: `python -m pytest tests/test_repository.py -v`
Run: `grep -rn "spaces and hyphens" docs/ src/ frontend/src/` — expected: only
inside the dated correction, where it is quoted as stale.

- [ ] **Step 8: Frontend gates**

Run: `cd frontend && npm run typecheck && npm test`
Expected: clean, 170 passing. A comment-only change cannot break either, which
is exactly why it must still be run — `npm test` does not type-check, and that
trap fired three times in one milestone.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/review/ReceiptForm.tsx docs/adr/ src/receipts/persist/repository.py
git commit -m "docs: record the measured PAN masking policy and correct three false claims"
```

---

### Task 7: Whole-branch verification

**Files:** none modified.

- [ ] **Step 1: Run the gate runner**

Run: `python scripts/verify.py`
Expected: PASS on pytest, ruff, typecheck, vitest, build. It names the gate it
fails on. A `SKIPPED` line means `npm` was not found — that is not a pass.

- [ ] **Step 2: Run the CLI from outside the repository**

A green suite is not evidence that installed software works — that lesson cost
this project two false certifications.

Run, from a directory that is **not** the repo:
`python -m receipts.cli --help` and `python -m receipts.cli users --help`
Expected: both print help and exit 0.

- [ ] **Step 3: Confirm nothing from `var/` is staged**

Run: `git status --short` and `git log --stat main..HEAD`
Expected: no path under `var/`, no `results.xml`, no throwaway migration, and
no leftover mutation from Tasks 1, 4 or 5.

- [ ] **Step 4: Re-measure the four defects against the merged branch**

Reproduce, do not reason:

```bash
python -c "import sys; sys.path.insert(0,'src'); from receipts.persist.repository import redact_pan; [print(repr(v),'->',repr(redact_pan(v))) for v in ['4111 1111 1111 11111','4111 1111 1111 1111 111','4111 1111 1111 1111.99','221 193 789 09013']]"
```

Expected: `*************1111`, `***************1111`, `************1111.99`,
and the TIN unchanged.

- [ ] **Step 5: Report**

Report the final Python and Vitest counts, the gate results, and the three
mutation observations from Task 1 Step 4. Do not claim completion without the
command output.

---

## Out of scope

- The `>19`-digit residual — documented in ADR-0018, deliberately not fixed.
- Login rate limiting, the `corrections` read route, an ASGI entry point, an
  admin release for a claimed task, and the five design §5 error-recovery rows.
  Each is its own named piece of work in the Phase 5 ledger.
- Anything needing a real provider — ISSUE-001 stays deferred.
