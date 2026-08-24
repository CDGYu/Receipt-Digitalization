"""Golden-set on-ramp (spec §15 M0).

The golden set is the highest-value artefact in the project: every later
decision — model choice, prompt wording, confidence threshold — is tuned against
it. This module is the *scaffolding* a human uses to drop in hand-labelled
receipts and immediately learn two things:

  1. Are my labels schema-valid? (:func:`validate_labels`)
  2. Is my set the right size and mix? (:func:`composition_stats`)

The actual receipts and labels are produced by a human. Nothing here touches the
network, and — mirroring the validator's contract — the functions are pure,
deterministic, and never mutate their inputs. :func:`validate_labels` and
:func:`composition_stats` additionally never raise on a malformed file: the
whole point is to *report* problems, not blow up on them.

Layout (``eval/golden/``)::

    labels/{id}.json     one hand-label per receipt, matching TEMPLATE.json
    images/              the source photos (git-ignored — receipts hold PII)
    manifest.json        id -> {"category": ..., "holdout": bool} sidecar
    TEMPLATE.json        a schema-valid worked example to copy
"""

from __future__ import annotations

import json
from pathlib import Path

from receipts.extract.schema import ReceiptExtraction

# --------------------------------------------------------------------------- #
# Well-known locations (mirrors harness.DEFAULT_RESULTS_DIR style)
# --------------------------------------------------------------------------- #

#: ``eval/golden/`` — where Milestone 0 lives.
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: The committed, schema-valid example a labeller copies for each new receipt.
TEMPLATE_PATH = GOLDEN_DIR / "TEMPLATE.json"

#: Default label and manifest locations under :data:`GOLDEN_DIR`.
DEFAULT_LABELS_DIR = GOLDEN_DIR / "labels"
DEFAULT_MANIFEST_PATH = GOLDEN_DIR / "manifest.json"

#: M0 composition targets (spec §15). Fractions of the whole set, except
#: ``holdout`` which is an inclusive range expressed as a string so it reads
#: unambiguously in the printed stats.
COMPOSITION_TARGETS: dict[str, float | str] = {
    "printed_clean": 0.60,
    "printed_degraded": 0.15,
    "handwritten": 0.20,
    "adversarial": 0.05,
    "holdout": "0.20-0.30",
}

#: The set is not decision-grade below this many receipts (spec §15: 50–100).
MINIMUM_RECEIPTS = 50


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #


def _is_label_file(path: Path) -> bool:
    """True for a receipt label, False for the template or a manifest sidecar.

    ``TEMPLATE.json`` is the worked example and ``manifest*.json`` is the
    category/holdout sidecar — neither is a receipt label.
    """
    name = path.name
    return name != "TEMPLATE.json" and not name.startswith("manifest")


def _label_files(labels_dir: Path) -> list[Path]:
    """Every label file under ``labels_dir``, sorted for determinism.

    A missing directory yields an empty list — :meth:`Path.glob` does not raise
    on a non-existent directory, so callers stay exception-free.
    """
    return sorted(p for p in labels_dir.glob("*.json") if _is_label_file(p))


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #


class PrivateLabelError(ValueError):
    """A ``p*`` label failed to load, reported without its contents.

    Subclasses :class:`ValueError` because that is what
    :class:`pydantic.ValidationError` already is, so a caller writing
    ``except ValueError`` is unaffected by the redaction. Nothing in the tree
    catches ``ValidationError`` by name.
    """


def _is_private_label(path: Path) -> bool:
    """True for a label whose contents may never be shown or committed.

    ADR-0050 makes the ``p`` prefix the privacy decision, and ``.gitignore``
    carries ``eval/golden/labels/p*.json``. This reads the *same* prefix, so
    the redaction boundary and the commit boundary cannot drift apart into two
    rules that disagree. A public label misnamed ``printed_003.json`` is
    redacted too, which is the harmless direction to be wrong in.
    """
    return path.name.startswith("p")


def _redacted_reason(exc: Exception) -> str:
    """Describe a failure using only the field path and the error kind.

    **Never derives a single character from the file's contents**, and that is
    the whole property. Pydantic renders the offending value as ``input_value=``
    (measured 2026-08-25: a tax id typed without quotes reached the terminal
    verbatim), and a JSON syntax error echoes a truncated window of the raw
    bytes instead -- so an unredacted message leaks in two different shapes.

    ``msg`` is dropped rather than kept, even though today's messages happen to
    be value-free. A custom validator raising ``ValueError(f"bad {value}")``
    renders that value into ``msg``, so keeping it would make the guarantee a
    standing audit of every validator anyone adds later. Emitting only ``loc``
    and ``type`` holds by construction instead. The cost is real: the parser's
    "trailing comma at line 1 column 51" is safe and useful, and it is lost. A
    labeller who needs it can validate a copy with the values stripped.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return f"{type(exc).__name__} (detail redacted)"
    try:
        details = errors(include_url=False, include_input=False, include_context=False)
    except TypeError:  # pragma: no cover - older pydantic without the keywords
        details = errors()
    fields = [
        f"{'.'.join(str(part) for part in item.get('loc', ())) or '<root>'}"
        f" [{item.get('type', 'unknown')}]"
        for item in details
    ]
    return f"{len(fields)} validation error(s), values redacted: " + "; ".join(fields)


def load_labels(labels_dir: Path) -> dict[str, ReceiptExtraction]:
    """Load every label under ``labels_dir`` keyed by filename stem.

    The template and manifest sidecars are skipped. Each remaining ``*.json`` is
    parsed with :meth:`ReceiptExtraction.model_validate_json`; a malformed or
    unreadable file raises here on purpose — this is the strict loader. Use
    :func:`validate_labels` for the forgiving, report-only variant.

    **The error names the file it choked on**, as a note on the exception rather
    than a new type, so callers catching the original type still do. Pinned by
    ``tests/test_golden_set.py::test_a_label_that_will_not_load_names_itself``,
    which asserts on the rendered traceback rather than on the mechanism.
    """
    labels: dict[str, ReceiptExtraction] = {}
    for path in _label_files(labels_dir):
        try:
            labels[path.stem] = ReceiptExtraction.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            # A private label is reported without its contents; see ADR-0050.
            #
            # ``from None`` is load-bearing, not tidiness. Raising inside an
            # ``except`` sets ``__context__``, and a rendered traceback prints
            # the chained exception's message in full -- so a wrapped error
            # that omits the value still shows it under "During handling of the
            # above exception". Suppressing the context is what actually
            # removes it, and
            # ``test_load_labels_does_not_echo_a_private_labels_value``
            # asserts on the rendered traceback precisely so that dropping
            # ``from None`` here goes red.
            if _is_private_label(path):
                raise PrivateLabelError(
                    f"{_redacted_reason(exc)} while loading golden label {path.name}"
                ) from None

            # Name the file, then let the error out untouched.
            #
            # **This is not the handler ISSUE-021 deleted.** That one swallowed
            # and returned ``{}``; this one adds the single thing the error was
            # missing and re-raises. ``path`` is a loop local, so without it a
            # reader gets the file's *content* and this function's line number
            # and no filename at all -- measured, the name appeared zero times
            # in a whole pytest run (ISSUE-022). A note rather than a wrapped
            # exception, so the type every caller already sees is unchanged.
            exc.add_note(f"while loading golden label {path.name}")
            raise
    return labels


def validate_labels(labels_dir: Path) -> list[str]:
    """Return human-readable errors for labels that fail schema validation.

    An empty list means every label is valid. Never raises: a malformed or
    schema-invalid file becomes an ``"{filename}: {reason}"`` entry rather than
    an exception, so a single bad label cannot hide the health of the rest.
    Entries are ordered by filename for a stable, diff-friendly report.
    """
    errors: list[str] = []
    for path in _label_files(labels_dir):
        try:
            ReceiptExtraction.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report every failure, never raise
            # This list is printed to a terminal by the documented labelling
            # procedure (eval/golden/README.md, and Task 3 steps 1 and 3 of the
            # growing-the-golden-set plan), which makes it the higher-traffic
            # of the two leak surfaces -- a labeller runs it after every batch.
            if _is_private_label(path):
                reason = _redacted_reason(exc)
            else:
                reason = " ".join(str(exc).split())
            errors.append(f"{path.name}: {reason}")
    return errors


def load_manifest(manifest_path: Path) -> dict[str, dict]:
    """Load the id -> metadata sidecar, or ``{}`` when it is absent.

    A present-but-non-object manifest also collapses to ``{}`` so downstream
    counting stays simple, and a malformed or unreadable file does the same --
    this stays a report-only helper that never raises.
    """
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Report-only helper: a malformed or unreadable manifest collapses to
        # {} rather than raising out of composition_stats.
        return {}
    return data if isinstance(data, dict) else {}


def composition_stats(
    labels_dir: Path, manifest_path: Path | None = None
) -> dict:
    """Summarise the golden set's size and mix against the M0 targets.

    Returns::

        {
            "total": int,               # label files on disk
            "meets_minimum": bool,      # total >= MINIMUM_RECEIPTS (50)
            "by_category": {cat: n},    # from the manifest, for labels present
            "holdout_count": int,       # labels flagged holdout in the manifest
            "targets": COMPOSITION_TARGETS,
        }

    ``by_category`` and ``holdout_count`` are derived from the manifest and keyed
    to labels that actually exist on disk, so manifest rows for deleted receipts
    are ignored and the counts never exceed ``total``. With no manifest the
    breakdown is empty / zero — the size checks still work without one.
    """
    label_ids = [p.stem for p in _label_files(labels_dir)]
    total = len(label_ids)

    manifest = load_manifest(manifest_path) if manifest_path is not None else {}

    by_category: dict[str, int] = {}
    holdout_count = 0
    for label_id in label_ids:
        entry = manifest.get(label_id)
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        if isinstance(category, str):
            by_category[category] = by_category.get(category, 0) + 1
        if entry.get("holdout") is True:
            holdout_count += 1

    return {
        "total": total,
        "meets_minimum": total >= MINIMUM_RECEIPTS,
        "by_category": by_category,
        "holdout_count": holdout_count,
        "targets": dict(COMPOSITION_TARGETS),
    }
