"""Shared greedy line-item alignment.

Aligns two lists of :class:`LineItem` by normalized-description similarity so
callers (result diffing, self-consistency voting, repair) can compare rows even
when one list has an extra or missing row. A single inserted or dropped row must
not cascade into marking every subsequent row unmatched — hence greedy
best-first matching by similarity rather than a positional zip.

Pure and stdlib-only: inputs are never mutated and the output is deterministic.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ..validate.rules import normalize_desc
from .schema import LineItem

#: Minimum normalized-description similarity for two rows to count as a match.
#: Mirrors the 0.6 overlap threshold used by the OCR-grounding rule (R061).
_MATCH_THRESHOLD = 0.6


def align_line_items(
    a: list[LineItem], b: list[LineItem]
) -> list[tuple[int | None, int | None]]:
    """Greedily align two line-item lists by normalized-description similarity.

    Returns index pairs:

      * ``(i, j)``    — ``a[i]`` matched ``b[j]``
      * ``(i, None)`` — ``a[i]`` had no match
      * ``(None, j)`` — ``b[j]`` had no match

    Similarity is ``difflib.SequenceMatcher`` ratio over
    :func:`normalize_desc`-normalized descriptions. The highest-similarity
    candidate pairs (at or above ``0.6``) are matched first; each index is used
    at most once. Ordering of the result: matched pairs sorted by ``i``, then
    unmatched ``a`` by ``i``, then unmatched ``b`` by ``j``. Inputs are not
    mutated.
    """
    norm_a = [normalize_desc(item.description_raw) for item in a]
    norm_b = [normalize_desc(item.description_raw) for item in b]

    # Candidate pairs above threshold, best similarity first. Ties break
    # deterministically toward the lowest i, then the lowest j.
    candidates: list[tuple[float, int, int]] = []
    for i, na in enumerate(norm_a):
        for j, nb in enumerate(norm_b):
            ratio = SequenceMatcher(None, na, nb).ratio()
            if ratio >= _MATCH_THRESHOLD:
                candidates.append((ratio, i, j))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    used_a: set[int] = set()
    used_b: set[int] = set()
    matched: list[tuple[int, int]] = []
    for _ratio, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matched.append((i, j))

    matched.sort(key=lambda pair: pair[0])
    result: list[tuple[int | None, int | None]] = list(matched)
    result.extend((i, None) for i in range(len(a)) if i not in used_a)
    result.extend((None, j) for j in range(len(b)) if j not in used_b)
    return result
