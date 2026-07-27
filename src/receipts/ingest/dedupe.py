"""Duplicate detection: perceptual image hashing and semantic matching (§14.1).

A receipt can be "the same" in two ways: the *same picture* re-uploaded (caught
by a perceptual hash that survives re-compression and light resizing) or the
*same purchase* photographed twice (same merchant + date + total). Ingest links
either kind to the existing receipt instead of creating a second one.

The hashing here is pure and content-blind. Duplicate *lookups* take an injected
iterable of candidates rather than querying a database -- persistence does not
exist yet (Phase 3), so these functions stay pure and testable and the caller
supplies whatever candidate set it has.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from PIL import Image

#: dHash works on a tiny grayscale thumbnail. Resizing to 9x8 yields 8 rows of
#: 8 adjacent-column comparisons = 64 bits. Width is one more than height so each
#: row produces exactly ``height`` difference bits.
_HASH_WIDTH = 9
_HASH_HEIGHT = 8


def compute_phash(img: Image.Image) -> str:
    """64-bit difference hash (dHash) of ``img``, hex-encoded (16 hex chars).

    The image is reduced to grayscale and downsampled to ``9x8``; each bit
    records whether a pixel is brighter than its immediate left neighbour, giving
    ``8 x 8 = 64`` orientation-of-gradient bits. dHash keys on the *direction* of
    brightness change rather than absolute values, so it is stable across
    re-encoding and modest scaling while still separating genuinely different
    images. Pure: the input image is not modified.
    """
    small = img.convert("L").resize(
        (_HASH_WIDTH, _HASH_HEIGHT), Image.Resampling.LANCZOS
    )
    pixels = np.asarray(small, dtype=np.int16)  # shape (8, 9)

    # Bit is set where a pixel is brighter than the pixel to its left. Comparing
    # adjacent columns collapses each 9-wide row to 8 bits.
    diff = pixels[:, 1:] > pixels[:, :-1]  # shape (8, 8) of bool

    # packbits reads the flattened bits MSB-first into 8 bytes -> a 64-bit int.
    packed = np.packbits(diff.flatten())
    value = int.from_bytes(packed.tobytes(), "big")
    return f"{value:016x}"


def phash_distance(a: str, b: str) -> int:
    """Hamming distance between two hex-encoded perceptual hashes.

    Counts the differing bits: ``0`` means identical, ``64`` means fully opposite.
    Small distances (a handful of bits) indicate near-duplicate images.
    """
    return (int(a, 16) ^ int(b, 16)).bit_count()


def find_near_duplicate_image(
    phash: str,
    candidates: Iterable[tuple[Any, str]],
    threshold: int = 5,
) -> Any | None:
    """Return the first candidate id whose stored hash is within ``threshold``.

    ``candidates`` is an injected iterable of ``(id, phash)`` pairs -- not a DB
    query (persistence is Phase 3). Returns ``None`` when every candidate is
    farther than ``threshold`` bits away. The default threshold of 5 tolerates
    re-compression noise without merging distinct receipts.
    """
    for candidate_id, candidate_phash in candidates:
        if phash_distance(phash, candidate_phash) <= threshold:
            return candidate_id
    return None


def find_semantic_duplicate(
    merchant_id: Any,
    txn_date: Any,
    total: Any,
    candidates: Iterable[dict],
) -> Any | None:
    """Return the id of a candidate matching on merchant *and* date *and* total.

    Same merchant + same transaction date + same total is almost certainly a
    re-upload of one purchase. Matching is exact equality on all three fields;
    ``candidates`` is an injected iterable of dicts with ``id``, ``merchant_id``,
    ``txn_date`` and ``total`` keys -- not a DB query (persistence is Phase 3).
    Returns ``None`` when nothing matches.
    """
    for candidate in candidates:
        if (
            candidate.get("merchant_id") == merchant_id
            and candidate.get("txn_date") == txn_date
            and candidate.get("total") == total
        ):
            return candidate.get("id")
    return None


def link_duplicate(new_id: Any, existing_id: Any) -> tuple:
    """Return the ``(new_id, existing_id)`` duplicate-link pair.

    Pure helper only: the DB write that actually records "this receipt duplicates
    that one" lives in the persistence layer (Phase 3), which does not exist yet.
    Returning the pair keeps this callable and testable now and gives the future
    writer a single, unambiguous source for the intended link.
    """
    return (new_id, existing_id)
