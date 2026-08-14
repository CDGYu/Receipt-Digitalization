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
