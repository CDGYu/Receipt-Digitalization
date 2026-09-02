"""The ``receipts`` operator CLI: entry point, exit-code contract, ``ingest``, ``users``.

ADR-0013 is the contract every command here (and every command a later task
adds) must honour:

  * **Exit codes.** ``0`` the command completed; ``1`` it could not (a rejected
    file, an unknown user, a duplicate account, ...); ``2`` is argparse's own
    usage error (an unknown command, a missing required argument). A receipt
    routed to review is *not* a failure and must never change the exit code --
    review is the system working as designed, and training operators (or CI) to
    treat it as an error is exactly what this contract exists to prevent.
  * **No interactive prompts, anywhere.** The CLI must run unattended from a
    script or from CI. ``users add`` reads the password from stdin, never from
    a flag -- a flag would land in shell history and in ``ps``. A piped or
    redirected stdin is read directly, one line, so
    ``echo "$PW" | receipts users add alice`` works unattended; an interactive
    terminal instead prompts via ``getpass`` so the password is not echoed.
    Plain ``getpass.getpass`` alone is not portable enough for that first
    case: ``getpass.unix_getpass`` checks ``isatty()`` and already falls back
    to a stdin read, but ``getpass.win_getpass`` -- the one Windows always
    uses -- has no such check and reads raw keystrokes via ``msvcrt``
    regardless, so a piped password would hang forever on Windows instead of
    being read. See :func:`_read_password`.
  * **``ingest`` does not enqueue.** It validates a file, stores its bytes, and
    writes a ``pending`` receipt row -- the same row shape ``POST /upload``
    writes. ``receipts process`` is the one place that drains pending rows, so
    an upload through either entry point is picked up by exactly the same
    query. See ``docs/adr/0013-cli-contract.md``.
  * **``process`` takes production's path by default.** It enqueues to RQ;
    ``--inline`` runs in-process for a single machine or a box with no Redis.
    A missing ``REDIS_URL`` while enqueueing is a hard failure naming
    ``--inline``, never a silent fallback -- a fallback would mean the
    operator believes work is queued when it is running in a terminal they
    are about to close.
  * **``reprocess`` never overwrites a human review.** A ``reviewed`` receipt
    is left exactly as the human left it, with or without ``--force``: the
    run still happens, but the refusal to write over it lives in
    :func:`~receipts.persist.repository.save_extraction` (ADR-0012), not
    here. This module reports what the pipeline decided; it does not
    duplicate the invariant. ``--force`` gates by *status*, not by
    permission: it extends reprocessing to an ``auto_approved`` receipt and
    never to a ``reviewed`` one.
  * **``export`` refuses rather than truncates.** Past ``_EXPORT_MAX_ROWS``
    matching receipts it prints an error and writes nothing, rather than
    silently shortening a file that is meant to read as a complete ledger.
    The query and row assembly are Task 1's
    :func:`~receipts.review.serializers.query_export_receipts` and
    :func:`~receipts.review.serializers.build_export_rows` -- the same two
    functions ``GET /export/xlsx`` calls -- so a CLI export and an API
    export of identical filters can never disagree about which receipts
    qualify.
  * **``merchants`` ships thin.** ``list`` reads the ``merchants`` table as
    it stands; ``hints`` shows, appends to, or clears the free-text
    ``hints`` column the extraction prompt injects. Spec section 18's
    "trust the image" sentence is appended to a supplied hint that does
    not already end with it, so a hint can never itself become a source of
    hallucination on the day a merchant changes its receipt format.
  * ``eval`` is a thin wrapper over ``eval.run_baseline.run_baseline``: it
    owns no scoring logic of its own, only argument plumbing, so "what
    counts as correct" never has two definitions to keep in sync. It
    prints ``format_report``'s spec section 16 table and writes a results
    file for ``calibrate`` to read. **It refuses a zero-receipt run**
    before printing anything, and validates ``--golden-dir`` before the
    baseline runs at all -- see :func:`cmd_eval`.
  * **``calibrate`` refuses rather than guess wherever the evidence does
    not support a number.** A zero-receipt result set is refused
    outright, printing no precision figure at all -- this project has
    already committed a results artifact reporting
    ``auto_approval_precision: 1.0`` on zero receipts once, and the
    command that picks the auto-approval threshold is the worst place to
    repeat it. The recommendation is additionally floored at
    :data:`~receipts.score.thresholds.REVIEW_THRESHOLD` and requires
    :data:`_MIN_APPROVED_SAMPLE` auto-approved receipts behind whatever
    precision it quotes, because ``calibration_curve`` reports a vacuous
    ``1.0`` for a threshold nothing clears and a merely-nonzero rate can
    be a sample of one. Every run closes with a standing caveat that no
    accuracy number from this system has been measured on a full baseline
    yet (spec section 16, ``docs/KNOWN_ISSUES.md`` ISSUE-001).
  * **Anything behind an optional extra is imported inside the command
    that needs it, never at module top.** Two families:

    ``eval/`` is deliberately excluded from the installed distribution
    (``pyproject.toml``: dev/research tooling, not part of the installed
    CLI), and the ``pipeline`` extra (Pillow, OpenCV, openpyxl,
    pypdfium2) is optional by design. A module-top import of either
    breaks *every* ``receipts`` command, not only the ones that need it:
    ``receipts users list`` has no business requiring a spreadsheet
    writer or an image library. This has now happened twice -- once for
    ``eval``, once for ``openpyxl``/``PIL``/``cv2`` -- because
    ``pytest``'s own ``pythonpath = ["src", "."]`` and a dev environment
    that has every extra installed both mask it in-process. Only a
    subprocess with the module blocked can see it; see
    ``tests/test_cli_reports.py::test_cli_imports_without_the_eval_package``.

    ``receipts.worker`` is imported lazily here for the *same* reason,
    not a different one: ``worker.py`` imports ``receipts.pipeline`` at
    *its* module top, so importing it drags in the ``pipeline`` extra.
    (``rq``/``redis`` are a separate matter and are handled inside
    ``worker.py`` itself, which imports them lazily behind the ``worker``
    extra -- that part needs nothing from this module.)

    When a needed package is genuinely unavailable, the command prints a
    clean message naming the extra and returns :data:`EXIT_FAILED` rather
    than letting ``ModuleNotFoundError`` escape as a traceback; see
    :func:`_is_missing_eval` and :func:`_is_missing_pipeline_extra`,
    which match the actual condition rather than swallowing every
    ``ModuleNotFoundError``.

Every ``cmd_*`` function takes its collaborators (``session_factory``,
``storage``, ``settings``) as keyword-only arguments with no defaults; only
``main`` builds the real ones. That is what keeps the test suite offline: a
test builds a throwaway SQLite session factory and a temp-directory
``LocalStorage`` and calls ``cmd_ingest``/``cmd_users`` directly, never through
``main``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from config.settings import Settings, get_settings

from .extract.clients.base import VLMClient
from .extract.clients.factory import make_extract_ladder
from .ingest.ingest import ReceiptJob, ingest_file
from .ingest.storage import StorageBackend, make_storage
from .persist.app_settings import settings_for_run
from .persist.models import Merchant, Receipt
from .persist.repository import (
    create_pending_receipt,
    get_receipt,
    query_receipts,
    redact_pan,
)
from .persist.session import make_engine, make_session_factory
from .persist.users import ROLE_REVIEWER, ROLES, create_user, deactivate, list_users, set_role
from .score.confidence import ReceiptStatus
from .score.thresholds import REVIEW_THRESHOLD

if TYPE_CHECKING:  # pragma: no cover - annotations only; needs the `pipeline` extra
    from .pipeline import ProcessResult

__all__ = [
    "EXIT_FAILED",
    "EXIT_OK",
    "build_parser",
    "cmd_calibrate",
    "cmd_eval",
    "cmd_export",
    "cmd_ingest",
    "cmd_merchants",
    "cmd_process",
    "cmd_reprocess",
    "cmd_sweep",
    "cmd_users",
    "main",
]

#: The command completed. A receipt routed to review still exits 0 (ADR-0013).
EXIT_OK = 0
#: The command could not complete: a rejected file, an unknown user, a
#: duplicate account, an unreachable database. Argparse's own usage error (an
#: unknown command, a missing argument) is exit 2 and never reaches this.
EXIT_FAILED = 1

#: Passed to :func:`~receipts.persist.repository.query_receipts` when
#: ``process --limit`` is omitted. ``query_receipts`` has no "unlimited"
#: option of its own -- its ``limit`` keyword defaults to 1000 -- so omitting
#: the keyword here would silently inherit that cap while ``--help`` keeps
#: promising "no cap": a backlog past 1000 used to be drained a page at a
#: time with nothing telling the operator some pending rows were left
#: behind. An explicit, effectively unbounded value makes "no cap" true.
_NO_LIMIT = sys.maxsize

#: Past this many matching receipts, ``export`` refuses rather than
#: truncating (see :func:`cmd_export`). A module global, not a local
#: constant inside the function, specifically so a test can lower it with
#: ``monkeypatch.setattr(cli_module, "_EXPORT_MAX_ROWS", ...)`` without a
#: database of five thousand receipts.
#:
#: **Deliberately a separate constant from ``review.api``'s own
#: ``_EXPORT_MAX_ROWS`` -- not imported from there, and not consolidated.**
#: They happen to share a value today, but they bound two different things:
#: the API's caps an in-memory workbook built inside one HTTP response,
#: while this one caps a file written to disk, and a future operator could
#: legitimately raise one without the other. Importing the API's would also
#: drag FastAPI back into the CLI, which Task 1 split ``query_export_receipts``
#: and ``build_export_rows`` out of ``review/api.py`` specifically to avoid
#: (ADR-0010). This project has already paid once for a duplicated constant
#: that drifted silently -- the 0.85/0.60 confidence thresholds ended up
#: with four separate copies -- so the rule going forward is that a
#: duplicate must either be consolidated or, as here, carry an explicit note
#: saying why it is independent.
_EXPORT_MAX_ROWS = 5000

#: Import names of the packages the optional ``pipeline`` extra installs.
#: Distribution names and import names differ (``pillow`` -> ``PIL``,
#: ``opencv-python-headless`` -> ``cv2``, ``pillow-heif`` -> ``pillow_heif``),
#: and it is the *import* name a :class:`ModuleNotFoundError` carries, so this
#: lists the latter. Kept in step with ``pyproject.toml``'s ``[pipeline]``.
_PIPELINE_EXTRA_MODULES = frozenset(
    {"PIL", "cv2", "openpyxl", "pillow_heif", "pypdfium2"}
)

#: Printed (to stderr) when a command needs the optional ``pipeline`` extra and
#: it is not installed. Unlike ``eval/`` (see :data:`_EVAL_NOT_INSTALLED`) there
#: *is* an install that fixes this, so the message names it.
_PIPELINE_NOT_INSTALLED = (
    "error: this command needs the optional `pipeline` extra (Pillow, OpenCV, "
    "openpyxl, pypdfium2), which is not installed in this environment. Install "
    "it with `pip install 'receipts[pipeline]'` and try again."
)


#: The one containment policy both of :func:`cmd_process`'s per-job loops use.
#:
#: Each loop catches ``BaseException`` -- not ``Exception`` -- and re-raises
#: only these two. The reasoning, recorded here rather than duplicated at both
#: catch sites:
#:
#: * ``Exception`` alone is too narrow. A ``client_factory`` (or a queue
#:   backend) that raises a ``BaseException`` subclass -- ``SystemExit`` from a
#:   library calling ``sys.exit``, or a framework's own cancellation type --
#:   escaped the batch with empty stdout and no summary, which is the exact
#:   symptom this containment exists to prevent. "Nothing is silently dropped"
#:   cannot depend on a third party's choice of base class.
#: * ``KeyboardInterrupt`` and ``SystemExit`` are still re-raised, because they
#:   are not a *receipt's* failure: they are the operator or the interpreter
#:   asking the run to stop. Swallowing them would turn Ctrl-C into a stream of
#:   ``failed`` lines and keep the batch going, which is worse than stopping.
#:
#: A contained job is reported on stdout as a ``failed`` line and counted, so
#: the run still ends with a summary and :data:`EXIT_FAILED` rather than a
#: traceback.
_UNCONTAINED = (KeyboardInterrupt, SystemExit)


def _is_missing_pipeline_extra(exc: ModuleNotFoundError) -> bool:
    """Whether ``exc`` is a package from the ``pipeline`` extra missing, rather
    than some unrelated import failing several frames deeper inside the same
    import.

    Same discipline as :func:`_is_missing_eval` and :func:`_is_missing_schema`:
    match the actual condition on ``.name``, and let anything this was not
    written for propagate rather than mislabel it as "install the extra".
    """
    root = (exc.name or "").split(".")[0]
    return root in _PIPELINE_EXTRA_MODULES


def _add_ingest(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "ingest",
        help="validate a receipt file (or a directory of them) and write a pending row",
        description=(
            "Validate, store, and write a pending receipt row for each file. "
            "This does not enqueue processing -- `receipts process` drains "
            "pending rows, whether they arrived here or through POST /upload."
        ),
    )
    parser.add_argument("path", help="a receipt image/PDF, or a directory containing them")
    parser.add_argument(
        "--source", default="upload",
        help="provenance recorded on the receipt job (default: %(default)s)",
    )
    parser.add_argument(
        "--recursive", action="store_true",
        help="when path is a directory, also descend into its subdirectories",
    )


def _add_users(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("users", help="manage reviewer/admin accounts")
    users_sub = parser.add_subparsers(dest="users_command", required=True)

    add = users_sub.add_parser(
        "add",
        help="create an account",
        description=(
            "Create an account. The password is read from stdin, never from "
            "a flag: it would otherwise land in shell history and in `ps`. A "
            "piped or redirected stdin is read directly, one line -- e.g. "
            "`echo \"$PW\" | receipts users add alice`, or a CI secret piped "
            "in -- so this runs unattended on every platform, including "
            "Windows. An interactive terminal instead prompts without "
            "echoing the password. There is no --password flag and none "
            "will be added."
        ),
    )
    add.add_argument("username")
    add.add_argument("--role", default=ROLE_REVIEWER, choices=sorted(ROLES),
                      help="default: %(default)s")

    users_sub.add_parser("list", help="list every account")

    deactivate_parser = users_sub.add_parser("deactivate", help="deactivate an account")
    deactivate_parser.add_argument("username")

    set_role_parser = users_sub.add_parser("set-role", help="change an account's role")
    set_role_parser.add_argument("username")
    set_role_parser.add_argument("role", choices=sorted(ROLES))


#: The largest value SQLite can store in an INTEGER column, and therefore the
#: largest ``--limit`` that can reach a query. Past it the driver raises
#: ``OverflowError: Python int too large to convert to SQLite INTEGER`` from
#: inside SQLAlchemy, as an unhandled traceback rather than a usage error.
#:
#: **A representability bound, deliberately not a policy one.** ADR-0034 capped
#: the HTTP routes' ``offset`` at a million because a deep offset is a
#: sequential scan no index removes and those routes have filters that answer
#: the same question better. Neither argument holds for a batch size:
#: ``--limit 5000000`` is a legitimate instruction from an operator with that
#: many pending receipts, so the only defensible ceiling is what the database
#: can actually hold.
_MAX_INT64 = 2**63 - 1


def _positive_int(value: str) -> int:
    """An ``argparse`` ``type=`` that only accepts an integer in ``1 .. 2**63-1``.

    ``--limit 0``, ``--limit -1`` and ``--workers 0`` all parse fine as plain
    integers but mean something silently wrong here: ``--limit 0`` reads as
    "take none" and prints ``nothing pending`` even with a full backlog, a
    negative ``--limit`` means "no limit" on SQLite but errors on Postgres,
    and ``--workers 0`` (or negative) is accepted by ``ThreadPoolExecutor``
    as "just run it sequentially" with nothing telling the operator that is
    what happened. Rejecting anything below 1 here is an ordinary argparse
    usage error (exit 2) instead of a confusing runtime surprise. Raising
    ``ValueError`` (from the bare ``int(value)``) or
    :class:`argparse.ArgumentTypeError` are both caught by argparse itself
    and turned into that same clean error, the same way ``type=uuid.UUID``
    already works for ``reprocess <id>``.

    **The upper bound is why this is not just ``>= 1``.** ``--limit 2**63``
    passed this check, reached ``query_receipts``, and raised ``OverflowError``
    out of the SQLite driver -- the same shape ADR-0034 closed on the HTTP
    routes, surviving here because the CLI has its own validator. See
    :data:`_MAX_INT64` for why the ceiling is representability rather than
    policy.

    ``--workers`` shares this validator and does **not** need the ceiling:
    measured, ``ThreadPoolExecutor(max_workers=2**63)`` constructs and runs a
    task, because threads are spawned lazily. It is bounded because the two
    flags share one rule, not because a second defect was found.
    """
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    if parsed > _MAX_INT64:
        raise argparse.ArgumentTypeError(
            f"must be at most {_MAX_INT64} (the largest integer the database "
            f"can store), got {value!r}"
        )
    return parsed


def _decimal(value: str) -> Decimal:
    """An ``argparse`` ``type=`` for ``--min-confidence`` (ADR-0001: money and
    confidence are ``Decimal``, never ``float``, anywhere on this path).

    ``Decimal(value)`` raises ``decimal.InvalidOperation`` for a malformed
    string -- and unlike ``ValueError``, argparse does not catch that on its
    own, so a bad ``--min-confidence`` would otherwise escape as an uncaught
    traceback instead of the clean exit-2 usage error every other ``type=``
    in this module produces. Re-raising as ``ArgumentTypeError`` is what
    :func:`_positive_int` already does for ``--limit``/``--workers``.

    ``InvalidOperation`` alone is not enough: ``"nan"``, ``"inf"`` and
    ``"-Infinity"`` are all *legal* ``Decimal``s and parse without raising.
    ``--min-confidence nan`` compared false against every stored confidence,
    so a typo produced a valid, empty workbook and exit ``0`` -- a filter that
    silently matched nothing looks exactly like "there were no such receipts".
    The ``is_finite()`` check mirrors
    :func:`~receipts.persist.repository._coerce_money`, which refuses the same
    values on the write side for the same reason.
    """
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value!r}") from None
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError(
            f"must be a finite decimal value, got {value!r}"
        )
    return parsed


def _add_process(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "process",
        help="drain pending receipts through the pipeline",
        description=(
            "Take every `pending` receipt -- oldest first -- and run it "
            "through the pipeline. By default this enqueues to RQ, "
            "production's own path; `--inline` runs in this process instead, "
            "for a single machine or a box with no Redis (ADR-0013)."
        ),
    )
    parser.add_argument(
        "--limit", type=_positive_int, default=None,
        help="take at most this many pending receipts this run (default: no cap)",
    )
    parser.add_argument(
        "--inline", action="store_true",
        help="run the pipeline in this process instead of enqueueing to RQ",
    )
    parser.add_argument(
        "--workers", type=_positive_int, default=4,
        help="thread pool size for --inline (default: %(default)s)",
    )


def _add_reprocess(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "reprocess",
        help="re-run the pipeline against one receipt",
        description=(
            "Re-run the pipeline against one receipt, synchronously. Allowed "
            "without --force on `pending`, `needs_review` and `rejected`; "
            "`auto_approved` needs --force, since overwriting a result the "
            "system already stands behind should be deliberate. A `reviewed` "
            "receipt is never overwritten, with or without --force -- the run "
            "still happens and a review task records what it produced "
            "(ADR-0013)."
        ),
    )
    parser.add_argument("id", type=uuid.UUID, help="the receipt id to reprocess")
    parser.add_argument(
        "--force", action="store_true",
        help="also reprocess an auto_approved receipt (never a reviewed one)",
    )


def _add_export(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "export",
        help="write the accounting workbook (spec section 13) for a set of receipts",
        description=(
            "Query receipts and write the spec section 13 workbook -- Receipts, "
            "LineItems, Needs Review, and Summary sheets -- to --out. "
            "`pending` and `rejected` receipts are excluded unless --status "
            "names one of them explicitly: a pending row is an upload in "
            "flight, not a transaction, and a rejected one is a duplicate "
            "the pipeline deliberately keeps out of exports. Refuses -- "
            "writing nothing -- rather than silently truncating past "
            f"{_EXPORT_MAX_ROWS} matching receipts."
        ),
    )
    parser.add_argument("--out", required=True, help="workbook path to write")
    parser.add_argument(
        "--from", dest="date_from", type=date.fromisoformat, default=None,
        help="only receipts transacted on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to", dest="date_to", type=date.fromisoformat, default=None,
        help="only receipts transacted on or before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--status", type=ReceiptStatus, default=None,
        help="only this status (default: every status except pending/rejected)",
    )
    parser.add_argument(
        "--merchant-id", type=uuid.UUID, default=None,
        help="only receipts for this merchant",
    )
    parser.add_argument(
        "--min-confidence", type=_decimal, default=None,
        help="only receipts scored at or above this confidence",
    )


def _add_merchants(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("merchants", help="list merchants and manage their extraction hints")
    merchants_sub = parser.add_subparsers(dest="merchants_command", required=True)

    merchants_sub.add_parser(
        "list",
        help="list every merchant: id, canonical name, tax id, receipt count",
        description=(
            "List every merchant: id, canonical name, tax id, receipt count. "
            "The receipt count is a running tally that can read high: a "
            "duplicate caught after extraction is credited before it is found "
            "to be a duplicate, and a receipt that moves to another merchant "
            "on reprocessing is not taken off the first merchant's total. "
            "Re-uploading the same image is not counted -- that duplicate is "
            "caught before any merchant is resolved."
        ),
    )

    hints_parser = merchants_sub.add_parser(
        "hints",
        help="show or edit a merchant's extraction hints",
        description=(
            "Print a merchant's current `merchants.hints` -- free text "
            "injected into the extraction prompt when the merchant is "
            "recognised (spec section 8.3). --add appends one hint; --clear empties "
            "the list. With neither flag, this only prints what is already "
            "stored."
        ),
    )
    hints_parser.add_argument("id", type=uuid.UUID, help="the merchant id")
    hints_group = hints_parser.add_mutually_exclusive_group()
    hints_group.add_argument("--add", metavar="TEXT", default=None, help="append a hint")
    hints_group.add_argument("--clear", action="store_true", help="remove every hint")


def _add_eval(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "eval",
        help="run the golden-set baseline and print the spec section 16 metrics",
        description=(
            "Run the M1 pipeline over the golden set and print the six spec "
            "section 16 metrics (eval.run_baseline). Writes a timestamped, "
            "prompt-versioned results file under --results-dir for "
            "`receipts calibrate` to read. No accuracy claim is implied by "
            "a single run -- see docs/KNOWN_ISSUES.md ISSUE-001."
        ),
    )
    parser.add_argument(
        "--golden-dir", default=None,
        help="golden set directory (default: eval.golden_set.GOLDEN_DIR)",
    )
    parser.add_argument(
        "--results-dir", default=None,
        help="where to write the results JSON (default: eval/results/)",
    )


def _add_calibrate(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "calibrate",
        help="recommend an auto-approve threshold from a `receipts eval` results file",
        description=(
            "Read a `receipts eval` results file and print the calibration "
            "curve (threshold, auto-approve rate, precision, and the "
            "approved/correct counts behind that precision), then recommend "
            "the lowest threshold that reaches --target precision, sits at or "
            f"above the {REVIEW_THRESHOLD} review boundary, and approves at "
            f"least {_MIN_APPROVED_SAMPLE} receipts. Recommends nothing when "
            "no threshold does all three -- never a threshold that approves "
            "everything, and never one whose precision rests on a sample of "
            "one. Refuses outright, printing no precision figure, on a "
            "zero-receipt result set. No accuracy claim is implied -- see "
            "docs/KNOWN_ISSUES.md ISSUE-001."
        ),
    )
    parser.add_argument(
        "--results", default=None,
        help="a specific results JSON to read (default: newest under --results-dir)",
    )
    parser.add_argument(
        "--results-dir", default=None,
        help="directory to search for the newest results file (default: eval/results/)",
    )
    parser.add_argument(
        "--target", type=_decimal, default=Decimal("0.99"),
        help="minimum acceptable auto-approval precision (default: %(default)s)",
    )
    parser.add_argument(
        "--set", dest="set_threshold", action="store_true",
        help=(
            "persist the recommended threshold to AUTO_APPROVE_THRESHOLD in the "
            "env file (--env-file, default .env). Writes ONLY when a threshold "
            "is recommended -- i.e. one that clears all three gates -- so this "
            "flag can never set the auto-approve gate to a value the command "
            "would refuse to recommend. Writes nothing when none is recommended."
        ),
    )
    parser.add_argument(
        "--env-file", default=".env",
        help="the env file --set writes AUTO_APPROVE_THRESHOLD to (default: %(default)s)",
    )


def _add_sweep(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "sweep",
        help="bring interrupted receipts to a terminal state",
        description=(
            "Find receipts whose processing stopped without reaching a "
            "terminal status and send them to review. An interruption -- a "
            "timeout, a container restart, an operator's Ctrl-C -- runs no "
            "handler in the process it kills, so nothing inside a run can "
            "close this; something that survives has to notice. Run it on a "
            "schedule. `--dry-run` reports what would move and writes nothing."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be swept without writing anything",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipts", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_ingest(sub)
    _add_users(sub)
    _add_process(sub)
    _add_reprocess(sub)
    _add_export(sub)
    _add_merchants(sub)
    _add_eval(sub)
    _add_calibrate(sub)
    _add_sweep(sub)
    return parser


def _make_storage(settings: Settings) -> StorageBackend:
    """Build the configured blob backend.

    The policy moved to :func:`receipts.ingest.storage.make_storage` when the
    ASGI entry point needed the same decision; this stays as a delegation so
    every call site in this module, and this name in any test that reaches for
    it, keep working. Never called for a command that does not need a backend,
    so ``receipts users list`` works with no blob store configured at all.
    """
    return make_storage(settings)


def _collect_files(path: Path, *, recursive: bool) -> list[Path]:
    """Files ``ingest`` should attempt: one path, or a directory's entries.

    A directory is *not* walked recursively unless asked: an operator pointing
    ``ingest`` at a folder that happens to contain unrelated subfolders should
    not have every nested file swept in by default.
    """
    if not path.is_dir():
        return [path]
    entries = path.rglob("*") if recursive else path.iterdir()
    return sorted(p for p in entries if p.is_file())


def cmd_ingest(
    args: argparse.Namespace,
    *,
    session_factory,
    storage: StorageBackend,
    settings: Settings,
) -> int:
    """Validate and store every file under ``args.path``; write pending rows.

    Each file is validated and stored independently, so one rejected file
    (printed as ``REJECTED  <name>: <reason>``, never silently dropped -- §18)
    does not stop the rest of the batch. Every successfully ingested job is
    then written as a ``pending`` receipt row in a single session and
    committed together. This does **not** enqueue processing (ADR-0013):
    ``receipts process`` drains pending rows from whichever entry point wrote
    them.

    **Rejections go to stderr; only ids and the summary go to stdout.** This
    command's stdout is machine-readable by construction -- one
    ``<id>  <filename>`` line per ingested file -- so
    ``receipts ingest ./batch > ids.txt 2> errors.log`` has to put the
    rejection prose in ``errors.log``, not in the id stream. Printing it to
    stdout left ``errors.log`` empty while a script parsing ids silently
    picked up ``REJECTED  notes.txt: ...`` as though it were one, and a CI job
    watching stderr saw nothing at all when files were dropped.
    """
    files = _collect_files(Path(args.path), recursive=args.recursive)

    jobs = []
    rejected = 0
    for file in files:
        try:
            # A PDF becomes one job per page, so one file can print several
            # ids. stdout stays one id per line, which is what keeps
            # `receipts ingest ./batch > ids.txt` machine-readable.
            new_jobs = ingest_file(
                file, storage, source=args.source, max_mb=settings.max_upload_mb
            )
        except ValueError as exc:
            print(f"REJECTED  {file.name}: {exc}", file=sys.stderr)
            rejected += 1
            continue
        jobs.extend(new_jobs)
        for job in new_jobs:
            print(f"{job.id}  {job.original_filename}")

    if jobs:
        with session_factory() as session:
            for job in jobs:
                create_pending_receipt(session, job)
            session.commit()

    print(f"ingested {len(jobs)}, rejected {rejected}")
    return EXIT_OK if rejected == 0 else EXIT_FAILED


def _read_password() -> str:
    """The new account's password, read from stdin -- never ``argv``.

    A piped or redirected stdin (``echo "$PW" | receipts users add alice``,
    or a CI step feeding in a secret) is read directly with ``readline``, one
    line, trailing newline stripped. An interactive terminal instead falls
    through to ``getpass.getpass`` so the password is not echoed.

    Checking ``isatty()`` here, rather than delegating straight to
    ``getpass.getpass``, is load-bearing on Windows: ``getpass.unix_getpass``
    already checks ``stream.isatty()`` and falls back to a plain stdin read,
    but ``getpass.win_getpass`` -- the one Windows always uses -- has no such
    check and unconditionally reads raw keystrokes via ``msvcrt``, so a piped
    password hangs forever there instead of being read. This makes the piped
    path identical on every platform.
    """
    if sys.stdin is not None and not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("password: ")


def cmd_users(args: argparse.Namespace, *, session_factory) -> int:
    """Dispatch ``users add|list|deactivate|set-role``. The caller commits.

    Every ``ValueError`` the user store raises (a duplicate username, an
    unknown one, an unknown role) becomes a message **on stderr** and
    :data:`EXIT_FAILED` rather than a traceback. Stderr, not stdout, for the
    same reason :func:`cmd_ingest` routes its rejections there: every other
    command in this module reports failures on stderr, and a CI step that
    alerts on stderr must not stay silent while ``users add`` refuses a
    duplicate account.
    """
    if args.users_command == "add":
        password = _read_password()
        with session_factory() as session:
            try:
                create_user(session, args.username, password, args.role)
                session.commit()
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_FAILED
        print(f"created {args.username} ({args.role})")
        return EXIT_OK

    if args.users_command == "list":
        with session_factory() as session:
            users = list_users(session)
        for user in users:
            state = "active" if user.is_active else "inactive"
            print(f"{user.username}\t{user.role}\t{state}")
        return EXIT_OK

    if args.users_command == "deactivate":
        with session_factory() as session:
            try:
                deactivate(session, args.username)
                session.commit()
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_FAILED
        print(f"deactivated {args.username}")
        return EXIT_OK

    if args.users_command == "set-role":
        with session_factory() as session:
            try:
                set_role(session, args.username, args.role)
                session.commit()
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_FAILED
        print(f"{args.username} is now {args.role}")
        return EXIT_OK

    raise AssertionError(  # unreachable: subparsers are required
        f"unhandled users subcommand {args.users_command!r}"
    )


def _job_from_receipt(receipt: Receipt) -> ReceiptJob:
    """Rebuild the job for a stored receipt.

    **Lossy by construction.** ``source``, ``original_filename`` and
    ``content_type`` are not §6 columns, so they cannot be recovered from the
    row. ``process_receipt`` uses ``id`` and ``image_key``; the other three are
    placeholders, and anyone who later needs faithful provenance has to add
    columns rather than infer them (ADR-0013). ``source`` is the one of the
    three that is not purely inert, though: a worker that later picks this
    job up off the queue logs it (``worker.py``'s ``"Processing receipt %s
    from %s"``), so a receipt that reaches the worker via ``receipts
    process`` is logged as arriving from ``"cli"`` even when it was
    originally uploaded through ``POST /upload``. Nothing is stored from it
    (``source`` is not a ``receipts`` column), so this is a worker-log
    inaccuracy, not a data-integrity one.
    """
    return ReceiptJob(
        id=receipt.id,
        image_key=receipt.image_key,
        source="cli",
        original_filename=Path(receipt.image_key).name,
        content_type="image/jpeg",
    )


def cmd_process(
    args: argparse.Namespace,
    *,
    session_factory,
    storage: StorageBackend,
    settings: Settings,
    client_factory: Callable[[], VLMClient] | None = None,
    queue_factory: Callable[[], Any] | None = None,
) -> int:
    """Drain ``pending`` receipts: enqueue to RQ, or run in-process (ADR-0013).

    The ``pending`` row is the single work list -- the same query picks up a
    receipt whether it arrived through ``receipts ingest`` or ``POST
    /upload`` -- taken oldest first. Omitting ``--limit`` always passes an
    explicit limit (:data:`_NO_LIMIT` in that case) rather than skipping the
    keyword, so ``--help``'s "no cap" is what actually happens instead of
    silently inheriting ``query_receipts``'s own default of 1000. With
    nothing pending this prints a message and returns :data:`EXIT_OK`: an
    empty work list is not a failure.

    **Enqueue path (the default).** This is production's own path, so it is
    the one that must run here too, or a worker-only bug stays invisible
    until deployment. A missing ``REDIS_URL`` is a hard failure naming
    ``--inline`` rather than a silent fallback -- a fallback would mean the
    operator believes work is queued when it is actually running in a
    terminal they are about to close. ``queue_factory`` defaults to
    :func:`~receipts.worker.make_queue`.

    **``--inline``** runs :func:`~receipts.pipeline.process_receipt`
    synchronously in this process, ``--workers`` at a time, building each
    call's primary rung from ``client_factory`` (defaulting to the probe
    primary from ``make_extract_ladder``) exactly the way
    :func:`~receipts.pipeline.process_batch` builds one client per job, with a
    shared triage rung and fallback built once from ``make_extract_ladder``.

    **Both loops contain per-job failures identically**
    (:data:`_UNCONTAINED`). On the inline path, ``process_receipt`` raises
    for the one case it cannot itself turn into a terminal row -- nothing at
    all could be written -- and ``client_factory()`` can raise too (a
    provider outage building the client); letting either escape the callable
    handed to ``ThreadPoolExecutor.map`` does not just lose *that* receipt's
    result, because CPython's ``Executor.map`` cancels every future still
    queued behind it. On the enqueue path a broker that drops mid-batch
    (``redis.ConnectionError`` out of ``queue.enqueue``) used to escape
    ``cmd_process`` entirely: a traceback, a couple of ``queued`` lines, no
    summary, and exit ``0`` -- the exit-code contract violated on the very
    path ADR-0013 calls production's own. Nothing was lost (the
    un-enqueued rows stay ``pending`` and the next run picks them up), but
    the operator was told nothing.

    Either way every job is always attempted and always reported -- as a
    normal per-receipt line, or as a ``failed`` one -- and a receipt landing
    in review still never flips the exit code (ADR-0013): this returns
    :data:`EXIT_FAILED` only when at least one receipt could not be run or
    queued at all, never because of where a receipt that *did* run ended up.
    """
    try:
        from .pipeline import BatchResult, process_receipt
        from .worker import enqueue_receipt, make_queue
    except ModuleNotFoundError as exc:
        if not _is_missing_pipeline_extra(exc):
            raise
        print(_PIPELINE_NOT_INSTALLED, file=sys.stderr)
        return EXIT_FAILED

    limit = _NO_LIMIT if args.limit is None else args.limit
    with session_factory() as session:
        pending = query_receipts(session, status=ReceiptStatus.PENDING, limit=limit)
        jobs = [_job_from_receipt(receipt) for receipt in pending]

    if not jobs:
        print("nothing pending")
        return EXIT_OK

    if not args.inline:
        if not settings.redis_url:
            print(
                "error: REDIS_URL is not set, so there is no queue to enqueue "
                "to. Run with --inline to process these receipts in this "
                "process instead.",
                file=sys.stderr,
            )
            return EXIT_FAILED

        queue_factory = queue_factory if queue_factory is not None else make_queue
        queue = queue_factory()
        queued = 0
        failed = 0
        for job in jobs:
            try:
                enqueue_receipt(job, queue)
            except _UNCONTAINED:
                raise
            except BaseException as exc:  # noqa: B036 - see _UNCONTAINED
                print(f"{job.id}  failed  {redact_pan(str(exc))}")
                failed += 1
                continue
            print(f"{job.id}  queued")
            queued += 1
        print(f"queued {queued}")
        if failed:
            print(f"failed: {failed}")
        return EXIT_FAILED if failed else EXIT_OK

    # An injected `client_factory` is a test seam and stays single-rung: a test
    # that hands over one scripted client must not silently acquire a second
    # from this machine's settings, and reuses that one client for triage
    # (`triage_client=None`). A real run builds all three rungs from
    # `make_extract_ladder`, so `receipts process` escalates and gives triage
    # its own full-timeout client exactly like the worker does -- wiring only
    # the worker is how these two paths drift (the factory's own docstring
    # records an earlier instance of that drift).
    if client_factory is not None:
        triage_client: VLMClient | None = None
        triage_fallback = None
        fallback = None
    else:
        # Fold the operator's saved processing mode into the settings before the
        # ladder is built, so `receipts process` honours it exactly like the
        # worker does -- the injected-factory seam above deliberately does not,
        # a scripted test must not acquire rungs from this machine's DB. Reads
        # the DB once, falls back to the pre-feature default when unreadable.
        settings = settings_for_run(settings, session_factory)
        # The triage rungs and extract fallback (full-timeout / cloud) are shared
        # across jobs; the per-job factory builds the primary extract probe rung
        # fresh for thread isolation, the way this path always built its per-job
        # client. All rungs come from the single `make_extract_ladder`
        # construction site, which returns
        # `(triage, triage_fallback, extract_primary, extract_fallback)`.
        triage_client, triage_fallback, _primary, fallback = make_extract_ladder(settings)
        client_factory = lambda: make_extract_ladder(settings)[2]  # noqa: E731

    def run(job: ReceiptJob) -> tuple[ReceiptJob, ProcessResult | None, BaseException | None]:
        try:
            result = process_receipt(
                job, client=client_factory(), storage=storage,
                triage_client=triage_client,
                triage_fallback_client=triage_fallback,
                extract_fallback_client=fallback,
                session_factory=session_factory, settings=settings,
            )
        except _UNCONTAINED:
            raise
        except BaseException as exc:  # noqa: B036 - see _UNCONTAINED
            return job, None, exc
        return job, result, None

    if args.workers <= 1 or len(jobs) <= 1:
        outcomes = [run(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            outcomes = list(pool.map(run, jobs))

    results: list[ProcessResult] = []
    failed = 0
    for job, result, exc in outcomes:
        if result is not None:
            print(f"{result.receipt_id}  {result.status.value}  {result.reason}")
            results.append(result)
        else:
            print(f"{job.id}  failed  {redact_pan(str(exc))}")
            failed += 1

    batch = BatchResult(processed=results)
    for status, count in batch.counts.items():
        print(f"{status.value}: {count}")
    if failed:
        print(f"failed: {failed}")
    print(f"total cost: {batch.total_cost_usd}")
    return EXIT_FAILED if failed else EXIT_OK


def cmd_reprocess(
    args: argparse.Namespace,
    *,
    session_factory,
    storage: StorageBackend,
    settings: Settings,
    client_factory: Callable[[], VLMClient] | None = None,
    queue_factory: Callable[[], Any] | None = None,
) -> int:
    """Re-run the pipeline against one receipt, synchronously (ADR-0013).

    An unknown id is :data:`EXIT_FAILED`. Otherwise a status gate runs before
    anything else: ``pending``, ``needs_review`` and ``rejected`` are always
    allowed; ``auto_approved`` needs ``--force``, since overwriting a result
    the system already stands behind should be deliberate.

    **A ``reviewed`` receipt is never gated here, with or without
    ``--force``.** ``--force`` is a status gate, not a permission override --
    it extends reprocessing to ``auto_approved`` and no flag extends it to
    ``reviewed``. That is not enforced in this function: it is left to
    :func:`~receipts.pipeline.process_receipt`, which runs to completion
    rather than raising and reports the refusal through its return value.
    The reporting below keys on ``result.failed_stage is not None`` --
    *any* stage, not only ``"persist"``: a reviewed receipt whose blob has
    gone missing fails at ``"load"`` and never reaches the persist refusal
    at all, but the row is left just as untouched (nothing in
    ``_persist_failure`` mutates a row already ``reviewed``, regardless of
    which stage failed), and reporting a bare ``reviewed  confidence=1.000``
    for that case would read exactly like a clean re-verification when
    nothing was actually re-extracted. Every failure -- reviewed or not --
    also prints ``result.reason``, matching what ``cmd_process --inline``
    already prints for the identical outcome; the previous version silently
    dropped it here. This function does not duplicate
    :func:`~receipts.persist.repository.save_extraction`'s refusal
    (ADR-0012) and does not call
    :func:`~receipts.review.queue.enqueue_review` again -- that would
    overwrite the reason the pipeline already wrote with a vaguer one.

    ``queue_factory`` is accepted only for signature parity with
    :func:`cmd_process`; a reprocess always runs synchronously in this
    process and never touches a queue.

    ``receipts.pipeline`` is imported here, inside the function, because it
    needs the optional ``pipeline`` extra; see the module docstring.
    """
    try:
        from .pipeline import process_receipt
    except ModuleNotFoundError as exc:
        if not _is_missing_pipeline_extra(exc):
            raise
        print(_PIPELINE_NOT_INSTALLED, file=sys.stderr)
        return EXIT_FAILED

    with session_factory() as session:
        receipt = get_receipt(session, args.id)
        if receipt is None:
            print(f"error: no receipt with id {args.id}", file=sys.stderr)
            return EXIT_FAILED
        status = receipt.status
        job = _job_from_receipt(receipt)

    if status is ReceiptStatus.AUTO_APPROVED and not args.force:
        print(
            f"error: receipt {args.id} is auto_approved; pass --force to "
            "reprocess it (a reviewed receipt is never reprocessed, with or "
            "without --force)",
            file=sys.stderr,
        )
        return EXIT_FAILED

    # Same seam rule as `cmd_process` above: a real run gives triage its own
    # full-timeout client and escalates through the probe primary; an injected
    # factory stays single-rung and reuses that one client for triage.
    if client_factory is not None:
        triage_client: VLMClient | None = None
        triage_fallback = None
        fallback = None
    else:
        settings = settings_for_run(settings, session_factory)
        triage_client, triage_fallback, _primary, fallback = make_extract_ladder(settings)
        client_factory = lambda: make_extract_ladder(settings)[2]  # noqa: E731
    result = process_receipt(
        job, client=client_factory(), storage=storage,
        triage_client=triage_client,
        triage_fallback_client=triage_fallback,
        extract_fallback_client=fallback,
        session_factory=session_factory, settings=settings,
    )

    if result.failed_stage is not None:
        if result.status is ReceiptStatus.REVIEWED:
            print(
                f"{result.receipt_id}  reviewed (unchanged): a human has "
                "already reviewed this receipt, so the run was not applied "
                f"to the stored row; it failed at {result.failed_stage!r} "
                f"and a review task is open with what happened -- "
                f"{result.reason}"
            )
        else:
            print(f"{result.receipt_id}  {result.status.value}  {result.reason}")
        return EXIT_OK

    print(f"{result.receipt_id}  {result.status.value}  confidence={result.confidence}")
    return EXIT_OK


def cmd_export(
    args: argparse.Namespace,
    *,
    session_factory,
    settings: Settings,
) -> int:
    """Write the §13 workbook for every receipt matching ``args``'s filters.

    The query and the read-side row assembly are entirely Task 1's
    :func:`~receipts.review.serializers.query_export_receipts` and
    :func:`~receipts.review.serializers.build_export_rows` -- the same two
    functions ``GET /export/xlsx`` calls -- so a CLI export and an API
    export of identical filters can never disagree about which receipts
    qualify or what ends up in a row. ``pending``/``rejected`` receipts are
    excluded unless ``--status`` names one of them explicitly; that
    exclusion lives in ``query_export_receipts`` itself, not here.

    Fetches ``_EXPORT_MAX_ROWS + 1`` rows -- one past the cap -- and, if
    that many actually come back, prints to stderr and returns
    :data:`EXIT_FAILED` **without calling**
    :func:`~receipts.export.xlsx.export_workbook` at all, so nothing is
    written to ``--out``: a silently shortened export reads as a complete
    ledger, which is worse than making the operator narrow the filter and
    ask again.

    ``settings.session_secret`` may be ``None`` -- the CLI needs no session
    of its own -- in which case ``build_export_rows`` leaves every row's
    image column empty rather than minting an unverifiable link.

    ``openpyxl`` is an optional ``pipeline``-extra dependency, so both
    ``receipts.export.xlsx`` **and** ``receipts.review.serializers`` (which
    imports ``ReceiptExportRow`` from it) are imported here rather than at
    module top; see the module docstring.

    ``--out`` is checked before any work happens: pointed at an existing
    directory it used to reach ``export_workbook`` and surface as a raw
    ``PermissionError`` (``IsADirectoryError`` off Windows). Every other way
    this command declines is a message plus :data:`EXIT_FAILED`, and a
    mistyped path is the most ordinary mistake there is.
    """
    try:
        from .export.xlsx import export_workbook
        from .persist.repository import mark_receipts_processed
        from .review.serializers import build_export_rows, query_export_receipts
    except ModuleNotFoundError as exc:
        if not _is_missing_pipeline_extra(exc):
            raise
        print(_PIPELINE_NOT_INSTALLED, file=sys.stderr)
        return EXIT_FAILED

    out_path = Path(args.out)
    if out_path.is_dir():
        print(
            f"error: --out {out_path} is a directory; give the path of the "
            "workbook file to write",
            file=sys.stderr,
        )
        return EXIT_FAILED

    with session_factory() as session:
        receipts = query_export_receipts(
            session,
            status=args.status,
            merchant_id=args.merchant_id,
            date_from=args.date_from,
            date_to=args.date_to,
            min_confidence=args.min_confidence,
            limit=_EXPORT_MAX_ROWS + 1,
        )
        if len(receipts) > _EXPORT_MAX_ROWS:
            print(
                f"error: this export matches more than {_EXPORT_MAX_ROWS} "
                "receipts; narrow the filter (status, merchant, or date "
                "range) and try again",
                file=sys.stderr,
            )
            return EXIT_FAILED

        extractions, export_rows = build_export_rows(
            session, receipts, secret=settings.session_secret,
            image_url_ttl_s=settings.export_image_url_ttl_s,
        )
        receipt_ids = [receipt.id for receipt in receipts]

    try:
        export_workbook(extractions, out_path, rows=export_rows)
    except OSError as exc:
        # A path the filesystem will not accept (no such parent directory, no
        # permission, a name the platform rejects) is the operator's typo, not
        # a bug: the same clean message plus EXIT_FAILED as every other refusal
        # here, rather than a traceback out of openpyxl's writer.
        print(f"error: could not write {out_path}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    with session_factory() as session:
        mark_receipts_processed(session, receipt_ids, processed_by=None)
        session.commit()
    print(f"wrote {out_path} ({len(receipts)} receipts)")
    return EXIT_OK


#: The exact suffix (case-insensitive) every stored hint must end with --
#: §18: hints are guidance only, and the prompt block they are injected into
#: must always close by telling the model to defer to the image when a hint
#: and the image disagree, or a hint becomes a source of hallucination on
#: the day a merchant changes its receipt format.
_TRUST_THE_IMAGE = "trust the image"


def cmd_merchants(args: argparse.Namespace, *, session_factory) -> int:
    """Dispatch ``merchants list|hints``. The caller commits.

    ``list`` prints one line per merchant: id, canonical name, tax id,
    receipt count. ``hints <id>`` prints the merchant's current hints,
    optionally mutating them first -- ``--add`` appends, ``--clear``
    empties -- and always re-prints the resulting list. An unknown id
    prints to stderr and is :data:`EXIT_FAILED`.

    **The JSON-mutation trap (verified against ``persist/models.py`` before
    this was written).** ``Merchant.hints`` is a plain ``sa.JSON()`` column
    with no ``MutableList`` registered, so SQLAlchemy does not track
    in-place mutation: ``merchant.hints.append(text)`` would silently never
    reach the database -- and the identity map hands the very same
    (mutated, in-memory-only) list back to any read in the *same* session,
    so the bug would not even surface in a same-session test. Rebinding the
    attribute (``merchant.hints = [*merchant.hints, text]`` /
    ``merchant.hints = []``) is what makes the ORM see a new value and mark
    the column dirty.
    """
    if args.merchants_command == "list":
        with session_factory() as session:
            merchants = session.scalars(select(Merchant).order_by(Merchant.canonical_name)).all()
        for merchant in merchants:
            print(
                f"{merchant.id}\t{merchant.canonical_name}\t"
                f"{merchant.tax_id or ''}\t{merchant.receipt_count}"
            )
        return EXIT_OK

    if args.merchants_command == "hints":
        with session_factory() as session:
            merchant = session.get(Merchant, args.id)
            if merchant is None:
                print(f"error: no merchant with id {args.id}", file=sys.stderr)
                return EXIT_FAILED

            if args.clear:
                merchant.hints = []
                session.commit()
            elif args.add is not None:
                text = args.add
                if not text.lower().endswith(_TRUST_THE_IMAGE):
                    text = f"{text}; {_TRUST_THE_IMAGE}"
                    print(
                        "note: hint did not end by deferring to the image; "
                        f'appended "; {_TRUST_THE_IMAGE}" (spec section 18)'
                    )
                merchant.hints = [*merchant.hints, text]
                session.commit()

            hints = list(merchant.hints)

        for hint in hints:
            print(hint)
        return EXIT_OK

    raise AssertionError(  # unreachable: subparsers are required
        f"unhandled merchants subcommand {args.merchants_command!r}"
    )


#: Printed (to stderr) when ``eval``/``calibrate`` cannot import ``eval.*`` at
#: all. ``eval/`` is dev/research tooling that deliberately does not ship
#: with the installed distribution (see ``pyproject.toml``'s
#: ``[tool.setuptools.packages.find]`` comment) -- unlike a missing optional
#: extra (``worker``, ``api``, ``pipeline``), there is no ``pip install
#: receipts[eval]`` that fixes this; the fix is running from a checkout.
_EVAL_NOT_INSTALLED = (
    "error: the evaluation tooling (the `eval` package) is not available in "
    "this environment. `eval/` ships with the project's repository, not "
    "with the installed `receipts` distribution -- run this from a "
    "checkout of the repository to use `receipts eval`/`receipts calibrate`."
)


def _is_missing_eval(exc: ModuleNotFoundError) -> bool:
    """Whether ``exc`` is ``eval``/``eval.*`` itself missing, not some other
    package missing several frames deeper inside the same import.

    ``eval.run_baseline`` pulls in ``receipts.pipeline``, which needs the
    optional ``pipeline`` extra (Pillow, OpenCV, ...); an incomplete install
    that has ``eval/`` but lacks that extra would also raise
    ``ModuleNotFoundError``, just naming ``PIL`` or similar instead. Checking
    ``.name`` rather than treating every ``ModuleNotFoundError`` as "eval is
    not installed" is the same discipline :func:`_is_missing_schema` already
    applies to ``DBAPIError`` below: match the actual condition, and let
    anything this was not written for propagate rather than mislabel it.
    """
    return exc.name == "eval" or (exc.name is not None and exc.name.startswith("eval."))


#: The smallest auto-approved sample :func:`cmd_calibrate` will recommend a
#: threshold from.
#:
#: **A floor against single-sample precision.** The guard this replaced only
#: excluded a threshold whose approved set was *empty*; one receipt that
#: happens to be critical-correct reads as ``100.00%`` precision and cleared
#: it, so a fifty-receipt run in which a single receipt passed produced a
#: confident recommendation resting on that one receipt -- under a caveat
#: quoting the fifty.
#:
#: **The value is provisional.** Five is chosen to be obviously more than one,
#: not because any analysis says five is enough; five approvals still cannot
#: support a 99% precision claim (a 99% claim needs hundreds). The real answer
#: is a power calculation against the larger held-out set that P8.T2 builds,
#: which does not exist yet -- see ``docs/KNOWN_ISSUES.md`` ISSUE-001. Raise
#: this when that set lands; do not lower it.
_MIN_APPROVED_SAMPLE = 5


def _approved_counts(results: list[Any], threshold: Decimal) -> tuple[int, int]:
    """``(approved, critical-correct)`` at ``threshold`` -- the sample a curve
    row's precision is computed over.

    Mirrors :func:`~eval.metrics.calibration_curve`'s own
    ``confidence >= threshold`` test on purpose: it is the definition of
    "auto-approved" that produced the precision being displayed, and the two
    must not drift. ``results`` is a list of
    :class:`~eval.metrics.EvalResult`, typed loosely here only because that
    class cannot be imported at module top (``eval/`` does not ship).
    """
    approved = [r for r in results if r.confidence >= threshold]
    return len(approved), sum(1 for r in approved if r.critical_correct)


#: The env var :func:`cmd_calibrate` ``--set`` persists the chosen threshold to.
#: The same name ``config.settings.Settings`` binds to ``auto_approve_threshold``
#: (case-insensitive), which is what ``route()`` gates on -- so a value written
#: here is the value the running system routes on after its next
#: ``get_settings()`` (a fresh ``Settings()``, not a process-wide singleton).
_THRESHOLD_ENV_KEY = "AUTO_APPROVE_THRESHOLD"


def _write_env_threshold(env_path: Path, threshold: Decimal) -> None:
    """Set ``AUTO_APPROVE_THRESHOLD`` to ``threshold`` in ``env_path``, in place.

    Replaces an existing ``AUTO_APPROVE_THRESHOLD=`` line (the FIRST one, matched
    ignoring surrounding whitespace and case, since pydantic-settings reads the
    key case-insensitively) and leaves every other line -- comments, ordering,
    the rest of the config -- exactly as it was. Appends the line when the key is
    absent, and creates the file when it does not exist.

    The value is ``str(threshold)`` -- the ``Decimal``'s own text, e.g. ``0.85``
    -- never a ``float``: this key round-trips back through
    ``Settings.auto_approve_threshold`` as a ``Decimal``, and a ``float`` here
    would reintroduce the rounding drift the whole money path exists to avoid.
    """
    line = f"{_THRESHOLD_ENV_KEY}={threshold}"

    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines()

    for index, current in enumerate(lines):
        stripped = current.strip()
        # Match `KEY=...` (optionally spaced) case-insensitively; leave a
        # commented `# AUTO_APPROVE_THRESHOLD=...` alone -- it is documentation,
        # not a live setting, and rewriting it would make the file lie.
        key_part = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key_part.casefold() == _THRESHOLD_ENV_KEY.casefold():
            lines[index] = line
            break
    else:
        lines.append(line)

    # Preserve a trailing newline: an env file ends with one, and a rewrite that
    # dropped it would show as a spurious last-line diff.
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _unreadable_results(results_path: Path, detail: str) -> str:
    """The stderr line for a results file :func:`cmd_calibrate` cannot read."""
    return (
        f"error: {results_path} is not a `receipts eval` results file this "
        f"version can read ({detail}); re-run `receipts eval` to produce a "
        "fresh one"
    )


def cmd_eval(
    args: argparse.Namespace,
    *,
    settings: Settings,
    client: VLMClient | None = None,
    run_baseline_fn: Callable[..., Any] | None = None,
) -> int:
    """Run the golden-set baseline and print the spec section 16 report.

    A thin wrapper over :func:`eval.run_baseline.run_baseline`: this command
    owns no scoring logic of its own, only argument plumbing, so "what counts
    as correct" never has two definitions to keep in sync. ``client`` exists
    for tests to inject; production always leaves it ``None`` and lets
    ``run_baseline`` build one from ``settings`` itself (refusing the
    response-less ``fake`` provider before any work happens).

    **``eval.run_baseline`` is imported here, inside the function, never at
    module top.** ``eval/`` does not ship with the installed distribution
    (see :data:`_EVAL_NOT_INSTALLED`); a module-top import broke every
    ``receipts`` command, not only this one, the moment the package was
    actually installed anywhere ``eval/`` did not happen to sit next to --
    caught by running the real installed console script, since ``pytest``'s
    own ``pythonpath`` setting hides the problem in-process. A
    :class:`ModuleNotFoundError` naming ``eval`` (checked via
    :func:`_is_missing_eval`, not caught blindly) is printed to stderr and
    turned into :data:`EXIT_FAILED`; anything else propagates.

    ``run_baseline_fn`` is the injection seam a test uses in place of the old
    ``monkeypatch.setattr(cli_module, "run_baseline", ...)`` pattern --
    matching how :func:`cmd_process`/:func:`cmd_reprocess` already accept
    ``client_factory``/``queue_factory`` rather than a test reaching into the
    module's globals. Left ``None``, production resolves it to the real
    ``run_baseline`` via the same lazy import.

    A refused provider (:class:`RuntimeError`) or a missing golden-set image
    (:class:`FileNotFoundError`) is printed to stderr and turned into
    :data:`EXIT_FAILED` rather than a traceback. ``run_baseline_fn`` is
    called with every argument as a keyword: the given test injects
    ``lambda **kw: report``, a callable that only accepts keyword arguments,
    so a positional call would break it even if production behaviour were
    otherwise identical.

    **This command refuses a zero-receipt run, twice over.** ``calibrate``,
    the *reader* of a results file, has always refused an empty result set;
    nothing guarded this command, the *producer* -- which also prints the
    system's headline metric to an operator's terminal and exits ``0``. A
    typo'd ``--golden-dir`` raised nothing at all (globbing a directory that
    does not exist simply yields no labels), so the run scored zero receipts,
    ``_build_report`` defined auto-approval precision as ``1.0`` because
    nothing had been approved, and the operator read
    ``Auto-approval precision: 100.00%`` off a run that had looked at no
    receipts. This project has committed exactly that artifact once already
    (ADR-0013), on exactly this path.

    So: ``--golden-dir`` is validated **before** ``run_baseline_fn`` is
    called, which is what stops a poisoned results file from ever being
    written -- the file is persisted inside ``run_eval``, so by the time a
    report comes back it is already on disk, and
    :func:`~eval.run_baseline.latest_results_file` sorts by mtime, meaning
    the newest (poisoned) file would shadow a genuine earlier baseline
    sitting in the same directory until a human deleted it. The
    ``n_receipts == 0`` check afterwards is the backstop for every other
    route to an empty run, including an injected ``run_baseline_fn``.
    """
    try:
        from eval.golden_set import GOLDEN_DIR
        from eval.run_baseline import format_report

        if run_baseline_fn is None:
            from eval.run_baseline import run_baseline as run_baseline_fn
    except ModuleNotFoundError as exc:
        if not _is_missing_eval(exc):
            raise
        print(_EVAL_NOT_INSTALLED, file=sys.stderr)
        return EXIT_FAILED

    golden_dir = Path(args.golden_dir) if args.golden_dir is not None else GOLDEN_DIR
    results_dir = Path(args.results_dir) if args.results_dir is not None else None

    # `run_eval` reads `golden_dir/labels/*.json`; both failure modes below are
    # silent there -- a missing directory and an empty one glob identically to
    # nothing -- so they are named here instead, before any work or any write.
    labels_dir = golden_dir / "labels"
    if not golden_dir.is_dir():
        print(
            f"error: no golden set directory at {golden_dir}; pass an existing "
            "--golden-dir (it must contain a `labels/` directory of "
            "*.json labels)",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if not sorted(labels_dir.glob("*.json")):
        print(
            f"error: the golden set at {golden_dir} has no labels to score "
            f"({labels_dir}/*.json is empty or missing); label the golden set "
            "first -- see eval/golden/README.md",
            file=sys.stderr,
        )
        return EXIT_FAILED

    try:
        report = run_baseline_fn(
            golden_dir=golden_dir,
            client=client,
            results_dir=results_dir,
            default_currency=settings.default_currency,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if report.n_receipts == 0:
        print(
            f"error: this run scored zero receipts from {golden_dir}; there is "
            "no metric to report from an empty run, and reporting one "
            "(auto-approval precision reads as a vacuous 100% when nothing was "
            "approved) is exactly the artifact this project has already "
            "committed once. Check the golden set and run `receipts eval` "
            "again.",
            file=sys.stderr,
        )
        return EXIT_FAILED

    print(format_report(report))
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace, *, results_dir: Path | None = None) -> int:
    """Recommend an auto-approve threshold from a `receipts eval` results file.

    **Imports ``eval.harness``/``eval.metrics``/``eval.run_baseline`` here,
    inside the function, never at module top** -- see :func:`cmd_eval`'s
    docstring and :data:`_EVAL_NOT_INSTALLED` for why. A
    :class:`ModuleNotFoundError` naming ``eval`` (:func:`_is_missing_eval`)
    is printed to stderr and turned into :data:`EXIT_FAILED` before any of
    this function's own argument handling runs; anything else propagates.
    No test needs to swap out ``calibration_curve``/``EvalResult``/
    ``latest_results_file`` for a double -- they are pure functions the
    given tests already exercise for real through an on-disk results file --
    so unlike ``cmd_eval`` there is no analogous ``*_fn`` injection seam
    here, only the same lazy import.

    Resolves the file to read: ``--results`` if given, else the newest file
    under ``--results-dir`` (falling back to the ``results_dir`` collaborator,
    then to :data:`~eval.harness.DEFAULT_RESULTS_DIR`) via
    :func:`~eval.run_baseline.latest_results_file` -- the function this task
    renamed from a private helper with exactly one caller into a legitimate
    second consumer, rather than importing the private name or reimplementing
    the newest-file lookup here. Neither resolves to a file: stderr names
    `receipts eval` as the fix, :data:`EXIT_FAILED`.

    **Refuses a zero-receipt result set outright, printing no precision
    figure at all.** This project has already committed a results artifact
    reporting ``auto_approval_precision: 1.0`` on zero receipts once; the
    command that picks the auto-approval threshold is the worst place to
    repeat that mistake.

    A results file this version cannot read -- malformed JSON, a ``results``
    key that is not a list, a receipt entry missing ``critical_correct``, a
    ``null`` confidence -- is a clean message plus :data:`EXIT_FAILED`, like
    every other refusal here, rather than a ``KeyError``/``TypeError``
    traceback out of the comprehension below.

    Otherwise rebuilds :class:`~eval.metrics.EvalResult` objects from the
    JSON's ``results`` list (``field_acc={}`` -- the dataclass has no default
    for it, and :func:`~eval.metrics.calibration_curve` reads only
    ``confidence``/``critical_correct``, never ``field_acc``) and prints the
    full curve: threshold, auto-approve rate, precision, **and the approved
    and correct counts that precision is computed from**, so the sample
    behind each figure is visible on screen rather than implied.

    **Three conditions gate the recommendation, and every one of them exists
    because a precision figure can be true and worthless at the same time.**
    A threshold is recommended only when it is the lowest that:

    1. is at or above :data:`~receipts.score.thresholds.REVIEW_THRESHOLD`.
       ``calibration_curve``'s sweep starts at ``0``, where *everything* is
       approved -- so a golden set on which every receipt is critical-correct
       (the expected outcome of a first clean baseline on a small curated
       set) scored precision ``1.0`` at threshold ``0`` and this command
       recommended it. ``Settings.auto_approve_threshold`` has no lower bound
       and ``route()`` approves on ``confidence >= auto_threshold``, so an
       operator who followed that recommendation would auto-approve every
       receipt at any confidence and no receipt would ever reach a human
       again. The command whose whole job is protecting auto-approval
       precision must not be able to recommend switching the gate off; §12's
       review boundary is the floor below which a receipt is a full re-key,
       and it is the same constant the router and the export sheet use.
    2. approves at least :data:`_MIN_APPROVED_SAMPLE` receipts. The previous
       guard only excluded a *zero*-sized approved set, not a **one**-sized
       one: fifty receipts of which a single one cleared reported
       ``100.00%`` precision on a sample of one, under a caveat that cited
       the fifty.
    3. reaches ``--target`` precision.

    :func:`~eval.metrics.calibration_curve` defines precision as ``1.0`` when
    nothing is approved, and its sweep always includes ``1.0``, above every
    observed confidence, so a result set that is
    critical-incorrect end to end still produces a curve row
    ``(1.0, rate=0.0, precision=1.0)``; condition 2 subsumes the old
    nonzero-rate check that existed to reject it.

    When nothing satisfies all three, this says so plainly and returns
    :data:`EXIT_FAILED` without recommending anything -- never the least-bad
    number as though it had passed.

    Always closes with a standing caveat, regardless of whether a
    recommendation was found: a threshold is only as trustworthy as the
    golden set it was measured on, and there are still no measured accuracy
    numbers for this system (``docs/KNOWN_ISSUES.md`` ISSUE-001) -- a
    handful of golden receipts cannot support a confident >=99% claim.
    """
    try:
        from eval.harness import DEFAULT_RESULTS_DIR
        from eval.metrics import EvalResult, calibration_curve
        from eval.run_baseline import latest_results_file
    except ModuleNotFoundError as exc:
        if not _is_missing_eval(exc):
            raise
        print(_EVAL_NOT_INSTALLED, file=sys.stderr)
        return EXIT_FAILED

    if args.results is not None:
        results_path = Path(args.results)
        if not results_path.exists():
            print(
                f"error: no results file at {results_path}; run `receipts eval` first",
                file=sys.stderr,
            )
            return EXIT_FAILED
    else:
        search_dir = (
            Path(args.results_dir) if args.results_dir is not None
            else (results_dir if results_dir is not None else DEFAULT_RESULTS_DIR)
        )
        found = latest_results_file(search_dir)
        if found is None:
            print(
                f"error: no results file under {search_dir}; run `receipts eval` first",
                file=sys.stderr,
            )
            return EXIT_FAILED
        results_path = found

    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        print(f"error: {results_path} is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if not isinstance(data, dict):
        print(_unreadable_results(results_path, "the top level is not an object"),
              file=sys.stderr)
        return EXIT_FAILED

    results_json = data.get("results", [])
    if not isinstance(results_json, list):
        print(_unreadable_results(results_path, '"results" is not a list'), file=sys.stderr)
        return EXIT_FAILED
    if not results_json:
        print(
            "error: this results file has zero receipts; no auto-approval "
            "threshold can be chosen from an empty result set",
            file=sys.stderr,
        )
        return EXIT_FAILED

    try:
        results = [
            EvalResult(
                receipt_id=r["receipt_id"],
                confidence=Decimal(r["confidence"]),
                critical_correct=r["critical_correct"],
                field_acc={},
            )
            for r in results_json
        ]
    except (InvalidOperation, KeyError, TypeError) as exc:
        # A missing `critical_correct` (KeyError), a `"confidence": null`
        # (TypeError out of Decimal), an entry that is not an object at all
        # (TypeError) -- all of them used to escape as a bare traceback while
        # every other way this command declines is a message plus EXIT_FAILED.
        print(
            _unreadable_results(results_path, f"{type(exc).__name__}: {exc}"),
            file=sys.stderr,
        )
        return EXIT_FAILED

    curve = calibration_curve(results)
    target = args.target

    # (threshold, rate, precision, approved, correct). The last two are
    # recomputed here rather than plumbed out of `calibration_curve`, whose
    # triple shape is the committed results-file format (`_report_to_dict`'s
    # "calibration"); the `>=` test mirrors that function's own, deliberately.
    rows = [
        (threshold, rate, precision, *_approved_counts(results, threshold))
        for threshold, rate, precision in curve
    ]

    print(f"Calibration curve -- {len(results)} receipt(s), target precision {target}")
    print(
        f"  {'threshold':>10}  {'auto-approve rate':>18}  {'precision':>10}"
        f"  {'approved':>8}  {'correct':>8}"
    )
    for threshold, rate, precision, approved, correct in rows:
        print(
            f"  {str(threshold):>10}  {rate * 100:>17.2f}%  {precision * 100:>9.2f}%"
            f"  {approved:>8d}  {correct:>8d}"
        )

    # Three gates, all in the fail-dangerous direction; see the docstring. The
    # sample floor subsumes the old `rate > 0.0` check, which only excluded an
    # approved set of size zero -- never one of size one.
    recommended = next(
        (
            (threshold, approved, correct)
            for threshold, _rate, precision, approved, correct in rows
            if threshold >= REVIEW_THRESHOLD
            and approved >= _MIN_APPROVED_SAMPLE
            and precision >= float(target)
        ),
        None,
    )

    print()
    if recommended is None:
        print(
            f"no threshold at or above {REVIEW_THRESHOLD} reaches "
            f"{float(target) * 100:.2f}% precision over at least "
            f"{_MIN_APPROVED_SAMPLE} auto-approved receipt(s); recommending none"
        )
        code = EXIT_FAILED
    else:
        threshold, approved, correct = recommended
        print(
            f"recommended threshold: {threshold} "
            f"({correct} of {approved} auto-approved receipt(s) critical-correct)"
        )
        # --set persists ONLY here, inside the branch that found a recommendation
        # -- so it can never write a value the three gates above rejected. The
        # "recommending none" path returns before reaching this, leaving the env
        # file untouched, which is why a --set that clears nothing is a no-op
        # rather than an error the operator has to guard against.
        if getattr(args, "set_threshold", False):
            env_path = Path(args.env_file)
            _write_env_threshold(env_path, threshold)
            print(
                f"set {_THRESHOLD_ENV_KEY}={threshold} in {env_path} "
                "(takes effect on the next process start)"
            )
        code = EXIT_OK

    print(
        "\ncaveat: a threshold is only as trustworthy as the golden set it "
        f"was measured on. {len(results)} receipt(s) cannot support a "
        f"{float(target) * 100:.2f}% precision claim -- no accuracy number "
        "from this system has been validated on a full baseline yet "
        "(docs/KNOWN_ISSUES.md, ISSUE-001). Treat this recommendation as "
        "directional, not final."
    )
    return code


def cmd_sweep(args: argparse.Namespace, *, session_factory, settings: Settings) -> int:
    """Bring interrupted receipts to a terminal state.

    Exits ``EXIT_OK`` even when it moved receipts: a receipt routed to review
    is a completed command, not a failure (ADR-0013).
    """
    from .sweep import sweep_stranded

    moved = sweep_stranded(session_factory, settings=settings, dry_run=args.dry_run)
    verb = "would send" if args.dry_run else "sent"
    print(f"{verb} {len(moved)} stranded receipt(s) to review")
    for receipt_id in moved:
        print(f"  {receipt_id}")
    return EXIT_OK


def _is_missing_schema(exc: DBAPIError) -> bool:
    """Whether ``exc`` looks like a query against a table that does not exist.

    SQLite raises ``OperationalError`` with "no such table" in the driver
    message; Postgres raises ``ProgrammingError`` whose underlying driver
    exception carries SQLSTATE ``42P01`` (undefined_table) as ``.pgcode``
    (psycopg2) or ``.sqlstate`` (psycopg 3). The code is checked first, and
    the message only as a fallback for drivers that expose neither, so this
    matches the actual condition rather than a string wherever the driver
    makes that possible.
    """
    code = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
    if code == "42P01":
        return True
    return "no such table" in str(exc.orig).lower()


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run the command, returning its exit code.

    Returns rather than raising ``SystemExit`` so a test can assert on the
    code; :func:`_console_main` below is what actually exits.

    Builds the real session factory and, only inside the branch that needs it,
    the real storage backend -- so ``receipts users list`` runs on a machine
    with no blob store configured.

    **This never creates the schema.** This project manages the schema with
    Alembic (``alembic/env.py``) and checks it against a drift guard;
    ``Base.metadata.create_all`` would build the tables without stamping
    ``alembic_version``, so a later ``python -m alembic upgrade head`` fails
    with "table already exists" -- turning a clear "you forgot to migrate"
    into a database that needs manual repair, on Postgres potentially a
    production one. Instead, a command run against a database nobody has
    migrated yet is caught below and turned into a clear diagnosis.
    """
    args = build_parser().parse_args(argv)
    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))

    try:
        if args.command == "ingest":
            return cmd_ingest(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings,
            )
        if args.command == "users":
            return cmd_users(args, session_factory=session_factory)
        if args.command == "process":
            # queue_factory is left None so cmd_process resolves it to
            # receipts.worker.make_queue behind its own lazy import: naming it
            # here would need a module-top `from .worker import make_queue`,
            # and worker.py imports receipts.pipeline at *its* module top, so
            # that one line would drag the optional `pipeline` extra back into
            # every command again (see the module docstring).
            return cmd_process(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings,
            )
        if args.command == "reprocess":
            return cmd_reprocess(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings,
            )
        if args.command == "export":
            return cmd_export(args, session_factory=session_factory, settings=settings)
        if args.command == "merchants":
            return cmd_merchants(args, session_factory=session_factory)
        if args.command == "eval":
            return cmd_eval(args, settings=settings)
        if args.command == "calibrate":
            return cmd_calibrate(args)
        if args.command == "sweep":
            return cmd_sweep(args, session_factory=session_factory, settings=settings)
        # unreachable: subparsers are required
        raise AssertionError(f"unhandled command {args.command!r}")
    except DBAPIError as exc:
        if not _is_missing_schema(exc):
            raise
        print(
            "error: the database schema is not initialised; "
            "run `python -m alembic upgrade head` and try again.",
            file=sys.stderr,
        )
        return EXIT_FAILED


def _console_main() -> None:  # pragma: no cover - entry point wrapper
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover - `python -m receipts.cli`
    _console_main()
