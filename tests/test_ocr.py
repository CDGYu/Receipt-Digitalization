"""The independent text layer (P2.T2).

Two kinds of test here, deliberately separated:

  * **The adapter**, driven with a canned engine result. These run offline and
    with no optional extra installed, and they are what pin the conversion --
    polygon to axis-aligned box, pixels to 0-1, and the confidence the engine
    hands back as a *string*.
  * **One end-to-end read**, which needs the real recogniser and skips without
    it. A green adapter suite is not evidence that an engine was ever called,
    and this repository has twice shipped something a green suite certified and
    a runtime broke.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from receipts.preprocess import ocr as ocr_module  # noqa: E402
from receipts.preprocess.ocr import OcrLayer, read_text_layer  # noqa: E402


def _png(width: int = 400, height: int = 200, text: tuple[str, ...] = ()) -> bytes:
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(text):
        draw.text((20, 30 + index * 60), line, fill=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _canned(result):
    """Stand in for the recogniser. It returns ``(result, elapsed)``."""

    def _engine():
        return lambda _image_bytes: (result, 0.0)

    return _engine


# --------------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------------- #


def test_a_polygon_in_pixels_becomes_an_axis_aligned_box_in_0_to_1(monkeypatch):
    """`LineItem.bbox` is declared normalised 0-1, so this must match it.

    The engine answers in pixels with a four-point polygon. Normalising here is
    what lets a word box and a line-item box be compared without either side
    knowing the other's dimensions.
    """
    monkeypatch.setattr(
        ocr_module,
        "_engine",
        _canned(
            [[[[40.0, 20.0], [200.0, 20.0], [200.0, 60.0], [40.0, 60.0]], "TOTAL", "0.9"]]
        ),
    )

    layer = read_text_layer(_png(width=400, height=200))

    (word,) = layer.words
    assert word.text == "TOTAL"
    assert word.bbox == (0.1, 0.1, 0.5, 0.3)


def test_the_confidence_the_engine_returns_as_a_string_becomes_a_float(monkeypatch):
    """Measured, not assumed: the engine hands back `'0.8493462984378521'`."""
    monkeypatch.setattr(
        ocr_module,
        "_engine",
        _canned(
            [[[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]], "X", "0.8493462984378521"]]
        ),
    )

    (word,) = read_text_layer(_png()).words

    assert isinstance(word.confidence, float)
    assert word.confidence == pytest.approx(0.849346, abs=1e-6)


def test_an_unparseable_confidence_costs_the_score_and_not_the_word(monkeypatch):
    """A word that was read is still a word, whatever its score parsed as."""
    monkeypatch.setattr(
        ocr_module,
        "_engine",
        _canned([[[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]], "KEPT", None]]),
    )

    (word,) = read_text_layer(_png()).words

    assert word.text == "KEPT"
    assert word.confidence == 0.0


def test_a_box_outside_the_frame_is_clamped(monkeypatch):
    """A polygon can sit a pixel outside the image. 0-1 must stay 0-1."""
    monkeypatch.setattr(
        ocr_module,
        "_engine",
        _canned([[[[-5.0, -5.0], [999.0, -5.0], [999.0, 999.0], [-5.0, 999.0]], "EDGE", "0.5"]]),
    )

    (word,) = read_text_layer(_png(width=400, height=200)).words

    assert word.bbox == (0.0, 0.0, 1.0, 1.0)


def test_recognising_nothing_is_an_empty_layer_and_not_an_error(monkeypatch):
    """**Empty is a real answer.**

    R060 and R061 both gate on `bool(ctx.ocr_text)`, so an empty layer leaves
    them skipping exactly as they did before this module existed -- rather than
    reporting that every field on a blank or illegible page was hallucinated.
    """
    monkeypatch.setattr(ocr_module, "_engine", _canned([]))

    layer = read_text_layer(_png())

    assert layer == OcrLayer(text="")
    assert not layer.text


def test_the_text_is_every_span_the_engine_read(monkeypatch):
    """What R060 and R061 actually consult."""
    monkeypatch.setattr(
        ocr_module,
        "_engine",
        _canned(
            [
                [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]], "SUPERMART", "0.9"],
                [[[0.0, 20.0], [10.0, 20.0], [10.0, 30.0], [0.0, 30.0]], "949.20", "0.9"],
            ]
        ),
    )

    layer = read_text_layer(_png())

    assert layer.text == "SUPERMART\n949.20"
    assert len(layer.words) == 2


# --------------------------------------------------------------------------- #
# The real engine
# --------------------------------------------------------------------------- #


def test_a_real_engine_reads_a_total_off_a_rendered_receipt():
    """The one test that proves an engine was called at all.

    Asserts on the DIGITS rather than on a string, because that is what R060
    compares and because OCR gets characters wrong -- measured on this fixture,
    the same engine reads "SUPERMART INC." as "SUPERMARTTNC". The total is the
    field R060 grounds and the one that has to survive.
    """
    pytest.importorskip("rapidocr_onnxruntime")

    layer = read_text_layer(
        _png(width=480, height=240, text=("SUPERMART INC.", "TOTAL      949.20"))
    )

    digits = "".join(character for character in layer.text if character.isdigit())
    assert "94920" in digits
    assert layer.words
    assert all(0.0 <= value <= 1.0 for word in layer.words for value in word.bbox)
