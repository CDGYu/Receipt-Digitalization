"""Read and write the `merchants` table (spec §8.3)."""

from __future__ import annotations

import base64
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from receipts.extract import prompts as P
from receipts.extract.schema import ReceiptExtraction
from receipts.ingest.storage import StorageBackend
from receipts.normalize import normalize_merchant_name
from receipts.persist.models import (
    Correction,
    ExtractionRun,
    Merchant,
    PassName,
    Receipt,
)
from receipts.score.confidence import ReceiptStatus

log = logging.getLogger(__name__)


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

    A key that MORE THAN ONE merchant answers to retrieves nothing. No answer is
    right in that case: whichever row came back would hand one merchant's hints
    to the other merchant's receipt -- the same harm fuzzy matching is refused
    for. Returning the first row scanned is not even stable, since nothing here
    orders the query. The ambiguous receipt loses its hints and nothing else; it
    still gets its merchant afterwards, from the `tax_id`.

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

    matches = [m for m in session.scalars(select(Merchant)).all() if key in _keys(m)]
    if len(matches) != 1:
        return None
    return matches[0]


def register(session: Session, extraction: ReceiptExtraction) -> Merchant | None:
    """Create a merchant from a **confirmed** extraction, or return None.

    Both a name and a `tax_id` are required. The TIN is the strongest identifier
    on this corpus, and requiring it is what stops a garbage
    `merchant_name_guess` from populating the table with noise (spec D2).

    An extraction whose `tax_id` is already known returns that merchant rather
    than creating a second row for it.

    A name that normalizes onto an existing merchant's key is NOT a reason to
    refuse. A different TIN is a different business, and letting the name veto
    a write the `tax_id` authorised would give the receipt's weakest field the
    final say over its strongest -- and leave a real merchant permanently
    unregisterable. `lookup` absorbs the resulting ambiguity by retrieving
    neither of them.
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

    A spelling whose key ANOTHER merchant already answers to is refused. A TIN
    authorises writes to its own merchant, not writes against everyone else's:
    learning a key someone else holds makes that key ambiguous, and `lookup`
    resolves an ambiguous key to nothing, so the write would silently
    de-register a merchant that never presented a TIN of its own. Declining
    costs one spelling, which is why the same collision is refused here and
    accepted in `register` -- there, refusing would cost a whole merchant.

    The list is reassigned rather than mutated in place: `name_variants` is a
    plain JSON column with no `MutableList`, so SQLAlchemy notices the change
    only on reassignment. An in-place `append` writes nothing at commit and
    loses the spelling without raising.
    """
    if not tax_id or not observed_name or merchant.tax_id != tax_id:
        return

    key = normalize_merchant_name(observed_name)
    if not key or key in _keys(merchant):
        return

    if any(
        other.id != merchant.id and key in _keys(other)
        for other in session.scalars(select(Merchant)).all()
    ):
        return

    merchant.name_variants = [*(merchant.name_variants or []), observed_name]


def increment(session: Session, merchant: Merchant) -> None:
    """Bump `receipt_count`. Callers commit; this only stages the change."""
    merchant.receipt_count = (merchant.receipt_count or 0) + 1


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

    Newest first, by `created_at`, with `id` breaking ties. Recency is what
    makes an example representative -- a merchant that changes its receipt
    layout should stop being taught the old one -- and `Receipt.id` alone
    cannot express that, being a random UUID: it would freeze on whichever
    candidates happen to sort lowest and keep teaching them as the corpus grows.
    The `id` tie-break is not decoration. The ordering must be **total** or the
    same rows can yield different examples on two calls, and `pipeline.py`'s
    `_attempt_prompt_hash` rebuilds this prompt afterwards to recover its hash;
    a different pick there records a hash that no call ever used. `created_at`
    is not total on its own: it defaults to `now()`, which is the *transaction*
    timestamp on Postgres and one-second resolution on SQLite, so receipts
    written together tie exactly.

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
        .order_by(Receipt.created_at.desc(), Receipt.id)
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
