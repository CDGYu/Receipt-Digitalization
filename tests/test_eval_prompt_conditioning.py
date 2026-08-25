"""ISSUE-034: the eval path measures a different prompt than production sends.

`run_receipt` -- the `build_eval_pipeline` path -- calls `extract_with_repair`
with no merchant hints and no few-shots. `process_receipt` passes `hints=` at
three call sites. So a baseline figure describes the *unhinted* prompt while the
product ships the hinted one, and until 2026-08-25 nothing in the artefact said
so: ADR-0049's 60.00-61.43% has been quoted as though it described what runs.

**These tests do not settle the ruling** -- hermetic eval versus eval that
mirrors production is the owner's, and it is a larger question than it reads as,
because the eval path takes no database session and therefore *cannot* reach the
merchant registry at all. What they pin is the half that is right either way:
whatever a run measured, the artefact has to say which.

Pure, offline, no network and no images.
"""

from __future__ import annotations

import inspect

from eval.run_repeats import config_identity
from receipts.pipeline import build_eval_pipeline, run_receipt

#: Parameter names that would let the eval path condition its prompt on
#: anything outside the golden set. Checked against the real signatures below.
_CONDITIONING_PARAMS = frozenset(
    {"hints", "few_shots", "session", "session_factory", "registry", "merchant"}
)


class _Rung:
    def __init__(self, model_id: str, use_tools: bool) -> None:
        self.model_id = model_id
        self.use_tools = use_tools


class _Tiers:
    def __init__(self) -> None:
        self.triage = _Rung("m", True)
        self.extract_rungs = [_Rung("m", True)]


class _Settings:
    default_currency = "PHP"
    vlm_timeout_s = 600


def test_the_config_block_says_the_run_was_unhinted():
    """A figure has to carry what conditioned it, not only what version it was.

    `prompt_bundle_hash` covers the static templates and the tool schema. It
    does **not** cover merchant hints, because those are injected into the user
    turn at run time -- so two runs with identical bundle hashes can still have
    measured different prompts. Without this key the artefact cannot distinguish
    them, and a reader has no way to know that ADR-0049's spread describes a
    prompt the product does not send.
    """
    config = config_identity(_Tiers(), _Settings())

    assert "prompt_conditioning" in config, sorted(config)
    assert config["prompt_conditioning"] == {
        "merchant_hints": False,
        "few_shots": False,
    }


def test_the_recorded_false_is_derived_from_the_signatures_not_asserted():
    """The pin that stops the record above from becoming a comfortable lie.

    `merchant_hints: False` is a fact about the code, not a preference, and a
    hardcoded constant would keep claiming it after someone threaded hints
    through. So this asserts the *reason* it is false: neither entry point on
    the eval path accepts anything that could condition the prompt, and
    `run_receipt` takes no session, so the registry is unreachable rather than
    merely unused.

    **Goes red the moment ISSUE-034's ruling is implemented**, which is the
    intent -- whoever adds `hints=` has to come here and update what the
    artefact records, rather than silently making it wrong.
    """
    for fn in (run_receipt, build_eval_pipeline):
        params = set(inspect.signature(fn).parameters)
        offending = params & _CONDITIONING_PARAMS
        assert not offending, (
            f"{fn.__name__} now accepts {sorted(offending)}, so the eval path "
            "can condition its prompt. `config_identity`'s "
            "`prompt_conditioning` block still reports False and is now a "
            "false claim -- update it, and settle ISSUE-034's ruling while you "
            "are here."
        )
