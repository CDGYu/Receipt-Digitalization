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
    script or from CI. ``users add`` reads the password with ``getpass`` rather
    than a flag: ``getpass`` reads stdin directly and falls back to it silently
    when stdin is not a tty, so ``echo "$PW" | receipts users add alice`` works
    unattended without ever putting the password in ``argv`` -- where it would
    land in shell history and in ``ps``.
  * **``ingest`` does not enqueue.** It validates a file, stores its bytes, and
    writes a ``pending`` receipt row -- the same row shape ``POST /upload``
    writes. ``receipts process`` (a later task) is the one place that drains
    pending rows, so an upload through either entry point is picked up by
    exactly the same query. See ``docs/adr/0013-cli-contract.md``.

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
from pathlib import Path

from config.settings import Settings, get_settings

from .ingest.ingest import ingest_file
from .ingest.storage import LocalStorage, S3Storage, StorageBackend
from .persist.models import Base
from .persist.repository import create_pending_receipt
from .persist.session import make_engine, make_session_factory
from .persist.users import ROLE_REVIEWER, ROLES, create_user, deactivate, list_users, set_role

__all__ = [
    "EXIT_FAILED",
    "EXIT_OK",
    "build_parser",
    "cmd_ingest",
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
            "Create an account. The password is read from stdin via getpass, "
            "never from a flag: it would otherwise land in shell history and "
            "in `ps`. getpass falls back to reading stdin directly when it is "
            "not a tty, so this still runs unattended from a script or CI -- "
            "e.g. `echo \"$PW\" | receipts users add alice` -- there is no "
            "--password flag and none will be added."
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipts", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_ingest(sub)
    _add_users(sub)
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


def cmd_users(args: argparse.Namespace, *, session_factory) -> int:
    """Dispatch ``users add|list|deactivate|set-role``. The caller commits.

    Every ``ValueError`` the user store raises (a duplicate username, an
    unknown one, an unknown role) becomes a printed message and
    :data:`EXIT_FAILED` rather than a traceback.
    """
    if args.users_command == "add":
        password = getpass.getpass("password: ")
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


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run the command, returning its exit code.

    Returns rather than raising ``SystemExit`` so a test can assert on the
    code; :func:`_console_main` below is what actually exits.

    Builds the real session factory and, only inside the branch that needs it,
    the real storage backend -- so ``receipts users list`` runs on a machine
    with no blob store configured. ``Base.metadata.create_all`` is idempotent
    (it only creates tables that do not already exist) and is called once here
    so a freshly pointed ``DATABASE_URL`` works immediately; it never touches a
    database that migrations have already brought up to date.
    """
    args = build_parser().parse_args(argv)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    if args.command == "ingest":
        return cmd_ingest(
            args, session_factory=session_factory, storage=_make_storage(settings),
            settings=settings,
        )
    if args.command == "users":
        return cmd_users(args, session_factory=session_factory)
    # unreachable: subparsers are required
    raise AssertionError(f"unhandled command {args.command!r}")


def _console_main() -> None:  # pragma: no cover - entry point wrapper
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover - `python -m receipts.cli`
    _console_main()
