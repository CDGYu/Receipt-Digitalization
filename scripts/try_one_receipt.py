"""Run ONE receipt end to end and show what the system produced.

A smoke test, not an eval: it answers "is the pipeline actually working against a
real model?" and shows the output stage by stage, so a failure is attributable to
a stage instead of to the whole run. `eval.run_baseline` is the real measurement
(spec §16) — this exists because a single call on a CPU-hosted model can take
minutes, and finding out which stage broke should not cost a full batch.

    python scripts/try_one_receipt.py            # defaults to r002
    python scripts/try_one_receipt.py r001       # the worst-legibility sample
    python scripts/try_one_receipt.py r001 --max-edge 1024   # faster, less legible

Every stage is timed and flushed as it completes, so progress is visible while a
slow call is still in flight. When a golden label exists for the receipt the
extraction is scored against it (the §16 metric-4 block, the critical-field gate,
line-item F1) — that is the closest thing to "did it get the receipt right".
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "eval" / "golden"

# Running a script puts *its own* directory on sys.path, not the repo root, so
# `config` and `eval` would not import. pyproject's `pythonpath` only applies to
# pytest. Add both roots here so this works from any cwd.
for _root in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _root not in sys.path:
        sys.path.insert(0, _root)


def _fmt(value: object) -> str:
    """Render a value for the summary, making null-ness obvious."""
    return "-" if value is None else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_id", nargs="?", default="r002")
    parser.add_argument(
        "--max-edge",
        type=int,
        default=None,
        help="downscale the longest edge (default: MAX_IMAGE_EDGE_PX from settings)",
    )
    parser.add_argument(
        "--repairs",
        type=int,
        default=0,
        help="repair rounds to allow after a failed validation (default 0)",
    )
    args = parser.parse_args()

    from config.settings import Settings
    from eval.metrics import critical_field_accuracy, field_accuracy, field_breakdown, line_item_f1
    from eval.run_baseline import format_breakdown
    from receipts.extract.clients.factory import make_client
    from receipts.extract.extractor import extract_with_repair, triage
    from receipts.extract.schema import ReceiptExtraction
    from receipts.normalize import normalize
    from receipts.pipeline import prepare_image
    from receipts.score.confidence import route, score_confidence
    from receipts.validate.context import ValidationContext
    from receipts.validate.validator import validate

    settings = Settings()
    max_edge = args.max_edge or settings.max_image_edge_px

    image = None
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
        candidate = GOLDEN / "images" / f"{args.receipt_id}{suffix}"
        if candidate.is_file():
            image = candidate
            break
    if image is None:
        print(f"No image for {args.receipt_id!r} under {GOLDEN / 'images'}", file=sys.stderr)
        return 1

    print("=" * 68)
    print(f"receipt   : {args.receipt_id}  ({image.name})")
    print(f"provider  : {settings.vlm_provider}  model={settings.vlm_model_extract}")
    print(f"endpoint  : {settings.vlm_base_url or '(provider default)'}")
    print(f"timeout   : {settings.vlm_timeout_s}s   max_edge={max_edge}")
    print(f"currency  : DEFAULT_CURRENCY={_fmt(settings.default_currency)}")
    print("=" * 68, flush=True)

    client = make_client(settings)
    ctx = ValidationContext()

    prepared = prepare_image(image, max_edge=max_edge)
    print(f"[prep ] {prepared.b64 and len(prepared.b64) * 3 // 4 // 1024}KB base64", flush=True)

    # --- pass 1: triage ---------------------------------------------------- #
    t0 = time.monotonic()
    try:
        triage_result, triage_resp = triage(prepared, client)
    except Exception as exc:
        print(f"[triage] FAILED after {time.monotonic() - t0:.0f}s: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"[triage] {time.monotonic() - t0:.0f}s  is_receipt={triage_result.is_receipt} "
        f"type={triage_result.document_type.value} print={triage_result.print_type.value} "
        f"legibility={triage_result.legibility.value} "
        f"est_items={triage_result.estimated_line_item_count}",
        flush=True,
    )
    print(
        f"         merchant_guess={_fmt(triage_result.merchant_name_guess)!r} "
        f"issues={triage_result.issues}",
        flush=True,
    )

    # --- pass 2 (+3): extract, validate, repair ---------------------------- #
    t0 = time.monotonic()
    try:
        outcome = extract_with_repair(
            prepared, client, triage_result=triage_result, ctx=ctx, max_repairs=args.repairs
        )
    except Exception as exc:
        print(f"[extract] FAILED after {time.monotonic() - t0:.0f}s: {type(exc).__name__}: {exc}")
        return 1
    print(f"[extract] {time.monotonic() - t0:.0f}s", flush=True)

    extraction = normalize(outcome.extraction, system_default_currency=settings.default_currency)
    report = validate(extraction, ctx)
    confidence = score_confidence(extraction, report, triage_result, consistency=None)
    status, priority, reason = route(confidence, report, extraction)

    # --- what the model actually read -------------------------------------- #
    t = extraction.totals
    print("\n" + "-" * 68)
    print("EXTRACTED")
    print("-" * 68)
    print(f"  merchant   : {_fmt(extraction.merchant.name)}")
    print(f"  tax_id     : {_fmt(extraction.merchant.tax_id)}")
    print(f"  invoice no : {_fmt(extraction.receipt.number)}")
    print(
        f"  date       : {_fmt(extraction.receipt.date)}   "
        f"raw={_fmt(extraction.receipt.date_raw)}"
    )
    print(f"  currency   : {_fmt(extraction.receipt.currency)}")
    print(f"  line items : {len(extraction.line_items)}")
    for item in extraction.line_items:
        print(
            f"    [{item.position}] {item.description_raw!r} "
            f"qty={_fmt(item.qty)} unit={_fmt(item.unit)} "
            f"price={_fmt(item.unit_price)} total={_fmt(item.line_total)}"
        )
    print(
        f"  totals     : subtotal={_fmt(t.subtotal)} tax={_fmt(t.tax)} "
        f"discount={_fmt(t.discount)} total={_fmt(t.total)}"
    )
    print(
        f"  payment    : {_fmt(extraction.payment.method)} "
        f"last4={_fmt(extraction.payment.card_last4)}"
    )
    print(
        f"  handwritten={extraction.meta.is_handwritten} "
        f"legibility={extraction.meta.legibility.value}"
    )

    # --- validation + routing ---------------------------------------------- #
    print("\n" + "-" * 68)
    print(f"VALIDATION  errors={report.error_count} warns={report.warn_count}")
    print("-" * 68)
    if report.findings:
        for f in report.findings:
            print(f"  [{f.severity.value:5}] {f.rule_id}: {f.message[:150]}")
    else:
        print("  (clean - no findings)")

    print("\n" + "-" * 68)
    print(f"CONFIDENCE  {confidence}   ->  {status.value} (priority {priority}: {reason})")
    print("-" * 68)

    # --- score against the hand-verified label ----------------------------- #
    label_path = GOLDEN / "labels" / f"{args.receipt_id}.json"
    if not label_path.is_file():
        print("\n(no golden label for this receipt - nothing to score against)")
        return 0

    truth = ReceiptExtraction.model_validate_json(label_path.read_text(encoding="utf-8"))
    acc = field_accuracy(extraction, truth)
    bd = field_breakdown(extraction, truth)
    precision, recall, f1 = line_item_f1(extraction.line_items, truth.line_items)
    critical = critical_field_accuracy(extraction, truth)

    print("\n" + "-" * 68)
    print("VS GOLDEN LABEL")
    print("-" * 68)
    print(f"  critical fields (merchant+date+total) all correct: {critical}")
    print(format_breakdown(bd))
    print(f"  line-item F1   : {f1:.2f}  (precision {precision:.2f} recall {recall:.2f})")
    wrong = sorted(p for p, ok in acc.items() if not ok)
    if wrong:
        print(f"  MISMATCHED ({len(wrong)}):")
        for path in wrong[:25]:
            print(f"    - {path}")
        if len(wrong) > 25:
            print(f"    ... and {len(wrong) - 25} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
