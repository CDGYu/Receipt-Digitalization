# Agent Memory — Receipt Digitization System

Durable working memory for cross-session continuity. Read this first, then
`docs/NEXT_SESSION_PROMPT.md` for the task list and the reading order. The
continuity protocol itself — what lives where, and why this snapshot must be
verified rather than trusted — is **ADR-0019**.
Last updated: **2026-07-31**, at `main @ 7deb3fb`.

## Snapshot

- **`main` @ `7deb3fb`, pushed — `origin/main` is identical. THE PAN HARDENING
  MILESTONE IS COMPLETE AND MERGED** (2026-07-31, true fast-forward from
  `ce98345`). `feat/pan-hardening` is kept at its merge point and pushed;
  merged branches and SDD workspaces are never cleaned up.
- **864 Python tests + 170 Vitest**, ruff clean, typecheck clean, build clean —
  `python scripts/verify.py` all five gates PASS, re-measured 2026-07-31 at
  `7deb3fb` (pytest count read from junitxml: 864/0/0/0).
- **Phases 0–5 complete, plus PAN hardening.** Phase 3 is complete except
  **P3.T6 calibration** (blocked on ISSUE-001).
- Dev interpreter **Python 3.14.4**. Node **v22.22.2** / npm **10.9.7**.
- Plan of record: `IMPLEMENTATION_PLAN.md`. The PAN milestone ledger — every
  measurement, the user's rulings, and the follow-ups list — is
  `.superpowers/sdd/2026-07-31-pan-hardening/progress.md`; Phase 5's is
  `.superpowers/sdd/2026-07-29-review-ui/progress.md`. **`.superpowers/` is
  gitignored, so nothing in it is findable by searching the tracked tree —
  open ledgers by path.**

## How to run

- **There are two test suites.**
  - `python -m pytest` — **864**, offline and **Node-free** (proven by running
    with the nodejs directory stripped from `PATH`). `pyproject` sets
    `pythonpath=["src","."]`, `testpaths=["tests"]`.
  - **Vitest, in `frontend/`** — **170**. `npm test`.
- **`npm test` does NOT type-check.** A TypeScript error ships green through it.
  **That trap fired three times in one milestone.** Run `npm run typecheck` too.
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. Fails loudly naming the gate; when `npm` is absent it prints a
  per-gate `SKIPPED` and still gates the Python half. **See ADR-0017.**
- Lint: `python -m ruff check .` — bare `ruff` is not on PATH. Types: `mypy src`
  (informational). Alembic: `python -m alembic` — its console script is not on
  PATH either.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is **not** on this machine.
- E2E (deliberate, not part of the sweep): `python scripts/seed_review_e2e.py
  --reset`, then `cd frontend && npx playwright test`. Playwright's Chromium is
  installed.
- Baseline: `python -m eval.run_baseline` — needs a **real provider + a labeled
  golden set**, else it refuses the `fake` provider / scores an empty set.
- **Terminal quirk:** piped pytest output can lose its final summary line. The
  old "PowerShell clips it" attribution is **unproven** — the globally-installed
  `superclaude` pytest plugin is suspected, but `-p no:superclaude` did not
  reproduce the clipping, so the cause is unestablished. The workaround stands
  either way: use `--junitxml` and read exact counts from the XML.

## What this project is

A VLM pipeline turning receipt photos into accounting-grade structured data.
**Prime directive: optimize auto-approval precision (target ≥99%), not raw
extraction accuracy. A wrong number is far worse than a missing one — prefer
`null` over a confident guess.** Three model passes (triage → extract → repair)
with deterministic validation between extract and repair, self-consistency for
handwriting, and one confidence score that routes to auto-approve or review.

## Invariants (never violate — see `.kiro/steering/receipt-system.md` + the ADRs)

`Decimal` on the money path, never `float` (ADR-0001). Validation is
deterministic/pure, never mutates, never raises, stable rule IDs. Tolerance is
cents-bounded (`rel=0.0002`, floor scales with line count). Repair keeps the
**best** attempt `(errors, warns, nulls)`; only errors trigger repair;
unparseable → re-extract; never alter numbers to force arithmetic. Structured
output via tool-use. Few-shot images first, target last. Consistency runs are
never cached. Merchant hints end with "trust the image." **A full PAN is never
persisted** (ADR-0018 is the measured policy). Nothing is silently dropped —
every receipt reaches a terminal state. **A machine run never overwrites a
`reviewed` row.** Excel is output only; the DB is the source of truth.

**PAN (ADR-0018):** the group-shape requirement in `_PAN_RE` is load-bearing —
three of the four real corpus TINs are **14 digits**, inside the 13–19 PAN
window, silent only because they print `3-3-3-N`. **Never relax the grouping
toward "any run of 13+ digits."** Any `_PAN_RE` change replays the committed
battery in `tests/test_repository.py` in **both** directions and tests **two
instances of what it guards in one input**.

**Frontend (ADR-0015):** money is a string end to end; **`<input type="number">`
and `valueAsNumber` are banned**; the browser stays same-origin so **no
`CORSMiddleware` is ever added**; SPA pages live under `/app/*` and no API path
moves.

## Decisions the user has made (do not re-ask)

- **Auth model — session auth + role checks (`reviewer`/`admin`), plus a separate
  API key for machine upload.** A shared key cannot attribute a correction to a
  reviewer, which would hollow out the `corrections` audit trail. (ADR-0012.)
- **Accounts live in a `users` table**; the confidence breakdown is **persisted**
  at process time (it cannot be honestly recomputed — triage issues and
  `meta.ambiguous_fields` are not stored); `admin` owns `/export/xlsx` + user
  management; `POST /upload` writes a `pending` row before queueing.
- **ISSUE-001 (the real baseline) is deferred until the system is built** — the
  user's explicit call. Do not start it unprompted.
- **Frontend is React 19 + Vite + TypeScript** (ADR-0015).
- **bbox highlighting is out of scope.** `line_items[].bbox` is structurally
  `None` — nothing asks for it and nothing computes it. Revisit only if P2.T2 is
  resolved with an OCR pass, which would supply both the grounding text layer and
  the coordinates.
- **Review-screen findings are labelled historical.** `apply_corrections` never
  re-runs validation, so findings go stale the moment a reviewer edits. A dry-run
  `POST /validate` endpoint was considered and deferred.
- **Push policy (2026-07-30): pushing `feat/*` branches is authorised. Ask before
  pushing `main`.** This replaced the earlier "never push" rule. (`main` was
  pushed after the PAN merge; it is in sync as of this stamp.)
- **`GET /review/next` resumes the caller's own in-progress task** before claiming
  a new one (2026-07-30, ADR-0016) — chosen over an explicit release route, which
  only fires when the client remembers to call it and so fixes deliberate
  abandonment but not reload, crash, or a dropped response.
- **`receipt.date_raw` is editable** (2026-07-31), as plain text — a date control
  would reformat the string, and preserving what the document printed is the whole
  reason the field exists.
- **The UI warns when the server stored something other than what was sent**
  (2026-07-31), by diffing the patch against the `ReceiptDetail` that `PATCH`
  returns. Money fields compare with trailing fractional zeros normalised, because
  `_MONEY = Numeric(14,4)` means every money value reads back at four decimals and
  a naive diff would fire on every edit.
- **PAN rulings (2026-07-31, the hardening milestone — ADR-0018):** the detector
  fix is the **minimal one-character widening** (`\d{1,4}` → `\d{1,7}` on the
  four-group tail), closing leak (a) — a 17–19-digit four-group PAN stored
  whole — completely. **Leak (b) (more than four groups leaves the remainder
  clear) is ACCEPTED, not fixed**: the greedy rewrite swallowed a *second*
  adjacent card whole and ate amounts; the scan-loop alternative closed (b)
  with neither regression but is O(n²) (~1715 ms on a 40 KB adversarial run vs
  ~4 ms). Both were measured and disclosed; the user ruled for minimal. The
  TaxBand.label fixture gap got **one user-authorized targeted fix** before the
  merge; the merge itself was local, with the push following separately.
- **Task 5's CI job was cut** (Phase 5). `.github/workflows/ci.yml` is gitignored
  and Actions does not run, so a tracked workflow would be a false signal.
  `scripts/verify.py` replaces it (ADR-0017).
- **Milestone close includes the handoff refresh** (2026-07-31, ADR-0019):
  `docs/MEMORY.md` + `docs/NEXT_SESSION_PROMPT.md` are refreshed and stamped in
  the same session as a merge, rulings are promoted out of the gitignored
  ledger into the tracked tree, and the next session verifies the stamp against
  the repo rather than trusting it.

## Still needing a user decision

1. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001, and
   therefore for all calibration.
2. **R060/R061 OCR grounding (P2.T2)** — model returns the text it read / a cheap
   OCR pass / drop the rules. Also gates bbox highlighting.
3. **Whether GitHub Actions should run again.** Nothing runs the frontend gates
   remotely. If yes, the workflow should call `scripts/verify.py` rather than
   re-listing the gates, so the two cannot drift.

## Built

**Core (Phases 0–2).** `extract/`: schema, prompts, json_io, paths, extractor
(3-pass + repair + best-attempt + self-consistency), lineitem_align,
clients/{base, fake, anthropic_client, openai_compat, factory}. `validate/`:
rules (28), report, context, validator. `normalize/`: numbers, dates, text.
`preprocess/`: image_ops, bounds, quality. `ingest/`: storage, dedupe, ingest.
`export/xlsx.py` (all four §13 sheets). `score/confidence.py` +
`score/thresholds.py` (the single source for `0.85`/`0.60`). `pipeline.py`,
`config/settings.py`, `eval/` (metrics, harness, golden_set, run_baseline).
**The R020/R024 VAT-inclusive fix shipped** — `prices_include_tax` is threaded
from `extract/schema.py` into `validate/rules.py`, so the rule is
convention-aware rather than assuming `Σ lines ≈ subtotal`.

**Phase 3 — persistence.** `persist/models.py` (**8 tables**: receipts,
line_items, merchants, extraction_runs, validation_findings, review_tasks,
corrections, users) + `docker-compose.yml`; `alembic/`; `persist/session.py`;
`persist/repository.py` (§14.8 + DB-backed dedupe); `review/queue.py`.
- `persist/__init__` is **lazy** (PEP 562 `__getattr__`) so a base install can
  still run migrations.
- `next_task` applies `FOR UPDATE SKIP LOCKED` only on dialects that support it —
  **SQLite silently drops the clause instead of erroring**, which is why the guard
  lives in Python.
- The migration drift guard runs on SQLite only, so a new ENUM member would pass
  locally and fail on Postgres.

**Phase 4 — service + CLI.** `pipeline.process_receipt` (the only function the
worker calls; all 8 stages wrapped so any exception lands `needs_review` naming
the stage, with a row *and* a review task); `extract/clients/limits.py`
(`VLMGate` + `CostGuard` + `GuardedVLMClient`); `worker.py` (RQ, lazily imported
behind a `worker` extra). `persist/users.py` (stdlib scrypt); `review/auth.py`
(signed-cookie sessions, HMAC URL signing); `review/{api,schemas,serializers}.py`
— `create_app` plus eleven routes. `cli.py`:
`ingest|process|export|eval|calibrate|merchants|reprocess|users`. ADR-0011,
ADR-0012, ADR-0013, ADR-0014.

**Phase 5 — the review UI.** `frontend/` (React 19 + Vite + TS): login, the
review screen, `ConfidenceRail`, `FindingsPanel`, `ImagePane` (signed URL, one
re-sign retry, then a visible failure), `ReceiptForm` (all 17 correctable paths),
`LineItemsTable` (7 fields, `position` read-only), `MoneyInput`, `patch.ts`
(`buildPatch` / `fieldsFromReceipt` / `findRewrites`), `session.ts`,
`ErrorBoundary`. A strictly sequential `PATCH → complete → next` with step-tagged
failures; ⌘/Ctrl+Enter approves; a rewrite warning that **holds the screen**
until acknowledged. Served same-origin under `/app` by a guarded `StaticFiles`
mount whose history fallback is navigation-only. Plus `scripts/seed_review_e2e.py`,
`scripts/serve_review_e2e.py` (**e2e-scoped, deliberately not a production entry
point**), `scripts/verify.py`, a Playwright acceptance spec, and
`frontend/tests/no-float-in-money-path.test.ts` (a source-scanning float guard —
measured sound, but it has **no rule that can fire on arithmetic**, so it cannot
settle whether an expression violates ADR-0001; read the code for that).

Backend changes Phase 5 forced: `receipt_detail` now returns `receipt_number`,
`txn_time` and `payment_method` (correctable but previously **invisible** — the
17 write paths and the 17 read keys were different 17s); and **`GET /review/next`
resumes the caller's own in-progress task** (ADR-0016), because nothing in the
system releases a claim.

**PAN hardening (2026-07-31, merged).** `_PAN_RE`'s four-group tail widened
`\d{1,4}` → `\d{1,7}` (leak (a) closed; leak (b) accepted and pinned;
ADR-0018). `save_extraction` redacts **every** extraction-sourced value it
stores — every scalar text column plus the `modifiers` JSON (`Modifier.label`
is model text) — via a `type(value) is str` gate (str-enums measured to survive
`redact_pan` only as plain strings, so the gate is exact-type on purpose);
system-minted values (`image_key`, `image_phash`, `status`, `confidence`,
`merchant_id`) are structurally excluded, because masking an all-digit
`image_phash` (a legal dHash) broke `phash_distance` and dedupe. `card_last4`
keeps the stronger `_last4` guarantee. `enqueue_review` redacts `reason` at the
sink — exception text interpolates raw model values and lands there. Guards:
a two-table column walk (`Receipt`/`LineItem`, String + JSON) with a fixture
seeding **all 22 reachable extraction text fields** (enumerated by walking the
pydantic schema programmatically, after a by-eye pass missed
`Totals.tax_breakdown[].label`), so a new text column fails RED; the four
corpus TINs pinned silent; the skip-recoverability triple pinned in
`tests/test_api_write.py`. Docs: ADR-0018 (the policy, the accepted false
positives, the two-instances rule), a dated ADR-0007 correction, and
`ReceiptForm.tsx`'s claim bounded to its measured 16-row table.

## Remaining work

**`docs/NEXT_SESSION_PROMPT.md` carries the full ordered task list.** Headlines:

1. **PAN follow-up (HIGH):** cards grouped outside the two canonical shapes
   (5-4-4-4, 6-4-4-4, 4-5-4-4, Diners 4-6-4, Maestro 4-4-5, double-space
   separators) store **whole** — pre-existing, measured, with a
   reviewer-measured candidate fix (enumerate groupings; 0 TIN regressions;
   never relax to "any 13+ run"). Fold in: pin ADR-0018's worked example;
   qualify ADR-0007's unqualified "a hash" bullet.
2. **Bound the machine-path `currency` write** — `save_extraction` writes an
   unconstrained `str` into `String(3)`; Postgres raises `DataError` (leak-(d)
   shape: the human path is guarded, the machine path is not).
3. **Fix the intermittent test's fixtures** — diagnosed as a thread race
   (identical blobs → dedupe `REJECTED` under load), **not** ordering;
   pytest-randomly is not installed.
4. Phase 5 follow-ups: the five design §5 error-recovery behaviours (including
   **no logout control**), a read route for `corrections`, a real ASGI entry
   point, an admin release for a claimed task.
5. **Phase 6** — merchants & few-shot. **Phase 7** — self-consistency wired into
   the pipeline, gated on `triage.is_handwritten`. **Phase 8** — calibration and
   eval-harness honesty.
6. **ISSUE-001 last.**

## Environment / provider (user's `.env`, gitignored)

- Active config: `VLM_PROVIDER=ollama`, `VLM_BASE_URL=http://localhost:11435/v1`,
  model `granite3.2-vision:2b` (both passes), `DEFAULT_CURRENCY=PHP`,
  `VLM_TIMEOUT_S=900`. `openai` SDK installed; `anthropic` is not.
- **Golden set is LIVE** — `eval/golden/labels|images/{r001,r002,r003}` on disk,
  both flagged readings user-verified. `eval/golden/images/` is gitignored (the
  parent is not — do not move real receipts up a level).
- Ollama runs in Docker (service `ollama`, host port **11435** → container 11434).
  The native Windows Ollama CLI on PATH points at 11434 and will say "could not
  connect" — use `docker exec ollama ollama …` or set `OLLAMA_HOST`.
- **Local CPU inference is not viable for real numbers.** No GPU passthrough;
  measured 262 s–1205 s for a *single* call. Ollama rejects a `tools` payload for
  models that do not declare the capability, so the local path runs JSON mode, not
  the intended tool-use route (ADR-0002). Offline spot checks only.
- **Security:** a commented-out Gemini key was once echoed in output → **rotate it
  before use.** Never echo `.env` secret values.
- **Git:** default branch `main`; `origin` → `CDGYu/Receipt-Digitalization`,
  **private**. Push `feat/*` freely; **ask before `main`**. Everything in sync
  at the stamp above.
- **Gitignored and untracked:** `.kiro/` (steering still auto-loads from disk),
  `.github/workflows/` (**Actions does not run**), `.superpowers/` (the SDD
  ledgers — invisible to anything searching the tracked tree), and **`var/`**,
  where `STORAGE_ROOT` defaults to `var/blobs` and writes **real receipt images**.
  Never stage one.
- **Harness notes:** the `developer-kit` plugin's `prevent-destructive-commands.py`
  hook used to block `git add`/`git commit`; those checks were removed on
  2026-07-28 and every genuinely destructive guard is still active. **A plugin
  update will overwrite this.** The same hook false-positives on a `grep` whose
  *pattern* names a sensitive file, and `developer-kit-typescript`'s
  `ts-file-validator.py` complains about PascalCase `.tsx` — it is a
  **PostToolUse** hook, so it cannot block a write and the file is created
  successfully; ignore the message. Also: during the PAN milestone a subagent
  three times reported "prompt injection" that was actually the harness's own
  file-watcher notice firing on git-checkout restorations — the right handling
  (which it did) is verify with git, do not comply, disclose.

## The real receipt corpus (from the user's first 3 samples, 2026-07-28)

The user's documents are **Philippine BIR "SALES INVOICE" forms: a
machine-printed template with every value filled in by hand.** Labelled in
`eval/golden/labels/r001-r003.json` (Metro Oil Subic, Summit Fuel OPC, Serv
Central). All confirmed against the code:

- **`document_type=INVOICE` + `print_type=MIXED`, not `handwritten_receipt`.**
  `TriageResult.is_handwritten` already returns True for `MIXED`, so **gate
  self-consistency on `triage.is_handwritten`, never on `document_type`.**
- **The handwriting penalty must read triage too.** `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these forms a model may report `False` while
  triage says `MIXED`, so the −0.15 is missed on exactly the receipts that need it.
- **Blank pre-printed product rows.** Metro Oil's form pre-prints six fuel rows
  with one filled in; a VLM will likely emit all six. Needs a prompt instruction
  and/or a rule (sibling of R052).
- **Buyer-vs-merchant trap.** Every form has `SOLD TO: Ideal Source` (the user's
  own company). `merchant.name` must be the ISSUER, never the buyer.
- **Printer-TIN trap.** The footer carries the *printing press's* TIN. r001's
  printer is Midland Press `000-296-795-000` (12 digits); r002's notes carry RJ
  Printing Press `103-969-951-00000` (14). `merchant.tax_id` must be the
  `VAT Reg. TIN` in the header.
- **The TINs are why the PAN grouping rule is load-bearing** (ADR-0018): three
  of the four labelled TINs are 14 digits — inside the PAN window — and print
  `3-3-3-N`. `redact_pan` sees `merchant.tax_id` via `save_extraction_run`'s
  raw-payload pass, so a grouping-agnostic widening would mask every merchant
  fingerprint Phase 6 depends on. Pinned by
  `test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints`.
- **Currency is never printed.** `normalize_currency` correctly refuses to guess,
  so `DEFAULT_CURRENCY=PHP` is required or currency stays null.
- **Composition:** if this hybrid form is the whole corpus, the spec's §15 target
  mix (60% printed-clean / 20% handwritten) does not describe reality. Raise
  before scaling M0.
- VAT is 12% and totals read `net + VAT = TOTAL AMOUNT DUE`. `Less: Withholding
  Tax` and the VATable / VAT-Exempt / Zero-Rated buckets appear on the forms but
  have no dedicated schema fields. Merchant `VAT Reg. TIN` is the strongest
  fingerprint for Phase 6 matching.

## DEFERRED — do this LAST

**ISSUE-001: run the first real baseline.** Parked by the user on 2026-07-28.
Full diagnosis and exact resume steps are in **`docs/KNOWN_ISSUES.md`** — read
that, do not re-derive it.

Everything needed is in place and the three labels validate with zero findings,
but `python -m eval.run_baseline` has never completed. The blocker is that
`granite3.2-vision:2b` on CPU takes ~262 s per call, so a run is 30–60 min and
dies to any interruption. **Fix: point it at a hosted tool-capable model** (the
commented-out Gemini block in `.env`; rotate that key first).

Until this runs there are **no real accuracy numbers**, no threshold calibration
(P3.T6 / P8.T1), and no way to judge a prompt or rule change. **Do not treat any
precision claim as measured.**

## Deferred follow-ups / known minors (non-blocking)

- **PAN — the accepted residue (ADR-0018):** leak (b)'s remainder-in-the-clear
  (user ruling), and four accepted false positives — a 13–19 digit all-numeric
  identifier; two column-scale amounts in one free-text value; ~1-in-200 random
  16-char hex hashes (**which is why no hash is ever routed through
  `redact_pan`** — `image_phash` is excluded structurally); a whole-number
  13–19 digit modifier amount. A reviewer confirming a 13–19-digit
  `receipt.number` sees it masked and a spurious `corrections` row minted —
  inherent to the policy, the old "two sides should agree" item is **closed**.
- The PAN grouping gap, the `currency` bound, and the intermittent's fixture
  race are **tasks 1–3 in the prompt**, not minors — listed there.
- `_persist_failure` never writes `image_phash`, so a failed receipt keeps `""`
  and can never serve as a dedupe **original** (address with Phase 6 dedupe).
- An auto-approving reprocess closes a review task a reviewer had already claimed.
- **No login rate limiting**, and each attempt costs a full scrypt derivation
  (~16 MB, ~57 ms) — `POST /auth/login` is an unauthenticated CPU/memory amplifier
  as well as an enumeration surface. Address before this faces more than a LAN.
- `receipts eval`/`calibrate` traceback without the `pipeline` extra while the
  other six commands degrade cleanly; `calibrate` needs nothing from it.
- An **all-failed** eval run still persists `"auto_approval_precision": 1.0` to the
  results JSON though the terminal prints `n/a`. **The artifact ban is not closed
  until the file is honest too** — fix with P8.
- Reprocessing a `reviewed` receipt records **no** `extraction_runs` — the
  transaction rolls back (ADR-0013's dated correction).
- Move confidence penalty weights into `config/rules.yaml` (P3.T6).
- `_attempt_prompt_hash` reconstructs each call's prompt; when merchant hints /
  few-shot land, the same values must be passed there or the stored hash drifts.
- **Semantic (merchant+date+total) dedupe is deliberately not wired** into
  `process_receipt` — `merchant_id` is NULL until Phase 6 (ADR-0011).
- `save_extraction` takes `report` but does **not** write findings — the pipeline
  calls `save_findings` separately.
- `_build_line_items` falls back to list order when emitted positions aren't
  distinct, so `unique(receipt_id, position)` can't sink a whole receipt.
- `enqueue_review` is check-then-insert against a UNIQUE column; concurrent
  enqueues can still raise `IntegrityError`.
- `vllm`/`ollama` still require `VLM_API_KEY`; `VLM_BASE_URL` ignored for
  `anthropic`.
- XLSX `write_only` streaming above 5000 rows is deferred.
- ruff sorts `from alembic import command` as **first-party** in tests (the
  repo-root `alembic/` dir shadows the package) — don't "fix" that import order.
- Phase 5's own minors are in its ledger with rulings; the PAN milestone's are
  in its ledger's FOLLOW-UPS section.

## Workflow & conventions

- **subagent-driven-development**: one fresh **`general-purpose`** implementer per
  task, briefed to read the real signatures first, work TDD, keep **both** suites
  green + ruff clean, and stage only its own files. The controller reviews the
  diff, re-runs the gates **independently**, then dispatches a task review, then
  commits and appends to the ledger.
- **Per milestone**: a feature branch; at the end a whole-branch review on the
  strongest model, **one** consolidated fix wave, one scoped re-review, then a
  fast-forward merge — **then the handoff refresh in the same session
  (ADR-0019)**. Branches and SDD workspaces are **kept**.
- **Probe before dispatching.** Phase 5's plan was wrong about existing code
  **eleven times**; the PAN plan repeated the pattern (wrong enum name, missing
  required argument, two false "protected" claims, a mis-attributed TIN). The
  plan's prose is reliable; its claims about existing APIs are not.
- Conventional commit messages (`feat(scope): …`, `fix: …`, `chore: …`, `docs: …`).

### Review standards — hold all of them

1. **Reviewers reproduce, they do not reason.**
2. **Every new test must be proven to fail** with its fix reverted.
3. **A test asserting the absence of breakage cannot be proven by a RED run** —
   revert each guarantee separately.
4. **A mutation must change exactly one thing**, or the result names the wrong
   cause.
5. **If a number can change without its sentence changing, it does not go in the
   comment.** One citation drifted `61 → 81 → 94 → 101`, once *inside the commit
   documenting the drift*.
6. **A claim about what your own artefacts say is itself a claim requiring a
   command.** Grep; do not recall.
7. **Do not credit a tool with settling a question you have not put to it** —
   including `grep` and the float guard.
8. **A stub that does not reflect the write is a fixture bug** that lies dormant
   until something reads the reply.
9. **Test a guard with two instances of what it guards in one input** — a
   scanner's failure mode lives at the boundary *between* two hits, and
   single-instance batteries are blind to it by construction.
10. **A battery you write agrees with you** — replay the committed battery in
    both directions before trusting a change.

And: **a green suite is not evidence that installed software works.** Anything
with an entry point gets run from outside the repository.

## Key references

- `RECEIPT_SYSTEM_SPEC.md` — §3 architecture, §6 data model (**8 tables**), §9
  normalization, §10 validation, §12 confidence + routing, §14 function
  inventory, §15 milestones, §16 eval, §17 config, **§18 traps (PAN)**, §19 DoD.
- `docs/NEXT_SESSION_PROMPT.md` — the ordered task list and reading order.
- `IMPLEMENTATION_PLAN.md` · `README.md` (§5 design decisions) · `VLM_AND_DATA.md`
- **`docs/KNOWN_ISSUES.md`** — ISSUE-001 with its diagnosis and resume steps.
- **`docs/adr/` — 0001–0019**; see `docs/adr/README.md`. Read **0001** first;
  **0018** before touching `_PAN_RE`/`redact_pan` (it supersedes 0007 on the
  masking rule); **0017** before believing a green test run; **0019** for how
  cross-session state works.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — per-milestone design
  and plan documents, including `2026-07-31-pan-hardening-design.md` and its
  plan.
- `.superpowers/sdd/<plan-name>/progress.md` — per-milestone ledgers.
  **Gitignored: open by path, they cannot be found by searching.**
- `semantic-review/` — older whole-branch review write-ups.
- `.kiro/steering/receipt-system.md` — always-on load-bearing rules (untracked).
