"""``receipts export``, ``receipts merchants``, ``receipts eval`` and
``receipts calibrate`` (P4.T4/T5, spec 14.10 / §13 / §16 / §18).

Everything here is offline: a file-backed SQLite database and no storage
backend at all -- export reads only ORM rows, never a blob, through Task 1's
``query_export_receipts``/``build_export_rows``. No provider, no Redis, no
network. ``eval``'s tests inject a ``run_baseline_fn`` double rather than
touch the pipeline or monkeypatch a module global, and ``calibrate`` only
ever reads a hand-written results JSON -- neither needs a database or a
provider either.

The load-bearing behaviours pinned down below:

  * ``export`` writes the same four §13 sheets (``Receipts``, ``LineItems``,
    ``Needs Review``, ``Summary``) that ``GET /export/xlsx`` writes, because
    both call the identical ``query_export_receipts``/``build_export_rows``
    pair -- a CLI export and an API export of the same filters can never
    disagree about which receipts qualify.
  * ``pending``/``rejected`` receipts are excluded by default -- a pending row
    is an upload in flight, not a transaction -- unless ``--status`` names one
    of them explicitly.
  * Past ``_EXPORT_MAX_ROWS`` matching receipts, ``export`` refuses and writes
    nothing, rather than silently truncating what would read as a complete
    ledger.
  * ``export`` needs no ``SESSION_SECRET``: with none configured, the image
    column is simply empty rather than an unsigned or fabricated link.
  * ``merchants hints --add`` rebinds ``Merchant.hints`` rather than mutating
    it in place. The column is a plain ``sa.JSON()`` with no ``MutableList``
    registered, so an in-place ``.append()`` would silently never reach the
    database -- and the identity map would still hand the mutated object back
    within the *same* session, so a same-session assertion would pass while
    the database held nothing. Every hints test below re-reads through a new
    ``session_factory()`` block for exactly that reason; that shape is
    deliberate and must not be "simplified" away.
  * §18: a merchant hint always ends by deferring to the image -- ``--add``
    appends "; trust the image" when the supplied text does not already end
    with it (case-insensitively), and says on stdout that it did.
  * ``calibrate`` refuses outright on a zero-receipt result set, printing no
    precision figure at all -- this project has already committed a results
    artifact reporting ``auto_approval_precision: 1.0`` on zero receipts
    once, and the command whose job is choosing an auto-approval threshold
    is the worst place to repeat it.
  * ``calibrate``'s recommendation ignores any threshold whose auto-approve
    rate is zero, even though ``calibration_curve`` reports that threshold's
    precision as a vacuous ``1.0`` (``eval/metrics.py:255-257``) -- the same
    trap one level deeper. A threshold that approves nothing is not a
    calibrated system, however perfect its precision reads.
  * ``eval``/``calibrate`` import ``eval.*`` lazily, inside ``cmd_eval``/
    ``cmd_calibrate``, never at module top -- a module-top import broke
    every ``receipts`` command (not only these two) the instant the CLI was
    actually installed somewhere ``eval/`` was not, since ``eval/`` is
    deliberately excluded from the distribution (``pyproject.toml``).
    ``pytest``'s own ``pythonpath = ["src", "."]`` masks this in-process --
    an in-process assertion cannot pin it -- so
    ``test_cli_imports_without_the_eval_package`` below runs in a
    subprocess with a ``sys.meta_path`` finder that blocks ``eval``/
    ``eval.*`` before ``import receipts.cli``, the same technique
    ``tests/test_import_isolation.py`` uses for the FastAPI check.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from decimal import Decimal as D
from pathlib import Path

import pytest
from openpyxl import load_workbook

from config.settings import Settings
from eval.metrics import EvalReport
from receipts import cli as cli_module
from receipts.cli import (
    EXIT_FAILED,
    EXIT_OK,
    build_parser,
    cmd_calibrate,
    cmd_eval,
    cmd_export,
    cmd_merchants,
)
from receipts.extract.schema import LineItem as ExtractLineItem
from receipts.extract.schema import Merchant as ExtractMerchant
from receipts.extract.schema import ReceiptExtraction, ReceiptMeta, Totals
from receipts.ingest.ingest import ReceiptJob
from receipts.persist.models import Base, Merchant
from receipts.persist.repository import save_extraction
from receipts.persist.session import make_engine, make_session_factory
from receipts.score.confidence import ReceiptStatus
from receipts.validate.report import ValidationReport

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def session_factory(tmp_path):
    """A file-backed SQLite database, so several sessions share it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def settings() -> Settings:
    """A session secret set, so most tests below exercise the signed
    image-URL path in ``build_export_rows`` (the normal, configured case).
    ``test_export_without_a_session_secret_still_writes_a_workbook`` builds
    its own ``Settings`` with ``session_secret=None`` to prove the CLI needs
    no session at all.
    """
    return Settings(_env_file=None, session_secret="test-secret")


# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #


def _receipt(session_factory, *, status: ReceiptStatus, total: D = D("224.00")) -> uuid.UUID:
    """One persisted receipt in the given terminal status."""
    job = ReceiptJob(
        id=uuid.uuid4(), image_key=f"receipts/2026/07/{uuid.uuid4()}/original.jpg",
        source="test", original_filename="r.jpg", content_type="image/jpeg",
    )
    extraction = ReceiptExtraction(
        merchant=ExtractMerchant(name="METRO OIL SUBIC, INC."),
        receipt=ReceiptMeta(date="2026-03-23", currency="PHP"),
        totals=Totals(total=total),
        line_items=[ExtractLineItem(position=1, description_raw="CLEAN DIESEL",
                                    line_total=total)],
    )
    with session_factory() as session:
        save_extraction(session, job, extraction, ValidationReport(), D("0.95"),
                        status, image_phash="a1b2c3d4a1b2c3d4")
        session.commit()
    return job.id


def _auto_approved_receipt(session_factory) -> uuid.UUID:
    return _receipt(session_factory, status=ReceiptStatus.AUTO_APPROVED)


def _pending_receipt_row(session_factory) -> uuid.UUID:
    return _receipt(session_factory, status=ReceiptStatus.PENDING)


def _merchant(session_factory, *, canonical_name: str, tax_id: str | None = None) -> uuid.UUID:
    """One merchants row. ``name_variants``/``hints`` default to [] via the ORM."""
    merchant = Merchant(id=uuid.uuid4(), canonical_name=canonical_name, tax_id=tax_id)
    with session_factory() as session:
        session.add(merchant)
        session.commit()
        return merchant.id


def _receipt_ids_in(path: Path) -> set[str]:
    """The `receipt_id` column of the Receipts sheet -- it is the first column."""
    sheet = load_workbook(path)["Receipts"]
    return {str(row[0].value) for row in sheet.iter_rows(min_row=2) if row[0].value}


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #


def test_export_writes_a_workbook_with_all_four_sheets(tmp_path, session_factory, settings):
    _auto_approved_receipt(session_factory)
    out = tmp_path / "book.xlsx"
    args = build_parser().parse_args(["export", "--out", str(out)])

    code = cmd_export(args, session_factory=session_factory, settings=settings)

    assert code == EXIT_OK
    assert load_workbook(out).sheetnames == ["Receipts", "LineItems", "Needs Review", "Summary"]


def test_export_excludes_pending_and_rejected_unless_asked(tmp_path, session_factory, settings):
    pending_id = _pending_receipt_row(session_factory)
    _auto_approved_receipt(session_factory)

    cmd_export(build_parser().parse_args(["export", "--out", str(tmp_path / "a.xlsx")]),
               session_factory=session_factory, settings=settings)
    default_ids = _receipt_ids_in(tmp_path / "a.xlsx")

    cmd_export(build_parser().parse_args(
        ["export", "--out", str(tmp_path / "b.xlsx"), "--status", "pending"]),
        session_factory=session_factory, settings=settings)
    asked_ids = _receipt_ids_in(tmp_path / "b.xlsx")

    # A pending row is an upload in flight, not a transaction.
    assert str(pending_id) not in default_ids
    assert str(pending_id) in asked_ids


def test_export_refuses_rather_than_truncating(
    tmp_path, session_factory, settings, monkeypatch, capsys
):
    for _ in range(2):
        _auto_approved_receipt(session_factory)
    monkeypatch.setattr(cli_module, "_EXPORT_MAX_ROWS", 1)
    out = tmp_path / "book.xlsx"

    code = cmd_export(build_parser().parse_args(["export", "--out", str(out)]),
                      session_factory=session_factory, settings=settings)

    # A silently shortened export reads as a complete ledger.
    assert code == EXIT_FAILED
    assert "narrow" in capsys.readouterr().err.lower()
    assert not out.exists()


def test_export_without_a_session_secret_still_writes_a_workbook(tmp_path, session_factory):
    _auto_approved_receipt(session_factory)
    out = tmp_path / "book.xlsx"

    code = cmd_export(build_parser().parse_args(["export", "--out", str(out)]),
                      session_factory=session_factory,
                      settings=Settings(_env_file=None, session_secret=None))

    # The CLI needs no session; the image column is simply empty.
    assert code == EXIT_OK and out.exists()


# --------------------------------------------------------------------------- #
# merchants
# --------------------------------------------------------------------------- #


def test_merchants_list_prints_each_merchant(session_factory, capsys):
    _merchant(session_factory, canonical_name="METRO OIL SUBIC, INC.", tax_id="221 193 789 09013")
    code = cmd_merchants(build_parser().parse_args(["merchants", "list"]),
                         session_factory=session_factory)
    assert code == EXIT_OK
    assert "METRO OIL SUBIC, INC." in capsys.readouterr().out


def test_merchants_hints_add_appends_trust_the_image(session_factory):
    merchant_id = _merchant(session_factory, canonical_name="SUMMIT FUEL OPC")
    args = build_parser().parse_args(
        ["merchants", "hints", str(merchant_id), "--add", "The TIN is in the header"])

    cmd_merchants(args, session_factory=session_factory)

    with session_factory() as session:
        hints = session.get(Merchant, merchant_id).hints
    # §18: a merchant hint always ends by deferring to the image.
    assert hints[0].endswith("trust the image")


def test_merchants_hints_does_not_double_append(session_factory):
    merchant_id = _merchant(session_factory, canonical_name="SERV CENTRAL, INC.")
    args = build_parser().parse_args(
        ["merchants", "hints", str(merchant_id), "--add", "Read the header; trust the image"])

    cmd_merchants(args, session_factory=session_factory)

    with session_factory() as session:
        assert session.get(Merchant, merchant_id).hints[0].count("trust the image") == 1


def test_merchants_hints_for_an_unknown_id_is_exit_one(session_factory):
    args = build_parser().parse_args(["merchants", "hints", str(uuid.uuid4())])
    assert cmd_merchants(args, session_factory=session_factory) == EXIT_FAILED


# --------------------------------------------------------------------------- #
# eval / calibrate test helpers
# --------------------------------------------------------------------------- #


def _write_results(results_dir: Path, *, receipts: int, results: list[dict]) -> Path:
    """A results file in the exact shape `eval/harness.py::_report_to_dict` writes."""
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "2026-07-29-1.0.0.json"
    path.write_text(json.dumps({
        "prompt_version": "1.0.0",
        "auto_approve_threshold": "0.85",
        "counts": {"receipts": receipts, "auto_approved": 0,
                   "critical_correct": 0, "failed": 0},
        "metrics": {"auto_approval_precision": 0.0, "auto_approval_rate": 0.0,
                    "critical_field_accuracy": 0.0, "field_accuracy": 0.0,
                    "line_item_precision": 0.0, "line_item_recall": 0.0,
                    "line_item_f1": 0.0, "cost_per_receipt": None,
                    "p50_latency_s": None, "p95_latency_s": None},
        "failures": [],
        "calibration": [],
        "results": results,
    }, indent=2), encoding="utf-8")
    return path


def _stub_report() -> EvalReport:
    """Just enough EvalReport for `format_report` to render the table."""
    return EvalReport(
        n_receipts=3, n_auto_approved=2, n_critical_correct=2,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0, auto_approval_rate=0.667,
        critical_field_accuracy=0.667, field_accuracy=0.85,
        line_item_precision=0.9, line_item_recall=0.9, line_item_f1=0.9,
    )


# --------------------------------------------------------------------------- #
# eval
# --------------------------------------------------------------------------- #


def test_eval_prints_the_six_metric_table(capsys):
    report = _stub_report()
    code = cmd_eval(
        build_parser().parse_args(["eval"]),
        settings=Settings(_env_file=None),
        run_baseline_fn=lambda **kw: report,
    )

    assert code == EXIT_OK
    out = capsys.readouterr().out
    # These are `format_report`'s real labels, verified against
    # eval/run_baseline.py -- it prints prose headings, NOT the snake_case
    # metric names. Assert on what the function actually emits.
    for label in ("Auto-approval precision:", "Critical-field accuracy:",
                  "Line-item F1:", "Cost per receipt:"):
        assert label in out


def test_eval_reports_a_refused_provider_as_exit_one(capsys):
    def refuse(**kwargs):
        raise RuntimeError("the fake provider carries no scripted responses")

    code = cmd_eval(
        build_parser().parse_args(["eval"]),
        settings=Settings(_env_file=None),
        run_baseline_fn=refuse,
    )

    assert code == EXIT_FAILED
    assert "scripted responses" in capsys.readouterr().err


def test_cli_imports_without_the_eval_package():
    """`receipts.cli` (and, transitively, every `receipts` command) must not
    require the `eval` package to import. `eval/` is deliberately excluded
    from the installed distribution (pyproject.toml: dev/research tooling,
    not part of the installed CLI), and a module-top `from eval... import`
    in cli.py breaks every command the instant that is actually true --
    reproduced against the real installed `receipts` console script from
    outside this repository before this test was written.

    Run in a subprocess with a `sys.meta_path` finder that raises
    `ModuleNotFoundError` for `eval`/`eval.*`, installed before
    `import receipts.cli` -- deterministic and platform-independent, unlike
    relying on cwd/pythonpath tricks. An in-process assertion cannot pin
    this: pytest's own `pythonpath = ["src", "."]` puts the repo root on
    `sys.path`, which is exactly what let the module-top import through
    unnoticed the first time. Same technique as
    `tests/test_import_isolation.py`'s FastAPI check, adapted to block an
    import outright rather than inspect `sys.modules` after the fact.
    """
    code = (
        "import sys\n"
        "class _BlockEval:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'eval' or name.startswith('eval.'):\n"
        "            raise ModuleNotFoundError(f'No module named {name!r}', name=name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _BlockEval())\n"
        "import receipts.cli\n"
        "receipts.cli.build_parser()\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# --------------------------------------------------------------------------- #
# calibrate
# --------------------------------------------------------------------------- #


def test_calibrate_refuses_a_zero_receipt_result_set(tmp_path, capsys):
    _write_results(tmp_path, receipts=0, results=[])
    code = cmd_calibrate(build_parser().parse_args(["calibrate"]), results_dir=tmp_path)

    # This project has already produced a 0/0 precision of 1.0 once. The command
    # whose job is choosing an auto-approval threshold is the worst place to
    # repeat it.
    assert code == EXIT_FAILED
    err = capsys.readouterr().err
    assert "zero receipts" in err.lower()
    assert "1.0" not in err


def test_calibrate_recommends_the_lowest_threshold_clearing_the_target(tmp_path, capsys):
    _write_results(tmp_path, receipts=3, results=[
        {"receipt_id": "r001", "confidence": "0.90", "critical_correct": True,
         "fields_correct": 1, "fields_total": 1},
        {"receipt_id": "r002", "confidence": "0.70", "critical_correct": False,
         "fields_correct": 0, "fields_total": 1},
        {"receipt_id": "r003", "confidence": "0.95", "critical_correct": True,
         "fields_correct": 1, "fields_total": 1},
    ])
    code = cmd_calibrate(
        build_parser().parse_args(["calibrate", "--target", "0.99"]), results_dir=tmp_path)

    out = capsys.readouterr().out
    assert code == EXIT_OK
    # 0.70 admits the incorrect receipt; 0.90 does not.
    assert "0.9" in out


def test_calibrate_when_no_threshold_clears_the_target_recommends_nothing(tmp_path, capsys):
    _write_results(tmp_path, receipts=2, results=[
        {"receipt_id": "r001", "confidence": "0.90", "critical_correct": False,
         "fields_correct": 0, "fields_total": 1},
        {"receipt_id": "r002", "confidence": "0.95", "critical_correct": False,
         "fields_correct": 0, "fields_total": 1},
    ])
    code = cmd_calibrate(
        build_parser().parse_args(["calibrate", "--target", "0.99"]), results_dir=tmp_path)

    out = capsys.readouterr().out.lower()
    assert code == EXIT_FAILED
    # Never return the least-bad number as though it passed.
    assert "no threshold" in out or "none" in out


def test_calibrate_with_no_results_file_is_exit_one(tmp_path, capsys):
    # Wrapped to stay under the project's 100-column limit; identical call/assertion
    # to the brief's verbatim single-line form.
    code = cmd_calibrate(build_parser().parse_args(["calibrate"]), results_dir=tmp_path)
    assert code == EXIT_FAILED
    assert "receipts eval" in capsys.readouterr().err
