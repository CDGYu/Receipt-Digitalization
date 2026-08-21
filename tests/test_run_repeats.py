"""The repeat runner: N runs, N directories, one aggregate.

Offline like the rest of the suite: no provider and no network. The seam is
``run_baseline``'s monkeypatchable ``make_pass_clients``, which every test that
drives a run replaces with scripted fakes. Those tests also write a synthetic
PNG beside each label -- ``build_eval_pipeline`` resolves an image file per
label and cannot run without one -- exactly as ``tests/test_run_baseline.py``
does.
"""

from __future__ import annotations

import itertools
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from eval.run_baseline import latest_results_file
from eval.run_repeats import (
    config_identity,
    prepare_run_dir,
    repeat_dir,
    run_repeats,
    rung_identity,
    spread_over,
)
from receipts.extract.clients.factory import PassClients
from receipts.extract.clients.fake import FakeVLMClient
from receipts.extract.schema import (
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)


def test_prepare_run_dir_creates_the_directory(tmp_path):
    run_dir = prepare_run_dir(tmp_path, "2026-08-22-cloud-only")
    assert run_dir == tmp_path / "2026-08-22-cloud-only"
    assert run_dir.is_dir()


def test_prepare_run_dir_creates_missing_parents(tmp_path):
    """The results root may not exist yet: eval/results/ is empty in a clone."""
    root = tmp_path / "not" / "there" / "yet"
    run_dir = prepare_run_dir(root, "r1")
    assert run_dir.is_dir()


def test_prepare_run_dir_refuses_an_existing_run_id(tmp_path):
    """An explicit reuse is refused, never silently overwritten.

    This is the run-id half of the collision the milestone exists to remove:
    ``_write_report`` names its file ``{date}-{prompt_version}.json``, so a
    second run into one directory destroys the first. Auto-suffixing would
    produce a second artifact nobody can tell from the first, so the answer is
    a refusal.
    """
    prepare_run_dir(tmp_path, "same")
    with pytest.raises(FileExistsError):
        prepare_run_dir(tmp_path, "same")


def test_repeat_dir_zero_pads_so_ten_repeats_sort(tmp_path):
    """Zero-padded, so repeat-02 sorts before repeat-10 in any listing."""
    run_dir = tmp_path / "run"
    assert repeat_dir(run_dir, 1).name == "repeat-01"
    assert repeat_dir(run_dir, 10).name == "repeat-10"
    names = sorted(repeat_dir(run_dir, i).name for i in (1, 2, 10))
    assert names == ["repeat-01", "repeat-02", "repeat-10"]


class _Settings:
    """The two settings the config block reads, and nothing else."""

    default_currency = "PHP"
    vlm_timeout_s = 600


class _Realish(FakeVLMClient):
    """A fake that carries ``use_tools``, as the real client does."""

    def __init__(self, model_id: str, use_tools: bool) -> None:
        super().__init__([], model_id=model_id)
        self.use_tools = use_tools


def test_rung_identity_records_a_tier_not_a_model():
    """ADR-0047 decision 2: a tier is a (model, use_tools) pair."""
    assert rung_identity(_Realish("m", True)) == {
        "model_id": "m",
        "use_tools": True,
    }


def test_rung_identity_records_null_when_use_tools_is_unobservable():
    """FakeVLMClient carries no ``use_tools``; every offline test uses one.

    Measured before this plan was written: ``use_tools`` is set in
    ``OpenAICompatClient.__init__`` and is absent from ``FakeVLMClient``.
    Reading the attribute directly would make every test below die on
    AttributeError, and null is honest -- it says "not observable here", which
    is what ``extract_rung_counts`` already says with the same value.
    """
    assert rung_identity(FakeVLMClient([], model_id="fake")) == {
        "model_id": "fake",
        "use_tools": None,
    }


def test_config_identity_gives_a_one_rung_run_a_one_element_list():
    """The spec's SS10 Q1: no null-shaped hole for a run with one rung.

    A one-rung and a two-rung run must diff against each other directly, so the
    difference between them is a list length and never a null that reads as
    "not measured".
    """
    only = _Realish("gemma4:cloud", True)
    tiers = PassClients(triage=only, extract_rungs=(only,))

    config = config_identity(tiers, _Settings())

    assert config["extract_rungs"] == [
        {"model_id": "gemma4:cloud", "use_tools": True}
    ]
    assert config["triage"] == {"model_id": "gemma4:cloud", "use_tools": True}
    assert config["default_currency"] == "PHP"
    assert config["vlm_timeout_s"] == 600


def test_config_identity_gives_a_two_rung_run_the_same_shape():
    """The ladder differs from the cloud-only run by list length, nothing else."""
    local = _Realish("granite3.2-vision:2b", True)
    cloud = _Realish("gemma4:cloud", True)
    tiers = PassClients(triage=local, extract_rungs=(local, cloud))

    config = config_identity(tiers, _Settings())

    assert config["extract_rungs"] == [
        {"model_id": "granite3.2-vision:2b", "use_tools": True},
        {"model_id": "gemma4:cloud", "use_tools": True},
    ]
    # Same keys as the one-rung run: the two artifacts are directly diffable.
    one = config_identity(
        PassClients(triage=cloud, extract_rungs=(cloud,)), _Settings()
    )
    assert set(config) == set(one)


def test_config_identity_records_the_triage_tier_not_the_first_rung():
    """Triage is its own tier, and no test above tells the two apart.

    ``make_pass_clients`` builds triage from ``vlm_model_triage`` with its own
    ``vlm_use_tools_triage``, so a run whose triage differs from rung one has to
    say so or the block misreports what ran.

    Measured, not assumed: with triage and rung one built from *one* client, as
    both tests above build them, swapping the block's ``tiers.triage`` for the
    first extract rung leaves every other test in this module green. The
    distinct clients here are what make that substitution fail.
    """
    triage = _Realish("triage-model", False)
    rung = _Realish("rung-model", True)

    config = config_identity(
        PassClients(triage=triage, extract_rungs=(rung,)), _Settings()
    )

    assert config["triage"] == {"model_id": "triage-model", "use_tools": False}
    assert config["extract_rungs"] == [
        {"model_id": "rung-model", "use_tools": True}
    ]


def test_config_identity_records_the_prompt_identity_it_did_not_invent():
    """Read from the module that owns them, never restated here.

    A copy of PROMPT_VERSION in this module is a second statement that can
    drift, which is the failure the whole repository legislates against.
    """
    from receipts.extract.prompts import PROMPT_VERSION, prompt_bundle_hash

    only = _Realish("m", True)
    config = config_identity(
        PassClients(triage=only, extract_rungs=(only,)), _Settings()
    )

    assert config["prompt_version"] == PROMPT_VERSION
    assert config["prompt_bundle_hash"] == prompt_bundle_hash()


def test_spread_reports_only_values_that_were_observed():
    """min, max and median are all real observations; no mean, no stdev.

    ``statistics.median`` averages the two middle values on an even count,
    which invents a figure nobody measured. ``median_low`` cannot.
    """
    out = spread_over([{"acc": 0.10}, {"acc": 0.20}, {"acc": 0.40}, {"acc": 0.80}])

    assert out["acc"]["min"] == 0.10
    assert out["acc"]["max"] == 0.80
    assert out["acc"]["median"] in (0.20, 0.40)
    assert out["acc"]["median"] in out["acc"]["values"]
    assert "mean" not in out["acc"]
    assert "stdev" not in out["acc"]


def test_spread_keeps_the_raw_values_in_repeat_order():
    """The file carries the observations, so any other summary is derivable."""
    out = spread_over([{"acc": 0.3}, {"acc": 0.1}, {"acc": 0.2}])
    assert out["acc"]["values"] == [0.3, 0.1, 0.2]
    assert out["acc"]["n"] == 3
    assert out["acc"]["n_null"] == 0


def test_spread_counts_nulls_separately_rather_than_averaging_over_them():
    """``auto_approval_precision`` is null when nothing was auto-approved.

    A ratio over no paths is undefined, not zero -- the rule ``format_report``
    already follows. Folding a null in as 0 would report a precision collapse
    that did not happen.
    """
    out = spread_over([{"p": 0.9}, {"p": None}, {"p": 0.7}])

    assert out["p"]["n"] == 2
    assert out["p"]["n_null"] == 1
    assert out["p"]["min"] == 0.7
    assert out["p"]["max"] == 0.9
    assert out["p"]["values"] == [0.9, None, 0.7]


def test_spread_of_an_all_null_metric_is_null_not_zero():
    out = spread_over([{"p": None}, {"p": None}])
    assert out["p"]["min"] is None
    assert out["p"]["max"] is None
    assert out["p"]["median"] is None
    assert out["p"]["n"] == 0
    assert out["p"]["n_null"] == 2


def test_spread_derives_its_keys_and_does_not_enumerate_them():
    """The key set is read from the dicts; no list of metric names lives here."""
    out = spread_over([
        {"known": 1, "added_next_year": 5},
        {"known": 2, "added_next_year": 7},
    ])
    assert set(out) == {"known", "added_next_year"}


def test_spread_skips_non_numeric_entries():
    """Counts and metrics are numeric; a stray string is not a distribution."""
    out = spread_over([{"label": "cloud", "n": 1}, {"label": "cloud", "n": 3}])
    assert set(out) == {"n"}


def test_spread_of_one_repeat_has_equal_min_and_max():
    """n=1 is the ladder run. It is a valid spread of one, not an error."""
    out = spread_over([{"acc": 0.5}])
    assert out["acc"]["min"] == out["acc"]["max"] == 0.5
    assert out["acc"]["n"] == 1


def test_spread_includes_a_key_only_one_repeat_reported():
    """Keys come from *any* input dict, not only the first one's.

    Added because no test above can fail on it: keys read from
    ``metric_dicts[0]`` alone leave every one of them green (measured). The
    union is the shape ``field_accuracy`` already takes over ``pred.keys() |
    tru.keys()``, for the same reason -- the key that appears on one side only
    is the one worth seeing.
    """
    out = spread_over([{"known": 1}, {"known": 2, "added_next_year": 7}])

    assert set(out) == {"known", "added_next_year"}
    assert out["added_next_year"]["n"] == 1


def test_spread_does_not_treat_a_boolean_as_a_measurement():
    """``bool`` is a subclass of ``int``, and a flag is not a distribution.

    Added because no test above can fail on it: drop the ``bool`` guard from
    ``_numeric`` and every one of them stays green (measured), while a run
    whose ``use_tools`` differed between repeats would report ``min`` False and
    ``max`` True as though the flag had been measured.
    """
    out = spread_over([{"use_tools": True, "acc": 0.5}, {"use_tools": False, "acc": 0.6}])

    assert set(out) == {"acc"}


# --------------------------------------------------------------------------- #
# run_repeats: the loop, the per-repeat directories, and the aggregate
#
# The fixture helpers below mirror ``tests/test_run_baseline.py``'s, which owns
# the originals. Copied rather than imported: ``tests/`` has no ``__init__.py``,
# so one test module reaching into another would rest on pytest's sys.path
# insertion rather than on a package, and would put this module's collection at
# the mercy of that one's import graph.
# --------------------------------------------------------------------------- #


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors test_run_baseline._good)."""
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                     unit_price=D("100.00"), line_total=D("100.00")),
            LineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                     unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _wrong_merchant() -> ReceiptExtraction:
    """The clean extraction with the merchant misread.

    ``critical_field_accuracy`` is merchant name AND date AND total, so this
    scores 0.0 on the golden receipt where ``_good`` scores 1.0 -- which is
    what gives two repeats something to disagree about.
    """
    extraction = _good()
    extraction.merchant.name = "NOT THE MERCHANT ON THE LABEL"
    return extraction


def _triage() -> TriageResult:
    # GOOD legibility keeps the clean receipt at a perfect confidence.
    return TriageResult(document_type=DocumentType.POS_RECEIPT,
                        legibility=Legibility.GOOD,
                        estimated_line_item_count=2)


def _unparseable() -> str:
    """A scripted body that will not coerce to ReceiptExtraction.

    ``FakeVLMClient`` treats a string entry as a ``parse_error``, which
    ``_evaluate`` resolves to a default ``ReceiptExtraction()`` -- what
    ``read_nothing`` calls "read nothing", and so what makes a rung escalate.
    """
    return "not json at all"


def _write_png(path: Path) -> None:
    """A synthetic RGB PNG, sized so resize_for_model logs no legibility warning."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


def _write_golden(golden: Path) -> None:
    """One labelled receipt (label + matching image) under a tmp golden dir.

    The ``pipeline`` extra guards sit on the fixture that needs them, as they do
    in ``tests/test_run_baseline.py``. They cannot fire while this module's own
    top-level ``eval.run_baseline`` import reaches Pillow first; they are kept
    so the fixture still says what it needs if that ever stops being true.
    """
    pytest.importorskip("PIL")
    pytest.importorskip("pillow_heif")

    labels = golden / "labels"
    images = golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)
    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")


def _fresh_tiers_factory(n_rungs=1):
    """A builder that mints FRESH fakes on every call.

    ``FakeVLMClient`` replays a fixed list and records calls, so returning one
    set of clients from a closure hands repeat 2 an exhausted object. A builder
    that reuses them fails with "FakeVLMClient exhausted", which looks like a
    product bug and is not one.
    """
    def build(settings=None):
        triage = FakeVLMClient([_triage()], model_id="triage-model")
        if n_rungs == 1:
            only = FakeVLMClient([_good()], model_id="cloud")
            return PassClients(triage=triage, extract_rungs=(only,))
        local = FakeVLMClient([_unparseable()], model_id="local")
        cloud = FakeVLMClient([_good()], model_id="cloud")
        return PassClients(triage=triage, extract_rungs=(local, cloud))

    return build


def _disagreeing_tiers_factory():
    """A builder whose consecutive calls read the merchant differently.

    Fresh fakes per call for the reason ``_fresh_tiers_factory`` gives, plus a
    call counter. Any two *consecutive* builds disagree, so the repeats disagree
    wherever in the sequence they fall: ``run_repeats`` also builds one set for
    the config block, and a test that had to know how many times the builder is
    called would be pinning an implementation detail.
    """
    calls = itertools.count()

    def build(settings=None):
        index = next(calls)
        body = _good() if index % 2 == 0 else _wrong_merchant()
        return PassClients(
            triage=FakeVLMClient([_triage()], model_id="triage-model"),
            extract_rungs=(FakeVLMClient([body], model_id="cloud"),),
        )

    return build


def _add_labelled_receipt(golden: Path, stem: str) -> None:
    """A further labelled receipt in a golden dir ``_write_golden`` already made."""
    (golden / "labels" / f"{stem}.json").write_text(
        _good().model_dump_json(), encoding="utf-8"
    )
    _write_png(golden / "images" / f"{stem}.png")


def _one_repeat_fails_factory():
    """Consecutive builds alternate between a whole repeat and a partial one.

    The odd build scripts one extraction for a two-receipt golden set, so the
    second extract call raises "exhausted" and ``run_eval`` records it as that
    receipt's failure. Offset-independent for the reason
    ``_disagreeing_tiers_factory`` gives.
    """
    calls = itertools.count()

    def build(settings=None):
        index = next(calls)
        bodies = [_good(), _good()] if index % 2 == 0 else [_good()]
        return PassClients(
            triage=FakeVLMClient([_triage(), _triage()], model_id="triage-model"),
            extract_rungs=(FakeVLMClient(bodies, model_id="cloud"),),
        )

    return build


def test_n_repeats_produce_n_directories_and_one_aggregate(tmp_path, monkeypatch):
    """The collision, closed by construction.

    ``_write_report`` names its file ``{date}-{prompt_version}.json``, both
    constant within a day, so repeats sharing a directory overwrite each other.
    Measured by making ``repeat_dir`` return the run directory itself: three
    repeats, one surviving file. Giving each repeat its own directory removes
    that -- and this test is the pin, proven red against exactly that mutation.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    aggregate = run_repeats(
        "run-a", 3, golden_dir=golden, results_root=tmp_path / "results"
    )

    run_dir = tmp_path / "results" / "run-a"
    dirs = sorted(p.name for p in run_dir.iterdir() if p.is_dir())
    assert dirs == ["repeat-01", "repeat-02", "repeat-03"]

    # One results file per repeat, all three surviving.
    files = sorted(run_dir.rglob("repeat-*/*.json"))
    assert len(files) == 3

    assert (run_dir / "aggregate.json").is_file()
    assert aggregate["n_repeats"] == 3
    assert len(aggregate["repeats"]) == 3

    # And nothing else at the top of the run dir. The aggregate is written
    # through `aggregate.json.tmp` and renamed over the old one; a temp file
    # left behind would be committed by the milestone's `git add eval/results/`.
    assert sorted(p.name for p in run_dir.iterdir() if p.is_file()) == [
        "aggregate.json"
    ]


def test_the_aggregate_points_at_each_repeats_own_results_file(tmp_path, monkeypatch):
    """Relative paths, so the artifact survives being cloned anywhere."""
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    run_repeats("run-b", 2, golden_dir=golden, results_root=tmp_path / "results")

    run_dir = tmp_path / "results" / "run-b"
    aggregate = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    for entry in aggregate["repeats"]:
        rel = entry["results_file"]
        assert not Path(rel).is_absolute()
        assert (run_dir / rel).is_file()


def test_the_aggregate_carries_the_rung_counts_the_results_file_does_not(
    tmp_path, monkeypatch
):
    """ISSUE-012, discharged for this artifact.

    The ladder escalates: rung 0 returns an unparseable body, so it reads
    nothing and is discarded, and ``cloud`` produces the kept extraction. The
    count must therefore be ``{"cloud": 1}`` and not ``{"local": 1}`` -- an
    assertion that a single key exists would pass either way.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(2)
    )

    aggregate = run_repeats(
        "run-c", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    for entry in aggregate["repeats"]:
        assert entry["extract_rung_counts"] == {"cloud": 1}
        assert entry["failures"] == []

    # And the per-run results file still does not carry them: this milestone
    # took no position on who owns that write.
    run_dir = tmp_path / "results" / "run-c"
    one = json.loads(
        (run_dir / aggregate["repeats"][0]["results_file"]).read_text(encoding="utf-8")
    )
    assert "extract_rung_counts" not in one


def test_the_aggregate_records_a_two_rung_ladder_as_two_tiers(tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(2)
    )

    aggregate = run_repeats(
        "run-d", 1, golden_dir=golden, results_root=tmp_path / "results"
    )

    rungs = aggregate["config"]["extract_rungs"]
    assert [r["model_id"] for r in rungs] == ["local", "cloud"]


def test_the_runner_writes_nothing_latest_results_file_can_see(tmp_path, monkeypatch):
    """The guarantee spec §3.2 rests on, stated over the real function.

    ``receipts calibrate`` with no ``--results`` resolves its input through
    ``latest_results_file``, which globs ``*.json`` non-recursively. An
    aggregate at the top of ``eval/results/`` would become the newest file and
    be handed to a command that cannot read it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    results_root = tmp_path / "results"

    run_repeats("run-e", 2, golden_dir=golden, results_root=results_root)

    assert latest_results_file(results_root) is None


def test_a_repeat_that_fails_a_receipt_says_so_in_the_aggregate(
    tmp_path, monkeypatch
):
    """A partially failed repeat must be visible in the aggregate.

    ``run_eval`` catches per receipt, so one bad receipt never takes the batch
    down; the aggregate carries ``failures`` per repeat, and that is what a
    reader discounts by. Nothing holds such a repeat out of the numbers: every
    repeat's metrics go into the spread unfiltered, and a failed receipt is
    counted in ``n_receipts`` with ``critical_correct`` false
    (``_Accumulator.add_failure``), so the repeat contributes a depressed figure
    to ``min``, ``median`` and ``values``. Pinned by
    ``test_a_failed_repeats_metrics_still_enter_the_spread``.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)

    def _explodes(settings=None):
        triage = FakeVLMClient([_triage()], model_id="triage-model")
        # No scripted extract response: the extract call raises "exhausted",
        # which run_eval records as a failure for that receipt.
        return PassClients(
            triage=triage, extract_rungs=(FakeVLMClient([], model_id="empty"),)
        )

    monkeypatch.setattr("eval.run_baseline.make_pass_clients", _explodes)

    aggregate = run_repeats(
        "run-f", 1, golden_dir=golden, results_root=tmp_path / "results"
    )

    entry = aggregate["repeats"][0]
    assert entry["counts"]["failed"] >= 1
    assert entry["failures"], "a failed receipt must reach the aggregate"


def test_the_spread_is_computed_over_repeats_that_disagree(tmp_path, monkeypatch):
    """Spec §8 guarantee 3: a spread over repeats that actually differ.

    Added because nothing asserted that a metric a run produced reaches the
    artifact at all -- measured 2026-08-22, when this was the only test here
    that read one: dropping ``"spread"`` from the aggregate, or returning ``{}``
    from ``_report_metrics``, left every other test in the module green. The
    per-repeat numbers are what this milestone exists to produce.

    Repeats that agreed would not close it either: over identical repeats
    ``min`` and ``max`` are the same number, so an implementation returning
    either one for both would still pass.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _disagreeing_tiers_factory()
    )

    aggregate = run_repeats(
        "run-g", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    observed = sorted(
        entry["metrics"]["critical_field_accuracy"] for entry in aggregate["repeats"]
    )
    assert observed == [0.0, 1.0]

    spread = aggregate["spread"]["critical_field_accuracy"]
    assert spread["min"] == 0.0
    assert spread["max"] == 1.0
    assert spread["n"] == 2
    assert spread["n_null"] == 0
    assert sorted(spread["values"]) == [0.0, 1.0]


def test_a_run_of_no_repeats_is_refused_before_the_run_id_is_claimed(tmp_path):
    """Zero repeats is not a run, and must not consume the run id.

    Added because no test above can fail on it: deleting the guard leaves them
    all green while ``run_repeats(id, 0)`` claims the run directory, writes no
    aggregate at all and returns ``{}`` (measured). The directory assertion is
    half the point -- ``prepare_run_dir`` refuses an id it has already seen, so
    a guard that fired after creating one would leave the id unusable for the
    real run.
    """
    results_root = tmp_path / "results"

    with pytest.raises(ValueError):
        run_repeats("run-h", 0, results_root=results_root)

    assert not (results_root / "run-h").exists()


def test_each_repeats_counts_are_the_counts_its_own_results_file_records(
    tmp_path, monkeypatch
):
    """The counts block is the report's own, not a second copy that can drift.

    Checked against the file ``run_eval`` wrote for that same repeat rather than
    against a list of key names: ``_report_to_dict`` builds both, so the equality
    holds however that block grows.

    Added because three of its four keys were asserted nowhere -- measured on the
    committed tree, hard-coding ``receipts``, ``auto_approved`` and
    ``critical_correct`` to 0 left all 27 tests green, and those three are the
    denominator and the numerators of every accuracy figure this artifact
    reports. The repeats deliberately disagree, so a block read once and reused
    for every entry fails here too.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _disagreeing_tiers_factory()
    )

    aggregate = run_repeats(
        "run-i", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    run_dir = tmp_path / "results" / "run-i"
    for entry in aggregate["repeats"]:
        on_disk = json.loads(
            (run_dir / entry["results_file"]).read_text(encoding="utf-8")
        )
        assert entry["counts"] == on_disk["counts"]

    counts = [e["counts"] for e in aggregate["repeats"]]
    assert sorted(c["critical_correct"] for c in counts) == [0, 1]
    assert [c["receipts"] for c in counts] == [1, 1]
    assert [c["failed"] for c in counts] == [0, 0]


def test_a_failed_repeats_metrics_still_enter_the_spread(tmp_path, monkeypatch):
    """What a repeat with a failure does to the numbers, stated and pinned.

    ``run_eval`` counts a failed receipt in ``n_receipts`` with
    ``critical_correct`` false, and ``run_repeats`` folds every repeat's metrics
    into the spread unfiltered. So a repeat that lost one receipt of two reports
    0.5, and 0.5 is what ``min`` reports -- a depressed figure that reads like a
    measurement.

    Nothing here argues that is the wrong behaviour: holding failed repeats out
    would leave an all-failed run with an empty spread, which says less than a
    low number beside a failure list. What was wrong is that nothing stated or
    tested it, so a reader quoting ``min`` as the worst case had nothing telling
    them what is in it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    _add_labelled_receipt(golden, "r2")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _one_repeat_fails_factory()
    )

    aggregate = run_repeats(
        "run-j", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    partial = [e for e in aggregate["repeats"] if e["failures"]]
    whole = [e for e in aggregate["repeats"] if not e["failures"]]
    assert len(partial) == 1 and len(whole) == 1

    assert partial[0]["counts"]["receipts"] == 2
    assert partial[0]["counts"]["failed"] == 1
    assert partial[0]["counts"]["critical_correct"] == 1
    assert partial[0]["metrics"]["critical_field_accuracy"] == 0.5
    assert whole[0]["metrics"]["critical_field_accuracy"] == 1.0

    spread = aggregate["spread"]["critical_field_accuracy"]
    assert spread["n"] == 2, "the repeat that failed a receipt is in the spread"
    assert spread["min"] == 0.5
    assert sorted(spread["values"]) == [0.5, 1.0]


def test_an_interrupted_run_keeps_the_repeats_it_completed(tmp_path, monkeypatch):
    """A killed run leaves an aggregate, and one that claims only what it holds.

    The rung counts and five of the config block's six keys are in no results
    file, so an aggregate written once at the end loses both when a five-repeat
    run dies at repeat three -- the two things this artifact exists to carry.

    ``run_baseline`` is patched through ``eval.run_baseline``, the same reach
    ``run_repeats`` takes: a module that had imported the name would keep
    calling the real one and this run would not stop at all.
    """
    import eval.run_baseline as run_baseline_module

    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    real = run_baseline_module.run_baseline
    calls = itertools.count(1)

    def _dies_on_the_third(*args, **kwargs):
        if next(calls) == 3:
            raise RuntimeError("the provider went away")
        return real(*args, **kwargs)

    monkeypatch.setattr("eval.run_baseline.run_baseline", _dies_on_the_third)

    results_root = tmp_path / "results"
    with pytest.raises(RuntimeError, match="went away"):
        run_repeats("run-k", 5, golden_dir=golden, results_root=results_root)

    run_dir = results_root / "run-k"
    written = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))

    # It never claims a repeat it does not carry ...
    assert written["n_repeats"] == len(written["repeats"]) == 2
    # ... and the interruption is legible as the two figures disagreeing.
    assert written["n_repeats_requested"] == 5
    assert sorted(p.name for p in run_dir.iterdir() if p.is_dir()) == [
        "repeat-01",
        "repeat-02",
    ]

    # The two things no results file carries survived the kill.
    assert [e["extract_rung_counts"] for e in written["repeats"]] == [
        {"cloud": 1},
        {"cloud": 1},
    ]
    assert written["config"]["extract_rungs"] == [
        {"model_id": "cloud", "use_tools": None}
    ]
    assert written["spread"]["critical_field_accuracy"]["n"] == 2


def test_the_aggregate_is_staged_beside_its_destination_and_renamed_over_it(
    tmp_path, monkeypatch
):
    """The atomic route is taken, not merely available.

    Added because nothing could see it: with the staging write redirected
    straight onto ``aggregate.json`` and the rename made a no-op -- byte for
    byte the truncating in-place write this replaced -- the module's other
    tests all pass. They can only see what is left on disk *afterwards*, and
    both routes leave the same thing.

    So the process is stopped at the one instant the two differ: between the
    staging write and the rename. ``KeyboardInterrupt`` rather than an
    ``OSError``, because an ``OSError`` there is a condition
    ``_rewrite_aggregate`` deliberately degrades past, and what is being pinned
    here is where the *new* bytes sit when everything stops -- beside the
    destination, never on top of it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    real_replace = Path.replace
    renames = itertools.count(1)

    def _killed_at_the_rename(self, target):
        if next(renames) == 2:
            raise KeyboardInterrupt("killed between the staging write and the rename")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _killed_at_the_rename)

    with pytest.raises(KeyboardInterrupt):
        run_repeats("run-l", 3, golden_dir=golden, results_root=tmp_path / "results")

    run_dir = tmp_path / "results" / "run-l"

    # The destination was never opened for writing, so it still parses -- and it
    # still holds the repeat before the one that was interrupted.
    survived = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    assert survived["n_repeats"] == 1
    assert len(survived["repeats"]) == 1

    # And repeat 2's aggregate is in the staging file: exactly where a write
    # straight onto the destination would not have put it.
    staged = json.loads((run_dir / "aggregate.json.tmp").read_text(encoding="utf-8"))
    assert staged["n_repeats"] == 2


def test_a_rename_the_platform_refuses_costs_the_aggregate_not_the_run(
    tmp_path, monkeypatch, capsys
):
    """The durability improvement must never cost the run.

    Measured on this machine: ``Path.replace`` onto a destination another handle
    holds **open for reading** raises ``PermissionError`` [WinError 5] and
    strands the staging file, while ``write_text`` onto that same destination,
    under that same handle, succeeds. An editor, an indexer or a scanner reading
    the file just written is enough, and this is the platform the multi-hour
    runs happen on.

    Raised out of the loop it would abort the run and burn the run id --
    ``prepare_run_dir`` refuses to reuse one -- so the property is that a rename
    which will not go through degrades to a non-atomic write and the run
    continues. Degraded, never silent: the fallback says so on stderr.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    def _always_refused(self, target):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", _always_refused)

    aggregate = run_repeats(
        "run-m", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    run_dir = tmp_path / "results" / "run-m"
    on_disk = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))

    # The run finished, and the artifact is the real one, not a stale rump.
    assert on_disk["n_repeats"] == 2
    assert on_disk == aggregate
    # Nothing stranded, on this path either.
    assert not (run_dir / "aggregate.json.tmp").exists()

    printed = capsys.readouterr().err
    assert "aggregate.json" in printed
    assert "not atomic" in printed
