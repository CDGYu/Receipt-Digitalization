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

## The solution

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
