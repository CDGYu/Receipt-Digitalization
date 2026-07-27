"""Money and decimal-convention parsing utilities.

These are STANDALONE helpers for raw-text / manual-entry paths. They are NOT
applied to fields that are already ``Decimal`` (json_io parses those before a
``ReceiptExtraction`` ever exists), and in particular :func:`quantize_money` is
display-only and must never run before validation.

Design contract, mirroring the rest of the pipeline:

  * Pure and deterministic. No I/O.
  * Never guess. Anything ambiguous or containing letters returns ``None`` --
    turning a handwritten ``O`` into a ``0`` inside a price is the exact silent
    corruption this system exists to prevent.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

#: Common currency symbols (never letters -- a letter in a number means we
#: cannot trust it and must refuse rather than guess).
_CURRENCY_SYMBOLS = "$\u20ac\u00a3\u00a5\u20b1\u20a9\u20b9\u00a2\u20aa\u20ab\u20b4\u20a6\u0e3f"
_CURRENCY_RE = re.compile(f"[{re.escape(_CURRENCY_SYMBOLS)}]")
_SPACE_RE = re.compile(r"\s+")
#: After stripping currency, whitespace and sign, only digits and the two
#: separators may remain. Anything else (a letter, another symbol) is a refusal.
_INVALID_NUMERIC_RE = re.compile(r"[^\d.,]")

#: Language codes that conventionally use a comma as the decimal separator.
#: Used only as a prior/tiebreak when the sample shapes are ambiguous.
_COMMA_DECIMAL_LANGS = frozenset(
    {
        "de", "fr", "es", "it", "nl", "pt", "pl", "ru", "sv", "da", "fi",
        "nb", "nn", "no", "cs", "hu", "tr", "el", "ro", "bg", "hr", "sk",
        "sl", "uk", "et", "lv", "lt", "ca", "is", "sr", "vi", "id", "af",
    }
)


def parse_money(value: Any, convention: str = "point") -> Decimal | None:
    """Parse a raw money value into a :class:`Decimal`, or ``None``.

    Strips currency symbols and thousands separators, honours ``convention``
    ("point" -> ``.`` is the decimal separator; "comma" -> ``,`` is), and
    returns ``None`` for anything ambiguous or containing letters. Never guesses.

    An already-``Decimal`` (or ``int``) value passes through unchanged.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # A float should never reach the money path, but if a manual/raw caller
        # hands one over, go through str() so we never inherit binary noise.
        return Decimal(str(value))
    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):  # accounting negative
        negative = True
        s = s[1:-1]

    s = _CURRENCY_RE.sub("", s)
    s = _SPACE_RE.sub("", s)
    if not s:
        return None

    if s[0] in "+-":
        negative = negative or s[0] == "-"
        s = s[1:]
    elif s[-1] in "+-":  # trailing sign, seen on some POS printers
        negative = negative or s[-1] == "-"
        s = s[:-1]
    if not s:
        return None

    # Any leftover letter or stray symbol means the value is not trustworthy.
    if _INVALID_NUMERIC_RE.search(s):
        return None

    if convention == "comma":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")

    try:
        result = Decimal(s)
    except InvalidOperation:
        return None
    if not result.is_finite():
        return None
    return -result if negative else result


def detect_decimal_convention(
    samples: list[str], merchant_default_locale: str | None = None
) -> str:
    """Infer "point" or "comma" from the shape of numeric samples.

    The rightmost separator in a value is treated as its decimal separator,
    except a single separator followed by exactly three digits (e.g. ``1.234``)
    is genuinely ambiguous and casts no vote. When the samples do not decide it,
    ``merchant_default_locale`` breaks the tie; failing that, "point".
    """
    point_votes = 0
    comma_votes = 0

    for sample in samples:
        s = (sample or "").strip()
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_dot < 0 and last_comma < 0:
            continue
        if last_dot >= 0 and last_comma >= 0:
            # Both present: the later separator is the decimal one.
            if last_comma > last_dot:
                comma_votes += 1
            else:
                point_votes += 1
            continue

        sep = "." if last_dot >= 0 else ","
        pos = max(last_dot, last_comma)
        digits_after = len(re.sub(r"\D", "", s[pos + 1:]))
        if digits_after == 3 and s.count(sep) == 1:
            continue  # 1.234 / 1,234 -> could be thousands; no vote
        if sep == ".":
            point_votes += 1
        else:
            comma_votes += 1

    if point_votes > comma_votes:
        return "point"
    if comma_votes > point_votes:
        return "comma"

    if merchant_default_locale:
        lang = re.split(r"[-_]", merchant_default_locale.strip().lower(), maxsplit=1)[0]
        if lang in _COMMA_DECIMAL_LANGS:
            return "comma"
    return "point"


def quantize_money(d: Decimal, places: int = 2) -> Decimal:
    """Round to ``places`` decimals, ROUND_HALF_UP. DISPLAY ONLY.

    Never call this before validation: re-quantizing an already-parsed value
    can manufacture a tolerance failure that looks like a model error.
    """
    quantum = Decimal(1).scaleb(-places)
    return d.quantize(quantum, rounding=ROUND_HALF_UP)
