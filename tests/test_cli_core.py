"""The ``receipts`` CLI skeleton: the parser, ``ingest``, and ``users`` (P4.T6).

Everything here is offline: a file-backed SQLite database and a temp-directory
:class:`LocalStorage`. No provider, no Redis, no network -- matching
``tests/test_process_receipt.py``'s fixture pattern.

The load-bearing behaviours pinned down below (ADR-0013):

  * ``ingest`` writes a ``pending`` row and stops -- it does not enqueue, so
    ``receipts process`` (a later task) is the one place that drains the work
    list, whether the row arrived from here or from ``POST /upload``.
  * A rejected file is reported by name and reason, never silently dropped, and
    it does not abort the files in the same batch that are fine (§18).
  * A directory is not walked recursively unless ``--recursive`` is given.
  * ``users add`` reads the password from stdin -- never ``argv``, which lands
    in shell history and in ``ps`` -- and never echoes it. A piped/redirected
    stdin is read directly; an interactive terminal falls back to ``getpass``.
  * Exit codes follow ADR-0013: ``0`` completed, ``1`` could not, ``2`` is
    argparse's own usage error.
  * ``main()`` never creates the schema itself (Alembic owns that); a command
    run against an un-migrated database fails cleanly, naming the fix.
"""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import select

from config.settings import Settings
from receipts.cli import EXIT_FAILED, EXIT_OK, build_parser, cmd_ingest, cmd_users, main
from receipts.ingest.storage import LocalStorage
from receipts.persist.models import Base, Receipt
from receipts.persist.session import make_engine, make_session_factory
from receipts.persist.users import get_user, verify_password
from receipts.score.confidence import ReceiptStatus

#: Minimal but genuinely JPEG-sniffable bytes (see
#: ``receipts.ingest.ingest._sniff_content_type``): the ``\xff\xd8`` header is
#: all the validator inspects.
JPEG_BYTES = b"\xff\xd8" + b"\x00" * 1024


@pytest.fixture()
def session_factory(tmp_path):
    """A file-backed SQLite database, so several sessions share it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


@pytest.fixture()
def tty_stdin(monkeypatch):
    """Make ``sys.stdin`` report as a real terminal.

    Pytest's own captured ``sys.stdin`` (``_pytest.capture.DontReadFromInput``)
    always reports ``isatty() is False`` and raises ``OSError`` on
    ``readline()`` -- which is exactly what a piped stdin looks like to
    :func:`receipts.cli._read_password`. Tests below that mean to exercise the
    *interactive* path (a password typed at a real prompt, via ``getpass``,
    mocked so nothing actually blocks) request this fixture so that branch --
    rather than the piped one -- is the one that runs.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #


def test_ingest_writes_a_pending_row_and_prints_the_id(tmp_path, session_factory, storage, capsys):
    image = tmp_path / "r001.jpg"
    image.write_bytes(JPEG_BYTES)
    args = build_parser().parse_args(["ingest", str(image)])

    code = cmd_ingest(args, session_factory=session_factory, storage=storage,
                       settings=Settings(_env_file=None))

    assert code == EXIT_OK
    with session_factory() as session:
        row = session.scalars(select(Receipt)).one()
    assert row.status is ReceiptStatus.PENDING
    # The hash is the worker's job; an empty one is what dedupe skips.
    assert row.image_phash == ""
    assert str(row.id) in capsys.readouterr().out


def test_ingest_reports_a_rejected_file_and_keeps_going(tmp_path, session_factory, storage, capsys):
    good = tmp_path / "ok.jpg"
    good.write_bytes(JPEG_BYTES)
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"hello")
    args = build_parser().parse_args(["ingest", str(tmp_path)])

    code = cmd_ingest(args, session_factory=session_factory, storage=storage,
                       settings=Settings(_env_file=None))

    out = capsys.readouterr().out
    # A rejected file is reported, never silently skipped -- and it does not
    # abort the receipts that are fine.
    assert "notes.txt" in out
    assert code == EXIT_FAILED          # something in the batch did not land
    with session_factory() as session:
        assert session.scalars(select(Receipt)).all().__len__() == 1


def test_ingest_of_a_directory_is_not_recursive_by_default(tmp_path, session_factory, storage):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.jpg").write_bytes(JPEG_BYTES)
    args = build_parser().parse_args(["ingest", str(tmp_path)])

    cmd_ingest(args, session_factory=session_factory, storage=storage,
               settings=Settings(_env_file=None))

    with session_factory() as session:
        assert session.scalars(select(Receipt)).all() == []


def test_ingest_recursive_finds_files_in_subdirectories(tmp_path, session_factory, storage):
    # A dedicated root, separate from tmp_path itself: session_factory's
    # sqlite file already lives directly under tmp_path, and --recursive
    # would otherwise sweep it up as just another file to reject.
    root = tmp_path / "receipts_dir"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "deep.jpg").write_bytes(JPEG_BYTES)
    args = build_parser().parse_args(["ingest", str(root), "--recursive"])

    code = cmd_ingest(args, session_factory=session_factory, storage=storage,
                       settings=Settings(_env_file=None))

    assert code == EXIT_OK
    with session_factory() as session:
        assert len(session.scalars(select(Receipt)).all()) == 1


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #


def test_users_add_creates_an_account_with_the_password_from_stdin(
    session_factory, monkeypatch, capsys, tty_stdin
):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw-alice")
    args = build_parser().parse_args(["users", "add", "alice", "--role", "admin"])

    code = cmd_users(args, session_factory=session_factory)

    assert code == EXIT_OK
    with session_factory() as session:
        user = get_user(session, "alice")
    assert user is not None and user.role == "admin"
    # The password must never appear in argv, and must not be echoed back.
    assert "pw-alice" not in capsys.readouterr().out


def test_users_add_reads_a_piped_password_without_touching_getpass(session_factory, monkeypatch):
    """A non-interactive stdin (a pipe, or a CI secret fed in) supplies the
    password directly -- this is the path that keeps `receipts users add`
    usable unattended, including on Windows, where `getpass.getpass` itself
    cannot be relied on to read a pipe (see `_read_password`'s docstring).
    """

    class _PipedStdin:
        def isatty(self) -> bool:
            return False

        def readline(self) -> str:
            return "pw-piped\n"

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("getpass.getpass must not be called for a piped stdin")

    monkeypatch.setattr("getpass.getpass", _must_not_be_called)
    monkeypatch.setattr(sys, "stdin", _PipedStdin())
    args = build_parser().parse_args(["users", "add", "alice"])

    code = cmd_users(args, session_factory=session_factory)

    assert code == EXIT_OK
    with session_factory() as session:
        user = get_user(session, "alice")
    assert user is not None
    # The trailing newline `readline()` returns must not become part of the
    # password, and the piped line must actually be what got stored.
    assert verify_password("pw-piped", user.password_hash)


def test_users_add_rejects_a_duplicate_username(session_factory, monkeypatch, tty_stdin):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    args = build_parser().parse_args(["users", "add", "alice"])
    cmd_users(args, session_factory=session_factory)

    assert cmd_users(args, session_factory=session_factory) == EXIT_FAILED


def test_users_list_prints_every_account(session_factory, monkeypatch, capsys, tty_stdin):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    cmd_users(build_parser().parse_args(["users", "add", "alice"]), session_factory=session_factory)

    code = cmd_users(build_parser().parse_args(["users", "list"]), session_factory=session_factory)

    assert code == EXIT_OK
    assert "alice" in capsys.readouterr().out


def test_users_deactivate_an_unknown_user_fails_cleanly(session_factory):
    args = build_parser().parse_args(["users", "deactivate", "ghost"])

    assert cmd_users(args, session_factory=session_factory) == EXIT_FAILED


def test_users_set_role_changes_an_existing_account(session_factory, monkeypatch, tty_stdin):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    cmd_users(build_parser().parse_args(["users", "add", "alice"]), session_factory=session_factory)

    code = cmd_users(build_parser().parse_args(["users", "set-role", "alice", "admin"]),
                      session_factory=session_factory)

    assert code == EXIT_OK
    with session_factory() as session:
        assert get_user(session, "alice").role == "admin"


# --------------------------------------------------------------------------- #
# The parser and main()
# --------------------------------------------------------------------------- #


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["nonsense"])
    assert exc.value.code == 2


def test_main_returns_an_exit_code_rather_than_exiting(tmp_path, monkeypatch):
    # main() must be callable from a test; the console-script wrapper owns SystemExit.
    # main() itself never creates the schema (Alembic owns that -- see
    # test_main_against_an_unmigrated_database_... below), so the fixture
    # creates it here, exactly as every other test file's session_factory
    # fixture does.
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    Base.metadata.create_all(make_engine(db_url))

    assert main(["users", "list"]) == EXIT_OK


def test_main_against_an_unmigrated_database_fails_cleanly_naming_the_fix(
    tmp_path, monkeypatch, capsys
):
    """The database exists (SQLite creates the file on connect) but nobody
    has run `alembic upgrade head` against it -- exactly what a freshly
    pointed `DATABASE_URL` looks like on day one. `main()` must not paper
    over that with `Base.metadata.create_all` (see its docstring: that would
    create the tables without stamping `alembic_version`, so a later real
    migration fails with "table already exists"). It must fail cleanly
    instead, naming the actual fix.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'unmigrated.db'}")

    code = main(["users", "list"])

    assert code == EXIT_FAILED
    assert "alembic upgrade head" in capsys.readouterr().err
