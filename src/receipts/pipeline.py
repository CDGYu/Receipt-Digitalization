"""M1 straight-line pipeline runner (spec §15 M1).

Ties the existing stages into a single call: a receipt image goes through
preprocessing, triage, schema-constrained extraction (with an optional repair
loop), and safe normalization. Nothing here owns prompt text, validation rules,
or provider details -- it only *sequences* pieces that are each tested in
isolation. That is what lets the same runner drive a real hosted model or the
offline ``FakeVLMClient`` unchanged: it talks to the :class:`VLMClient`
interface only.

It also exposes :func:`build_eval_pipeline`, an adapter shaped to
:func:`eval.harness.run_eval`'s injected-pipeline contract -- the glue that lets
``receipts eval`` produce a real baseline once a provider and golden images
exist.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .extract.clients.base import VLMClient
from .extract.extractor import PreparedImage, extract_with_repair, triage
from .extract.schema import ReceiptExtraction
from .normalize import normalize
from .preprocess.image_ops import (
    fix_orientation,
    load_image,
    resize_for_model,
    to_base64,
    to_rgb,
)
from .validate.context import ValidationContext
from .validate.report import ValidationReport

#: Extensions the eval adapter searches, in order, to match a label by stem.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")


def prepare_image(image_path: Path, *, max_edge: int = 2048) -> PreparedImage:
    """Preprocess ``image_path`` into the :class:`PreparedImage` the extractor
    consumes.

    Pixels only, in order: open -> apply and strip EXIF orientation -> flatten
    to RGB -> fit the longest edge to ``max_edge`` -> JPEG base64. ``image_hash``
    is a digest of the transported bytes so a response cache (when one is later
    wired in) keys correctly; it is harmless when no cache is used.
    """
    image = load_image(Path(image_path))
    image = fix_orientation(image)
    image = to_rgb(image)
    image = resize_for_model(image, max_edge=max_edge)
    b64 = to_base64(image)
    image_hash = hashlib.sha256(b64.encode("ascii")).hexdigest()
    return PreparedImage(b64=b64, media_type="image/jpeg", image_hash=image_hash)


def run_receipt(
    image_path: Path,
    client: VLMClient,
    ctx: ValidationContext,
    *,
    max_attempts: int = 1,
) -> tuple[ReceiptExtraction, ValidationReport]:
    """Run one receipt end to end: preprocess -> triage -> extract(+repair) ->
    normalize.

    ``max_attempts`` is the total number of extraction attempts the model is
    given: the initial extract plus up to ``max_attempts - 1`` repair rounds, so
    the default of 1 is a single extract with no repair. Returns the normalized
    winning extraction paired with the validation report for that attempt (the
    report reflects what the model produced and the repair loop reasoned about;
    normalization is safe canonicalization applied on top).

    Works with any :class:`VLMClient` -- a real client from the factory or the
    offline ``FakeVLMClient``.
    """
    image = prepare_image(image_path)
    triage_result, _triage_response = triage(image, client)
    outcome = extract_with_repair(
        image,
        client,
        triage_result=triage_result,
        ctx=ctx,
        max_repairs=max(0, max_attempts - 1),
    )
    return normalize(outcome.extraction), outcome.report


def _find_image(images_dir: Path, stem: str, suffixes: tuple[str, ...]) -> Path | None:
    """First existing ``{stem}{suffix}`` under ``images_dir``, or ``None``."""
    for suffix in suffixes:
        candidate = images_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def build_eval_pipeline(
    client: VLMClient,
    ctx: ValidationContext,
    images_dir: Path,
    *,
    image_suffixes: tuple[str, ...] = DEFAULT_IMAGE_SUFFIXES,
) -> Callable[[Path], tuple[ReceiptExtraction, Decimal]]:
    """Adapt the runner to :func:`eval.harness.run_eval`'s ``PipelineFn``.

    Returns ``pipeline_fn(label_path)`` that locates the image whose stem matches
    the label file's stem under ``images_dir``, runs it through
    :func:`run_receipt`, and returns ``(extraction, confidence)``. A missing
    image raises a clear :class:`FileNotFoundError`.

    Confidence scoring does not exist yet (P3.T4 / M3), so this returns a
    PLACEHOLDER ``Decimal("1.0")``. Real confidence -- folding the validation
    report plus the triage and self-consistency signals into one score -- lands
    with the score module; swap it in here when it does.
    """
    images_dir = Path(images_dir)

    def pipeline_fn(label_path: Path) -> tuple[ReceiptExtraction, Decimal]:
        stem = Path(label_path).stem
        image_path = _find_image(images_dir, stem, image_suffixes)
        if image_path is None:
            raise FileNotFoundError(
                f"No image for label {stem!r} under {images_dir} "
                f"(tried suffixes: {', '.join(image_suffixes)})"
            )
        extraction, _report = run_receipt(image_path, client, ctx)
        # PLACEHOLDER confidence -- the real score arrives with the score module
        # (P3.T4 / M3), which will read _report + triage/consistency signals.
        return extraction, Decimal("1.0")

    return pipeline_fn
