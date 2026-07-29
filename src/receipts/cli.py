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
    file for ``calibrate`` to read.
  * **``calibrate`` refuses rather than guess wherever the evidence does
    not support a number.** A zero-receipt result set is refused
    outright, printing no precision figure at all -- this project has
    already committed a results artifact reporting
    ``auto_approval_precision: 1.0`` on zero receipts once, and the
    command that picks the auto-approval threshold is the worst place to
    repeat it. The recommendation itself ignores any threshold whose
    auto-approve rate is zero, even though ``calibration_curve`` reports
    that threshold's precision as a vacuous ``1.0`` -- the same trap one
    level deeper, inside a result set that does have receipts. Every run
    closes with a standing caveat that no accuracy number from this
    system has been measured on a full baseline yet (spec section 16,
    ``docs/KNOWN_ISSUES.md`` ISSUE-001).

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
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from config.settings import Settings, get_settings
from eval.harness import DEFAULT_RESULTS_DIR
from eval.metrics import EvalResult, calibration_curve
from eval.run_baseline import format_report, latest_results_file, run_baseline

from .export.xlsx import export_workbook
from .extract.clients.base import VLMClient
from .extract.clients.factory import make_client
from .ingest.ingest import ReceiptJob, ingest_file
from .ingest.storage import LocalStorage, S3Storage, StorageBackend
from .persist.models import Merchant, Receipt
from .persist.repository import create_pending_receipt, get_receipt, query_receipts
from .persist.session import make_engine, make_session_factory
from .persist.users import ROLE_REVIEWER, ROLES, create_user, deactivate, list_users, set_role
from .pipeline import BatchResult, ProcessResult, process_receipt
from .review.serializers import build_export_rows, query_export_receipts
from .score.confidence import ReceiptStatus
from .worker import enqueue_receipt, make_queue

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


def _positive_int(value: str) -> int:
    """An ``argparse`` ``type=`` that only accepts an integer ``>= 1``.

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
    """
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
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
    """
    try:
        return Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value!r}") from None


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
        "list", help="list every merchant: id, canonical name, tax id, receipt count",
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
            "curve (threshold, auto-approve rate, precision), then recommend "
            "the lowest threshold whose precision reaches --target with a "
            "nonzero auto-approve rate -- a threshold nothing is approved "
            "at is never recommended, however perfect calibration_curve "
            "reports its precision as being. Refuses outright, printing no "
            "precision figure, on a zero-receipt result set. No accuracy "
            "claim is implied -- see docs/KNOWN_ISSUES.md ISSUE-001."
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
    return parser


def _make_storage(settings: Settings) -> StorageBackend:
    """Build the configured blob backend. Never called for a command that
    does not need one, so ``receipts users list`` works with no blob store
    configured at all.
    """
    if settings.storage_backend == "local":
        return LocalStorage(Path(settings.storage_root))
    if not settings.s3_bucket:
        raise ValueError(
            f"STORAGE_BACKEND={settings.storage_backend!r} requires S3_BUCKET to be set"
        )
    return S3Storage(settings.s3_bucket)


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
    """
    files = _collect_files(Path(args.path), recursive=args.recursive)

    jobs = []
    rejected = 0
    for file in files:
        try:
            job = ingest_file(file, storage, source=args.source, max_mb=settings.max_upload_mb)
        except ValueError as exc:
            print(f"REJECTED  {file.name}: {exc}")
            rejected += 1
            continue
        jobs.append(job)
        print(f"{job.id}  {file.name}")

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
    unknown one, an unknown role) becomes a printed message and
    :data:`EXIT_FAILED` rather than a traceback.
    """
    if args.users_command == "add":
        password = _read_password()
        with session_factory() as session:
            try:
                create_user(session, args.username, password, args.role)
                session.commit()
            except ValueError as exc:
                print(f"error: {exc}")
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
                print(f"error: {exc}")
                return EXIT_FAILED
        print(f"deactivated {args.username}")
        return EXIT_OK

    if args.users_command == "set-role":
        with session_factory() as session:
            try:
                set_role(session, args.username, args.role)
                session.commit()
            except ValueError as exc:
                print(f"error: {exc}")
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
    call's client from ``client_factory`` (defaulting to
    ``lambda: make_client(settings)``) exactly the way
    :func:`~receipts.pipeline.process_batch` builds one client per job.

    Every job's call is wrapped in its own ``try/except`` rather than left to
    raise. ``process_receipt`` only ever raises for the one case it cannot
    itself turn into a terminal row -- nothing at all could be written -- and
    ``client_factory()`` can raise too (a provider outage building the
    client); either way, letting that escape the callable handed to
    ``ThreadPoolExecutor.map`` does not just lose *that* receipt's result --
    CPython's ``Executor.map`` cancels every future still queued behind it,
    so one bad receipt used to silently abandon the rest of the batch,
    including receipts that had not even started, and the exception then
    escaped ``cmd_process`` entirely instead of becoming the documented
    :data:`EXIT_FAILED`. Catching it here means every job is always
    attempted and always reported -- as a normal per-receipt line, or as a
    ``failed`` one -- and a receipt landing in review still never flips the
    exit code (ADR-0013): this returns :data:`EXIT_FAILED` only when at
    least one receipt could not be run at all, never because of where a
    receipt that *did* run ended up.
    """
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
        for job in jobs:
            enqueue_receipt(job, queue)
            print(f"{job.id}  queued")
        print(f"queued {len(jobs)}")
        return EXIT_OK

    client_factory = (
        client_factory if client_factory is not None else (lambda: make_client(settings))
    )

    def run(job: ReceiptJob) -> tuple[ReceiptJob, ProcessResult | None, Exception | None]:
        try:
            result = process_receipt(
                job, client=client_factory(), storage=storage,
                session_factory=session_factory, settings=settings,
            )
        except Exception as exc:  # the one thing process_receipt/client_factory can raise
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
            print(f"{job.id}  failed  {exc}")
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
    """
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

    client_factory = (
        client_factory if client_factory is not None else (lambda: make_client(settings))
    )
    result = process_receipt(
        job, client=client_factory(), storage=storage,
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
    """
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

    out_path = Path(args.out)
    export_workbook(extractions, out_path, rows=export_rows)
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


def cmd_eval(
    args: argparse.Namespace, *, settings: Settings, client: VLMClient | None = None,
) -> int:
    """Run the golden-set baseline and print the spec section 16 report.

    A thin wrapper over :func:`eval.run_baseline.run_baseline`: this command
    owns no scoring logic of its own, only argument plumbing, so "what counts
    as correct" never has two definitions to keep in sync. ``client`` exists
    for tests to inject; production always leaves it ``None`` and lets
    ``run_baseline`` build one from ``settings`` itself (refusing the
    response-less ``fake`` provider before any work happens).

    A refused provider (:class:`RuntimeError`) or a missing golden-set image
    (:class:`FileNotFoundError`) is printed to stderr and turned into
    :data:`EXIT_FAILED` rather than a traceback. ``run_baseline`` is called
    with every argument as a keyword, and referenced by its bare module-level
    name (imported at module top, not through ``eval.run_baseline.``) so a
    test can replace it with ``monkeypatch.setattr(cli_module, "run_baseline",
    ...)`` and this function picks up the replacement without change.
    """
    golden_dir = Path(args.golden_dir) if args.golden_dir is not None else None
    results_dir = Path(args.results_dir) if args.results_dir is not None else None

    try:
        report = run_baseline(
            golden_dir=golden_dir,
            client=client,
            results_dir=results_dir,
            default_currency=settings.default_currency,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(format_report(report))
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace, *, results_dir: Path | None = None) -> int:
    """Recommend an auto-approve threshold from a `receipts eval` results file.

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

    Otherwise rebuilds :class:`~eval.metrics.EvalResult` objects from the
    JSON's ``results`` list (``field_acc={}`` -- the dataclass has no default
    for it, and :func:`~eval.metrics.calibration_curve` reads only
    ``confidence``/``critical_correct``, never ``field_acc``), prints the full
    threshold/rate/precision curve, and recommends the lowest threshold whose
    precision reaches ``--target`` **and whose auto-approve rate is greater
    than zero**.

    The rate check is the entire reason this function exists rather than a
    one-line scan. ``calibration_curve`` defines precision as ``1.0`` when
    nothing is approved (``eval/metrics.py:255-257``), and its threshold
    sweep always includes ``1.0``, above every observed confidence -- so a
    result set that is critical-incorrect end to end still produces a curve
    row ``(1.0, rate=0.0, precision=1.0)``. A scan that only checks precision
    would recommend that: a threshold that auto-approves nothing, reported as
    perfect. That is the same vacuous zero-receipt precision this project has
    already committed once as an artifact, hiding one level deeper -- inside
    a result set that does have receipts. If no threshold clears the target
    with a nonzero rate, this says so plainly and returns
    :data:`EXIT_FAILED` without recommending anything.

    Always closes with a standing caveat, regardless of whether a
    recommendation was found: a threshold is only as trustworthy as the
    golden set it was measured on, and there are still no measured accuracy
    numbers for this system (``docs/KNOWN_ISSUES.md`` ISSUE-001) -- a
    handful of golden receipts cannot support a confident >=99% claim.
    """
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

    data = json.loads(results_path.read_text(encoding="utf-8"))
    results_json = data.get("results", [])
    if not results_json:
        print(
            "error: this results file has zero receipts; no auto-approval "
            "threshold can be chosen from an empty result set",
            file=sys.stderr,
        )
        return EXIT_FAILED

    results = [
        EvalResult(
            receipt_id=r["receipt_id"],
            confidence=Decimal(r["confidence"]),
            critical_correct=r["critical_correct"],
            field_acc={},
        )
        for r in results_json
    ]
    curve = calibration_curve(results)
    target = args.target

    print(f"Calibration curve -- {len(results)} receipt(s), target precision {target}")
    print(f"  {'threshold':>10}  {'auto-approve rate':>18}  {'precision':>10}")
    for threshold, rate, precision in curve:
        print(f"  {str(threshold):>10}  {rate * 100:>17.2f}%  {precision * 100:>9.2f}%")

    # Ignore any threshold whose auto-approve rate is zero: calibration_curve
    # reports precision 1.0 there (nothing approved reads as vacuously
    # "perfect"), and its sweep always includes threshold 1.0. Recommending
    # that would repeat the zero-receipt precision trap one level deeper --
    # see the docstring.
    recommended = next(
        (
            threshold for threshold, rate, precision in curve
            if rate > 0.0 and precision >= float(target)
        ),
        None,
    )

    print()
    if recommended is None:
        print(
            f"no threshold reaches {float(target) * 100:.2f}% precision with a "
            "nonzero auto-approve rate; recommending none"
        )
        code = EXIT_FAILED
    else:
        print(f"recommended threshold: {recommended}")
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
            return cmd_process(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings, queue_factory=make_queue,
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
