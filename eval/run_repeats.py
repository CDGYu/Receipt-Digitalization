"""Repeat a baseline run N times and write one aggregate artifact.

``eval.run_baseline`` runs the golden set **once** and writes
``{date}-{prompt_version}.json``. Both components are constant within a day, so
two runs on one day overwrite each other -- measured, with a control. ISSUE-001
step 6 requires repeats, because cloud inference is not deterministic at
``temperature=0``.

This module sits *above* ``run_baseline`` and changes nothing below it. Each
repeat gets its own ``results_dir``, which removes the collision by construction
rather than by renaming anything, and the aggregate this module writes is the
only place a *spread* and the per-rung provenance appear together.

    python -m eval.run_repeats --run-id 2026-08-22-cloud-only --repeats 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import eval.run_baseline as _baseline
from config.settings import get_settings
from eval.harness import DEFAULT_RESULTS_DIR, _report_to_dict

__all__ = [
    "config_identity",
    "main",
    "prepare_run_dir",
    "repeat_dir",
    "run_repeats",
    "rung_identity",
    "spread_over",
]


def prepare_run_dir(results_root: Path, run_id: str) -> Path:
    """Create ``results_root/run_id``, refusing to reuse an existing one.

    ``exist_ok=False`` is the point, not an oversight. A second run into a
    directory that already holds one destroys its results file, which is the
    exact defect this module exists to remove -- reintroducing it one level up
    would be worse than leaving it where it was, because the run *looks* like it
    produced a fresh artifact.

    Auto-suffixing was considered and rejected: it produces a second artifact
    indistinguishable from the first, and "nothing silently dropped" is a
    project non-negotiable.

    **The run directory must be a direct child of the results root**, and that
    is checked rather than assumed. ``Path(root) / ""`` is ``root`` itself, so
    an empty run id put ``aggregate.json`` at the top of the results root --
    measured against this module, ``--run-id ""`` exited 0 and
    ``latest_results_file(root)`` then returned that aggregate, which is the
    input ``receipts calibrate`` resolves when the operator names no
    ``--results``. The check is stated as that one property rather than as a
    list of rejected spellings, because a list closes the shapes it names and
    re-opens on the next one; ``""``, ``"."``, ``".."``, a separator and an
    absolute path all fail it for the same reason.

    The refusal is a :class:`ValueError` and happens before ``mkdir``, so a
    rejected id creates nothing -- including the results root itself, which a
    clean checkout does not have.
    """
    root = Path(results_root)
    run_dir = root / run_id
    if run_dir.resolve().parent != root.resolve():
        raise ValueError(
            f"run id {run_id!r} must be a plain directory name directly under "
            f"{root}, and resolves to {run_dir.resolve()} instead. An "
            f"aggregate written anywhere but one level down is one "
            f"latest_results_file can see, and that is what receipts "
            f"calibrate reads when no --results is given."
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def repeat_dir(run_dir: Path, index: int) -> Path:
    """``run_dir/repeat-NN``. Not created here.

    Zero-padded so a listing sorts correctly past nine repeats. Creation is left
    to ``_write_report``, which already does ``mkdir(parents=True,
    exist_ok=True)`` -- creating it here as well would be a second statement of
    the same thing that can drift.
    """
    return Path(run_dir) / f"repeat-{index:02d}"


def rung_identity(client: Any) -> dict[str, Any]:
    """One rung, as the ``(model, use_tools)`` pair ADR-0047 decision 2 defines.

    ``use_tools`` is read from the client rather than from ``Settings`` because
    the *resolved* per-rung value is the thing that differs between rungs --
    ``VLM_USE_TOOLS`` is process-wide and cannot express a ladder whose rungs
    disagree, which is the constraint that ADR made a decision about.

    Read defensively, because it is genuinely optional: ``OpenAICompatClient``
    sets it, ``FakeVLMClient`` does not, and every offline test uses a fake.
    ``None`` means "not observable here", which is the same thing
    ``extract_rung_counts`` says with the same value.
    """
    return {
        "model_id": getattr(client, "model_id", None),
        "use_tools": getattr(client, "use_tools", None),
    }


def config_identity(tiers: Any, settings: Any) -> dict[str, Any]:
    """What ran, in enough detail to tell two runs apart.

    ``extract_rungs`` is a list so a one-rung run and a two-rung run share one
    schema and differ only in length -- never a null that a reader could take
    for "not measured".

    Prompt identity is imported, never restated: a second copy of
    ``PROMPT_VERSION`` here is a copy that can drift.
    """
    from receipts.extract.prompts import PROMPT_VERSION, prompt_bundle_hash

    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_bundle_hash": prompt_bundle_hash(),
        "default_currency": settings.default_currency,
        "vlm_timeout_s": settings.vlm_timeout_s,
        "triage": rung_identity(tiers.triage),
        "extract_rungs": [rung_identity(c) for c in tiers.extract_rungs],
    }


def _numeric(value: Any) -> bool:
    """True for a real number. ``bool`` is excluded: it is not a distribution."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def spread_over(metric_dicts: list[dict[str, Any]]) -> dict[str, dict]:
    """Per metric, the shape of what N repeats actually produced.

    **Every figure here was observed.** ``median_low`` rather than ``median``,
    because ``median`` averages the two middle values on an even count and so
    reports a number no repeat produced. No mean and no standard deviation: a
    stdev over five samples reads as a statistic without being one, and the
    whole reason step 6 demands repeats is that a single figure was going to be
    read as more than it was. The raw values are in the file, so anyone who
    wants another summary can compute it and say so.

    **Keys are derived from the inputs**, never enumerated here. The key set
    is the union over every input dict -- the shape ``field_accuracy`` already
    takes with ``pred.keys() | tru.keys()``, and for the same reason: a key
    only one side reported must not vanish. A key in that union is reported
    when some repeat gave it a number, or when every repeat gave it ``None``,
    and only then.

    Nulls are counted, never folded in as zero. ``auto_approval_precision`` is
    ``None`` when nothing was auto-approved, and a ratio over no paths is
    undefined rather than bad.
    """
    keys: list[str] = []
    for d in metric_dicts:
        for k in d:
            if k not in keys:
                keys.append(k)

    out: dict[str, dict] = {}
    for key in keys:
        raw = [d.get(key) for d in metric_dicts]
        observed = [v for v in raw if _numeric(v)]
        if not observed and not all(v is None for v in raw):
            # Nothing numeric, and not every value null: not a distribution at
            # all, so the key is dropped. An all-null metric is the *other*
            # case and is reported -- with null figures, never with zeroes.
            continue
        out[key] = {
            "min": min(observed) if observed else None,
            "max": max(observed) if observed else None,
            "median": statistics.median_low(observed) if observed else None,
            "n": len(observed),
            "n_null": sum(1 for v in raw if v is None),
            "values": raw,
        }
    return out


def _report_metrics(report: Any) -> dict[str, Any]:
    """The numeric surface of one report, derived from the report itself.

    Reads the same dictionary the results file is built from, so no list of
    metric names lives here. What reaches the spread is ``spread_over``'s rule,
    not this function's.
    """
    return dict(_report_to_dict(report).get("metrics", {}))


def _report_counts(report: Any) -> dict[str, Any]:
    """The count block of one report, on ``_report_metrics``'s rule.

    The keys are ``_report_to_dict``'s, read from it rather than re-listed
    here, so this block and the file each repeat writes cannot fall out of step,
    and no list of key names -- and no count of them -- lives here to age.
    """
    return dict(_report_to_dict(report).get("counts", {}))


#: How many times the rewrite tries the atomic route before giving up on it.
#: The holders that refuse a rename on Windows -- a scanner reading the file
#: just written, an indexer, an editor -- let go in milliseconds, so a couple of
#: retries converts most of them into a normal atomic write; a run that waits
#: longer than that is paying for durability with time it does not have.
_RENAME_ATTEMPTS = 3

#: Seconds before the second attempt; the third waits twice this.
_RENAME_BACKOFF_S = 0.05


def _rewrite_aggregate(run_dir: Path, payload: str) -> None:
    """Put ``payload`` in ``<run_dir>/aggregate.json``, atomically where it can.

    The file is written beside its destination and renamed over it, so a reader
    sees the previous aggregate or the new one and never a half-written file --
    ``write_text`` truncates before it writes, and this rewrite happens once per
    repeat rather than once per run.

    **The atomicity is the bonus and must never be the cost.** ``Path.replace``
    onto a destination another handle holds open raises ``PermissionError`` on
    Windows -- measured on this machine, from nothing more than a reader with
    the file open -- while ``write_text`` onto that same destination, under that
    same handle, succeeds. Raised out of the loop that failure would abort the
    run *and* burn the run id, which :func:`prepare_run_dir` refuses to reuse,
    for the sake of a window a kill has to land inside. So a rename that will
    not go through degrades to writing in place, and **no ``OSError`` from the
    staging write, the rename or the in-place write escapes**.

    That is the whole of the claim, and it is deliberately narrower than "no
    path here raises". ``KeyboardInterrupt`` is not an ``OSError`` and escapes
    from anywhere --
    ``test_the_aggregate_is_staged_beside_its_destination_and_renamed_over_it``
    stops the process between the staging write and the rename and relies on it
    doing so -- and a ``BrokenPipeError`` from one of the diagnostic prints in
    the handlers below is an ``OSError`` no handler here covers.

    The staging file does not survive either path. A process killed between the
    staging write and the rename can leave one, and a killed process cleans
    nothing up in any design; what it does leave behind is a destination that
    still parses.
    """
    target = run_dir / "aggregate.json"
    pending = run_dir / "aggregate.json.tmp"
    try:
        pending.write_text(payload, encoding="utf-8")
        for attempt in range(1, _RENAME_ATTEMPTS + 1):
            try:
                pending.replace(target)
                return
            except OSError as exc:
                if attempt == _RENAME_ATTEMPTS:
                    print(
                        f"Could not rename {pending.name} over {target.name} "
                        f"({type(exc).__name__}: {exc}). Writing the aggregate "
                        f"in place instead, which is not atomic.",
                        file=sys.stderr,
                    )
                    break
                time.sleep(_RENAME_BACKOFF_S * attempt)
        target.write_text(payload, encoding="utf-8")
    except OSError as exc:
        # Not a raise: every completed repeat's own results file is already on
        # disk and the remaining repeats are still worth running. The aggregate
        # is the thing that degraded, and saying so is what keeps that from
        # being a silent drop.
        print(
            f"Could not write {target} ({type(exc).__name__}: {exc}). This "
            f"run's aggregate is missing or stale; each repeat's own results "
            f"file is unaffected.",
            file=sys.stderr,
        )

    try:
        pending.unlink(missing_ok=True)
    except OSError as exc:
        print(
            f"Could not remove {pending} ({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )


def run_repeats(
    run_id: str,
    repeats: int,
    *,
    golden_dir: Path | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    """Run the baseline ``repeats`` times and write one aggregate artifact.

    Each repeat gets its own ``results_dir`` under ``<run_dir>/repeat-NN``,
    which is what stops ``{date}-{prompt_version}.json`` from colliding. The
    aggregate is rewritten after **every** repeat, not once at the end: the
    per-rung counts and five of the config block's six keys are in no results
    file, so a sequence killed part way through would otherwise lose exactly
    what this artifact exists to carry.

    ``n_repeats`` is the number of entries the file actually holds, never the
    number asked for, so the artifact cannot claim a repeat it does not carry.
    ``n_repeats_requested`` is the target; the two disagree exactly when a run
    was interrupted, which is how a reader tells one apart from a complete run
    of the smaller size.

    ``n_failed`` counts failed **receipts**, summed over the repeats the file
    holds -- the same thing ``repeats[i].counts.failed`` counts, on the same
    rule, hoisted to the top level because that is where a headline is read.
    Measured on the committed tree before it existed: a run whose every extract
    call raised wrote ``spread.critical_field_accuracy = {"min": 0.0, "max":
    0.0, ...}``, and the command printed only ``Wrote <path>`` and
    ``Repeats: 2``. The failure signal was real and two levels down.

    ``spread_omitted`` names the metric keys the repeats carried that the
    spread has no entry for. It is derived by subtracting one from the other,
    never by restating :func:`spread_over`'s rule -- a second copy of that rule
    is one that can drift. It is empty today and is not decoration: a metric
    whose value is non-numeric in every repeat gets no entry at all, with no
    ``n``, no ``n_null`` and no ``values`` to say it was ever there, and
    ``cost_per_receipt`` reaches this block as ``str(Decimal)`` -- measured,
    ``_report_to_dict`` stringifies it -- the day a run measures a cost.

    ``scored_receipts`` names the receipts the run covered: the sorted union
    of ``receipt_id`` over the repeats the file holds. A clone can hold fewer
    labels than the machine that ran the eval -- ``p``-prefixed labels under
    ``eval/golden/labels/`` are gitignored -- so two aggregates can carry
    different numbers over different receipts with nothing in either file
    saying so. A list rather than a count of the private ones, because a
    count would be a second copy of the naming rule and a second copy of a
    rule is one that can drift.

    Both ``make_pass_clients`` and ``run_baseline`` are reached **through the
    ``eval.run_baseline`` module** rather than imported by name here. That is
    load-bearing for the first of them: ``run_baseline`` looks
    ``make_pass_clients`` up in its own module globals, so a name imported into
    *this* module would be a second binding that a
    ``monkeypatch.setattr("eval.run_baseline.make_pass_clients", ...)`` never
    reaches -- the config block below would call the real factory and describe a
    ladder no repeat ran. ``run_baseline`` is reached the same way so there is
    one rule here rather than two.
    """
    if repeats < 1:
        # Before the run directory is created: `prepare_run_dir` refuses an id
        # it has already seen, so claiming one for a run of nothing would burn
        # the id the real run wanted.
        raise ValueError(f"repeats must be at least 1, got {repeats}")

    root = Path(results_root) if results_root is not None else DEFAULT_RESULTS_DIR
    run_dir = prepare_run_dir(root, run_id)
    settings = get_settings()
    # For the config block only. `run_baseline` builds its own clients on every
    # call, and must: its one client parameter is `client=`, whose branch is
    # deliberately a single rung serving every pass
    # (tests/test_run_baseline.py::test_an_injected_client_gets_no_ladder), so
    # feeding these forward would disable the ladder silently.
    tiers = _baseline.make_pass_clients(settings)

    config = config_identity(tiers, settings)
    entries: list[dict[str, Any]] = []
    scored: set[str] = set()
    aggregate: dict[str, Any] = {}

    for index in range(1, repeats + 1):
        target = repeat_dir(run_dir, index)
        report = _baseline.run_baseline(golden_dir=golden_dir, results_dir=target)
        # Which receipts this number is over. A clone can hold fewer labels
        # than the machine that ran it -- `eval/golden/labels/p*.json` is
        # gitignored -- so a total alone does not say what was covered.
        # Accumulated across repeats rather than read off one: `run_eval` globs
        # the labels directory afresh on every repeat, so a label that appears
        # or disappears mid-run leaves two repeats covering different receipts,
        # and the union is what the run as a whole reached. A receipt is here
        # even when nothing was read from it: one `except` in `run_eval` covers
        # a label that would not read or validate, a pipeline call that raised
        # and a scoring error alike, and it records an `EvalResult` carrying
        # the id on every one of them. The same rule as `n_receipts`, where
        # nothing silently leaves the batch -- so this key names what the run
        # was run over, not what succeeded. `n_failed` is the other question.
        scored.update(r.receipt_id for r in report.results)

        written = sorted(target.glob("*.json"))
        entries.append({
            "index": index,
            "results_file": (
                written[0].relative_to(run_dir).as_posix() if written else None
            ),
            "counts": _report_counts(report),
            "metrics": _report_metrics(report),
            "extract_rung_counts": report.extract_rung_counts,
            "failures": [list(f) for f in report.failures],
        })

        spread = spread_over([e["metrics"] for e in entries])
        aggregate = {
            "run_id": run_id,
            "n_repeats": len(entries),
            "n_repeats_requested": repeats,
            "n_failed": sum(e["counts"].get("failed", 0) for e in entries),
            "config": config,
            "repeats": entries,
            "spread": spread,
            "spread_omitted": sorted(
                {k for e in entries for k in e["metrics"]} - set(spread)
            ),
            "scored_receipts": sorted(scored),
        }
        # Serialized here and persisted there: a file system that will not take
        # the write is a condition of the machine the run is on and must not
        # cost the run. ``default=str`` makes the same trade one step earlier --
        # a value this module cannot encode is stringified rather than raised
        # over, so no multi-hour run is lost to one unserializable field. It is
        # not free, and ``spread_omitted`` above is what keeps it from being
        # silent: a stringified number is not numeric, so ``spread_over`` gives
        # that key no entry.
        _rewrite_aggregate(run_dir, json.dumps(aggregate, indent=2, default=str))

    return aggregate


def _announce_partial(aggregate_path: Path) -> None:
    """Name the aggregate a killed run left behind, when there is one.

    :func:`run_repeats` rewrites the aggregate **inside** the repeat loop for
    exactly this case: an interrupted sequence keeps the per-rung counts and
    the config block, which no results file holds. That artifact is invisible
    from the terminal otherwise, and it cannot be reached by re-running --
    :func:`prepare_run_dir` refuses a run id it has already seen, so the id is
    burnt the moment the run started.

    Silent when the file is absent, because every refusal that fires before a
    repeat completes reaches this too, and there is nothing to name.
    """
    if not aggregate_path.is_file():
        return
    try:
        partial = json.loads(aggregate_path.read_text(encoding="utf-8"))
        held, asked = partial["n_repeats"], partial["n_repeats_requested"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Named anyway. A file this function cannot parse is still the only
        # copy of that run's provenance, and "there is something here I could
        # not read" beats saying nothing at all.
        print(
            f"A partial aggregate is at {aggregate_path}, and how much it "
            f"holds could not be read back ({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )
        return
    print(
        f"A partial aggregate is at {aggregate_path}: {held} of {asked} "
        f"repeat(s), carrying each completed repeat's rung counts and the "
        f"config block, which no results file holds. The run id cannot be "
        f"reused -- name the next run something else.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Both identifying arguments are required.

    A reused ``--run-id`` is a clean message and a non-zero exit, not a
    ``FileExistsError`` traceback -- the shape ``eval.run_baseline.main``
    already gives a refusal. Returning the code rather than raising
    ``SystemExit`` is ``receipts.cli.main``'s shape and is for its stated
    reason: a test can then assert on the code, and the ``__main__`` guard
    below is what actually exits.

    **Nothing is announced that was not found on disk.** The success line names
    a path assembled here from the same results root, run id and file name that
    :func:`run_repeats` and :func:`_rewrite_aggregate` assemble it from between
    them, so it is a second statement of that layout; it is checked against the
    file system before it is printed, which is what stops the second statement
    from drifting into a false one. :func:`_rewrite_aggregate` deliberately does
    not raise when the file system refuses the write, so "the call returned" is
    not evidence that the artifact exists -- and a command that reports success
    while producing no artifact is the failure this module was written to
    remove.

    **A run that scored no receipt is refused too**, and that is a third
    refusal rather than a variant of the second: the run completed and the
    aggregate is on disk and well formed. What makes it worthless is that a
    zero-receipt repeat reports its accuracy figures as `0.0` rather than null,
    so the file reads as a measured zero. The predicate is *every* repeat, not
    *any*, because a mixed run is the worse artifact of the two.

    **A run that died part way through names what it left behind.** The
    aggregate is rewritten inside the repeat loop precisely so a killed
    sequence keeps the rung counts and the config block no results file holds,
    and the operator cannot re-run into that run id --
    :func:`prepare_run_dir` refuses to reuse one -- so a handler that said only
    "the run failed" would strand the artifact it exists to protect.
    """
    # Raw, because the description *is* the module docstring and its last line
    # is the command this module advertises. The default formatter reflows the
    # whole thing into one paragraph and wraps that command mid-line, so what
    # ``--help`` shows an operator cannot be copied and run -- measured.
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True,
                        help="names this run's directory; must not already exist")
    parser.add_argument("--repeats", type=int, required=True,
                        help="how many times to run the golden set")
    parser.add_argument("--golden-dir", type=Path, default=None)
    parser.add_argument("--results-root", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.results_root if args.results_root is not None else DEFAULT_RESULTS_DIR
    written = Path(root) / args.run_id / "aggregate.json"

    try:
        aggregate = run_repeats(
            args.run_id,
            args.repeats,
            golden_dir=args.golden_dir,
            results_root=args.results_root,
        )
    except FileExistsError:
        print(
            f"Run id {args.run_id!r} already has a directory. Runs are never "
            f"overwritten -- choose another --run-id.",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError) as exc:
        # The common provider-failure path: a throttle or a dropped connection
        # reaches here as a `RuntimeError`. Naming the partial artifact is the
        # whole difference between an interrupted run and a lost one.
        print(f"Cannot run repeats: {exc}", file=sys.stderr)
        _announce_partial(written)
        return 1

    if not written.is_file():
        print(
            f"Ran {aggregate['n_repeats']} repeat(s), but {written} is not "
            f"there. Each repeat's own results file is unaffected; the "
            f"aggregate is what is missing.",
            file=sys.stderr,
        )
        return 1

    # Every repeat, not merely one of them. A repeat that scored nothing does
    # not report null metrics: `_build_report` computes the accuracy figures
    # inline as `(x / n) if n else 0.0` (`eval/harness.py`), so a zero-receipt
    # repeat contributes a numeric `0.0`. It enters the spread as an observed
    # zero and drags `min` and `median` down. Measured: one real repeat at 0.55
    # beside one empty repeat gives `median: 0.0`. Refusing only when *no*
    # repeat scored would let exactly that artifact through.
    empty = [e["index"] for e in aggregate["repeats"] if not e["counts"].get("receipts")]
    if empty:
        # Read through `_baseline` rather than imported here, on this module's
        # existing rule for that module: `run_baseline` resolves a `None`
        # golden dir against its own global, so this names the directory that
        # actually ran instead of a second binding that could differ from it.
        golden = args.golden_dir if args.golden_dir is not None else _baseline.GOLDEN_DIR
        print(
            f"Repeat(s) {', '.join(str(i) for i in empty)} of "
            f"{aggregate['n_repeats']} scored no receipts against {golden}. "
            f"An aggregate over zero receipts is well formed and worthless -- "
            f"its accuracy figures are 0.0, not null, so it reads as a "
            f"measured zero. Check --golden-dir. {written} was written and is "
            f"not a baseline.",
            file=sys.stderr,
        )
        return 1

    print(f"Wrote {written}")
    print(f"Repeats: {aggregate['n_repeats']}")
    # Derived from what was written, not recomputed from the run: this is the
    # block a reader quotes, and until now an every-receipt-failed run printed
    # exactly the two lines above and nothing else -- measured end to end, with
    # `spread.critical_field_accuracy` at 0.0 and exit code 0. Not refusing
    # such a run stays correct; an all-failed run is an observation. Being
    # unable to see it from here was the defect.
    scored = sum(e["counts"].get("receipts", 0) for e in aggregate["repeats"])
    if aggregate["n_failed"]:
        print(
            f"Failed receipts: {aggregate['n_failed']} of {scored} across "
            f"{aggregate['n_repeats']} repeat(s). A failed receipt is counted "
            f"in n_receipts and scores zero, so it is already inside every "
            f"figure in `spread` -- read repeats[i].failures before quoting "
            f"one."
        )
    else:
        print(
            f"Failed receipts: none, over {scored} receipt(s) in "
            f"{aggregate['n_repeats']} repeat(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
