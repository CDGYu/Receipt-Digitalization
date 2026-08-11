# Known Issues / Deferred Work

Open problems that are understood but deliberately parked. Each entry records what
happened, what was already fixed, what is still open, and the exact steps to
resume — so picking it up later does not mean re-deriving the diagnosis.

---

## ISSUE-001 — The first real baseline run has never completed

**Status:** OPEN — deferred by the user until the system is built.
**Owner action required:** yes (provider choice, see "Recommended fix").
**Discovered:** 2026-07-28. **Blocks:** the first real accuracy numbers (spec §16),
threshold calibration (P3.T6 / P8), and any prompt/rule change that should be
re-evaluated.

### Goal

Run `python -m eval.run_baseline` over the three hand-verified golden receipts and
get the six §16 metrics. Everything needed for this is in place: the labels, the
images, the pipeline, the scorer, and the harness. The run itself has not
succeeded.

### What happened

**Attempt 1 — 14:40, died on receipt 1.**
`VLMTransientError: connection: Request timed out.`
The client used the openai SDK's own 180s default while a single triage call takes
~262s. Root cause: `VLM_TIMEOUT_S` was declared in `Settings` but **never passed to
the client constructor** by the factory — the same shape of bug `VLM_BASE_URL`
once had. **FIXED** in `1f9f122`; the configured timeout now reaches the client
(verified: `client._client.timeout == 900.0`).

**Attempt 2 — 15:22, ran ~65 minutes, then vanished.**
Zero bytes of output, no results file written, process gone. This is the signature
of the process being **killed**, not failing: an unhandled exception would have
printed a traceback, and the harness fix in `1f9f122` would have recorded a
per-receipt failure and still written a report. Most likely the background process
was torn down when a long foreground wait was interrupted.

### Measured end-to-end run (2026-07-29, r002 via `scripts/try_one_receipt.py`)

The pipeline **does work end to end** — but the local model cannot read the
receipt. Timings on this hardware (CPU-only):

| image `max_edge` | base64 | triage | extract | total |
|---|---|---|---|---|
| 2048 (default) | 745 KB | **887 s** | timed out at 900 s, then retried | never finished |
| 768 | 129 KB | **314 s** | **1057 s** | ~23 min |

At 2048px, triage alone (887s) sits *just under* the 900s timeout — which is why
the earlier baseline attempts died. At 768px it completes, but
`resize_for_model` correctly warns `estimated text height 7.7px is below 12px`,
and the extraction comes back effectively empty: every field null, two blank line
items.

**The safety machinery behaved exactly as designed on that bad extraction** —
R010 ERROR (total is null) plus R011/R012/R053 warnings, confidence `0.000`,
routed `needs_review` at priority 0 (urgent). It did not auto-approve garbage.
Scored against the golden label: critical fields correct = False, line-item
F1 = 0.00. So the infrastructure is validated; the *model* is the problem.

### Root cause still open

**`granite3.2-vision:2b` on CPU is too slow, and too weak, to iterate against.** A 3-receipt baseline is 6+ calls (triage + extract per
receipt, more if a repair fires), so ~30–60 minutes per run — and the eval harness
is meant to be re-run on *every* prompt, model, or rule change (§16). Two
consequences:

1. Each run is long enough that an interruption kills it before it finishes.
2. Even when it works, the iteration loop is impractical.

Secondary: Ollama rejects a `tools` payload for models that do not declare the
capability, so the local path runs in JSON mode rather than schema-constrained
tool-use (handled by `VLM_USE_TOOLS` / the provider default in
`factory.py`, but it means the local run is not exercising the intended
structured-output path — see ADR-0002 and the steering rule "structured output via
tool-use, not 'reply in JSON'").

### Recommended fix

**Point the baseline at a hosted, tool-capable model.** `.env` already has a
commented-out Gemini block using the OpenAI-compatible endpoint:

```
VLM_PROVIDER=openai
VLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
VLM_API_KEY=<a fresh key>
VLM_MODEL_EXTRACT=gemini-3.5-flash
VLM_MODEL_TRIAGE=gemini-3.1-flash-lite
```

This turns 30+ minutes into well under a minute and exercises real tool-use.
Keep the Ollama config commented alongside it for offline/zero-cost spot checks —
the provider abstraction (ADR-0002) means switching is one env var.

> **SECURITY:** the Gemini key currently sitting commented-out in `.env` was
> echoed in terminal output during this session. **Rotate it before use.** `.env`
> is gitignored, so it was never committed.

**Alternatives if staying local:**
- Run one receipt at a time — `run_baseline(golden_dir=...)` accepts any directory
  with a `labels/` + `images/` pair, so a single-label dir works.
- Let it run uninterrupted and accept 30–60 min. Start it detached, and do not
  block the session on a foreground wait.
- Try a larger/faster local vision model that declares tool-use support
  (Qwen-VL class), or run Ollama with GPU acceleration.

### Readiness check, 2026-08-11 — everything but the key

Re-run of the resume steps that do not need a provider. **Only step 1 is
outstanding, and only a human can do it.**

| checked | result |
|---|---|
| current config | **still local**: `VLM_PROVIDER=ollama`, `granite3.2-vision:2b`, `VLM_TIMEOUT_S=900`. The hosted block is still commented out. |
| `DEFAULT_CURRENCY` | `PHP` — already correct, per step 1's warning |
| hosted wiring (step 3) | **works.** With the Gemini env block and a dummy key, `make_client` builds an `OpenAICompatClient` at the right `base_url` |
| `VLM_TIMEOUT_S` reaches the client | **yes** — 120.0 s. Attempt 1's root cause is genuinely fixed, not just believed to be |
| `use_tools` on the hosted path | **True** — so the run exercises real tool-use, closing the "Secondary" gap above |
| golden set | 3 labels, 3 images; **all three still validate with zero findings**, so the precondition under "What to expect" still holds |

No network call was made: the `openai` constructor does not touch the network,
so this proves wiring, not reachability. **The key is the only remaining
variable** — a valid key turns this from unverified to running.

**The compromised key was NOT echoed again** during this check. Configuration
presence was reported as a boolean.

### How to resume (exact steps)

1. Rotate the Gemini key; put the hosted config in `.env` (block above).
   Keep `DEFAULT_CURRENCY="PHP"` — BIR invoices never print a currency, and
   without it currency resolves to null on every receipt.
2. `VLM_TIMEOUT_S` can drop back to ~120 for a hosted model.
3. Sanity-check the wiring before a full run:
   ```
   python -c "from config.settings import Settings; from receipts.extract.clients.factory import make_client; s=Settings(); c=make_client(s); print(s.vlm_provider, s.vlm_model_extract, float(c._client.timeout))"
   ```
4. Time a single call first, so a slow provider is caught in one call, not six:
   `triage(prepare_image(Path('eval/golden/images/r001.jpg')), client)`
5. Then the full run: `python -m eval.run_baseline`
   (writes `eval/results/{date}-{PROMPT_VERSION}.json` and prints the §16 table).
6. Commit the results file — §16 requires results be committed so regressions show
   up in a diff, grouped by `prompt_bundle_hash()`.

### What to expect, and what would be suspicious

- The three labels currently validate with **zero** findings, so any ERROR in the
  run comes from the *model's* extraction, not from the rules.
- `is_receipt` came back **false** for a valid invoice on the local model. Nothing
  reads that field yet (grep: no consumers in `src/`), so it is harmless today —
  but the §3 "reject garbage before you pay for extraction" gate does not exist,
  and when it is built it must **not** hard-reject on a small model's `is_receipt`.
  Route to review instead; nothing is ever silently dropped.
- Two traps the local model *did* get right, and worth confirming on the hosted
  one: it named the merchant (`METRO OIL SUBIC INC.`) rather than the buyer
  (`Ideal Source`), and it counted **1** line item rather than all six pre-printed
  fuel rows.
- Confidence/auto-approval numbers are meaningful now (real scoring is wired in),
  but the ≥99% precision target **cannot be validated on three receipts** — treat
  the first run as a smoke test plus a directional read, not a calibration.

### Two side-findings from the smoke run

**`is_receipt` came back `false` for a valid invoice on both receipts tried**
(r001 and r002). Nothing reads that field yet — grep finds no consumers in
`src/` — so it is harmless today, but the §3 "reject garbage before you pay for
extraction" gate does not exist. When it is built it must **not** hard-reject on a
small model's `is_receipt`; route to review instead (nothing is ever silently
dropped).

**`field_accuracy` counts fields the model cannot possibly match.** The flattened
comparison includes `meta.*`, so the annotator prose in a golden label's
`meta.notes` is scored against whatever the model wrote, and `meta.legibility` /
`meta.is_handwritten` are model self-reports rather than facts about the receipt.
On the smoke run these were among the 27 mismatches. Consider excluding `meta.*`
(or at least `meta.notes`) from the field-accuracy denominator so the number
reflects transcription, not annotation. Until then, read per-field accuracy as
slightly pessimistic.

### Related

- `docs/MEMORY.md` — "The real receipt corpus" (why this corpus is unusual) and
  the deferred-task list.
- ADR-0002 (provider abstraction / runtime config), ADR-0003 (confidence).
- `.superpowers/sdd/progress.md` — the full session-by-session trail.
