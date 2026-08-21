"""The repeat runner: N runs, N directories, one aggregate.

Offline like the rest of the suite. Nothing here touches a provider, a network
or an image; the seam is ``run_baseline``'s injectable client and the
monkeypatchable ``make_pass_clients``.
"""

from __future__ import annotations

import pytest

from eval.run_repeats import (
    config_identity,
    prepare_run_dir,
    repeat_dir,
    rung_identity,
    spread_over,
)
from receipts.extract.clients.factory import PassClients
from receipts.extract.clients.fake import FakeVLMClient


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
    """A metric added to the report later appears without anybody deciding."""
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
    """Every key appearing in *any* input dict, not only the first one's.

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
