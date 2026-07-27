"""Text canonicalization and currency resolution (stdlib only).

``clean_text`` is applied by callers to NON-numeric fields only. It performs no
OCR-confusion character swaps -- it will never turn a letter into a digit.
``normalize_currency`` resolves an ISO 4217 code by a fixed precedence and
returns ``None`` rather than guessing (in particular, never from language).
"""

from __future__ import annotations

import re
import unicodedata

#: Control characters to drop. Deliberately excludes tab/newline/CR (\x09,
#: \x0a, \x0d): those are whitespace and get collapsed, not stripped as junk.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")
_BRANCH_CODE_RE = re.compile(r"#\s*\d+")

#: Recognised ISO 4217 alphabetic codes. A currency is only accepted if it is
#: already one of these -- an unrecognised code is treated as "not a code".
_ISO_4217: frozenset[str] = frozenset(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND
    BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF
    DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD
    HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KRW
    KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR
    MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN
    PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN
    SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VED
    VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL
    """.split()
)

#: Legal-entity suffixes dropped when FINGERPRINTING a merchant name. The
#: display name keeps the original -- these are for grouping only.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "co", "ltd", "corp", "llc", "plc", "gmbh", "ag", "sa", "bv",
        "pte", "pty", "srl", "nv", "kg", "oy", "ab", "as", "spa",
        "limited", "incorporated", "corporation", "company",
    }
)
#: Words that introduce a branch/store code, dropped along with a trailing number.
_BRANCH_WORDS = frozenset({"branch", "store", "br", "outlet", "loc", "location"})


def clean_text(s: str) -> str:
    """NFKC-normalize, strip control characters, and collapse whitespace.

    Never performs OCR-confusion swaps (no ``O`` -> ``0``); it only canonicalizes
    formatting. Applied by callers to non-numeric fields only.
    """
    text = unicodedata.normalize("NFKC", s)
    text = _CONTROL_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_merchant_name(s: str) -> str:
    """Casefold and strip legal suffixes and branch codes, for FINGERPRINTING.

    This is intentionally lossy and is NOT the display name -- callers keep the
    original name for display and use this only to group receipts by merchant.
    """
    cleaned = clean_text(s or "").casefold()
    cleaned = _BRANCH_CODE_RE.sub(" ", cleaned)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    tokens = [t for t in cleaned.split() if t not in _LEGAL_SUFFIXES]

    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _BRANCH_WORDS:
            # Drop the branch word and a following numeric code, if any.
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                i += 2
                continue
            i += 1
            continue
        out.append(token)
        i += 1
    return " ".join(out).strip()


def normalize_currency(
    symbol_or_code: str | None,
    merchant_default: str | None,
    system_default: str | None = None,
) -> str | None:
    """Resolve to an ISO 4217 code by precedence, or ``None``.

    Order: an explicit recognised ISO code on the receipt, then the merchant
    default, then the system default, then ``None``. A bare currency SYMBOL is
    ambiguous ("$" -> USD/CAD/AUD/...) and is NOT resolved -- we would rather
    return ``None`` than guess. Currency is never inferred from language.
    """
    for candidate in (symbol_or_code, merchant_default, system_default):
        code = _as_iso_code(candidate)
        if code is not None:
            return code
    return None


def _as_iso_code(value: str | None) -> str | None:
    """Return the upper-cased value iff it is a recognised ISO 4217 code."""
    if not value:
        return None
    code = value.strip().upper()
    return code if code in _ISO_4217 else None
