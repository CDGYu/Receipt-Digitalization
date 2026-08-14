# Known Issues / Deferred Work

Open problems that are understood but deliberately parked. Each entry records what
happened, what was already fixed, what is still open, and the exact steps to
resume — so picking it up later does not mean re-deriving the diagnosis.

---

## ISSUE-001 — The first real baseline run has never completed

**Status:** OPEN — deferred by the user until the system is built.
**Owner action required:** yes — but **not the provider choice this issue
recommends.** See the ruling immediately below.
**Discovered:** 2026-07-28. **Blocks:** the first real accuracy numbers (spec §16),
threshold calibration (P3.T6 / P8), and any prompt/rule change that should be
re-evaluated.

> ## USER RULING, 2026-08-14 — Ollama only, and accuracy is the priority
>
> **This issue's "Recommended fix" is SUPERSEDED and must not be re-proposed.**
> The user has ruled that this system uses **Ollama only — no Gemini, no OpenAI,
> no Anthropic, no other hosted API.** Three sections below still argue for a
> hosted provider and are marked where they stand: *Recommended fix*, *How to
> resume* step 1, and the readiness check's hosted-wiring row. They are kept as
> the record of what was tried, not as instructions.
>
> **Alongside it: high extraction accuracy is the stated goal.** No target number
> is agreed, and none is defensible yet — this issue says so itself, because
> three golden receipts cannot validate any accuracy claim.
>
> **The two rulings collide with measured hardware, and that collision is now the
> open question.** Measured on this box 2026-08-14: **Intel i3-1115G4, 2 cores /
> 4 threads**, 15.7 GB RAM (~7.0 free), **Intel UHD iGPU only** — Ollama reports
> `library=cpu`, `size_vram=0`, and WSL2 cannot pass an Intel iGPU through.
> **One model is pulled: `granite3.2-vision:2b`.**
>
> A 2.5B model already costs 31.6 min per receipt here and reads nothing. High
> accuracy needs a 7B-class document model, which on two CPU cores is roughly 3×
> that. **Ollama-only + this machine + high accuracy is over-constrained**, and
> one of three things must give:
>
> 1. **Ollama Cloud** — still Ollama, no code change (see "A third local option"
>    below). Unverified: whether a suitable vision model is offered and whether
>    it accepts a `tools` payload.
> 2. **A machine with a real GPU** running Ollama — the user's own 2026-08-11
>    plan.
> 3. **This box, a bigger model, hours per receipt** — a one-off baseline is
>    feasible; the re-run-on-every-change loop §16 wants is not.
>
> **Not yet chosen.** Nothing downstream can produce a real accuracy number until
> it is.

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

### Recommended fix — SUPERSEDED 2026-08-14 by the ruling at the top

*(Kept as the record of what was diagnosed and tried. **Do not act on it**: the
user has ruled Ollama-only. The security note at the end of this section still
stands — that key needs revoking whether or not it is ever used.)*

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

*(**The hosted-wiring row below is superseded 2026-08-14 — Ollama only.** The
measurement stands: the OpenAI-compatible client does build against a hosted
`base_url`. It is simply no longer a path this project will take. Every other
row still applies, and two of them matter more than ever under the ruling:
`DEFAULT_CURRENCY=PHP` is correct, and the golden set is three labels.)*

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

### The local path, re-measured 2026-08-11 — it got WORSE

The user chose to stay on Ollama, so the "alternatives if staying local" above
were run rather than argued about. **One receipt (`r001`), 768px, detached,
`VLM_TIMEOUT_S=1800`** so a slow extract could not time out and burn a retry.

| | July (this issue, above) | **2026-08-11** |
|---|---|---|
| one receipt at 768px | ~1371 s (~23 min) | **1896 s (31.6 min)** |

**~38% slower than July, on the same model and the same image.** Not explained
here — Ollama moved to 0.32.4 and nothing else about the box is known to have
changed. Recorded as a measurement, not a diagnosis.

What the run produced:

```
Receipts: 1   Auto-approved: 0   Critical-correct: 0   Failed: 0
Auto-approval precision:  n/a      Critical-field accuracy: 0.00%
Field accuracy:        45.00%      Line-item F1:            0.00%
confidence 0.000, critical_correct false, fields_correct 18 / 40
```

**`Failed: 0` is the good news and the whole of it:** the pipeline completes end
to end against a real provider. Everything else says the model cannot read the
receipt — confidence `0.000`, no critical field right, no line item found.

**Do not read 45% as "nearly half right".** As this issue's own side-findings
note, `field_accuracy` counts `meta.*` — annotator prose and model self-reports
— and a field that is null in both label and extraction scores as correct. The
number is dominated by agreeing-about-nothing.

**The GPU finding is current, not inherited.** Ollama ran discovery on
2026-08-11 and reported `library=cpu … total "7.6 GiB" available "7.2 GiB"` with
no device, and `/api/ps` showed `size_vram=0` while the model was loaded. CPU-only
is measured today, not assumed still true from July.

**Not committed to `eval/results/`.** One receipt, at a non-default resolution,
from a model that read nothing, would be the *first* artefact in that directory
and would sit beside future real baselines as though comparable. It lives in
`var/` (gitignored). §16 wants results committed so regressions show in a diff;
this is not a result, it is a liveness check.

### A third local option this issue did not have: Ollama Cloud

`ollama signin` **exists in the installed build** (0.32.4, verified via
`ollama --help`), and the server already reports `OLLAMA_NO_CLOUD:false` with
`OLLAMA_REMOTES:[ollama.com]`. That makes "stay on Ollama, stop paying the CPU
cost" a real option rather than a hypothetical, and it needs no code change —
`VLM_PROVIDER=ollama` with the same `base_url`, a cloud model tag, and
**`VLM_USE_TOOLS=true`** to override `_TOOLS_OFF_BY_DEFAULT`, which otherwise
silently keeps this provider in JSON mode (the "Secondary" finding above).

Untested here: no account was created, so whether a suitable vision model is
offered and whether it accepts a `tools` payload are both unverified.

### How to resume (exact steps)

1. ~~Rotate the Gemini key; put the hosted config in `.env` (block above).~~
   **SUPERSEDED 2026-08-14 — Ollama only.** Replace this step with: settle the
   runtime question in the ruling at the top, then pull a document-capable
   vision model to replace `granite3.2-vision:2b`, which is the single largest
   cause of zero accuracy. **Set `VLM_USE_TOOLS=true`** once the chosen model
   declares tool support — `factory.py`'s `_TOOLS_OFF_BY_DEFAULT` contains
   `ollama`, so the local path has never exercised schema-constrained tool-use
   and runs in JSON mode, against ADR-0002 and the steering rule.
   **Revoke the old Gemini key anyway** — it was echoed to a terminal and this
   repo is public.
   Keep `DEFAULT_CURRENCY="PHP"` — BIR invoices never print a currency, and
   without it currency resolves to null on every receipt.
2. `VLM_TIMEOUT_S` stays high for a local model. It is `900` now; a bigger model
   on two CPU cores may need more, and Attempt 1 of this issue died because a
   timeout was too short rather than too long.
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

> **Correction, 2026-08-12 — the diagnosis stands, the remedy was refuted.**
> Measured before acting on it (ADR-0030). Excluding `meta.*` moves the floor an
> empty extraction reaches from 42.50% to 39.39% on r001, and on r003 from
> 36.59% to 36.36% — **0.22 points**. Excluding only `meta.notes` **raises**
> every floor, because `notes` is a path an empty extraction *fails*, so
> dropping it removes a penalty rather than a gift. The real driver was
> agreement about absence: of r001's 17 free points, 12 were **non-`meta`** paths
> where neither side was filled — fields the receipt does not have. (The
> qualifier matters: without it the count is 14, because two `meta.*` paths are
> `[]` on both sides, and those two are already counted among the `meta.*`
> self-reports resting at their schema defaults.) **ADR-0040** is what shipped
> instead: metric 4 became a set of ratios and counts over one classifier that
> reads *filled* from the truth side only — its decision 2 is where they are
> named. Its probe re-derives every figure in this note.
>
> The last sentence above — "read per-field accuracy as slightly pessimistic" —
> was the reading under the old scalar and is left as the record of what was
> thought. Under `transcription_accuracy` it no longer holds: the floor is
> ~5.9%, not ~40%.

### Related

- `docs/MEMORY.md` — "The real receipt corpus" (why this corpus is unusual) and
  the deferred-task list.
- ADR-0002 (provider abstraction / runtime config), ADR-0003 (confidence).
- `.superpowers/sdd/progress.md` — the full session-by-session trail.
