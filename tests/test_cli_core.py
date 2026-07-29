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
  * ``users add`` reads the password from stdin via ``getpass`` -- never
    ``argv``, which lands in shell history and in ``ps`` -- and never echoes it.
  * Exit codes follow ADR-0013: ``0`` completed, ``1`` could not, ``2`` is
    argparse's own usage error.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from config.settings import Settings
from receipts.cli import EXIT_FAILED, EXIT_OK, build_parser, cmd_ingest, cmd_users, main
from receipts.ingest.storage import LocalStorage
from receipts.persist.models import Base, Receipt
from receipts.persist.session import make_engine, make_session_factory
from receipts.persist.users import get_user
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
    session_factory, monkeypatch, capsys
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


def test_users_add_rejects_a_duplicate_username(session_factory, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    args = build_parser().parse_args(["users", "add", "alice"])
    cmd_users(args, session_factory=session_factory)

    assert cmd_users(args, session_factory=session_factory) == EXIT_FAILED


def test_users_list_prints_every_account(session_factory, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    cmd_users(build_parser().parse_args(["users", "add", "alice"]), session_factory=session_factory)

    code = cmd_users(build_parser().parse_args(["users", "list"]), session_factory=session_factory)

    assert code == EXIT_OK
    assert "alice" in capsys.readouterr().out


def test_users_deactivate_an_unknown_user_fails_cleanly(session_factory):
    args = build_parser().parse_args(["users", "deactivate", "ghost"])

    assert cmd_users(args, session_factory=session_factory) == EXIT_FAILED


def test_users_set_role_changes_an_existing_account(session_factory, monkeypatch):
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    assert main(["users", "list"]) == EXIT_OK
