# Corrections Read Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `GET /receipts/{receipt_id}/corrections` — one receipt's correction history, readable by the reviewer who holds or held it and by any admin.

**Architecture:** A scoped reader `list_corrections` in `review/queue.py` beside `list_tasks`, borrowing its `visible_to=None`-is-admin convention and returning `list[Correction] | None` so that "not permitted" and "none exist" stay distinguishable. A `correction_summary` serializer, a shared `_PageResponse` base for the now-three page envelopes, and a thin route in `_install_read_routes` that checks existence (404) before scope (403).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.x ORM, Pydantic v2, pytest.

**Design:** `docs/superpowers/specs/2026-08-10-corrections-read-route-design.md` (approved 2026-08-10).

## Global Constraints

- **Money is a string** (ADR-0001). `value_before` / `value_after` are already `Text`; they pass through as `str | None` and are **never** re-parsed through `money()`.
- **`null` ≠ `0` ≠ empty** (ADR-0027 §4). `None` from `list_corrections` means *not permitted*; `[]` means *permitted, none exist*. Never collapse them.
- **Pure read** (ADR-0006): explicit `Session` first positional arg, no flush, no commit, no `ValueError`.
- **A full PAN is never persisted, and now never served.** This route makes `corrections.value_after` HTTP-readable for the first time. No redaction is added here; the write-side invariant is relied on and pinned (Task 3, Step 9).
- **No frontend work.** Nothing under `frontend/`.
- **`python scripts/verify.py` is what "passing" means** (ADR-0017). `npm test` does not type-check.
- **Baseline to preserve: 979 pytest, 346 Vitest across 25 files.** Vitest must not move at all — no frontend file is touched.
- **Bound for every task:** all 979 existing tests pass **unmodified**. Anything that needs an existing test changed is a **stop-and-report**, not a fix.
- Run the suite with bare `python -m pytest` — `pyproject.toml` sets `addopts = "-q"`, so `-q` prints no pass count.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/receipts/review/queue.py` | Modify | Add `list_corrections` — the scoped read and the only place the scope predicate lives |
| `src/receipts/review/__init__.py` | Modify | Re-export `list_corrections` |
| `src/receipts/review/serializers.py` | Modify | Add `correction_summary` — one `Correction` row as JSON |
| `src/receipts/review/schemas.py` | Modify | Add `_PageResponse` base; reparent the two existing envelopes; add `CorrectionListResponse` |
| `src/receipts/review/api.py` | Modify | Register the route in `_install_read_routes` |
| `tests/test_review_queue.py` | Modify | Queue-level scope, the None-vs-`[]` pin, ordering |
| `tests/test_api_read.py` | Modify | Route-level status codes, pagination both directions, the `READ_ROUTES` comment |
| `tests/test_api_write.py` | Modify | The PAN pin for the new HTTP surface |

`correction_summary` goes in `serializers.py` (whose job is rendering rows as JSON, and which already imports `ReviewTask`) rather than beside `_task_summary` in `api.py`. `api.py` is 934 lines; `serializers.py` is 492. `_task_summary`'s placement in `api.py` was already corrected once — `docs/MEMORY.md` records it was moved out from under a "Write routes" banner when a read route began consuming it.

---

### Task 1: `list_corrections` — the scoped read

**Files:**
- Modify: `src/receipts/review/queue.py`
- Modify: `src/receipts/review/__init__.py`
- Test: `tests/test_review_queue.py`

**Interfaces:**
- Consumes: `Correction` from `..persist.models`; `ReviewTask`, `ReviewState` already imported by `queue.py`.
- Produces:
  ```python
  def list_corrections(
      session: Session,
      receipt_id: uuid.UUID,
      *,
      visible_to: str | None = None,
      limit: int = 50,
      offset: int = 0,
  ) -> list[Correction] | None
  ```
  `None` = the caller may not see this receipt's history. `[]` = they may, and there is none. Task 3 maps `None` → 403.

- [ ] **Step 1: Add the test helper and the first failing tests**

In `tests/test_review_queue.py`, add `Correction` to the `receipts.persist` import and `list_corrections` to the `receipts.review` import. Then append:

```python
def _correction(
    session: Session,
    receipt_id: uuid.UUID,
    field_path: str,
    *,
    before: str | None,
    after: str | None,
    by: str = "alice",
    at: datetime | None = None,
) -> Correction:
    """One audit row. ``at`` is explicit where ordering is under test, because
    SQLite's CURRENT_TIMESTAMP resolves only to the second."""
    row = Correction(
        receipt_id=receipt_id,
        field_path=field_path,
        value_before=before,
        value_after=after,
        corrected_by=by,
    )
    if at is not None:
        row.created_at = at
    session.add(row)
    session.flush()
    return row


def test_list_corrections_is_unrestricted_for_the_admin_case(engine: sa.Engine):
    """``visible_to=None`` needs no review task at all -- an auto-approved
    receipt that was never queued still has readable history for an admin."""
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        rows = list_corrections(session, receipt.id)

        assert rows is not None
        assert [row.field_path for row in rows] == ["receipt.total"]


def test_list_corrections_refuses_a_receipt_the_reviewer_never_held(engine: sa.Engine):
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        assert list_corrections(session, receipt.id, visible_to="carol") is None


def test_refusal_and_emptiness_are_different_answers(engine: sa.Engine):
    """The pin that keeps 403 reachable.

    ``None`` is "you may not see this"; ``[]`` is "you may, and there is
    none". Flattening the return type to ``list[Correction]`` -- returning
    ``[]`` for both -- turns the route's 403 into an indistinguishable empty
    200, which is ADR-0027 section 4's collapse one layer below the UI. This
    test is the one that goes red for it.
    """
    with Session(engine) as session:
        held = _receipt(session)
        session.add(
            ReviewTask(receipt_id=held.id, reason="quick verify", assigned_to="carol",
                       state=ReviewState.DONE)
        )
        never_held = _receipt(session)
        session.commit()

        assert list_corrections(session, held.id, visible_to="carol") == []
        assert list_corrections(session, never_held.id, visible_to="carol") is None


def test_a_closed_task_still_grants_its_holder_the_history(engine: sa.Engine):
    """"Held **or previously held**" -- the 2026-08-10 ruling.

    ``close_task`` deliberately leaves ``assigned_to`` set on a ``DONE`` task
    (ADR-0025), so a reviewer keeps the history of what they reviewed. Goes red
    if the scope narrows to ``state == IN_PROGRESS``.
    """
    with Session(engine) as session:
        receipt = _receipt(session)
        session.add(
            ReviewTask(receipt_id=receipt.id, reason="quick verify", assigned_to="carol",
                       state=ReviewState.DONE)
        )
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        rows = list_corrections(session, receipt.id, visible_to="carol")

        assert rows is not None and len(rows) == 1


def test_list_corrections_orders_oldest_first(engine: sa.Engine):
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "second", before=None, after="b",
                    at=datetime(2026, 7, 3, 9, 0, 1, tzinfo=UTC))
        _correction(session, receipt.id, "first", before=None, after="a",
                    at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC))
        session.commit()

        rows = list_corrections(session, receipt.id)

        assert [row.field_path for row in rows] == ["first", "second"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_review_queue.py -k corrections_or_refusal --no-header`

Better, run the five by name:

```
python -m pytest tests/test_review_queue.py -k "list_corrections or refusal_and_emptiness or closed_task_still_grants" --no-header
```

Expected: **collection error** — `ImportError: cannot import name 'list_corrections' from 'receipts.review'`. That is the correct first failure; it proves the import wiring is part of the deliverable.

- [ ] **Step 3: Implement `list_corrections`**

In `src/receipts/review/queue.py`, extend the models import to include `Correction`:

```python
from ..persist.models import Correction, Receipt, ReviewState, ReviewTask
```

Then add, directly below `list_tasks`:

```python
def list_corrections(
    session: Session,
    receipt_id: uuid.UUID,
    *,
    visible_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Correction] | None:
    """One receipt's correction history, or ``None`` if this caller may not see it.

    ``visible_to=None`` is unrestricted -- the admin case, spelled explicitly at
    the call site rather than as a bare boolean, exactly as :func:`list_tasks`
    spells it. A username scopes to receipts that caller **holds or has held**:
    any ``review_tasks`` row assigned to them, in any state. ``close_task``
    leaves ``assigned_to`` set on a ``DONE`` task (ADR-0025), which is what makes
    "has held" expressible at all, and what lets a reviewer see the corrections
    they themselves just made.

    **Two different negatives, deliberately not merged.** ``None`` means the
    caller may not read this receipt's history; ``[]`` means they may and there
    is none. A single ``list`` return would make the route unable to answer 403
    at all, and would answer "there are no corrections" -- which is false -- to
    someone who simply is not entitled to know. That is ADR-0027 section 4's
    ``null`` is not ``0`` is not empty, one layer below the UI, and
    ``test_refusal_and_emptiness_are_different_answers`` is its pin.

    Scope deliberately **excludes** the ``state == OPEN`` half of
    :func:`list_tasks`' reviewer scope. That half exists to show a reviewer the
    backlog they may claim; correction history is not backlog, and including it
    would disclose every unclaimed receipt's attribution to every reviewer.

    Ordered ``created_at`` then ``id``. ``id`` is a UUID and carries no time, so
    it is a tiebreaker only -- but a necessary one: one ``apply_corrections``
    call writes every row of a patch in a single flush, so ties are the normal
    case.

    A pure read: no flush, no commit, no ``ValueError``. The route validates
    ``limit`` and ``offset`` before this is reached.
    """
    if visible_to is not None:
        held = session.scalar(
            select(ReviewTask.id)
            .where(ReviewTask.receipt_id == receipt_id)
            .where(ReviewTask.assigned_to == visible_to)
            .limit(1)
        )
        if held is None:
            return None

    query = (
        select(Correction)
        .where(Correction.receipt_id == receipt_id)
        .order_by(Correction.created_at, Correction.id)
    )
    return list(session.scalars(query.limit(limit).offset(offset)))
```

- [ ] **Step 4: Export it**

In `src/receipts/review/__init__.py`, add `"list_corrections"` to `__all__` (alphabetically, between `"enqueue_review"` and `"list_tasks"`) and add it to the `from .queue import (...)` block in the same alphabetical position.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_review_queue.py --no-header`
Expected: PASS, with 5 more tests than before.

- [ ] **Step 6: Prove the scope predicate is load-bearing (mutation)**

Delete the `.where(ReviewTask.assigned_to == visible_to)` line, run `python -m pytest tests/test_review_queue.py --no-header`, and confirm `test_list_corrections_refuses_a_receipt_the_reviewer_never_held` and `test_refusal_and_emptiness_are_different_answers` go **red**. Read the failure text — confirm it is the assertion the pin exists for, not an incidental error (review standard 15). **Restore the line.**

- [ ] **Step 7: Run the full Python suite and commit**

Run: `python -m pytest`
Expected: `984 passed` (979 + 5). If any pre-existing test changed status, **stop and report**.

```bash
git add src/receipts/review/queue.py src/receipts/review/__init__.py tests/test_review_queue.py
git commit -m "feat: list_corrections, scoped to who holds or held the receipt"
```

---

### Task 2: The serializer and the third page envelope

**Files:**
- Modify: `src/receipts/review/serializers.py`
- Modify: `src/receipts/review/schemas.py`
- Test: `tests/test_review_queue.py` is untouched here; serializer tests go in `tests/test_api_read.py` alongside the route in Task 3. This task's own proof is the type check plus the two existing envelopes staying byte-compatible.

**Interfaces:**
- Consumes: `Correction` from `..persist.models`.
- Produces:
  ```python
  def correction_summary(correction: Correction) -> dict[str, Any]
  class CorrectionListResponse(_PageResponse)   # items: list[dict[str, Any]], has_more: bool
  ```

- [ ] **Step 1: Write the failing serializer test**

Append to `tests/test_api_read.py` (it already has the fixtures Task 3 needs, and `correction_summary` is only ever consumed by that route):

```python
def test_correction_summary_renders_a_row_without_inventing_precision():
    """``value_before``/``value_after`` are already text -- ``_as_text`` rendered
    them at write time. Re-parsing them as ``Decimal`` to re-render would invent
    precision the audit trail never recorded, and would fail outright on the
    ``field_path``s that are not money. ``None`` stays ``None``: the field had no
    value on that side of the change, which is not ``"0"`` and not ``""``.
    """
    row = Correction(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        receipt_id=RECEIPT_B,
        field_path="receipt.total",
        value_before=None,
        value_after="1000",
        corrected_by="alice",
        created_at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC),
    )

    assert correction_summary(row) == {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "field_path": "receipt.total",
        "value_before": None,
        "value_after": "1000",
        "corrected_by": "alice",
        "created_at": "2026-07-03T09:00:00+00:00",
    }
```

Add `Correction` to the `receipts.persist` import and `correction_summary` to the `receipts.review.serializers` import in that module.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_api_read.py -k correction_summary --no-header`
Expected: collection error — `ImportError: cannot import name 'correction_summary'`.

- [ ] **Step 3: Implement the serializer**

In `src/receipts/review/serializers.py`, add `Correction` to the `..persist.models` import, add `"correction_summary"` to `__all__` (first, alphabetically before `"money"`), and add the function beside `_finding`:

```python
def correction_summary(correction: Correction) -> dict[str, Any]:
    """One ``corrections`` row as JSON (``GET /receipts/{id}/corrections``).

    ``receipt_id`` is deliberately absent: the route is nested under the
    receipt, so every row on a page shares the id already in the request path.

    ``value_before``/``value_after`` pass through as text and do **not** go
    through :func:`money`. They were rendered by ``_as_text`` at write time and
    the columns are ``Text``; re-parsing a stored string to re-render it would
    invent precision the audit trail never recorded, and most ``field_path``
    values are not money at all. ``None`` means the field had no value on that
    side of the change -- not ``"0"``, not empty (ADR-0027 section 4).
    """
    return {
        "id": str(correction.id),
        "field_path": correction.field_path,
        "value_before": correction.value_before,
        "value_after": correction.value_after,
        "corrected_by": correction.corrected_by,
        "created_at": correction.created_at.isoformat(),
    }
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_api_read.py -k correction_summary --no-header`
Expected: PASS.

- [ ] **Step 5: Introduce the shared page envelope**

`docs/MEMORY.md`'s deferred follow-ups records: *"`ReviewTaskListResponse`'s body is byte-identical to `ReceiptListResponse`'s. Defensible — distinct response models give distinct OpenAPI schema names — but a third page envelope earns a base."* This is the third. In `src/receipts/review/schemas.py`, replace the two existing class bodies and add the third:

```python
class _PageResponse(BaseModel):
    """One page of rows, plus whether another exists.

    Three routes share this body. Each keeps its **own** subclass rather than
    reusing this one directly, because distinct response models give distinct
    OpenAPI schema names -- that was the recorded reason the bodies were
    duplicated, and subclassing preserves it while removing the copy.

    ``items`` stays ``dict[str, Any]``: the payload's real shape is proven
    against the serializers in ``tests/test_api_read.py``, and redeclaring it
    here would be one more place for the two to drift silently. See this
    module's docstring.
    """

    items: list[dict[str, Any]]
    has_more: bool


class ReceiptListResponse(_PageResponse):
    """One page of :func:`receipt_summary` rows (``GET /receipts``).

    ``has_more`` is read off the extra row a ``limit + 1`` fetch returns, not
    a ``COUNT(*)`` -- see ``_install_read_routes``.
    """


class ReviewTaskListResponse(_PageResponse):
    """One page of ``_task_summary`` rows (``GET /review/tasks``)."""


class CorrectionListResponse(_PageResponse):
    """One page of :func:`correction_summary` rows
    (``GET /receipts/{receipt_id}/corrections``).

    A page here is one receipt's audit trail, oldest first.
    """
```

Add `"CorrectionListResponse"` to `__all__` (alphabetically, after `"CorrectionPatch"`).

- [ ] **Step 6: Verify the two existing envelopes did not change shape**

Run: `python -m pytest tests/test_api_read.py tests/test_api_write.py --no-header`
Expected: PASS, unchanged. Any failure here means the reparenting altered a wire body — **stop and report**; do not adjust an existing test to match.

- [ ] **Step 7: Type-check and commit**

Run: `python -m ruff check .` then `python -m pytest`
Expected: ruff clean; `985 passed` (984 + 1).

```bash
git add src/receipts/review/serializers.py src/receipts/review/schemas.py tests/test_api_read.py
git commit -m "feat: correction_summary, and a shared base for the three page envelopes"
```

---

### Task 3: The route

**Files:**
- Modify: `src/receipts/review/api.py`
- Test: `tests/test_api_read.py`, `tests/test_api_write.py`

**Interfaces:**
- Consumes: `list_corrections` (Task 1), `correction_summary` and `CorrectionListResponse` (Task 2), plus `get_receipt`, `require_user`, `ROLE_ADMIN`, `Query`, `HTTPException` — all already imported by `api.py`.
- Produces: `GET /receipts/{receipt_id}/corrections`.

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_api_read.py`:

```python
def _corrections_for(session_factory, receipt_id: uuid.UUID, *, by: str = "alice") -> None:
    """Two audit rows, timestamps explicit so ordering is under test."""
    with session_factory() as session:
        session.add_all(
            [
                Correction(receipt_id=receipt_id, field_path="receipt.total",
                           value_before="900", value_after="1000", corrected_by=by,
                           created_at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)),
                Correction(receipt_id=receipt_id, field_path="payment.method",
                           value_before=None, value_after="VISA", corrected_by=by,
                           created_at=datetime(2026, 7, 3, 9, 0, 1, tzinfo=UTC)),
            ]
        )
        session.commit()


def test_an_admin_reads_a_receipt_they_never_held(session_factory, admin_client, receipt_id):
    _corrections_for(session_factory, receipt_id)

    response = admin_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    body = response.json()
    assert [row["field_path"] for row in body["items"]] == ["receipt.total", "payment.method"]
    assert body["has_more"] is False


def test_the_holding_reviewer_reads_the_history(session_factory, reviewer_client, receipt_id):
    """``_claim_as`` hands alice the seeded priority-1 task, which is
    ``RECEIPT_B``'s -- the same receipt the ``receipt_id`` fixture names."""
    _corrections_for(session_factory, receipt_id)
    _claim_as(session_factory, "alice")

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_a_reviewer_who_never_held_the_receipt_is_refused(
    session_factory, reviewer_client, receipt_id
):
    """The seeded task for ``RECEIPT_B`` is ``OPEN`` and unassigned, so alice
    does not hold it. 403, not 404 and not an empty 200: the receipt exists
    (``GET /receipts/{id}`` already discloses that to any signed-in user), and
    "not permitted" is not "none exist".
    """
    _corrections_for(session_factory, receipt_id)

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 403


def test_an_unknown_receipt_is_404_even_for_an_admin(admin_client):
    """Existence is checked **before** scope, so a probe for a random id cannot
    be told apart from any other absent receipt."""
    response = admin_client.get(f"/receipts/{uuid.uuid4()}/corrections")

    assert response.status_code == 404


def test_an_in_scope_receipt_with_no_corrections_is_an_empty_200(
    session_factory, reviewer_client, receipt_id
):
    """The other half of the 403 above. Together these two are what make the
    empty list mean something: with only one of them, a route that returned
    ``{"items": []}`` for *everything* would pass.
    """
    _claim_as(session_factory, "alice")

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    assert response.json() == {"items": [], "has_more": False}


@pytest.mark.parametrize("actor", ["anonymous", "api_key"])
def test_corrections_require_a_session(clients, receipt_id, actor):
    """Written out rather than added to ``READ_ROUTES`` -- see the comment on
    that table for why this route cannot express itself there."""
    assert clients[actor].get(f"/receipts/{receipt_id}/corrections").status_code == 401


def test_corrections_paginate_in_both_directions(session_factory, admin_client, receipt_id):
    """``has_more`` is pinned **true and false**. ``GET /receipts``' own
    ``has_more`` is unpinned in the ``True`` direction -- a constant
    ``has_more: False`` survives all 979 tests, measured at the admin-UI-routes
    close. This route does not inherit that hole.
    """
    _corrections_for(session_factory, receipt_id)

    first = admin_client.get(f"/receipts/{receipt_id}/corrections?limit=1").json()
    assert [row["field_path"] for row in first["items"]] == ["receipt.total"]
    assert first["has_more"] is True

    second = admin_client.get(f"/receipts/{receipt_id}/corrections?limit=1&offset=1").json()
    assert [row["field_path"] for row in second["items"]] == ["payment.method"]
    assert second["has_more"] is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_api_read.py -k corrections --no-header`
Expected: the six status-code tests fail with **404** (FastAPI has no such route), and the pagination test fails on `KeyError`/404. Confirm the 403 test fails *because it got 404*, not because it got 200 — that distinction is the point of the test.

- [ ] **Step 3: Implement the route**

In `src/receipts/review/api.py`, add `list_corrections` to the `.queue` import, `correction_summary` to the `.serializers` import, and `CorrectionListResponse` to the `.schemas` import. Then add directly below `get_one_receipt` in `_install_read_routes`:

```python
    @app.get("/receipts/{receipt_id}/corrections", response_model=CorrectionListResponse)
    def list_receipt_corrections(
        receipt_id: uuid.UUID,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> Any:
        """One receipt's correction history, oldest first.

        Guarded by ``require_user``, **not** ``require_role``: both roles reach
        it. An admin reads any receipt's; a reviewer reads only a receipt they
        hold or have held (ADR-0031, the ruling confirmed 2026-08-10).

        **Existence is checked before scope, and the order is the contract.** A
        receipt that does not exist is 404; one that exists but is out of scope
        is 403. 403 rather than 404 because ``GET /receipts/{receipt_id}`` takes
        ``require_user`` and nothing else -- any signed-in caller can already
        confirm any receipt exists, so a 404 here would hide nothing and mislead
        a legitimate reviewer. And 403 rather than an empty 200 because an
        in-scope receipt with no corrections **is** an empty 200, and that is a
        true and useful answer: "you may not see this" is not "there is
        nothing here" (ADR-0027 section 4).

        This route makes ``corrections.value_after`` readable over HTTP for the
        first time. It adds no redaction: ``_plan_change`` masks every coerced
        text path on the way in, precisely because this column is the copy
        nothing later scrubs. Relied on and pinned end-to-end rather than
        re-filtered here, which would be dead code under the invariant --
        ``test_a_pan_never_reaches_the_corrections_route``.

        Like the other two list routes, ``has_more`` comes off a ``limit + 1``
        fetch. That makes three sites carrying ``limit=limit + 1``; anchor on
        text unique to this one when mutating (review standard 16).
        """
        visible_to = None if user.role == ROLE_ADMIN else user.username
        with request.app.state.session_factory() as session:
            if get_receipt(session, receipt_id) is None:
                raise HTTPException(status_code=404, detail=f"no receipt with id {receipt_id}")
            rows = list_corrections(
                session,
                receipt_id,
                visible_to=visible_to,
                limit=limit + 1,
                offset=offset,
            )
            if rows is None:
                raise HTTPException(
                    status_code=403,
                    detail="you may not read this receipt's correction history",
                )
            items = [correction_summary(row) for row in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}
```

- [ ] **Step 4: Run the route tests to verify they pass**

Run: `python -m pytest tests/test_api_read.py -k corrections --no-header`
Expected: PASS (8 tests — the parametrised auth test counts twice).

- [ ] **Step 5: Record why the route is absent from `READ_ROUTES`**

Add directly above the `READ_ROUTES` list in `tests/test_api_read.py`:

```python
# `GET /receipts/{id}/corrections` is deliberately NOT in this table. The
# matrix asserts 200 for every actor in `allowed`, but a reviewer reaching that
# route gets 200 or 403 depending on a `review_tasks` row, not on their role --
# the same reason `POST /review/{id}/complete` is absent. Adding it would either
# assert something false or silently depend on whether the `receipt_id` fixture
# happens to be claimed. Its 401 half is pinned by
# `test_corrections_require_a_session`, and its 200/403 split by the four tests
# beside it.
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: `993 passed` (985 + 8).

- [ ] **Step 7: Commit the route**

```bash
git add src/receipts/review/api.py tests/test_api_read.py
git commit -m "feat: GET /receipts/{id}/corrections, existence before scope"
```

- [ ] **Step 8: Write the failing PAN test for the new HTTP surface**

`tests/test_api_write.py` already pins a PAN in three places — the `receipts` row, the `GET` body, and `corrections.value_after` read *from the database*. The route adds a fourth: that column is now reachable over HTTP. Append to `tests/test_api_write.py`:

```python
def test_a_pan_never_reaches_the_corrections_route(reviewer_client, receipt_id, task_id):
    """The fourth place, and it did not exist until the corrections route did.

    ``test_a_dotted_pan_is_masked_in_the_row_the_body_and_the_audit_copy`` reads
    ``corrections.value_after`` straight out of the database. That was the only
    way to reach it. This route serves the same column over HTTP, so the
    masking now has a network egress it never had, and the guarantee has to be
    asserted where a client actually sees it.

    Takes the existing ``task_id`` fixture for its **side effect**, not its
    value: it enqueues the seeded receipt and claims it for alice, which is what
    entitles her to read the history. Without it this test would get a 403 and
    assert nothing about redaction -- see Step 9, where that is exactly the
    wrong-reason failure to watch for.

    Goes red if ``_plan_change``'s ``after = redact_pan(after)`` is removed.
    """
    typed = "VISA 4111111111111111"
    assert reviewer_client.patch(
        f"/receipts/{receipt_id}", json={"payment": {"method": typed}}
    ).status_code == 200

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    assert "4111111111111111" not in response.text
    assert typed not in response.text
    assert [row["value_after"] for row in response.json()["items"]] == ["VISA ************1111"]
```

**No new helper.** `tests/test_api_write.py` already has a `task_id` fixture that does `enqueue_review` then `next_task(session, assignee="alice")` on the seeded receipt — requesting it is the whole setup. Adding a second claim helper would be a duplicate, and a second `enqueue_review` on one receipt updates the existing row rather than creating one, so the two would interact.

- [ ] **Step 9: Run it, then prove it is load-bearing**

Run: `python -m pytest tests/test_api_write.py -k pan_never_reaches --no-header`
Expected: PASS.

Now the mutation. In `src/receipts/persist/repository.py`, change `_plan_change`'s `after = redact_pan(after)` to `after = after`. Run the same test.
Expected: **FAIL**, on the `"4111111111111111" not in response.text` assertion. Read the failure and confirm it is that assertion — not a 403 or a 404, which would mean the test never reached the surface it exists to guard (review standard 15). **Restore the line** and re-run to confirm green.

- [ ] **Step 10: Full gates and commit**

Run: `python scripts/verify.py` — **background it**, it exceeds a two-minute tool timeout, and do not edit any file while it runs.
Expected: all five PASS. pytest `994`; Vitest **346 across 25 files, unchanged** — no frontend file was touched, so any movement there means something is wrong.

```bash
git add tests/test_api_write.py
git commit -m "test: a PAN never reaches the corrections route, the new egress"
```

---

### Task 4: ADR-0031 and the continuity pair

**Files:**
- Create: `docs/adr/0031-the-corrections-read-route.md`
- Modify: `docs/adr/README.md`, `docs/MEMORY.md`

- [ ] **Step 1: Write ADR-0031**

Record: the confirmed ruling and its provenance (answered 2026-08-05, disclaimed, re-confirmed verbatim 2026-08-10); "held or previously held" and why `IN_PROGRESS`-only and the `OPEN` half were both rejected; 403-vs-404-vs-empty-200 with the premise it rests on; that the scope protects **attribution**, not the receipt, and why that is coherent beside an unscoped `GET /receipts/{id}`; PAN relied-on-and-pinned with its stated limit; and the recorded follow-up that **if `GET /receipts/{id}` is ever scoped, the 403 decision must be revisited**.

- [ ] **Step 2: Add the row to `docs/adr/README.md`**

One table row, plus a sentence in the guidance paragraph — 0031 is the one to read before changing who can see correction attribution.

- [ ] **Step 3: Move the ruling out of "Still needing a user decision"**

In `docs/MEMORY.md`, delete item 1 of "Still needing a user decision" and add the confirmed ruling to "Decisions the user has made" with its date. **While in that list, fix the duplicate `2.` numbering** — it currently runs 1, 2, 2, 3, 4, 5, 6, so seven items present as six.

- [ ] **Step 4: Close the deferred envelope item**

In `docs/MEMORY.md`'s deferred follow-ups, mark the *"a third page envelope earns a base"* bullet resolved, naming `_PageResponse`.

- [ ] **Step 5: Verify no stale text survives, then commit**

Grep each edited claim by **one distinctive word** (review standard 21 — the phrase wraps across lines and `git grep` misses it). Chain the check to the commit with `&&`, never `;`:

```bash
git grep -n "third page envelope" -- docs && echo "CHECK: is it marked resolved?"
git add docs/adr/0031-the-corrections-read-route.md docs/adr/README.md docs/MEMORY.md && \
  git diff --cached --stat && \
  git commit -m "docs: ADR-0031, and the ruling moves out of the open-questions list"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §2.1 contract → Task 3 Step 3; §2.2 scope → Task 1 Steps 3, 5; §2.3 403/404/empty → Task 3 Steps 1, 3; §2.4 ordering → Task 1 Step 1; §2.5 shape and the envelope base → Task 2; §2.6 placement and the `| None` return → Task 1; §3.1 PAN → Task 3 Steps 8–9; §3.2 attribution → Task 4 Step 1; §4 tests 1–11 → Tasks 1 and 3; §4.1 `READ_ROUTES` → Task 3 Step 5; §7 follow-ups → Task 4 Step 1.

**Type consistency.** `list_corrections` is declared once (Task 1) and consumed with the same keyword arguments in Task 3. `correction_summary` returns the six keys Task 2's test asserts and Task 3's tests read (`field_path`, `value_after`). `CorrectionListResponse` is defined in Task 2 and referenced in Task 3.

**Count arithmetic.** 979 → 984 (Task 1, +5) → 985 (Task 2, +1) → 993 (Task 3 Step 6, +8: five named tests, one parametrised over two actors, plus the pagination test — 5 + 2 + 1) → 994 (Task 3 Step 10, +1). **These are predictions, not measurements.** Plan RED predictions have been wrong before in this repo — 3 of 4 in one task, 1 of 6 in another. Read every failure reason rather than matching colours, and correct the count in the ledger rather than trusting this line.

**Known risk.** Task 2 reparents two shipped response models. If FastAPI's OpenAPI generation orders inherited fields differently from declared ones, a schema-snapshot test could move. No such test is known to exist, which is why Step 6 runs both API modules before proceeding — and if one moves, that is a stop-and-report, not a test to adjust.
