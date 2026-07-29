"""HMAC signing for time-limited links (P4.T3/T5, spec §14/§17).

Split out of :mod:`receipts.review.auth` so it can be imported without the
web framework: :func:`sign_url` and :func:`verify_signature` are shared by
the API's signed image routes and by the workbook export, and export must
not depend on FastAPI/Starlette to run on a CLI-only box.
"""

from __future__ import annotations

import hashlib
import hmac
import time

__all__ = ["sign_url", "verify_signature"]


def sign_url(payload: str, *, secret: str, ttl_s: int, now: int | None = None) -> tuple[str, int]:
    """Return ``(signature, exp)`` for ``payload``, valid for ``ttl_s`` seconds.

    ``now`` is injectable so a test can prove expiry without sleeping; a
    ``None`` default reads the wall clock.

    The signed message is ``f"{payload}|{exp}"`` -- a plain ``|`` join, not an
    escaped encoding. That is safe only if no component of ``payload`` can
    itself contain ``|``: a caller assembling ``payload`` from several parts
    (Task 5 joins a receipt id and an image variant) must validate each part
    against a closed set or a known-safe format -- a UUID for the id, an enum
    member for the variant -- rather than pass free text through, or two
    different logical URLs could sign identically.
    """
    exp = (now if now is not None else int(time.time())) + ttl_s
    message = f"{payload}|{exp}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return signature, exp


def verify_signature(
    payload: str, *, secret: str, signature: str, exp: int, now: int | None = None
) -> bool:
    """Whether ``signature`` is valid for ``payload``/``exp`` and not expired."""
    current = now if now is not None else int(time.time())
    if exp < current:
        return False
    message = f"{payload}|{exp}".encode()
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    # Compared as bytes: signature commonly arrives from a query string, and
    # hmac.compare_digest() raises TypeError on a non-ASCII str rather than
    # returning False. A malformed signature must fail closed as "invalid",
    # not crash the caller with a 500 (see require_upload for the same fix).
    return hmac.compare_digest(expected.encode(), signature.encode())
