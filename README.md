<p align="center">
  <img src="frontend/public/logo-lockup.svg" alt="Receipt Digitalization" width="360" />
</p>

# Receipt Digitalization

Turn photographs of receipts — any merchant, printed or handwritten — into
structured, accounting-grade data and an Excel workbook, using a
Vision-Language Model (VLM).

This README is about **the problem and the solution**: what makes reading
receipts hard when the output has to be trusted, and how this system is built
to earn that trust. For running it, see
**[HOW_TO_RUN.md](HOW_TO_RUN.md)** (everyday use) and
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** (full deployment). The design detail
lives in **[RECEIPT_SYSTEM_SPEC.md](RECEIPT_SYSTEM_SPEC.md)** and
**[VLM_AND_DATA.md](VLM_AND_DATA.md)**.

---

## The problem

The task sounds simple: take a photo of a receipt, get back the numbers. It is
not, and the reason is the word **accounting**.

- **Input is uncontrolled.** JPEG, PNG, HEIC, or PDF, from arbitrary merchants,
  so there is no per-merchant template to lean on. Real capture conditions
  apply: phone cameras, indoor light, glare, folds, faded thermal ink, partial
  crops. Some receipts are **handwritten**.
- **Output has to be trustworthy.** The numbers feed a ledger. A total that is
  off by a digit is not a small error — it is a wrong entry in someone's books.

The hard part is no longer reading the characters. Modern VLMs already beat
dedicated OCR engines on noisy documents, and for handwriting they are the only
practical option at all. The difficulty has moved to two questions:

1. Can arbitrary layouts be turned into **one consistent schema**?
2. Can the system tell **when it got a number wrong**?

A VLM asked to read an ambiguous handwritten `1` that might be a `7` does not
hesitate. It emits the most probable token in the same confident tone as
everything else. So the real failure mode is not a missing value — it is a
**confident wrong value that looks exactly like a correct one.**

---

## The solution, in one sentence

**Build the system to know which of its own extractions to doubt.** Optimize for
*auto-approval precision*, not raw extraction accuracy — because a system that
reads 85% of fields correctly and reliably flags the uncertain ones is useful,
while one that reads 95% correctly but cannot say which 5% are wrong has
automated nothing.

The governing metric: **of the receipts auto-approved without human review,
what fraction are fully correct? Target ≥99%.** Then, holding that, maximize how
many get auto-approved. Everything below follows from that choice.

---

## How it works

    A[Upload / batch] --> B[Ingest + preprocess]
    B --> C[Pass 1 — Triage: is this a legible receipt?]
    C -->|yes| D[Pass 2 — Extract: schema-constrained, few-shot]
    D --> E[Normalize]
    E --> F[Validate: 28 deterministic rules]
    F -->|errors| G[Pass 3 — Repair with the exact failing numbers]
    G --> E
    F -->|clean| H{Handwritten?}
    H -->|yes| I[Self-consistency: 3 runs, vote per field]
    H -->|no| J[Score confidence]
    I --> J
    J --> K{Confidence high enough?}
    K -->|yes| L[Auto-approve]
    K -->|no| M[Review queue: human corrects]
    L --> N[(Database)]
    M --> N
    N --> O[Excel export]
    M -.corrections feed few-shot.-> D
```

### Three model passes

1. **Triage** (cheap model) — Is this a receipt? Printed or handwritten? How
   legible? It returns **no amounts**; its job is to reject garbage before you
   pay for extraction and to pick the right extraction prompt.
2. **Extract** (strong model) — A schema-constrained tool-use call. If the
   merchant is recognized, up to two verified prior extractions are injected as
   few-shot examples (images first, the target receipt last).
3. **Repair** (only when validation finds errors) — The model gets its own
   previous output *plus the specific numbers that do not reconcile*:

   ```
   [R021] Line 1 'CHKN BRST 1KG': qty(2) x unit_price(125) = 250,
          but line_total was extracted as 185.
   [R022] subtotal(847.50) + tax(101.70) - discount(0) = 949.20,
          but total was extracted as 847.50.
   ```

   Naming the exact figures is what makes repair work — "please check your math"
   does almost nothing. And a load-bearing instruction: *do not alter numbers to
   force the arithmetic.* Real receipts genuinely fail to add up (cash rounding,
   manual overrides, promos), so the model keeps the printed values and a flag
   is set instead.

### Deterministic validation, not another model call

Between extract and repair sits ordinary arithmetic — **28 pure-function rules,
no I/O, never mutating their input, never raising:**

- Do the line items sum to the subtotal?
- Does `qty × unit_price` equal each line total?
- Does `subtotal + tax − discount` equal the total?
- Is the date real, and not in the future?

This layer costs nothing to run, never hallucinates, and produces the single
largest accuracy jump in the system. Rule IDs (`R001`, `R021`, …) are stable and
never renumbered — they are stored in the database and shown in the review UI.

### Self-consistency for handwriting

Handwritten receipts are extracted **three times** at non-zero temperature and
compared field by field. Fields that agree are high-confidence; fields that
disagree are flagged; a field with no majority is set to `null`. This turns the
model's non-determinism into a free, honest uncertainty signal — far more honest
than asking the model how confident it is.

### One confidence score, then routing

Every signal folds into a single number: validation findings, legibility,
handwritten-or-not, missing critical fields, fields the model flagged as
ambiguous, consistency disagreement, and a small bonus for a known merchant.
Above the threshold it auto-approves; below, it routes to review with a priority
and a reason.

**Nothing is ever silently dropped.** Every receipt reaches a terminal state; if
any stage throws, the receipt is marked `needs_review` with the failing stage as
the reason.

---

## Why these choices (the traps avoided)

- **`Decimal` everywhere in the money path — never `float`.** A stray float
  creates tolerance failures that look like model errors. A schema test asserts
  no field is typed `float`.
- **Tolerance is bounded in cents, not proportional.** A "safe-feeling" 0.5%
  tolerance excuses a `945.20`-for-`949.20` misread. The rule uses `rel =
  0.0002` and scales the floor with line count only where error genuinely
  accumulates.
- **Rules must stay silent when they should.** R052 drops summary rows
  (`SUBTOTAL`, `VAT`) but must not delete real products like `TOTAL WINE CO
  MERLOT` — so it uses exact match after normalization, and the tests pin the
  *silent* case, not just the firing case.
- **Structured output via tool-use, not "reply in JSON."** The provider
  constrains generation to the schema, so malformed output is rare rather than a
  routine retry.
- **Repair keeps the *best* attempt**, ranked `(error_count, warn_count,
  null_count)` — not the last, because a repair on a poor image sometimes makes
  things worse.
- **Only errors trigger repair; warnings lower confidence instead.** An
  unparseable response triggers a re-extract, not a repair.
- **Consistency runs are never cached** — a cache hit would manufacture false
  agreement.
- **Excel is an output format, never the source of truth** — exports read from
  the database.

---

## What's in the box

A staged pipeline — ingest → preprocess → triage → extract → normalize →
validate → repair → score → route → persist → export — fronted by a FastAPI
review service with an async job queue and a keyboard-first review UI.

| Area | Location | What it does |
|---|---|---|
| Extraction | `src/receipts/extract/` | Schema, prompts, tool-schema prep, tolerant parsing, the three-pass orchestrator, and VLM clients (Anthropic, OpenAI-compatible, and an offline fake) |
| Validation | `src/receipts/validate/` | The 28 rules, the runner, findings/repair rendering, tunable config |
| Pipeline | `src/receipts/pipeline.py`, `worker.py` | The end-to-end runners and the RQ queue worker |
| Persistence | `src/receipts/persist/` | SQLAlchemy models + repository (Postgres in prod, SQLite in dev) |
| Review | `src/receipts/review/`, `frontend/` | Review API and the React review UI |
| Export | `src/receipts/export/` | The Excel workbook (receipt-level and line-item sheets) |
| Evaluation | `eval/` | The accuracy harness, metrics, and baseline runners |
| Config | `config/rules.yaml`, `config/settings.py` | Tolerances/thresholds and runtime settings |

The whole pipeline is exercised **offline** by a fake VLM client that replays
scripted responses — the test suite runs with no network access and zero API
cost. Run it with `python -m pytest` (pyproject sets `pythonpath=src`,
`testpaths=tests`).

---

## Data: benchmark with public sets, calibrate with your own

Three jobs, three sources:

- **Benchmarking** (model A vs. B): public datasets — CORD, MC-OCR, SROIE, and
  others. Check each licence; several are research-only.
- **Calibration** (where the confidence threshold goes): **your own receipts,
  and nothing else.** No public set has your merchants, capture conditions,
  currency, or tax conventions.
- **Handwriting**: no public receipt dataset exists — you collect your own, and
  sample *writers*, not merchants.

The dataset that ends up mattering most is your own `corrections` table: every
human edit in the review queue writes a row, and within months it captures
precisely your failure modes. It pays out as merchant hints (immediately),
verified few-shot examples (weeks), and fine-tuning (months, only as a cost
optimization).

---

## Running it

- **Everyday use:** double-click `Start Receipt Review.bat` — see
  **[HOW_TO_RUN.md](HOW_TO_RUN.md)**.
- **Full deployment** (database, Redis, Ollama, API, worker):
  **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) §6**, an ordered runbook.
- **The library/tests only:**

  ```bash
  pip install -e ".[dev]"
  python -m pytest
  ```

`.env.example` is the tracked template — copy it to `.env` and set the required
values. Every other knob has a working default, documented at its field in
`config/settings.py`.

---

## The one thing to carry through all of it

The temptation is to optimize extraction accuracy. Resist it slightly. The
system's value comes from knowing *which* extractions to doubt — that is what
turns a clever demo into something an accountant will actually rely on.

Build the thing that flags its own uncertainty. The accuracy follows.

---

## License

Released under the MIT License — see [LICENSE](LICENSE).
