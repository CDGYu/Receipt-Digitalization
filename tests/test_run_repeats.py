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
    main,
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
    """The two settings the config block reads, and nothing else.

    **Values the environment cannot produce.** ``"PHP"`` and ``600`` are what
    ``get_settings()`` resolves on the machine this runs on -- measured -- so
    a stub carrying them cannot tell a block that read *this* object from one
    that ignored its argument and read a process-global ``Settings()``.
    Measured with exactly that mutation on the committed tree: all 41 tests
    stayed green. ``"XTS"`` is the ISO 4217 code reserved for testing and no
    configuration resolves to it; ``999`` is not the timeout default.
    """

    default_currency = "XTS"
    vlm_timeout_s = 999


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
    """The spec's §10 Q1: no null-shaped hole for a run with one rung.

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
    assert config["default_currency"] == "XTS"
    assert config["vlm_timeout_s"] == 999


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
    """A key is dropped when **no** repeat gave it a number and not all gave null.

    Not "a non-numeric value drops the key": that is false as a sufficient
    condition, and spec §4.2 states the rule as a biconditional for this
    reason. The mixed arm below is the counter-example, measured -- one number
    and one string reports the key, with the string uncounted.
    """
    out = spread_over([{"label": "cloud", "n": 1}, {"label": "cloud", "n": 3}])
    assert set(out) == {"n"}

    mixed = spread_over([{"x": 1}, {"x": "a"}])
    assert mixed["x"]["n"] == 1
    assert mixed["x"]["values"] == [1, "a"]


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


def _differently_escalating_tiers_factory():
    """A builder whose consecutive calls are kept by *different* rungs.

    The even build's rung 0 reads the receipt and is kept, so the count is
    ``{"local": 1}``. The odd build's rung 0 returns an unparseable body, reads
    nothing, is discarded, and the cloud rung's extraction is kept --
    ``{"cloud": 1}``. Fresh fakes per call, and offset-independent, both for the
    reasons ``_disagreeing_tiers_factory`` gives.
    """
    calls = itertools.count()

    def build(settings=None):
        index = next(calls)
        rung_zero = _good() if index % 2 == 0 else _unparseable()
        return PassClients(
            triage=FakeVLMClient([_triage()], model_id="triage-model"),
            extract_rungs=(
                FakeVLMClient([rung_zero], model_id="local"),
                FakeVLMClient([_good()], model_id="cloud"),
            ),
        )

    return build


def _every_receipt_fails_factory():
    """A builder whose extract rung carries no scripted response at all.

    Every extract call raises "exhausted", which ``run_eval`` records as that
    receipt's failure -- the shape a cloud throttle takes on the final rung,
    where there is no rung after it to escalate to. Two triage responses,
    because the golden set this drives carries two labels.
    """
    def build(settings=None):
        return PassClients(
            triage=FakeVLMClient([_triage(), _triage()], model_id="triage-model"),
            extract_rungs=(FakeVLMClient([], model_id="empty"),),
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
    # The loop below is vacuous over an empty list, and an aggregate carrying
    # no entries at all passes it -- measured, with ``"repeats": entries[:0]``.
    assert len(aggregate["repeats"]) == 2
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


def test_each_repeats_rung_counts_are_that_repeats_own(tmp_path, monkeypatch):
    """Every entry carries its **own** counts, not a constant and not repeat 1's.

    Added because nothing here could fail on it. Measured on the committed
    tree, each mutation still parsing: replacing
    ``report.extract_rung_counts`` with a hardcoded ``{"cloud": 1}``, and
    reusing repeat 1's counts for every later entry, each left **all 41** tests
    green. The two tests that read the field both used fixtures where every
    repeat produced the identical count, so neither could tell a per-repeat
    read from a constant.

    This is the field ISSUE-012 is about and the one spec §6 hangs an
    obligation on -- "if the counts show granite kept any receipt, that
    extraction is inspected and the finding recorded before any number is
    published". That obligation is unenforceable if repeat 3's counts can
    silently be repeat 1's. Spec §8 guarantee 3 applies exactly this standard
    to the spread; this is guarantee 2 held to it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _differently_escalating_tiers_factory()
    )

    aggregate = run_repeats(
        "run-p", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    first, second = (e["extract_rung_counts"] for e in aggregate["repeats"])
    assert first != second, (
        "consecutive builds are kept by different rungs, so equal counts mean "
        "the entries are not reading their own repeat's report"
    )
    # And each names the rung that actually produced the kept extraction, so a
    # pair that merely differed would not pass either.
    assert sorted([first, second], key=sorted) == [{"cloud": 1}, {"local": 1}]


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


def test_the_aggregate_counts_every_failed_receipt_at_the_top_level(
    tmp_path, monkeypatch
):
    """An all-failed run is legible from the top of the file, not two levels down.

    Not refusing such a run is correct and unchanged -- an all-failed run *is*
    an observation, and spec §7 plans for it. What was missing is that the
    failure signal lived only at ``repeats[i].counts.failed`` and
    ``repeats[i].failures``: ``spread``, which is where a headline is read,
    carried none of it. Reproduced end to end on the committed tree -- three
    receipts, every extract call raising, two repeats -- exit code 0,
    ``Repeats: 2``, and ``spread.critical_field_accuracy = {"min": 0.0, "max":
    0.0, "median": 0.0, "n": 2, "n_null": 0}``. A cloud throttle is exactly how
    this arises.

    The total is over **every** repeat: one repeat's ``failed`` is 2 here and
    the run's is 4, so a roll-up that read a single entry fails.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    _add_labelled_receipt(golden, "r2")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _every_receipt_fails_factory()
    )

    aggregate = run_repeats(
        "run-q", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    assert [e["counts"]["failed"] for e in aggregate["repeats"]] == [2, 2]
    assert aggregate["n_failed"] == 4
    # It is in the artifact, not only in the return value: the file is what a
    # reader quotes from.
    run_dir = tmp_path / "results" / "run-q"
    on_disk = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    assert on_disk["n_failed"] == 4
    # And the run was not refused, which is the decision this pins in place.
    assert on_disk["n_repeats"] == 2


def test_a_metric_that_reaches_no_spread_is_named_rather_than_dropped(
    tmp_path, monkeypatch
):
    """A metric with no spread entry is named, not silently absent.

    ``_report_to_dict`` writes ``cost_per_receipt`` as
    ``str(report.cost_per_receipt)`` (``eval/harness.py``) and ``_numeric``
    rejects strings, so a key non-numeric in **every** repeat gets no spread
    entry at all: no ``n``, no ``n_null``, no ``values``, nothing saying it was
    there. Measured: ``spread_over([{"cost_per_receipt": "0.0123"},
    {"cost_per_receipt": "0.0456"}])`` returns ``{}``.

    Latent today, which is why the string is injected at the seam that produces
    it rather than waited for: an offline run leaves the cost unset, and an
    all-``None`` metric *is* reported. That is the control arm below -- the
    same key, same run, present in ``spread`` and absent from
    ``spread_omitted`` -- so neither list is a constant.
    """
    import eval.run_repeats as run_repeats_module

    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    results_root = tmp_path / "results"

    # Control, unpatched: the cost is null in every repeat, so it is reported.
    clean = run_repeats("run-r-clean", 2, golden_dir=golden, results_root=results_root)
    assert clean["spread_omitted"] == []
    assert clean["spread"]["cost_per_receipt"]["n_null"] == 2

    real_metrics = run_repeats_module._report_metrics

    def _with_a_measured_cost(report):
        metrics = dict(real_metrics(report))
        # Exactly what `_report_to_dict` writes the day a cost is measured.
        metrics["cost_per_receipt"] = str(D("0.0123"))
        return metrics

    monkeypatch.setattr("eval.run_repeats._report_metrics", _with_a_measured_cost)

    measured = run_repeats("run-r-cost", 2, golden_dir=golden, results_root=results_root)

    assert "cost_per_receipt" not in measured["spread"]
    assert measured["spread_omitted"] == ["cost_per_receipt"]
    # The value is not lost, only its spread: it is in every repeat's own block.
    assert measured["repeats"][0]["metrics"]["cost_per_receipt"] == "0.0123"


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


# --------------------------------------------------------------------------- #
# The command an operator types.
# --------------------------------------------------------------------------- #


def test_both_arguments_are_required(tmp_path, capsys):
    """No default can silently collide, and no default can produce a
    single-run artifact that reads as a baseline.

    ``--results-root`` is passed on both calls although neither reaches it: if
    ``--repeats`` ever stopped being required, ``main(["--run-id", "x"])``
    would run against ``DEFAULT_RESULTS_DIR`` and create ``eval/results/x/`` in
    the repository, which is not gitignored. A test's failure mode must not
    write into the tracked tree.
    """
    root = str(tmp_path / "results")
    with pytest.raises(SystemExit):
        main(["--repeats", "3", "--results-root", root])
    with pytest.raises(SystemExit):
        main(["--run-id", "x", "--results-root", root])


def test_main_refuses_a_reused_run_id_with_a_message_not_a_traceback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    (tmp_path / "results" / "taken").mkdir(parents=True)

    code = main([
        "--run-id", "taken",
        "--repeats", "1",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code != 0
    assert "taken" in capsys.readouterr().err


def test_main_writes_the_aggregate_and_reports_where(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    code = main([
        "--run-id", "run-g",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "aggregate.json" in out
    assert (tmp_path / "results" / "run-g" / "aggregate.json").is_file()


def test_prepare_run_dir_refuses_a_run_id_that_is_not_a_directory_under_the_root(
    tmp_path,
):
    """One property: the run directory is a **direct child** of the results root.

    Carried into this task as a measured minor: ``prepare_run_dir(root, "")``
    resolves to ``root`` itself, so ``aggregate.json`` lands at the top of the
    results root. Measured against this module before the guard existed:
    ``--run-id ""`` exited 0, printed ``Wrote <root>/aggregate.json``, and
    ``latest_results_file(root)`` then returned that aggregate -- the input
    ``receipts calibrate`` resolves when the operator names no ``--results``.

    Stated as one property rather than as a list of rejected spellings: an
    enumerated defence closes the shapes it lists and re-opens on the next one.
    The values below are examples of the property, not the property.
    """
    root = tmp_path / "results"  # absent, as eval/results/ is on a clean checkout
    for run_id in ["", ".", "..", "a/b", str(root.parent / "elsewhere")]:
        with pytest.raises(ValueError):
            prepare_run_dir(root, run_id)
    # Refused before ``mkdir``: a rejected id creates nothing, root included.
    assert not root.exists()


def test_main_refuses_a_run_id_that_would_put_the_aggregate_where_calibrate_looks(
    tmp_path, monkeypatch, capsys
):
    """The §3.2 guarantee, stated over the command an operator actually types.

    The results root deliberately does **not** exist when this runs, which is
    the state ``eval/results/`` is in on a clean checkout -- with it absent,
    ``mkdir(parents=True, exist_ok=False)`` succeeds on the root itself and the
    reuse refusal never fires.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    results_root = tmp_path / "results"

    code = main([
        "--run-id", "",
        "--repeats", "1",
        "--golden-dir", str(golden),
        "--results-root", str(results_root),
    ])

    assert code != 0
    assert "Cannot run repeats" in capsys.readouterr().err
    # Refused before ``mkdir``, so the root itself was never claimed -- which
    # is also why there is no `latest_results_file` assertion here: `glob` on
    # an absent directory returns `[]`, so that call returns `None` by
    # construction whenever the line above holds, and could never fail.
    # `test_the_runner_writes_nothing_latest_results_file_can_see` pins the
    # guarantee where it can fail: after a full run, with the root present.
    assert not results_root.exists()


def test_main_names_the_file_it_actually_wrote_and_counts_what_it_carries(
    tmp_path, monkeypatch, capsys
):
    """The printed path and count are pinned to the artifact, not to a literal.

    ``assert "aggregate.json" in out`` passes against a message naming a path
    that does not exist, because the substring is a literal in the ``print``.
    What an operator needs from that line is the file they can open, so the
    assertion is over the parsed path and the aggregate the run returned.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    code = main([
        "--run-id", "run-n",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code == 0
    out = capsys.readouterr().out
    reported = Path(out.splitlines()[0].removeprefix("Wrote "))
    assert reported.is_file(), f"{reported} was announced and is not there"
    on_disk = json.loads(reported.read_text(encoding="utf-8"))
    assert on_disk["n_repeats"] == 2
    assert f"Repeats: {on_disk['n_repeats']}" in out


def test_main_says_how_many_receipts_failed(tmp_path, monkeypatch, capsys):
    """The failure roll-up, in the three-line block a reader quotes.

    Measured on the committed tree, three receipts with every extract call
    raising over two repeats: the command printed ``Wrote <path>`` and
    ``Repeats: 2``, exited 0, and said nothing whatever about the six failed
    receipts. Spec §7's "Read ``failures`` before quoting ``min``" lived in the
    spec, not in the terminal and not in the artifact.

    ``code == 0`` is asserted deliberately: **not** refusing an all-failed run
    is the standing decision, and this pin holds it in place while making the
    run visible.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    _add_labelled_receipt(golden, "r2")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _every_receipt_fails_factory()
    )

    code = main([
        "--run-id", "allfail",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "Failed receipts: 4 of 4 across 2 repeat(s)" in out


def test_main_says_so_explicitly_when_no_receipt_failed(tmp_path, monkeypatch, capsys):
    """The clean case is stated, not left to the absence of a line.

    A roll-up printed only when something failed is one a reader cannot
    distinguish from a roll-up that was never wired up. This is the control arm
    for ``test_main_says_how_many_receipts_failed``, at the same interface.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    code = main([
        "--run-id", "clean",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "Failed receipts: none, over 2 receipt(s) in 2 repeat(s)" in out


def test_main_names_the_partial_aggregate_a_killed_run_left_behind(
    tmp_path, monkeypatch, capsys
):
    """A provider failure mid-run names the artifact it did not take with it.

    ``main`` catches ``RuntimeError``, which is the common provider-failure
    path -- a cloud throttle arrives as one. Measured on the committed tree, a
    ``RuntimeError`` at repeat 3 of 5: stderr carried ``Cannot run repeats:
    ...``, exit code 1, and nothing else, while ``aggregate.json`` sat on disk
    with ``n_repeats = 2``.

    That artifact is the entire reason ``_rewrite_aggregate`` runs inside the
    loop -- a killed sequence keeps the rung counts and the config block no
    results file holds -- and ``prepare_run_dir`` had already made the run id
    unusable, so the operator could not have found it by re-running either.
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
            raise RuntimeError("cloud throttled: 429 after 5 retries")
        return real(*args, **kwargs)

    monkeypatch.setattr("eval.run_baseline.run_baseline", _dies_on_the_third)

    results_root = tmp_path / "results"
    code = main([
        "--run-id", "killed",
        "--repeats", "5",
        "--golden-dir", str(golden),
        "--results-root", str(results_root),
    ])

    assert code == 1
    err = capsys.readouterr().err
    assert "cloud throttled" in err
    # The path, so it can be opened, and both figures, so its incompleteness is
    # legible from the message rather than only from the file.
    assert str(results_root / "killed" / "aggregate.json") in err
    assert "2 of 5 repeat(s)" in err


def test_main_announces_no_partial_aggregate_when_there_is_none(
    tmp_path, monkeypatch, capsys
):
    """Silent when nothing survived: the refusal fired before any repeat ran.

    The control arm for the test above. ``run_repeats`` refuses ``--repeats 0``
    before ``prepare_run_dir`` claims the id, so no aggregate exists, and a
    handler that announced one unconditionally would name a file that is not
    there -- the exact failure ``main``'s "nothing is announced that was not
    found on disk" paragraph exists to prevent.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    results_root = tmp_path / "results"

    code = main([
        "--run-id", "nothing",
        "--repeats", "0",
        "--results-root", str(results_root),
    ])

    assert code == 1
    err = capsys.readouterr().err
    assert "Cannot run repeats" in err
    assert "partial aggregate" not in err


def test_main_does_not_report_an_aggregate_the_file_system_refused(
    tmp_path, monkeypatch, capsys
):
    """A write that degraded to nothing must not be announced as a success.

    ``_rewrite_aggregate`` deliberately does not raise when the file system
    refuses the write -- every completed repeat's own results file is already
    on disk and the remaining repeats are still worth running -- so
    ``run_repeats`` returning is not evidence that the artifact exists. A
    command that exits 0 saying ``Wrote <path>`` over an absent file is the
    exact shape this module was written to remove.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    real_write_text = Path.write_text

    def _refuse_the_aggregate(self, *args, **kwargs):
        # Only the aggregate and its staging file: each repeat's own results
        # file must still be written, because that is the case being described.
        if self.name.startswith("aggregate.json"):
            raise OSError(28, "No space left on device")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _refuse_the_aggregate)

    code = main([
        "--run-id", "run-o",
        "--repeats", "1",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    run_dir = tmp_path / "results" / "run-o"
    assert not (run_dir / "aggregate.json").exists()
    assert code != 0
    captured = capsys.readouterr()
    assert "Wrote" not in captured.out
    # ``_rewrite_aggregate`` puts "aggregate" on stderr by itself, so a
    # substring that loose would pass without ``main`` saying anything at all.
    # This is ``main``'s own sentence, and only ``main`` writes it.
    assert "Ran 1 repeat(s)" in captured.err
    # The repeat's own results file survived, which is what makes the aggregate
    # the only casualty.
    assert sorted((run_dir / "repeat-01").glob("*.json"))


def _empties_the_golden_set_after_the_first_repeat(golden, run_dir):
    """A builder that removes every label once repeat 1 has written its file.

    Keyed on observable state -- repeat 1's own results file being on disk --
    rather than on a call count. ``run_repeats`` builds one extra set for the
    config block, so a test that counted builder calls would be pinning an
    implementation detail, which is the trap ``_disagreeing_tiers_factory``
    already names.
    """
    def build(settings=None):
        if any((run_dir / "repeat-01").glob("*.json")):
            for label in (golden / "labels").glob("*.json"):
                label.unlink()
        return PassClients(
            triage=FakeVLMClient([_triage()], model_id="triage-model"),
            extract_rungs=(FakeVLMClient([_good()], model_id="cloud"),),
        )

    return build


def test_main_refuses_an_aggregate_that_scored_no_receipts(
    tmp_path, monkeypatch, capsys
):
    """A mistyped ``--golden-dir`` must not exit 0 over a well-formed nothing.

    ``glob`` on an absent directory yields ``[]`` and raises nothing, so a typo
    produces zero labels, zero pipeline calls, a results file per repeat and a
    complete aggregate. Measured on the committed tree before this guard:
    ``--golden-dir <absent> --repeats 2`` printed ``Wrote ...`` and exited 0
    with three JSON files on disk, all over zero receipts.

    **The artifact is not empty-looking, it is zero-looking.** Measured from
    that same run: ``spread.critical_field_accuracy`` came back
    ``{"min": 0.0, "median": 0.0, "n": 2, "n_null": 0}`` -- a headline accuracy
    of 0.00%, reported as observed rather than as "not measured":
    ``_build_report`` computes those figures inline as ``(x / n) if n else 0.0``
    (``eval/harness.py``), so a zero-receipt repeat contributes a numeric
    ``0.0``.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    code = main([
        "--run-id", "typo",
        "--repeats", "2",
        "--golden-dir", str(tmp_path / "no-such-golden-dir"),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code != 0
    captured = capsys.readouterr()
    assert "Wrote" not in captured.out
    # The message names the directory that produced nothing, because the path
    # is the thing the operator mistyped.
    assert "no-such-golden-dir" in captured.err


def test_main_refuses_when_only_some_repeats_scored_nothing(
    tmp_path, monkeypatch, capsys
):
    """The predicate is *every* repeat, not *any* repeat.

    "No repeat scored a receipt" would pass this run, and the aggregate it let
    through would be worse than the all-empty one: measured on this module,
    ``spread_over([{"critical_field_accuracy": 0.55}, {...: 0.0}])`` returns
    ``{"min": 0.0, "max": 0.55, "median": 0.0, "n": 2, "n_null": 0}``. The
    empty repeat contributes a numeric ``0.0``, not a null, so it enters the
    distribution and drags the headline median to zero -- from a run whose one
    real measurement was 0.55, with nothing in the file saying why.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    run_dir = tmp_path / "results" / "half"
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients",
        _empties_the_golden_set_after_the_first_repeat(golden, run_dir),
    )

    code = main([
        "--run-id", "half",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    # The precondition this test rests on: one repeat scored, one did not.
    aggregate = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    scored = [e["counts"]["receipts"] for e in aggregate["repeats"]]
    assert scored == [1, 0], f"fixture did not produce a mixed run: {scored}"

    assert code != 0
    captured = capsys.readouterr()
    assert "Wrote" not in captured.out
    # The rendered index list, not the bare digit. ``"2" in err`` is satisfied
    # by the literal ``of 2`` in the same sentence whatever the indices say --
    # measured: pinning ``entries[i]["index"]`` to the constant 1, and shifting
    # every index by 100, each leave all 41 tests green.
    assert "Repeat(s) 2 of 2" in captured.err


def _adds_a_label_after_the_first_repeat(golden, run_dir):
    """A builder that grows the golden set once repeat 1 has written its file.

    Keyed on observable state -- repeat 1's own results file being on disk --
    rather than on a call count, for the reason
    ``_empties_the_golden_set_after_the_first_repeat`` gives: ``run_repeats``
    builds one extra set for the config block.

    Growing the labels directory is what makes two repeats cover *different*
    receipts, because ``run_eval`` globs it afresh on every repeat. A repeat
    that merely **fails** a receipt does not: measured on this module, two
    labels driven by ``_one_repeat_fails_factory`` give both repeats the id set
    ``{r1, r2}``, because ``run_eval``'s except branch still records an
    ``EvalResult`` carrying the failed receipt's id (``eval/harness.py``).

    Two scripted responses per client, for the repeat that sees two labels; the
    repeat that sees one leaves the second unused.
    """
    def build(settings=None):
        if any((run_dir / "repeat-01").glob("*.json")):
            _add_labelled_receipt(golden, "r2")
        return PassClients(
            triage=FakeVLMClient([_triage(), _triage()], model_id="triage-model"),
            extract_rungs=(FakeVLMClient([_good(), _good()], model_id="cloud"),),
        )

    return build


def test_the_aggregate_names_the_receipts_it_scored(tmp_path, monkeypatch):
    """A number is only comparable to another number over the same receipts.

    The golden set can hold gitignored labels, so a clone scores fewer receipts
    than this machine does. The aggregate says which, rather than leaving a
    reader to infer coverage from a total.

    The golden set **grows between the repeats**, so the two cover different
    receipts and the union is not repeat 1's view. Without that this test
    cannot fail for the reason it is named for: measured, restricting the
    accumulator to ``index == 1`` leaves it green over a one-label golden set,
    and green again over two labels where one repeat fails a receipt. Proven
    red against that mutation with the fixture below.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    run_dir = tmp_path / "results" / "run-ids"
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients",
        _adds_a_label_after_the_first_repeat(golden, run_dir),
    )

    aggregate = run_repeats(
        "run-ids", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    scored = aggregate["scored_receipts"]
    assert scored == sorted(set(scored)), "sorted and deduplicated"
    assert scored, "a scored run names at least one receipt"
    # The ids themselves. `sorted(...)` satisfies the property above no
    # matter what it sorted, and set iteration order is hash-seeded, so the
    # property alone catches an unsorted `list(scored)` only on some seeds.
    assert scored == ["r1", "r2"]

    per_repeat = [
        {
            r["receipt_id"]
            for r in json.loads(
                (run_dir / entry["results_file"]).read_text(encoding="utf-8")
            )["results"]
        }
        for entry in aggregate["repeats"]
    ]
    # The precondition that makes the check below discriminating.
    assert per_repeat == [{"r1"}, {"r1", "r2"}], (
        f"fixture did not make the repeats differ: {per_repeat}"
    )

    # It is the union over repeats, not one repeat's view.
    assert set(scored) == set().union(*per_repeat)

    # In the artifact, not only in the return value: the file is what a reader
    # quotes from.
    on_disk = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    assert on_disk["scored_receipts"] == scored
