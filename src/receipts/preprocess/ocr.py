"""An independent text layer, read off the same pixels the model was shown.

R060 and R061 check an extraction against ``ctx.ocr_text``. **Nothing ever
produced it.** Measured 2026-08-25: `ocr_text` was declared in
`validate/context.py`, read by those two rules, and written in exactly two test
files -- nowhere in `src/` or `eval/`. So both rules' ``applies()`` returned
False on every receipt this system has ever processed, and
:mod:`receipts.validate.validator` makes a skipped rule indistinguishable from a
passing one: two rules that read as coverage and were inert. This module is the
source they were written against (IMPLEMENTATION_PLAN P2.T2).

**Independence is the entire point, and it is why the cheap option was refused.**
The 2026-08-23 ruling rejected asking the extraction model to return the text it
read, because a model's own transcription is not independent of its own misread
-- it would agree with a hallucinated total as readily as with a real one.
R060's value is that a *second* reader, which never saw the schema or the
prompt, disagrees.

**The engine is imported inside the function**, for the reason
:func:`~receipts.ingest.ingest.expand_pdf` documents: it belongs to an optional
extra, and a module-top import would make every importer of this package --
`receipts.cli`, and so `receipts users list` -- require it.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

__all__ = ["OcrLayer", "OcrWord", "read_text_layer"]


@dataclass(frozen=True)
class OcrWord:
    """One recognised span, with where it sits on the image.

    ``bbox`` is ``(x0, y0, x1, y1)`` **normalised to 0-1** and axis-aligned,
    matching `LineItem.bbox`'s declared convention so the two can be compared
    without either side knowing the other's pixel dimensions. The engine returns
    a four-point polygon; this is its bounding box, which loses rotation and is
    what a highlight rectangle needs anyway (P5.T1).
    """

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class OcrLayer:
    """What a second reader saw. ``text`` is what R060/R061 consult.

    ``words`` carries the coordinates P5.T1's bounding-box highlighting needs and
    that nothing else in this system produces. Nothing reads it yet; it is here
    because the pass that yields the text yields the boxes for free, and running
    OCR twice to get them separately would be the expensive mistake.
    """

    text: str
    words: tuple[OcrWord, ...] = field(default_factory=tuple)


def _engine():
    """The recogniser, built once per process.

    Construction measured at ~1.2s on this box against ~1.0s for an inference,
    so building one per receipt would roughly double the cost of the pass for
    nothing. Cached on the function rather than at module import because
    importing this module must stay free for callers that never OCR anything.
    """
    if not hasattr(_engine, "_cached"):
        from rapidocr_onnxruntime import RapidOCR

        _engine._cached = RapidOCR()
    return _engine._cached


def read_text_layer(image_bytes: bytes) -> OcrLayer:
    """Read ``image_bytes`` with an engine that never saw the prompt or schema.

    Returns an empty layer when the engine recognises nothing -- a blank page, or
    a photograph too poor to read. **Empty is a real answer and not an error:**
    R060 and R061 both gate on ``bool(ctx.ocr_text)``, so an empty layer leaves
    them skipping exactly as they did before this module existed, rather than
    reporting that every field was hallucinated.

    Raises nothing of its own. The caller decides what a failed pass costs; on
    the pipeline path it costs the grounding rules and not the receipt.
    """
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
    if not width or not height:
        return OcrLayer(text="")

    result, _elapsed = _engine()(image_bytes)
    if not result:
        return OcrLayer(text="")

    words: list[OcrWord] = []
    for polygon, text, confidence in result:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        words.append(
            OcrWord(
                text=str(text),
                bbox=(
                    _unit(min(xs) / width),
                    _unit(min(ys) / height),
                    _unit(max(xs) / width),
                    _unit(max(ys) / height),
                ),
                # The engine hands confidence back as a STRING. Measured, not
                # assumed: `'0.8493462984378521'`. A float() on it is the whole
                # conversion, and a malformed one costs the score and not the
                # word.
                confidence=_as_float(confidence),
            )
        )

    # Joined in the engine's own order rather than re-sorted top-to-bottom.
    # Neither consumer cares -- R060 compares digit sequences and R061 compares
    # a token SET -- and imposing a reading order would be a decision about
    # multi-column receipts that nothing here has measured.
    return OcrLayer(text="\n".join(word.text for word in words), words=tuple(words))


def read_prepared(b64: str) -> OcrLayer:
    """:func:`read_text_layer` over a :class:`PreparedImage`'s base64 payload.

    The pipeline holds the image as base64 because that is what a model call
    wants. Reading the *prepared* pixels rather than the original is deliberate:
    the grounding rules are asking whether the model could have read what it
    claims, so the second reader should be shown what the model was shown.
    """
    return read_text_layer(base64.b64decode(b64))


def _unit(value: float) -> float:
    """Clamp to 0-1. A polygon can sit a pixel outside the frame."""
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("OCR returned a non-numeric confidence %r; recording 0.0", value)
        return 0.0
