# Phase 6 — Merchant Fingerprinting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognise a receipt's merchant before extraction, feed that merchant's
hints (and, on the Cloud tier, few-shot examples) into the extraction prompt, and
populate `receipts.merchant_id` so semantic dedupe can finally run.

**Architecture:** One new module, `receipts/merchants/registry.py`, is the only
code that touches the `merchants` table. Everything else is wiring: eight
components already exist and are called by nothing. Identity is two-phase —
`TriageResult.merchant_name_guess` retrieves a merchant before extraction, and the
extracted `tax_id` confirms it afterwards. No write path trusts a guess.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x ORM, Pydantic v2, pytest. In-memory
SQLite for tests (`PRAGMA foreign_keys=ON`). No network, no Node.

**Spec:** `docs/superpowers/specs/2026-08-14-merchant-fingerprinting-design.md`
— **read its dated note before Task 3**; it corrects §4's signature and rules out
the obvious few-shot source.

## Global Constraints

- **Money is `Decimal`, never `float`.** `tests/test_no_float_in_money_path.py`
  enforces it.
- **No fuzzy matching.** Exact match on normalized names and known variants only
  (spec D2). A miss means no hints and today's exact behaviour.
- **No write path trusts a guess.** `register` and `confirm` both require a
  `tax_id` from the extraction (spec D2).
- **Text hints on both tiers; few-shot images on the Cloud tier only** (spec D1).
  The pipeline decides; `registry` knows nothing about tiers.
- **A few-shot source must be `status='reviewed'`, have zero `corrections` rows,
  and exactly one `extraction_runs` row with `pass_name='extract'`** (spec D5 +
  its dated note).
- **Any value threaded into the extraction prompt must also be threaded into
  `_attempt_prompt_hash`.** Miss this and every recorded `prompt_hash` describes
  a prompt that was never sent.
- **Tests:** in-memory SQLite, `PRAGMA foreign_keys=ON`, mirroring
  `tests/test_dedupe_db.py`. There is no `conftest.py`; each file defines its own
  fixtures.
- **Run the suite with bare `python -m pytest`.** `pyproject.toml` sets
  `addopts = "-q"`, so `-q` becomes `-qq` and prints no pass count.
- **Lint:** `python -m ruff check .` must be clean.
- **Stage by explicit path. Never `git add -A`.**

---

### Task 1: Merchant lookup (the read path)

**Files:**
- Create: `src/receipts/merchants/__init__.py`
- Create: `src/receipts/merchants/registry.py`
- Test: `tests/test_merchant_registry.py`

**Interfaces:**
- Consumes: `normalize_merchant_name` from `receipts.normalize`; `Merchant` from
  `receipts.persist`.
- Produces: `lookup(session: Session, name_guess: str | None) -> Merchant | None`

- [ ] **Step 1: Write the failing test**

```python
"""The merchant registry: the only module that touches the `merchants` table.

In-memory SQLite with FK enforcement, mirroring `tests/test_dedupe_db.py`.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.merchants.registry import lookup
from receipts.persist import Merchant
from receipts.persist.models import Base


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


def _merchant(session: Session, name: str, **kw) -> Merchant:
    merchant = Merchant(canonical_name=name, **kw)
    session.add(merchant)
    session.flush()
    return merchant


def test_lookup_matches_the_canonical_name_exactly(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "METRO OIL SUBIC INC.")

        assert found is not None
        assert found.id == stored.id


def test_lookup_folds_case_punctuation_and_legal_suffix(engine: sa.Engine) -> None:
    """`normalize_merchant_name` is what makes these the same merchant."""
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "Metro Oil Subic Inc")

        assert found is not None
        assert found.id == stored.id


def test_lookup_matches_a_known_variant(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(
            session, "METRO OIL SUBIC INC.", name_variants=["METRO OIL SUBIC BAY"]
        )

        found = lookup(session, "metro oil subic bay")

        assert found is not None
        assert found.id == stored.id


def test_lookup_does_not_guess(engine: sa.Engine) -> None:
    """No fuzzy matching (spec D2): a near miss is a miss."""
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, "METRO 0IL SUBIC") is None


@pytest.mark.parametrize("guess", [None, "", "   ", "Inc."])
def test_lookup_returns_none_for_an_empty_guess(engine: sa.Engine, guess) -> None:
    """`"Inc."` normalizes to the empty string -- it is all legal suffix."""
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, guess) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_merchant_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receipts.merchants'`

- [ ] **Step 3: Create the package and implement `lookup`**

Create `src/receipts/merchants/__init__.py`:

```python
"""Merchant identity: recognise a merchant, and remember what it is called.

`registry` is the only module in the codebase that writes the `merchants`
table. Nothing here trusts a pre-extraction guess: a guess may retrieve a
merchant, but only an extracted `tax_id` may create or rename one.
"""

from .registry import lookup

__all__ = ["lookup"]
```

> **Export only what exists.** Tasks 2 and 3 each add their own names to this
> import and to `__all__` as they land. Listing all five here would make
> `import receipts.merchants` raise `ImportError` for the whole of Tasks 1 and 2.

Create `src/receipts/merchants/registry.py`:

```python
"""Read and write the `merchants` table (spec §8.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from receipts.normalize import normalize_merchant_name
from receipts.persist.models import Merchant


def _keys(merchant: Merchant) -> set[str]:
    """Every normalized spelling this merchant answers to."""
    names = [merchant.canonical_name, *(merchant.name_variants or [])]
    return {k for k in (normalize_merchant_name(n or "") for n in names) if k}


def lookup(session: Session, name_guess: str | None) -> Merchant | None:
    """The merchant whose canonical name or a known variant matches exactly.

    Matching is exact over `normalize_merchant_name`, which casefolds and strips
    legal suffixes, punctuation and branch codes -- so `METRO OIL SUBIC INC.`
    and `Metro Oil Subic Inc` are the same merchant. **There is deliberately no
    fuzzy matching** (spec D2): `merchant_name_guess` comes from triage, and a
    wrong match injects another merchant's hints into the prompt, which is worse
    than injecting none.

    Scans every merchant, because the normalizer is Python and cannot run in
    SQL. That is fine at this corpus's scale (one business's suppliers); if the
    table ever grows past a few thousand rows, store the normalized key as a
    column and index it.
    """
    if not name_guess:
        return None
    key = normalize_merchant_name(name_guess)
    if not key:
        return None

    for merchant in session.scalars(select(Merchant)).all():
        if key in _keys(merchant):
            return merchant
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_merchant_registry.py -v`
Expected: PASS, 8 tests (the parametrize contributes 4).

- [ ] **Step 5: Prove the no-fuzzy-matching test can fail**

Temporarily change `if key in _keys(merchant):` to
`if any(k.startswith(key[:6]) for k in _keys(merchant)):`.

Run: `python -m pytest tests/test_merchant_registry.py -v`
Expected: `test_lookup_does_not_guess` FAILS. **Revert the change** and re-run to
confirm green. A pin never proven red is not a pin.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/merchants/__init__.py src/receipts/merchants/registry.py tests/test_merchant_registry.py
git commit -m "feat(merchants): exact-match merchant lookup over normalized names"
```

---

### Task 2: The write paths — register, confirm, increment

**Files:**
- Modify: `src/receipts/merchants/registry.py`
- Test: `tests/test_merchant_registry.py`

**Interfaces:**
- Consumes: `lookup`, `_keys` from Task 1.
- Produces:
  - `register(session: Session, extraction: ReceiptExtraction) -> Merchant | None`
  - `confirm(session: Session, merchant: Merchant, tax_id: str | None, observed_name: str | None) -> None`
  - `increment(session: Session, merchant: Merchant) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_merchant_registry.py`:

```python
from receipts.extract.schema import Merchant as ExtractMerchant
from receipts.extract.schema import ReceiptExtraction
from receipts.merchants.registry import confirm, increment, register


def _extraction(name: str | None, tax_id: str | None) -> ReceiptExtraction:
    return ReceiptExtraction(merchant=ExtractMerchant(name=name, tax_id=tax_id))


def test_register_creates_a_merchant_from_a_confirmed_extraction(engine) -> None:
    with Session(engine) as session:
        created = register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))

        assert created is not None
        assert created.canonical_name == "METRO OIL SUBIC INC."
        assert created.tax_id == "123-456-789"


@pytest.mark.parametrize(
    ("name", "tax_id"),
    [("METRO OIL SUBIC INC.", None), (None, "123-456-789"), (None, None)],
)
def test_register_refuses_without_both_a_name_and_a_tax_id(engine, name, tax_id) -> None:
    """A guess must never create a merchant (spec D2)."""
    with Session(engine) as session:
        assert register(session, _extraction(name, tax_id)) is None
        assert session.scalars(select(Merchant)).all() == []


def test_register_returns_the_existing_merchant_for_a_known_tax_id(engine) -> None:
    with Session(engine) as session:
        first = register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))
        again = register(session, _extraction("METRO OIL SUBIC BAY", "123-456-789"))

        assert again is not None and first is not None
        assert again.id == first.id
        assert len(session.scalars(select(Merchant)).all()) == 1


def test_confirm_learns_a_new_spelling(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "123-456-789", "METRO OIL SUBIC BAY")

        assert merchant.name_variants == ["METRO OIL SUBIC BAY"]
        assert lookup(session, "metro oil subic bay") is not None


def test_confirm_ignores_a_mismatched_tax_id(engine) -> None:
    """The TIN is what authorises the rename. Without it, nothing is learned."""
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "999-999-999", "TOTALLY DIFFERENT SHOP")

        assert merchant.name_variants == []


def test_confirm_does_not_duplicate_a_spelling_it_already_knows(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "123-456-789", "Metro Oil Subic Inc")

        assert merchant.name_variants == []


def test_increment_counts_receipts(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.")
        assert merchant.receipt_count == 0

        increment(session, merchant)
        increment(session, merchant)

        assert merchant.receipt_count == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_merchant_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'confirm'`

- [ ] **Step 3: Implement the write paths**

Append to `src/receipts/merchants/registry.py`:

```python
def register(session: Session, extraction: ReceiptExtraction) -> Merchant | None:
    """Create a merchant from a **confirmed** extraction, or return None.

    Both a name and a `tax_id` are required. The TIN is the strongest identifier
    on this corpus, and requiring it is what stops a garbage
    `merchant_name_guess` from populating the table with noise (spec D2).

    An extraction whose `tax_id` is already known returns that merchant rather
    than creating a second row for it.
    """
    name = (extraction.merchant.name or "").strip()
    tax_id = (extraction.merchant.tax_id or "").strip()
    if not name or not tax_id:
        return None

    existing = session.scalars(
        select(Merchant).where(Merchant.tax_id == tax_id)
    ).first()
    if existing is not None:
        return existing

    merchant = Merchant(
        canonical_name=name, tax_id=tax_id, name_variants=[], hints=[]
    )
    session.add(merchant)
    session.flush()
    return merchant


def confirm(
    session: Session,
    merchant: Merchant,
    tax_id: str | None,
    observed_name: str | None,
) -> None:
    """Teach the registry a new spelling -- the ONLY path that widens matching.

    Gated on the extracted `tax_id` matching the merchant's. Without that gate a
    misrecognised receipt would permanently attach its merchant's name to the
    wrong row, and every later receipt with that spelling would inherit the
    wrong hints.

    The list is reassigned rather than mutated in place: `name_variants` is a
    JSON column, and SQLAlchemy does not track in-place mutation of one.
    """
    if not tax_id or not observed_name or merchant.tax_id != tax_id:
        return

    key = normalize_merchant_name(observed_name)
    if not key or key in _keys(merchant):
        return

    merchant.name_variants = [*(merchant.name_variants or []), observed_name]


def increment(session: Session, merchant: Merchant) -> None:
    """Bump `receipt_count`. Callers commit; this only stages the change."""
    merchant.receipt_count = (merchant.receipt_count or 0) + 1
```

Add to the imports at the top of `registry.py`:

```python
from receipts.extract.schema import ReceiptExtraction
```

Widen `src/receipts/merchants/__init__.py` to export what now exists:

```python
from .registry import confirm, increment, lookup, register

__all__ = ["confirm", "increment", "lookup", "register"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_merchant_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Prove the two guards can fail**

Revert them **one at a time** — a single mutation each, so a pass cannot be
credited to the wrong guard:

1. In `register`, change `if not name or not tax_id:` to `if not name:`.
   Expected: `test_register_refuses_without_both_a_name_and_a_tax_id` FAILS on the
   `tax_id=None` case. Revert.
2. In `confirm`, drop `or merchant.tax_id != tax_id` from the guard.
   Expected: `test_confirm_ignores_a_mismatched_tax_id` FAILS. Revert.

Re-run the file after reverting both and confirm green.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/merchants/__init__.py src/receipts/merchants/registry.py tests/test_merchant_registry.py
git commit -m "feat(merchants): create and rename merchants only on a confirmed tax id"
```

> `__init__.py` is in that list because Step 3 widens its exports. The first draft
> of this plan omitted it, which would have written the widening and not committed
> it.

---

### Task 3: Few-shot selection

**Read the spec's dated note first.** It rules out the obvious source and changes
this function's signature.

**Files:**
- Modify: `src/receipts/merchants/registry.py`
- Test: `tests/test_merchant_few_shots.py`

**Interfaces:**
- Consumes: `Merchant`, `Receipt`, `Correction`, `ExtractionRun`, `PassName` from
  `receipts.persist.models`; `ReceiptStatus` from `receipts.score.confidence`;
  `StorageBackend` from `receipts.ingest.storage`; `FewShot` from
  `receipts.extract.prompts`.
- Produces:
  `few_shots_for(session: Session, storage: StorageBackend, merchant: Merchant | None, limit: int = 2) -> list[FewShot]`

- [ ] **Step 1: Write the failing test**

```python
"""Few-shot candidate selection: only VERIFIED extractions may teach the model.

Spec D5 -- `status='reviewed'` AND zero `corrections` rows -- plus the dated
note's third condition: exactly one `extraction_runs` row with
`pass_name='extract'`, because `extract_with_repair` returns the BEST attempt
and `_persist_outcome` does not record which one that was.
"""

from __future__ import annotations

import base64
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.merchants.registry import few_shots_for
from receipts.persist import Merchant, Receipt
from receipts.persist.models import Base, Correction, ExtractionRun, PassName
from receipts.score.confidence import ReceiptStatus

IMAGE = b"\x89PNG\r\n\x1a\n-pretend-this-is-a-receipt"


class _Storage:
    """The two-method slice of StorageBackend this function uses."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, key: str) -> bytes:
        return self._blobs[key]


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


def _candidate(
    session: Session,
    merchant: Merchant,
    *,
    status: ReceiptStatus = ReceiptStatus.REVIEWED,
    corrections: int = 0,
    extract_runs: int = 1,
    tax_id: str = "123-456-789",
) -> Receipt:
    """A receipt plus the audit rows that decide whether it may teach."""
    receipt_id = uuid.uuid4()
    receipt = Receipt(
        id=receipt_id,
        merchant_id=merchant.id,
        image_key=f"receipts/{receipt_id}/original.jpg",
        image_phash="",  # NOT NULL with no default -- omit it and every test
                         # in this file dies on IntegrityError, not on the
                         # behaviour it means to assert.
        status=status,
    )
    session.add(receipt)
    session.flush()

    for i in range(extract_runs):
        session.add(
            ExtractionRun(
                receipt_id=receipt_id,
                pass_name=PassName.EXTRACT,
                attempt=i + 1,
                model_id="test-model",
                prompt_hash="0" * 16,
                raw_response={
                    "raw": None,
                    "parsed": {"merchant": {"name": "METRO OIL", "tax_id": tax_id}},
                    "parse_error": None,
                },
            )
        )
    for _ in range(corrections):
        session.add(
            Correction(
                receipt_id=receipt_id,
                field_path="total",
                value_before="1",
                value_after="2",
                corrected_by="alice",
            )
        )
    session.flush()
    return receipt


def _merchant(session: Session) -> Merchant:
    merchant = Merchant(canonical_name="METRO OIL SUBIC INC.", tax_id="123-456-789")
    session.add(merchant)
    session.flush()
    return merchant


def test_a_clean_reviewed_receipt_becomes_a_few_shot(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant)
        storage = _Storage({receipt.image_key: IMAGE})

        shots = few_shots_for(session, storage, merchant)

        assert len(shots) == 1
        assert shots[0].image_b64 == base64.b64encode(IMAGE).decode("ascii")
        assert shots[0].extraction.merchant.tax_id == "123-456-789"


def test_the_tax_id_survives_into_the_example(engine) -> None:
    """The whole reason `_export_extraction` is not the source (spec dated note)."""
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant)
        storage = _Storage({receipt.image_key: IMAGE})

        shots = few_shots_for(session, storage, merchant)

        assert shots[0].extraction.merchant.tax_id is not None


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"status": ReceiptStatus.AUTO_APPROVED}, "never reviewed by a human"),
        ({"status": ReceiptStatus.NEEDS_REVIEW}, "not reviewed yet"),
        ({"corrections": 1}, "a human changed something, so it taught an error"),
        ({"extract_runs": 2}, "which attempt won is not recorded"),
        ({"extract_runs": 0}, "no extraction to learn from"),
    ],
)
def test_unverified_receipts_never_teach(engine, kwargs, why) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant, **kwargs)
        storage = _Storage({receipt.image_key: IMAGE})

        assert few_shots_for(session, storage, merchant) == [], why


def test_no_merchant_means_no_few_shots(engine) -> None:
    with Session(engine) as session:
        assert few_shots_for(session, _Storage({}), None) == []


def test_limit_is_respected(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        blobs = {}
        for _ in range(3):
            receipt = _candidate(session, merchant)
            blobs[receipt.image_key] = IMAGE

        assert len(few_shots_for(session, _Storage(blobs), merchant, limit=2)) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_merchant_few_shots.py -v`
Expected: FAIL — `ImportError: cannot import name 'few_shots_for'`

- [ ] **Step 3: Implement `few_shots_for`**

Append to `src/receipts/merchants/registry.py`:

```python
def few_shots_for(
    session: Session,
    storage: StorageBackend,
    merchant: Merchant | None,
    limit: int = 2,
) -> list[P.FewShot]:
    """Verified prior extractions for this merchant, as in-context examples.

    Three conditions, and every one of them is about trust:

    * `status='reviewed'` -- a human looked at it;
    * **zero** rows in `corrections` -- the human changed nothing, so the stored
      extraction is what the model produced AND what the human accepted;
    * **exactly one** `extraction_runs` row with `pass_name='extract'` --
      `extract_with_repair` returns the best attempt rather than the last, and
      `_persist_outcome` does not record which one won, so more than one leaves
      the winner ambiguous.

    The extraction is rebuilt from `extraction_runs.raw_response["parsed"]`,
    **not** from the receipt row: `review/serializers.py`'s `_export_extraction`
    is lossy on `merchant.tax_id`, and an example asserting a null TIN would
    teach the model to omit the strongest identifier on this corpus.

    A receipt whose blob is missing is skipped rather than raised on -- a
    prompting aid must never be the reason a receipt fails to process.
    """
    if merchant is None or limit <= 0:
        return []

    corrected = select(Correction.receipt_id).distinct()
    extract_counts = (
        select(ExtractionRun.receipt_id, func.count().label("n"))
        .where(ExtractionRun.pass_name == PassName.EXTRACT)
        .group_by(ExtractionRun.receipt_id)
        .subquery()
    )

    rows = session.execute(
        select(Receipt, ExtractionRun)
        .join(extract_counts, extract_counts.c.receipt_id == Receipt.id)
        .join(
            ExtractionRun,
            (ExtractionRun.receipt_id == Receipt.id)
            & (ExtractionRun.pass_name == PassName.EXTRACT),
        )
        .where(
            Receipt.merchant_id == merchant.id,
            Receipt.status == ReceiptStatus.REVIEWED,
            Receipt.id.notin_(corrected),
            extract_counts.c.n == 1,
        )
        .order_by(Receipt.id)
        .limit(limit)
    ).all()

    shots: list[P.FewShot] = []
    for receipt, run in rows:
        parsed = (run.raw_response or {}).get("parsed")
        if not parsed:
            continue
        try:
            data = storage.get(receipt.image_key)
        except (KeyError, FileNotFoundError, OSError):
            log.warning("Few-shot blob missing for receipt %s; skipping", receipt.id)
            continue
        shots.append(
            P.FewShot(
                image_b64=base64.b64encode(data).decode("ascii"),
                extraction=ReceiptExtraction.model_validate(parsed),
            )
        )
    return shots
```

Add to the imports at the top of `registry.py`:

```python
import base64
import logging

from sqlalchemy import func

from receipts.extract import prompts as P
from receipts.ingest.storage import StorageBackend
from receipts.persist.models import Correction, ExtractionRun, PassName, Receipt
from receipts.score.confidence import ReceiptStatus

log = logging.getLogger(__name__)
```

Widen `src/receipts/merchants/__init__.py` a final time:

```python
from .registry import confirm, few_shots_for, increment, lookup, register

__all__ = ["confirm", "few_shots_for", "increment", "lookup", "register"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_merchant_few_shots.py -v`
Expected: PASS.

- [ ] **Step 5: Prove each trust condition independently**

Remove **one** `where` clause at a time and confirm exactly the matching
parametrized case fails, then restore it before removing the next:

| removed clause | expected failure |
|---|---|
| `Receipt.status == ReceiptStatus.REVIEWED` | the two `status` cases |
| `Receipt.id.notin_(corrected)` | the `corrections: 1` case |
| `extract_counts.c.n == 1` | the `extract_runs: 2` case |

Each guarantee must be reverted separately; a batch revert proves only that at
least one of them matters.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/merchants/registry.py tests/test_merchant_few_shots.py
git commit -m "feat(merchants): select few-shot examples only from verified extractions"
```

---

### Task 4: Thread hints into extraction AND the prompt hash

**This is the highest-risk task in the plan.** `_attempt_prompt_hash` rebuilds
each attempt's prompt to recover its hash. If hints reach the extraction call but
not the reconstruction, every recorded `prompt_hash` describes a prompt that was
never sent — silently, with every gate green — and the eval harness groups results
by `prompt_bundle_hash()`.

**Files:**
- Modify: `src/receipts/pipeline.py` (the `extract` stage; `_attempt_prompt_hash`;
  `_persist_outcome`'s call to it)
- Test: `tests/test_pipeline_merchant_hints.py`
- **Modify: `tests/test_process_receipt.py`** — it pins the `STAGES` tuple by
  exact equality, so adding `"merchant"` to `STAGES` necessarily reddens it.
  Update the pin, and add a `merchant`-stage case beside the other per-stage §18
  failure tests, which that file keeps one of per stage.

**Interfaces:**
- Consumes: `lookup` (Task 1), `few_shots_for` (Task 3).
- Produces: `_attempt_prompt_hash(..., hints: P.MerchantHints | None, few_shots: list[P.FewShot])`

- [ ] **Step 1: Write the failing test**

```python
"""Hints reach the extraction prompt AND the prompt hash rebuilt for the audit.

The second half is the point. `_attempt_prompt_hash` reconstructs each attempt's
prompt from its inputs; if it is not given the same hints the call used, the
stored `prompt_hash` names a prompt that never existed.
"""

from __future__ import annotations

from receipts.extract import prompts as P
from receipts.extract.schema import TriageResult


def _hints() -> P.MerchantHints:
    return P.MerchantHints(
        merchant_name="METRO OIL SUBIC INC.",
        hints=["fuel rows are pre-printed; trust the image"],
    )


def test_hints_change_the_extraction_prompt() -> None:
    triage = TriageResult()
    without = P.build_extraction_prompt(triage, None, [])
    with_hints = P.build_extraction_prompt(triage, _hints(), [])

    assert with_hints != without
    assert "METRO OIL SUBIC INC." in with_hints


def test_the_rebuilt_hash_matches_the_prompt_that_was_sent() -> None:
    """If this fails, the audit trail is lying about what was asked."""
    triage = TriageResult()
    hints = _hints()

    sent = P.prompt_hash(
        P.build_extraction_prompt(triage, hints, []) + P.SYSTEM_EXTRACTION
    )
    rebuilt = P.prompt_hash(
        P.build_extraction_prompt(triage, hints, []) + P.SYSTEM_EXTRACTION
    )
    unhinted = P.prompt_hash(
        P.build_extraction_prompt(triage, None, []) + P.SYSTEM_EXTRACTION
    )

    assert rebuilt == sent
    assert rebuilt != unhinted, "a hinted prompt must not hash like an unhinted one"
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_pipeline_merchant_hints.py -v`
Expected: both PASS immediately. **This is deliberate and is not the task's RED
phase.** They pin `prompts.py`, which already works, and exist to prove the
premise the wiring depends on: a hinted prompt does not hash like an unhinted
one. If either fails, stop — the task's whole approach is unsound.

**The real RED phase is Step 6**, which proves the coupling this task exists to
create. Do not skip it, and do not treat Step 2's green as evidence of anything
beyond `prompts.py` behaving.

- [ ] **Step 3: Change `_attempt_prompt_hash` to take the hints**

`Attempt` is already imported in `pipeline.py` from `receipts.extract.extractor`
— it is **not** in `receipts.persist.models`. You are editing an existing
signature, so no new import is needed for it.

In `src/receipts/pipeline.py`, change the signature and the final return:

```python
def _attempt_prompt_hash(
    attempt: Attempt,
    attempts: list[Attempt],
    attempt_number: int,
    triage_result: TriageResult,
    hints: P.MerchantHints | None = None,
    few_shots: list[P.FewShot] | None = None,
) -> str:
    """Reconstruct the `prompt_hash` for one attempt.

    Prompt building is pure, so rebuilding the prompt from what produced it
    gives the same 16-char hash the call used. **The hints and few-shots passed
    here must be the identical objects passed to `extract_with_repair`** -- a
    mismatch produces a hash for a prompt that was never sent, and nothing else
    in the system would notice.
    """
    if attempt.pass_name == "repair":
        previous = attempts[attempt_number - 2]
        return P.prompt_hash(
            P.build_repair_prompt(
                previous.extraction, previous.report.render_for_repair_prompt()
            )
        )
    return P.prompt_hash(
        P.build_extraction_prompt(triage_result, hints, few_shots or [])
        + P.SYSTEM_EXTRACTION
    )
```

- [ ] **Step 4: Thread hints through `process_receipt` and `_persist_outcome`**

In the `extract` stage of `process_receipt`, replace the `(M5)` comment:

Add the import at the top of `pipeline.py`:

```python
from receipts.merchants import registry
```

`registry.lookup` takes a `Session`, **not** a `session_factory`. Open a short
one, copy the two values out as plain Python, and close it before the model call
— a detached ORM instance held across a multi-minute inference call is a bug
waiting to happen, and on this hardware that call can take half an hour.

```python
        with _stage("merchant"):
            hints: P.MerchantHints | None = None
            with session_factory() as session:
                merchant = registry.lookup(session, triage_result.merchant_name_guess)
                if merchant is not None and merchant.hints:
                    hints = P.MerchantHints(
                        merchant_name=merchant.canonical_name,
                        hints=list(merchant.hints),
                    )
            # Few-shot IMAGES are Cloud-tier only (spec D1): on the local model
            # each example multiplies inference cost by one whole image. The
            # selector exists (registry.few_shots_for) and is deliberately not
            # called here -- see the note below.
            few_shots: list[P.FewShot] = []

        with _stage("extract"):
            outcome = extract_with_repair(
                image,
                guarded,
                triage_result=triage_result,
                ctx=ctx,
                hints=hints,
                few_shots=few_shots,
                max_repairs=max(0, settings.max_repair_attempts),
                normalize_fn=_normalizer(settings.default_currency),
            )
```

> **`few_shots` is empty on purpose, and `few_shots_for` is therefore uncalled by
> this milestone.** That is spec D1 plus spec §10: the local-to-Cloud escalation
> is its own work, so there is no Cloud tier here to attach images to. Task 3
> builds and pins the selector so the escalation milestone inherits a tested
> component rather than writing one under time pressure. **A reviewer should
> expect this and not file it as dead code** — but it *is* uncalled, and that is
> worth stating rather than discovering.

Pass both into `_persist_outcome` and on to `_attempt_prompt_hash`:

```python
                _attempt_prompt_hash(
                    attempt, outcome.attempts, attempt_number, triage_result,
                    hints, few_shots,
                ),
```

Add `"merchant"` to the `STAGES` tuple, immediately before `"extract"`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: PASS. `_stage("merchant")` means any registry failure marks the receipt
`needs_review` with `merchant` as the reason rather than raising — nothing is
silently dropped (§18).

- [ ] **Step 6: Prove the coupling**

In `_persist_outcome`, revert the `_attempt_prompt_hash` call to pass `None, []`
while leaving the extraction call hinted. Write a test that processes a receipt
whose merchant has hints and asserts the stored `extraction_runs.prompt_hash`
equals `P.prompt_hash(P.build_extraction_prompt(triage, hints, []) + P.SYSTEM_EXTRACTION)`.
Expected: FAIL. Restore, and confirm PASS.

**This test is the whole point of the task — do not skip it.**

- [ ] **Step 7: Commit**

```bash
git add src/receipts/pipeline.py tests/test_pipeline_merchant_hints.py tests/test_process_receipt.py
git commit -m "feat(pipeline): merchant hints reach the prompt and the recorded hash"
```

---

### Task 5: Persist merchant_id, and apply the merchant's default currency

**Files:**
- Modify: `src/receipts/pipeline.py` (`_persist_outcome`)
- Test: `tests/test_pipeline_merchant_hints.py`

**Interfaces:**
- Consumes: `register`, `confirm`, `increment` (Task 2).
- Produces: `receipts.merchant_id` populated for confirmed merchants.

- [ ] **Step 1: Write the failing test**

```python
def test_a_confirmed_extraction_populates_merchant_id(session_factory, storage, settings):
    """Without this, semantic dedupe stays blind and receipt_count stays zero."""
    job = _job(storage)
    client = _Client([_triage(), _good_with_tax_id()])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.merchant_id is not None
        merchant = session.get(Merchant, receipt.merchant_id)
        assert merchant.tax_id == "123-456-789"
        assert merchant.receipt_count == 1
```

Copy `_job`, `_Client`, `_triage`, `_run`, `session_factory`, `storage` and
`settings` from `tests/test_process_receipt.py`; add `_good_with_tax_id()`
returning `_good()` with `merchant.tax_id` set to `"123-456-789"`.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_pipeline_merchant_hints.py -v -k merchant_id`
Expected: FAIL — `assert None is not None`.

- [ ] **Step 3: Resolve and persist the merchant**

Inside `_persist_outcome`'s session, before `save_extraction`:

> **[CORRECTED 2026-08-14 during execution — the ordering below is WRONG. Resolve
> by TIN FIRST.]** The original read `lookup` → then `register`/`confirm`. Two
> defects, both proven by driving the real registry:
>
> * **`confirm` becomes dead code.** `lookup` matches on
>   `normalize_merchant_name(name)`, and `confirm` recomputes that same key from
>   that same string — so `key in _keys(merchant)` always holds and `confirm`'s own
>   guard discards every call. Under this ordering `confirm` can never widen
>   anything, for anybody.
> * **A second business is never registered.** A merchant sharing a normalized name
>   with an incumbent resolves to the incumbent forever, and its receipts are
>   attributed to the wrong company. Measured: 1 merchant row where TIN-first
>   gives 2.
>
> Use `register` (TIN-authoritative) first, falling back to `lookup` by name:

```python
        extracted = outcome.extraction
        # TIN first: it is the authoritative identifier, and it is the only
        # thing that may create a merchant. Name lookup is the fallback for an
        # extraction whose TIN the model could not read.
        merchant_row = registry.register(session, extracted)
        if merchant_row is not None:
            registry.confirm(
                session,
                merchant_row,
                extracted.merchant.tax_id,
                extracted.merchant.name,
            )
        else:
            merchant_row = registry.lookup(session, extracted.merchant.name)
        if merchant_row is not None:
            registry.increment(session, merchant_row)
```

> **What a populated `merchant_id` does and does not guarantee.** The `lookup`
> fallback means a TIN-less extraction whose *name* matches a registered merchant
> still gets `merchant_id` set and still credits `receipt_count`. That is
> deliberate — `lookup` refuses ambiguous keys, so a name match is a real match —
> but it means **`merchant_id` is not proof that a TIN was read.** Task 6 keys
> semantic dedupe on this column, so read that sentence before relying on it.

Pass `merchant_id=merchant_row.id if merchant_row else None` to `save_extraction`
— the keyword already exists on it.

- [ ] **Step 4: Apply the merchant's default currency**

`_normalizer(settings.default_currency)` is the global fallback. Where a merchant
is known and carries `default_currency`, prefer it. **Locate the `_normalizer`
call by symbol, not by line number** — `pipeline.py` has grown.

> **[CORRECTED 2026-08-14 during execution — do NOT write
> `merchant.default_currency or settings.default_currency`.]** That collapses a
> three-step chain into one value. `normalize_currency` walks
> `(printed, merchant_default, system_default)` and `_as_iso_code` returns `None`
> for an unrecognised code — so collapsing it means an unrecognised merchant
> currency stores **no currency at all** instead of falling through to the system
> default. Measured: collapsed → `None`, chained → `PHP`. Pass the two defaults
> separately and let the chain do its job.

Because the merchant is only known *after* triage, this applies from the
`merchant` stage onward, which is where the normalizer is constructed.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/pipeline.py tests/test_pipeline_merchant_hints.py
git commit -m "feat(pipeline): populate merchant_id and prefer the merchant's currency"
```

---

### Task 6: Semantic dedupe

**It cannot run where image dedupe runs.** That stage is pre-extraction;
`merchant_id`, `txn_date` and `total` do not exist until after. **It therefore
never saves a model call** — by the time a semantic duplicate is detectable it has
already been paid for in full. Do not cite §18 cost control for this path.

**Files:**
- Modify: `src/receipts/pipeline.py` (`_persist_outcome`)
- Test: `tests/test_pipeline_semantic_dedupe.py`

**Interfaces:**
- Consumes: `find_duplicate_by_content`, `mark_duplicate` from `receipts.persist`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_second_receipt_from_the_same_merchant_date_and_total_is_a_duplicate(
    session_factory, storage, settings
):
    first = _job(storage)
    _run(first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=7))  # a different image
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )

    assert result.duplicate_of == first.id
    with session_factory() as session:
        row = session.get(Receipt, second.id)
        assert row.status is ReceiptStatus.REJECTED
        assert row.total is not None, "the paid-for extraction is kept (spec D4)"


def test_two_unresolved_merchants_are_never_merged(session_factory, storage, settings):
    """The pipeline is stricter than the repository: NULL merchant_id never matches.

    `find_duplicate_by_content` permits NULL-to-NULL. Under exact-match-only
    resolution many early receipts have no merchant, and two different shops
    sharing a date and total would otherwise be merged.
    """
    first = _job(storage)
    _run(first, _Client([_triage(), _good_no_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=9))
    result = _run(
        second, _Client([_triage(), _good_no_tax_id()]), session_factory, storage, settings
    )

    assert result.duplicate_of is None
```

`_good_no_tax_id()` is `_good()` with `merchant.tax_id = None`, so no merchant is
registered and `merchant_id` stays NULL on both rows.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_pipeline_semantic_dedupe.py -v`
Expected: the first FAILS (`assert None == UUID(...)`); the second PASSES
vacuously, because nothing dedupes yet. **Both matter** — the second is the guard
that must still pass after Step 3.

- [ ] **Step 3: Add the check inside `_persist_outcome`**

After the merchant is resolved and before `save_extraction`:

```python
        if merchant_row is not None:
            duplicate = find_duplicate_by_content(
                session,
                merchant_row.id,
                _txn_date(outcome.extraction),
                outcome.extraction.totals.total,
                exclude_id=job.id,
            )
            if duplicate is not None:
                status = ReceiptStatus.REJECTED
                priority = -1
                reason = f"duplicate of receipt {duplicate.id}"
```

Then after `save_extraction` returns, call
`mark_duplicate(session, receipt.id, duplicate.id)` and set
`ProcessResult.duplicate_of`.

**The `merchant_row is not None` guard is load-bearing** and is the restriction
this milestone adds over the repository's own contract. `mark_duplicate` already
raises `ValueError` on a dangling FK or a cycle, so the chain cannot be corrupted.

Use the same date the row is persisted with, so the stored value and the dedupe
key cannot disagree; reuse whatever `save_extraction` uses to derive `txn_date`
rather than reparsing.

- [ ] **Step 4: Run both tests, then the full suite**

Run: `python -m pytest tests/test_pipeline_semantic_dedupe.py -v`
Expected: both PASS.
Run: `python -m pytest`
Expected: PASS.

- [ ] **Step 5: Prove the NULL guard**

Remove `if merchant_row is not None:` around the dedupe block.
Expected: `test_two_unresolved_merchants_are_never_merged` FAILS. Restore and
re-run.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/pipeline.py tests/test_pipeline_semantic_dedupe.py
git commit -m "feat(pipeline): semantic dedupe, and never on an unresolved merchant"
```

---

### Task 7: The CLI stops printing a placeholder it no longer needs

`receipts merchants list` prints `-` for `receipt_count`, and its `description`
explains that nothing increments the column. Task 5 made that false. **A stale
explanation is a defect here, not a cosmetic issue.**

**This task REPLACES an existing test rather than adding one.**
`tests/test_cli_reports.py::test_merchants_list_does_not_print_a_confident_zero_receipt_count`
currently pins the `-`, and its docstring says *"`merchants.receipt_count` is
never incremented before Phase 6"*. **Its name is a claim too** — leaving the
name while inverting the body is the copy-that-greps-miss failure this project
keeps paying for.

**Files:**
- Modify: `src/receipts/cli.py` (`_add_merchants` description, the `list` handler,
  and the `_RECEIPT_COUNT_NOT_TRACKED` constant)
- Modify: `tests/test_cli_reports.py`

**Interfaces:** none produced.

- [ ] **Step 1: Replace the existing test**

Delete `test_merchants_list_does_not_print_a_confident_zero_receipt_count`
entirely — docstring included — and put this in its place. The helpers
(`_merchant`, `cmd_merchants`, `build_parser`, `EXIT_OK`) are already imported in
that file; `_merchant` needs a `receipt_count` keyword adding to it:

```python
def test_merchants_list_prints_the_real_receipt_count(session_factory, capsys):
    """Phase 6 increments `receipt_count`, so printing it is no longer a lie.

    This replaces a test that pinned a `-` placeholder. The placeholder existed
    because nothing incremented the column and a column of `0`s would have read
    as "no receipts" rather than "not counted".
    """
    _merchant(
        session_factory,
        canonical_name="METRO OIL SUBIC, INC.",
        tax_id="221 193 789 09013",
        receipt_count=3,
    )

    code = cmd_merchants(
        build_parser().parse_args(["merchants", "list"]),
        session_factory=session_factory,
    )

    assert code == EXIT_OK
    line = capsys.readouterr().out.strip()
    assert line.split("\t")[-1] == "3"
```

Widen the `_merchant` helper in the same file:

```python
def _merchant(
    session_factory, *, canonical_name: str, tax_id: str | None = None,
    receipt_count: int = 0,
) -> uuid.UUID:
    """One merchants row. ``name_variants``/``hints`` default to [] via the ORM."""
    merchant = Merchant(
        id=uuid.uuid4(), canonical_name=canonical_name, tax_id=tax_id,
        receipt_count=receipt_count,
    )
    with session_factory() as session:
        session.add(merchant)
        session.commit()
        return merchant.id
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_cli_reports.py -v -k receipt_count`
Expected: FAIL — `assert '-' == '3'`.

- [ ] **Step 3: Print the number and delete the stale explanation**

Replace `_RECEIPT_COUNT_NOT_TRACKED` in the `list` handler with
`merchant.receipt_count`, delete the now-unused constant, and rewrite the
subparser `description` so it no longer claims the count is untracked. **Delete
the claim rather than rewording it** — a correction that keeps explaining itself
is how this project's prose defects propagate.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_cli_reports.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm the constant is gone**

Run: `git grep -n "_RECEIPT_COUNT_NOT_TRACKED"`
Expected: no output. A leftover constant is a leftover claim.

- [ ] **Step 6: Final verification and commit**

```bash
python -m pytest
python -m ruff check .
git add src/receipts/cli.py tests/test_cli_reports.py
git commit -m "fix(cli): merchants list prints a real receipt count"
```

---

## Closing checks

- [ ] `python scripts/verify.py` — all five gates PASS. **Background it**; it
      exceeds a two-minute timeout, and do not edit source while it runs.
- [ ] `git grep -n "(M5)"` — every marker this plan addresses is gone or its
      comment updated. A marker pointing at finished work is a false claim.
- [ ] No accuracy claim anywhere in the diff. Nothing here can be measured until
      ISSUE-001's baseline runs; saying hints improve extraction is a hypothesis.
