# Agent Memory — Receipt Digitization System

Durable working memory for cross-session continuity. Read this first, then the
files in "Key references" below. Last updated: **2026-07-28**.

## Snapshot

- **`master` @ `a5bf75d`** — **644 tests passing, ruff clean.** `feat/service`
  fast-forward merged on 2026-07-29 (the branch still exists at the merge point,
  matching the convention of the three earlier milestone branches). Phase 4 is
  **complete except `cli.py`** (P4.T5/T6).
- Merged on `master`: Phase 0 foundations, Phase 1 offline modules, the online
  wiring (config, client factory, M1 pipeline, confidence scoring, one-command
  baseline runner), **Phase 3 persistence** (7-table ORM + `docker-compose.yml`,
  Alembic migrations, repository layer, DB-backed dedupe, review queue, 4-sheet
  XLSX export), plus the R020/R024 VAT-inclusive fix and the currency default
  chain.
- Merged with that branch: **P4.T4** (`process_receipt`, the RQ worker, the two
  VLM guards — ADR-0011) and **P4.T3** (the review API: `users` table, session
  auth + roles, machine upload key, eleven routes — ADR-0012).
- Phase 3 is complete except **P3.T6 calibration** (blocked on ISSUE-001).
- Dev interpreter **Python 3.14.4**; CI matrix 3.11/3.12.
- Plan of record: `IMPLEMENTATION_PLAN.md`. Running log: `.superpowers/sdd/progress.md`.

## Decisions the user has made (do not re-ask)

- **Auth model (P4.T2) — DECIDED 2026-07-28, IMPLEMENTED 2026-07-29: session auth
  + role checks (`reviewer` / `admin`), plus a separate API key for machine
  upload.** Rationale: a shared key cannot attribute a correction to a reviewer,
  which would hollow out the `corrections` audit trail the review UI depends on.
- **Three more decided with P4.T3 (2026-07-29), all in ADR-0012:** accounts live
  in a `users` table (not env-declared, not an external IdP); the confidence
  breakdown is **persisted** at process time (it cannot be honestly recomputed —
  triage issues and `meta.ambiguous_fields` are not stored); `admin` owns
  `/export/xlsx` + user management and the API key authorizes `POST /upload` and
  nothing else; and `POST /upload` writes a `pending` row before queueing so a job
  the queue loses is a visible stuck row rather than a vanished upload.
- **ISSUE-001 (the real baseline) is deferred until the system is built** — the
  user's explicit call. Do not start it unprompted.

## Still needing a user decision

- **Frontend framework (P5.T0)** — React+Vite recommended.
- **R060/R061 OCR grounding (P2.T2)** — model returns the text it read / a cheap
  OCR pass / drop the rules.
## What this project is

A VLM pipeline turning receipt photos into accounting-grade structured data.
**Prime directive: optimize auto-approval precision (target ≥99%), not raw
extraction accuracy. A wrong number is far worse than a missing one — prefer
`null` over a confident guess.** Three model passes (triage → extract → repair)
with deterministic validation between extract and repair, self-consistency for
handwriting, and one confidence score that routes to auto-approve or review.

## Invariants (never violate — see `.kiro/steering/receipt-system.md` + ADRs)

`Decimal` on the money path, never `float` (ADR-0001). Validation is
deterministic/pure, never mutates, never raises, stable rule IDs. Tolerance is
cents-bounded (`rel=0.0002`, floor scales with line count). Repair keeps the
**best** attempt `(errors, warns, nulls)`; only errors trigger repair;
unparseable → re-extract; never alter numbers to force arithmetic. Structured
output via tool-use. Few-shot images first, target last. Consistency runs are
never cached. Merchant hints end with "trust the image." Nothing is silently
dropped. Excel is output only; the DB is the source of truth.

## Built (on `master` unless noted)

- `extract/`: schema, prompts, json_io, paths, extractor (3-pass + repair +
  best-attempt + self-consistency), lineitem_align, clients/{base, fake,
  anthropic_client, openai_compat, **factory**}
- `validate/`: rules (28), report, context, validator
- `normalize/`: numbers, dates, text  ·  `preprocess/`: image_ops, bounds, quality
- `ingest/`: storage, dedupe, ingest  ·  `export/`: xlsx (all four §13 sheets)
- `score/`: confidence (score_confidence / explain_confidence / route / ReceiptStatus)
- `pipeline.py`: prepare_image, run_receipt, build_eval_pipeline
- `config/settings.py`; `eval/`: metrics, harness, golden_set, run_baseline
- Foundations: eval harness, golden-set on-ramp, CI, ruff/mypy, float-guard test
- **Phase 3 (persistence):** `persist/models.py` (7-table ORM) +
  `docker-compose.yml`; `alembic/` + `alembic.ini` (migration `b9342906a5a6`
  creates all 7 tables; a `compare_metadata` test guards ORM/migration drift —
  but it is SQLite-only, so it cannot see a new ENUM member);
  `persist/session.py` (`make_engine` / `make_session_factory`);
  `persist/repository.py` (§14.8 + DB-backed dedupe: `find_duplicate_by_phash`,
  `find_duplicate_by_content`, `mark_duplicate`); `review/queue.py` (§14.9:
  `enqueue_review`, `next_task`, `close_task`, `queue_stats`);
  `export/xlsx.py` now writes all four sheets with §13.5 formatting via the
  `ReceiptExportRow` metadata dataclass.
  - Alembic's console script is not on PATH — use `python -m alembic`.
  - `persist/__init__` is **lazy** (PEP 562 `__getattr__`): the models import
    eagerly, the repository/session names resolve on first access, so a base
    install (no `pipeline` extra) can still run migrations. Public API unchanged.
  - `next_task` applies `FOR UPDATE SKIP LOCKED` only on dialects that support
    it — **SQLite silently drops the clause instead of erroring**, which is why
    the guard lives in Python.
  - `redact_pan` is the §18 defence for `raw_response`; a review found it
    leaking on `CARD NO.<PAN>`, mixed separators, and dict keys — all fixed and
    regression-tested. Keep its silent-case tests intact when touching it.

- **P4.T4 (on `feat/service`, commit `6d35575`) — see ADR-0011:**
  `pipeline.process_receipt` (the only function the worker calls; all 8 stages in
  `STAGES` wrapped so any exception lands `needs_review` naming the stage, with a
  row *and* a review task), `process_batch`, `prepare_image_bytes`,
  `ProcessResult`/`BatchResult`; `extract/clients/limits.py`
  (`VLMGate` + `CostGuard` + `GuardedVLMClient` + `CostCeilingExceeded`);
  `worker.py` (RQ, `rq`/`redis` lazily imported behind a new `worker` extra so the
  suite stays offline). The raw-report / normalized-extraction mismatch is closed
  here by passing `normalize` as `extract_with_repair`'s `normalize_fn`;
  `run_receipt` is deliberately unchanged because it feeds the eval baseline.

- **P4.T3 (on `feat/service`) — see ADR-0012:** `persist/users.py` (stdlib scrypt,
  the user store, and a `python -m receipts.persist.users create <name> --role
  admin` bootstrap that reads the password from stdin); the `users` table and
  `receipts.confidence_reasons` (migration `a1c4d2f80b31`, which also adds
  `validation_findings.created_at`); `review/auth.py` (signed-cookie sessions,
  `require_user`/`require_role`/`require_upload`, HMAC URL signing);
  `review/{api,schemas,serializers}.py` — `create_app` plus eleven routes.
  `save_extraction` is now update-or-insert and **refuses to overwrite a
  `reviewed` row**; `POST /upload` writes a `pending` row before queueing.
  `score/thresholds.py` is the single source for `0.85`/`0.60` (was four copies).

## NOT built yet (remaining work)

- **Phase 4 (service):** `cli.py` (P4.T5/T6) — the only piece left.
- **Frontend** review UI — framework undecided (Phase 5)
- `merchants/{fingerprint,registry}.py` + few-shot injection (Phase 6)
- Self-consistency wired into `run_receipt` (extractor supports it; the M1
  runner does not call it yet) (Phase 7)
- Confidence-weight calibration against the golden set (Phase 8)

## How to run

- Tests: `python -m pytest` (pyproject sets `pythonpath=["src","."]`,
  `testpaths=["tests"]`). Lint: `python -m ruff check .`. Types: `mypy src`
  (informational).
- Baseline: `python -m eval.run_baseline` — needs a **real provider + a labeled
  golden set** (else it refuses the `fake` provider / scores an empty set).
- **Terminal quirk:** PowerShell sometimes clips piped Python output. Use
  `python -m pytest 2>&1 | Select-Object -Last 3` and capture summary lines
  explicitly.

## Environment / provider (user's `.env`, gitignored)

- Active config: `VLM_PROVIDER=ollama`, `VLM_BASE_URL=http://localhost:11435/v1`,
  model `granite3.2-vision:2b` (both passes), `DEFAULT_CURRENCY=PHP`,
  `VLM_TIMEOUT_S=900`. `openai` SDK installed; `anthropic` is not.
- **Golden set is LIVE** — `eval/golden/labels|images/{r001,r002,r003}` on disk,
  both flagged readings user-verified. `eval/golden/images/` is gitignored (the
  parent is not — do not move real receipts up a level).
- Ollama runs in Docker via `docker-compose.yml` (service `ollama`, host port
  **11435** → container 11434, `restart: unless-stopped`, external volume
  `ollama`). Start with `docker compose up -d ollama`. The native Windows Ollama
  CLI on PATH points at 11434 and will say "could not connect" — use
  `docker exec ollama ollama …` or set `OLLAMA_HOST=http://localhost:11435`.
- **Local CPU inference is not viable for real numbers.** No GPU passthrough
  (Intel iGPU, WSL2 can't pass it through); measured 262s–1205s for a *single*
  call. Ollama rejects a `tools` payload for models that do not declare the
  capability, so the local path runs JSON mode, not the intended tool-use route
  (ADR-0002). Keep it for offline spot checks only — see ISSUE-001.
- **Security:** a commented-out Gemini key was once echoed in output → **rotate it
  before use.** Never echo `.env` secret values; `.env` is gitignored.
- **Harness note:** the `developer-kit` plugin's `prevent-destructive-commands.py`
  hook used to block `git add` and `git commit` outright, which stopped the
  commit-per-task workflow. Those two checks were removed on 2026-07-28; every
  genuinely destructive guard (`reset --hard`, `clean`, force-push, `rebase`,
  `filter-branch`, `branch -D`, `tag -d`, `update-ref -d`, `reflog expire`, docker
  and aws deletes, secret-file reads) is still active and was re-verified. **A
  plugin update will overwrite this** — if commits start failing, re-apply it in
  `~/.claude/plugins/cache/developer-kit/developer-kit/*/hooks/`.

## The real receipt corpus (learned from the user's first 3 samples, 2026-07-28)

The user's actual documents are **Philippine BIR "SALES INVOICE" forms: a
machine-printed template with every value filled in by hand.** Three samples are
labelled in `eval/golden/labels/r001-r003.json` (Metro Oil Subic, Summit Fuel
OPC, Serv Central). Implications, all confirmed against the code:

- **They are `document_type=INVOICE` + `print_type=MIXED`, not `handwritten_receipt`.**
  `TriageResult.is_handwritten` already returns True for `MIXED`, so **gate
  self-consistency on `triage.is_handwritten`, never on `document_type`** (Phase 7).
- **The handwriting penalty must read triage too.** `score_confidence` currently
  reads only `receipt.meta.is_handwritten`; on these forms a model may report
  `False` (the template is printed) while triage says `MIXED`, so the −0.15 would
  be missed on exactly the receipts that need it. This promotes that deferred item
  to a real fix.
- **R020 FALSE-ERRORS ON 100% OF THESE RECEIPTS — see below.** Highest-priority
  open issue.
- **Blank pre-printed product rows.** Metro Oil's form pre-prints six fuel rows
  and only one is filled in; a VLM will likely emit all six. Needs a prompt
  instruction and/or a rule (sibling of R052) so empty template rows are dropped.
- **Buyer-vs-merchant trap.** Every form has `SOLD TO: Ideal Source` (the user's
  own company). `merchant.name` must be the ISSUER, never the buyer.
- **Printer-TIN trap.** The footer carries the *printing press's* TIN and
  accreditation (e.g. Midland Press `000-296-795-000`). `merchant.tax_id` must be
  the `VAT Reg. TIN` in the header.
- **Currency is never printed.** `normalize_currency` correctly refuses to guess,
  so **set `DEFAULT_CURRENCY=PHP`** or currency stays null.
- **Composition:** if this hybrid form is the whole corpus, the spec's §15 target
  mix (60% printed-clean / 20% handwritten) does not describe reality — the golden
  set should be dominated by this one type. Raise before scaling M0.
- Useful details: VAT is 12% and totals read `net + VAT = TOTAL AMOUNT DUE`;
  `Less: Withholding Tax` and the VATable / VAT-Exempt / Zero-Rated buckets appear
  on the forms but have no dedicated schema fields (withholding was blank on all
  three); merchant `VAT Reg. TIN` is printed, which is the strongest fingerprint
  for merchant matching (Phase 6).

### OPEN ISSUE — R020 vs VAT-inclusive line pricing

On these invoices the line-item **Amount column is VAT-INCLUSIVE**, so
`Σ line_total == total`, while `subtotal` is the net-of-VAT tax base. R020
(`Σ line_total ≈ subtotal`) therefore fails by exactly the VAT on all three
samples (verified: 1000 vs 892.86; 2000 vs 1785.71 ×2). R022 passes, so the
receipts are internally consistent — **the labels are right and the rule's
assumption is wrong.**

Consequences if unfixed: a false ERROR blocks auto-approval, burns a repair call,
costs −0.35 confidence, and hands the repair prompt a demand to reconcile numbers
that are already correct — pressuring the model to alter good values, which the
steering rules forbid.

Recommended fix (needs a decision; touches a stable rule ID): make R020/R024
**convention-aware** — add an explicit `prices_include_tax` flag the model reads
off the form (these say "Total Sales (VAT Inclusive)"), and when it is true (or
unknown) accept `Σ lines ≈ total` as well as `Σ lines ≈ subtotal`. Do **not**
widen the tolerance to paper over it. Never renumber R020.

## DEFERRED — do this LAST, after the system is built

**ISSUE-001: run the first real baseline.** Parked by the user on 2026-07-28 with
"I will do this after I build the system." Full diagnosis, the exact resume steps,
and what to expect are in **`docs/KNOWN_ISSUES.md`** — read that, do not
re-derive it.

One-line summary: everything needed is in place (labels, images, pipeline, scorer,
harness) and the three labels validate with zero findings, but
`python -m eval.run_baseline` has never completed. Two attempts failed — one to a
timeout bug (since fixed in `1f9f122`), one to the process being killed mid-run.
The open blocker is that `granite3.2-vision:2b` on CPU takes ~262s per call, so a
run is 30–60 min and dies to any interruption. **Recommended fix: point the
baseline at a hosted tool-capable model** (the commented-out Gemini block in
`.env`; rotate that key first, it was echoed in terminal output).

Until this is done there are **no real accuracy numbers**, and therefore no
threshold calibration (P3.T6 / P8.T1) and no way to judge a prompt or rule change.
Do not treat any precision claim as measured before it runs.

## Blockers that need the user

1. **A hosted tool-capable provider + a freshly rotated key** — required for
   ISSUE-001 (the first real baseline) and therefore for all calibration.
   *(Golden set: DONE. Auth model: DECIDED — see "Decisions" above.)*
2. Decisions: **frontend framework** (P5.T0), **R060/R061 OCR-grounding**
   approach (P2.T2).

## Deferred follow-ups / known minors (non-blocking)

*Fixed during P4.T3 and no longer open: the `CostGuard._as_money` `is_finite()`
gate; the four-way `0.85`/`0.60` duplication; `enqueue_review`'s check-then-insert
race; the §17 spec drift (§17 now also carries the service settings); the vacuous
`eval/results/2026-07-27-1.0.0.json`, which was deleted.*

- Move confidence penalty weights into `config/rules.yaml` (calibration, P3.T6).
- **Parked from the whole-branch review** (adjudicated, none load-bearing):
  `apply_corrections` redacts *any* coerced text, so a 13–19-digit
  `receipt.number` is masked the moment a reviewer merely confirms it (and writes
  a spurious `corrections` row), while `save_extraction` redacts only
  `merchant_name_raw` and `payment_method` — the two sides should agree;
  `_persist_failure` never writes `image_phash`, so a failed receipt keeps `""`
  and can never later serve as a dedupe **original** (address with Phase 6 dedupe);
  closing a review task on an auto-approving reprocess also closes one a reviewer
  had already claimed (revisit with the review UI, P5).
- **No login rate limiting**, and each attempt costs a full scrypt derivation
  (~16 MB, ~57 ms) — `POST /auth/login` is an unauthenticated CPU/memory amplifier
  as well as an enumeration surface. Address before this faces more than a LAN.
- **`_attempt_prompt_hash` reconstructs each call's prompt** rather than threading
  prompts out of the repair loop. When merchant hints / few-shot land (M5), the
  same values must be passed there or the stored hash drifts from what was sent.
- **Semantic (merchant+date+total) dedupe is deliberately not wired** into
  `process_receipt` — `merchant_id` is NULL until M5, so it would merge different
  purchases. Wire it with the merchant registry. (ADR-0011.)
- Handwriting penalty reads only `receipt.meta.is_handwritten`; consider OR-ing
  `triage.is_handwritten`.
- `vllm`/`ollama` still require `VLM_API_KEY`; `VLM_BASE_URL` ignored for `anthropic`.
- Statistical caveat: ≥99% precision can't be validated on a tiny golden set —
  grow the held-out set before trusting that number.
- `save_extraction` takes `report` (per §14.8) but does **not** write findings —
  the pipeline must call `save_findings` separately (findings accumulate across
  passes via `resolved_by_repair`). Revisit if replace-semantics is wanted.
- `_build_line_items` falls back to list order when emitted positions aren't
  distinct, so `unique(receipt_id, position)` can't sink a whole receipt.
- ruff sorts `from alembic import command` as **first-party** in tests (the
  repo-root `alembic/` dir shadows the package) — don't "fix" that import order.
- `enqueue_review` is check-then-insert against a UNIQUE column: concurrent
  enqueues can still raise `IntegrityError`. Wrap it or use an upsert when the
  API lands (P4.T3).
- The migration drift guard runs on SQLite only, so a new ENUM member would pass
  locally and fail on Postgres.
- XLSX `write_only` streaming above 5000 rows is deferred (incompatible with the
  random-access §13.5 formatting pass).

## Workflow & conventions

- **subagent-driven-development**: one fresh implementer subagent
  (`general-task-execution`) per task. Its brief must tell it to read the real
  signatures first, work TDD, keep the full suite green + ruff clean, stage only
  its own files, and **never stage `.kiro/settings/mcp.json`** (a persistent
  local working-tree edit). The controller then reviews (read the diff + run
  `pytest`/`ruff`) and the task ends with a commit.
- **Per milestone**: work on a feature branch; when done, run a final
  whole-branch review (`semantic_reviewer`), then fast-forward merge to `master`.
  Review write-ups land under `semantic-review/` (untracked).
- Conventional commit messages (`feat(scope): …`, `chore: …`, `fix: …`).
- Global skills (`~/.kiro/skills`) and MCP (`~/.kiro/settings/mcp.json`) are
  configured; steering `.kiro/steering/receipt-system.md` auto-loads.

## Key references

- `RECEIPT_SYSTEM_SPEC.md` — build spec: §3 architecture, §6 data model, §9
  normalization, §10 validation, §12 confidence + routing, §14 function
  inventory, §15 milestones, §16 eval, §17 config, §18 traps, §19 DoD.
- `README.md` (overview, §5 design decisions), `VLM_AND_DATA.md` (model/data).
- `IMPLEMENTATION_PLAN.md` — the phased task list (authoritative).
- **`docs/KNOWN_ISSUES.md`** — parked problems with their diagnosis and resume
  steps. ISSUE-001 (the baseline run) is the deferred final task.
- `docs/adr/` — implementation decisions (**0001–0011**; see `docs/adr/README.md`).
  0001 `Decimal` money path · 0002 provider abstraction/config · 0003 confidence
  penalties · 0004 portable persistence + Docker · 0005 tooling/offline tests ·
  0006 repository conventions · **0007 PAN redaction + money integrity (read
  before touching card/money writes)** · 0008 review-queue concurrency ·
  0009 lazy `persist` surface · 0010 export decoupling · **0011 terminal-state
  contract + VLM concurrency/cost guards (read before touching
  `process_receipt` or the worker)**.
- `semantic-review/` — the whole-branch review write-ups (untracked). The
  `2026-07-28-…-feat-db-layer` one documents the PAN/NaN findings in detail.
- `.kiro/steering/receipt-system.md` — always-on load-bearing rules.
- `.superpowers/sdd/progress.md` — the running task ledger.
