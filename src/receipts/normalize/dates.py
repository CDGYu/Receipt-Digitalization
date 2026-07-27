"""Date and time parsing utilities (stdlib only).

The load-bearing rule here: an ambiguous date (DD/MM vs MM/DD, both components
<= 12) must NOT be resolved by guessing. It returns ``(None, True)`` so the
caller can park the verbatim string and leave the canonical date null.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

#: Leading 4-digit year: unambiguous ISO-style ``YYYY[-/.]M[-/.]D``.
_ISO_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
#: Day/month first with a 2- or 4-digit year at the end.
_DMY_RE = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")
#: Accepted clock formats, tried in order. 24h first so "14:32" is not misread.
_TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p")


def parse_date(
    raw: str, hint_format: str | None = None, today: date | None = None
) -> tuple[date | None, bool]:
    """Parse ``raw`` into ``(date, was_ambiguous)``.

    * A valid ISO ``YYYY-MM-DD`` (``.``/``/`` separators accepted) -> ``(date, False)``.
    * If exactly one of the first two components is > 12, order is known -> ``(date, False)``.
    * If both are <= 12 and the order is unknown -> ``(None, True)``.
    * ``hint_format`` (a ``strptime`` format) is tried first when provided.
    * Anything else -> ``(None, False)``.

    ``today`` anchors the sliding window used to expand a 2-digit year; it
    defaults to :meth:`date.today` but can be injected so the 2-digit-year
    branch is deterministic and testable rather than wall-clock dependent.
    """
    if not raw or not raw.strip():
        return (None, False)
    s = raw.strip()
    if today is None:
        today = date.today()

    if hint_format:
        try:
            return (datetime.strptime(s, hint_format).date(), False)
        except ValueError:
            pass  # fall through to the heuristics

    iso = _ISO_RE.fullmatch(s)
    if iso:
        year, month, day = int(iso[1]), int(iso[2]), int(iso[3])
        try:
            return (date(year, month, day), False)
        except ValueError:
            return (None, False)

    dmy = _DMY_RE.fullmatch(s)
    if dmy:
        first, second, tail = int(dmy[1]), int(dmy[2]), dmy[3]
        year = int(tail) if len(tail) == 4 else expand_two_digit_year(int(tail), today)
        if first > 12 and second > 12:
            return (None, False)  # neither can be a month
        if first > 12:
            day, month = first, second
        elif second > 12:
            month, day = first, second
        else:
            return (None, True)  # both <= 12: order genuinely unknown
        try:
            return (date(year, month, day), False)
        except ValueError:
            return (None, False)

    return (None, False)


def parse_time(raw: str) -> time | None:
    """Parse a clock time (24h or 12h with AM/PM) into a :class:`time`, or ``None``."""
    if not raw or not raw.strip():
        return None
    s = raw.strip().upper().replace(".", "")
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def expand_two_digit_year(yy: int, reference: date) -> int:
    """Map a 2-digit year to a 4-digit year near ``reference`` (sliding window).

    The candidate in ``reference``'s century is chosen unless it lands more than
    50 years away, in which case it slides to the adjacent century.
    """
    century = reference.year - (reference.year % 100)
    candidate = century + yy
    if candidate - reference.year > 50:
        candidate -= 100
    elif reference.year - candidate > 50:
        candidate += 100
    return candidate
