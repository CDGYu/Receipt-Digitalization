"""Read and write the `merchants` table (spec §8.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from receipts.extract.schema import ReceiptExtraction
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

    A key that MORE THAN ONE merchant answers to retrieves nothing. `register`
    identifies merchants by `tax_id`, so two of them can hold names that
    normalize alike, and then no answer is right: whichever row came back would
    hand one merchant's hints to the other merchant's receipt -- the same harm
    fuzzy matching is refused for. Returning the first row scanned is not even
    stable, since nothing here orders the query. The ambiguous receipt loses
    its hints and nothing else; it still gets its merchant afterwards, from the
    `tax_id`.

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
