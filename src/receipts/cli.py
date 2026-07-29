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
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.exc import DBAPIError

from config.settings import Settings, get_settings

from .extract.clients.base import VLMClient
from .extract.clients.factory import make_client
from .ingest.ingest import ReceiptJob, ingest_file
from .ingest.storage import LocalStorage, S3Storage, StorageBackend
from .persist.models import Receipt
from .persist.repository import create_pending_receipt, get_receipt, query_receipts
from .persist.session import make_engine, make_session_factory
from .persist.users import ROLE_REVIEWER, ROLES, create_user, deactivate, list_users, set_role
from .pipeline import BatchResult, process_receipt
from .score.confidence import ReceiptStatus
from .worker import enqueue_receipt, make_queue

__all__ = [
    "EXIT_FAILED",
    "EXIT_OK",
    "build_parser",
    "cmd_ingest",
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
        "--limit", type=int, default=None,
        help="take at most this many pending receipts this run (default: no cap)",
    )
    parser.add_argument(
        "--inline", action="store_true",
        help="run the pipeline in this process instead of enqueueing to RQ",
    )
    parser.add_argument(
        "--workers", type=int, default=4,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipts", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_ingest(sub)
    _add_users(sub)
    _add_process(sub)
    _add_reprocess(sub)
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
    columns rather than infer them (ADR-0013).
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
    /upload`` -- taken oldest first and capped by ``--limit``. With nothing
    pending this prints a message and returns :data:`EXIT_OK`: an empty work
    list is not a failure.

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
    :func:`~receipts.pipeline.process_batch` builds one client per job. A
    receipt that lands in review is the system working as designed: this
    returns :data:`EXIT_OK` regardless of where any individual receipt ended
    up, and fails only if the command itself could not run.
    """
    with session_factory() as session:
        if args.limit is None:
            pending = query_receipts(session, status=ReceiptStatus.PENDING)
        else:
            pending = query_receipts(session, status=ReceiptStatus.PENDING, limit=args.limit)
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

    def run(job: ReceiptJob):
        return process_receipt(
            job, client=client_factory(), storage=storage,
            session_factory=session_factory, settings=settings,
        )

    if args.workers <= 1 or len(jobs) <= 1:
        results = [run(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run, jobs))

    for result in results:
        print(f"{result.receipt_id}  {result.status.value}  {result.reason}")

    batch = BatchResult(processed=results)
    for status, count in batch.counts.items():
        print(f"{status.value}: {count}")
    print(f"total cost: {batch.total_cost_usd}")
    return EXIT_OK


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
    rather than raising and reports the refusal through its return value --
    ``result.status is ReceiptStatus.REVIEWED`` with ``result.failed_stage ==
    "persist"`` (:func:`~receipts.persist.repository.save_extraction`,
    ADR-0012). This function only reports that outcome; duplicating the
    refusal here would let the two drift, and calling
    :func:`~receipts.review.queue.enqueue_review` again would overwrite the
    reason the pipeline already wrote with a vaguer one.

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

    if result.status is ReceiptStatus.REVIEWED and result.failed_stage == "persist":
        print(
            f"{result.receipt_id}  reviewed (unchanged): a human has already "
            "reviewed this receipt, so the run was not applied to the stored "
            f"row; a review task is open with what this run produced -- "
            f"{result.reason}"
        )
        return EXIT_OK

    print(f"{result.receipt_id}  {result.status.value}  confidence={result.confidence}")
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
            return cmd_process(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings, queue_factory=make_queue,
            )
        if args.command == "reprocess":
            return cmd_reprocess(
                args, session_factory=session_factory, storage=_make_storage(settings),
                settings=settings,
            )
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
