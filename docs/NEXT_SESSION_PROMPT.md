You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone. ADR-0019 made the refresh part of
closing a milestone; **ADR-0021 makes it part of ending any session**, and its
2026-08-02 correction widened the freshness check after a docs-only task proved
invisible to it. This verification step is permanent.

**No branch is in flight.** The PAN grouping milestone is **complete and merged**
(2026-08-02, true fast-forward `1d9f3e3` → `0d6cea2`). `feat/pan-grouping` is
kept at its merge point and pushed; merged branches and SDD workspaces are never
cleaned up.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, what is built,
   the environment, blockers, deferred and parked items.
2. **`.superpowers/sdd/2026-07-31-pan-grouping/progress.md`** — the completed
   ledger of the PAN grouping milestone: every measurement, both user rulings,
   all four task entries with what the controller re-verified itself, the
   whole-branch review, the fix wave, the re-review, and the six
   plan-versus-reality defects. Open it before touching anything PAN-adjacent.
   `.superpowers/sdd/2026-07-31-pan-hardening/progress.md` holds the previous
   milestone's follow-ups; `.superpowers/sdd/2026-07-29-review-ui/progress.md`
   holds the Phase 5 parked items behind task 3. **Note: `.superpowers/` is
   gitignored, so nothing in it is findable by searching the tracked tree — you
   must open it by path.**
3. **`docs/adr/README.md`, then the ADRs it indexes (0001–0021).** Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything touching money.
   - **0018 then 0020, including 0020's dated correction (2026-08-02)** —
     **anything touching `_PAN_RE`, `_mask_pan`, or `redact_pan`.** 0018
     supersedes 0007 on the masking rule; **0020 supersedes 0018 on the
     detector shape** and is the current record of which groupings are covered
     and which residual is accepted; its correction records the real
     false-positive surface of the `{1,2}` separator cap. 0007 still governs
     money integrity and bounded text and carries two dated corrections.
   - **0006** repository conventions (injected session, **caller commits**,
     `ValueError` boundary) — anything writing to the DB.
   - **0011** terminal-state contract + VLM concurrency/cost guards.
   - **0012** review API: identity, the `pending` row, the persisted confidence
     breakdown, and **"a machine run never overwrites a `reviewed` row"**.
   - **0013** CLI contract, including `calibrate`'s three gates.
   - **0014** optional-dependency import discipline — **anything adding an
     import to a module reachable from an entry point.**
   - **0015** the review UI: same-origin serving, the `/app` prefix, the guarded
     static mount, money as a string in the browser.
   - **0016** `GET /review/next` resumes the caller's own in-progress task —
     anything touching `review/queue.py` or the claim lifecycle.
   - **0017** two test suites and `scripts/verify.py` — **read before believing
     a green test run.**
   - **0019 + 0021, including 0021's dated correction** — session continuity:
     where state lives, the promotion rule, the two-position stamp, the widened
     freshness check, and why this snapshot must be verified rather than
     trusted.
   - **0002** provider abstraction · **0008** review-queue concurrency.
4. **`.kiro/steering/receipt-system.md`** — the always-on load-bearing rules.
   Still auto-loads and is on disk, but **gitignored and untracked**.
5. **`docs/superpowers/plans/2026-07-31-pan-grouping.md`** and
   **`docs/superpowers/specs/2026-07-31-pan-grouping-design.md`** — only if
   touching the PAN detector area. The design's §4 battery, §5 residual and the
   §2.2/§4.6 dated corrections are the measured record.
6. **`IMPLEMENTATION_PLAN.md`** — the authoritative phased task list.
7. **`docs/KNOWN_ISSUES.md`** — ISSUE-001 (the deferred baseline), with its full
   diagnosis and exact resume steps. **Do not re-derive it.**
8. **`RECEIPT_SYSTEM_SPEC.md`** as needed: §6 data model (**eight** tables),
   §8.5 repair, §9 normalization, §10 validation/tolerance, §12 confidence +
   routing, §13 Excel, §14 function inventory (§14.8 repository, §14.9 review
   API, §14.10 the CLI), §15 milestones, §16 eval, §17 config, §18 traps
   (**PAN handling**), §19 DoD.
9. Older design docs, only if touching what they cover:
   `docs/superpowers/specs/2026-07-31-pan-hardening-design.md` (§1.2 the TIN
   constraint, §2.1 the ruling, §4 the measured battery),
   `docs/superpowers/specs/2026-07-29-review-ui-design.md`,
   `docs/superpowers/specs/2026-07-29-cli-design.md`,
   `docs/superpowers/specs/2026-07-28-review-api-design.md`.

## Where we are

- **`main` @ `0d6cea2` (last code commit), PUSHED and in sync with
  `origin/main`**, with this handoff refresh as a docs-only commit on top. No
  branch is in flight. A stamp cannot name the commit that writes it, so the
  check is a command (ADR-0021, as corrected 2026-08-02 — docs are now
  included, with the handoff pair itself excluded):

  ```
  git log --oneline 0d6cea2..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved after
  it was written.

**Phases 0–5 are complete, plus PAN hardening (merged) and PAN grouping
(merged).** The PAN grouping milestone's twelve branch commits, headline:

| commit | what |
|---|---|
| `d529b0f` | design doc, **ADR-0020**, ADR README |
| `b8666f0` | the implementation plan, four tasks |
| `348b509` | **Task 1** — the detector, its behavioural tests, five falsified prose passages |
| `a883df6` | **Task 2** — two structural guards, the worked-example pin, the residual pin |
| `b3f5dbd` | **Task 3** — ReceiptForm's redaction table, re-measured through the real `PATCH` route |
| `71e42a1` | **Task 4** — ADR-0007's "a hash" bullet pointed at its dated correction |
| `d7667c1` `3d7ae19` `0d6cea2` | **the consolidated fix wave** after the whole-branch review |

**Gates at `0d6cea2`, re-measured by the controller, not taken from a report:**
`python scripts/verify.py` **all five PASS**; pytest **916/0/0/0** read from
junitxml; Vitest **170**. `main` and the branch are the same commit, so those
are `main`'s numbers.

### What shipped, and what it does not claim

`_PAN_RE` recognises **seven separated shapes** — `4-4-4-N`, Amex `4-6-5`,
Diners `4-6-4`, Maestro/legacy-Visa `4-4-5`, and the hand-written `5-4-4-4`,
`6-4-4-4`, `4-5-4-4` — plus the unseparated form, and the separator accepts one
or two characters (`{1,2}`). Each fixed-shape alternative has a digit total
inside 13–19, so `_mask_pan`'s length check stays unreachable **by
construction** — pinned structurally, with the lead-3 guard now sweeping **all
42** separator spellings the pattern accepts.

**It did not close the class, and saying so would be false.** Against the
plausible band (every group 4–7 digits, totalling 13–19, 97 shapes): **15
compliant / 76 storing a whole card**, pinned by
`test_redact_pan_still_stores_some_groupings_whole` so the gap reads as a
decision. ADR-0020 carries the number.

**The `{1,2}` cap's real cost is 36 two-character spellings, 30 of them mixed**
(`', '`, `'. '`, `'./'`, …), every one firing where the baseline was silent —
measured: `'PO 4500, 4501, 4502, 4503 RECEIVED'` →
`'PO ************4503 RECEIVED'`. The original "one more spelling" claim was
found false by the whole-branch review and corrected by dated appendix
(ADR-0020) and in the design doc; the surface is pinned by
`test_column_amounts_separated_by_two_characters_are_the_cost_of_the_cap`.
The false-positive *class* (column-scale amounts side by side) is pre-existing;
the surface widened. **Whether to narrow the separator (e.g. to doubling only)
is a queued user decision — see "Blocked on me".**

**The load-bearing lesson (ADR-0020): coverage and cross-boundary risk move
together.** A generalised alternative covered 80 of 97 shapes and **leaked a
full second card** by tiling a `4-6-5-4` span across two adjacent Amex numbers
— `re.sub` never rescans inside a match. An earlier form failed 13 committed
battery tests. **Any shape added to `_PAN_RE` requires the two-instance check,
every time.** The whole-branch review re-ran that check over **146,410**
two-instance inputs: zero leaks, zero regressions.

**Alternation order is NOT load-bearing** — the trailing `(?!\d)` rejects
truncated matches; measured, three orderings identical. Do not preserve the
committed order out of superstition.

### Running it

- **There are two test suites.** `python -m pytest` (**916**; offline and
  Node-free) and **Vitest in `frontend/`** (**170**).
- **`npm test` does NOT type-check.** Run `npm run typecheck` too. That trap
  fired three times in one milestone.
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. **ADR-0017.**
- **Piped pytest output can lose its final summary line in this environment.**
  The `superclaude` attribution remains **unproven**. Workaround regardless:
  `--junitxml` and read the counts from the XML.
- **The Grep tool mangles `/` in its content output in this environment**
  (`"/receipts/"` → `"\receipts\"`, `[ .\-_/,]` → `[ .\-_\,]`, inconsistently
  within one result). It nearly produced a false `_PAN_RE` defect report.
  **Verify any slash-sensitive claim with Read, `git grep` via Bash, or by
  executing — never from Grep-tool output.**
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is not on this machine.
- The e2e is run deliberately, not as part of the sweep:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

### Git

- Default branch **`main`**, remote `origin` → `CDGYu/Receipt-Digitalization`,
  **public**. `main` is pushed and in sync as of this stamp.
- **Pushing `feat/*` branches is authorised. Ask before pushing `main`** — the
  2026-08-02 push was a one-time authorization for the PAN grouping merge.
- **`.kiro/` and `.github/workflows/` are gitignored and untracked.** GitHub
  Actions does not run; `scripts/verify.py` is the substitute, and **nothing
  runs the frontend gates on GitHub.**
- **`var/` is gitignored** — `STORAGE_ROOT` defaults to `var/blobs` and writes
  real receipt images there. Never stage one.

## Non-negotiables

`Decimal` on the money path (never `float`); deterministic, pure validation that
never mutates and never raises; stable rule IDs; prefer `null` over a confident
wrong value; **a full PAN never persisted**; nothing silently dropped (every
receipt reaches a terminal state); **a machine run never overwrites a `reviewed`
row**; no module-top import of an optional extra on any path reachable from an
entry point; structured output via tool-use; few-shot images first, target
receipt last; consistency runs never cached; `python -m pytest` stays **offline
and Node-free**.

**PAN (ADR-0018 + ADR-0020 + 0020's correction):** the group-shape requirement
in `_PAN_RE` is load-bearing. Three of the four real corpus TINs are 14 digits,
inside the PAN window; what keeps them silent is that **every alternative opens
with a group of at least four digits while every corpus TIN opens with three**
— pinned across the whole shape space by
`test_pan_re_never_starts_a_match_at_a_three_digit_group` (now sweeping all 42
separator spellings). **Never relax it toward "any run of 13+ digits."** Any
`_PAN_RE` change replays the **committed** battery in both directions, tests
**two instances of what it guards in one input**, and keeps
`test_every_pan_re_match_holds_between_thirteen_and_nineteen_digits` green.
Note: the 42/36/30 separator-surface counts quoted in comments and corrections
are **unpinned** — pinning `len(_ALL_SEPARATOR_SPELLINGS) == 42` is a queued
one-liner (task 8).

**Frontend (ADR-0015):** money is a string end to end and
**`<input type="number">` and `valueAsNumber` are banned**; the browser stays
same-origin so **no `CORSMiddleware` is ever added**; SPA pages live under
`/app/*` and no API path moves.

## The work, in order

### 1. Bound the machine-path `currency` write

`save_extraction` writes `currency=receipt_meta.currency` **directly** into a
`String(3)` column. **Reproduced by measurement:** `ReceiptMeta.currency` is
`str | None` with no constraints; `Receipt.currency` is `String(3)`; the human
path (`receipt.currency` → `_bounded_optional_text`) raises
`ValueError: currency holds at most 3 characters, got 16`; and
`repository.py` (in `save_extraction`) passes the value through unguarded.
SQLite stores an over-long value silently; Postgres raises `DataError` — a
receipt-killing exception on the machine path. Same shape as leak (d): a guard
the human path has and the machine path lacks. Wire the bound into
`save_extraction`.

### 2. Fix the intermittent test's fixtures — the diagnosis is done, stop re-deriving it

`tests/test_cli_pipeline.py::test_inline_one_failing_receipt_does_not_abandon_the_others`
is **NOT** flaky-by-ordering. **pytest-randomly is not installed** (pytest11
entry points on this machine: `anyio`, `superclaude`). It is a **load-sensitive
thread race in the test's own fixtures**: `_job` calls `_png_bytes()`, which
returns a **byte-identical** uniform 900×1400 PNG every time, so three receipts
share a sha256 and a phash → whichever commits first makes another a dedupe
duplicate → `REJECTED` where the test expects `AUTO_APPROVED`. Reproduced 11/12
under six CPU burners; corroborated twice by fresh agents hitting it unprompted.
**Fix: distinct blobs per receipt in the fixture.** Do not chase test ordering.

### 3. Phase 5 follow-ups, each a named piece of work

- **The five design §5 error-recovery behaviours that never shipped** — no
  logout control anywhere, no return-to-receipt after a 401, no inline
  field-level error on a 400 (one page-level alert instead), no distinct
  backend-down 503 state, no re-fetch-`next` on 403/404. The plan dropped design
  §5's error table wholesale, so no task owned any of them.
- **A read route for the `corrections` table.** The audit trail is write-only
  from the API's perspective. Additive; needs its own auth question.
- **An ASGI entry point and a deployment story.** `create_app` is a factory
  nothing calls — **verified: there is no `app = create_app(...)` anywhere under
  `src/`**; the only callers are tests plus the deliberately e2e-scoped
  `scripts/serve_review_e2e.py`. Do not promote that script without deciding
  the settings, session, storage and host policy on purpose.
- **An admin release for a claimed task** (`IN_PROGRESS` → `OPEN`). There is no
  inverse of a claim anywhere in the system.
- Smaller parked items are listed in the Phase 5 ledger with rulings:
  `ReviewScreen.tsx` citing `queue.py:198-199` for writes at `:289-290`; no UI
  route reaching a skipped receipt; 405 responses under `/app` carrying no
  `Allow` header; two tabs of one reviewer silently overwriting each other;
  `ReviewScreen.tsx` past its size ceiling; `preventDefault()` firing on
  screens with no approve action.

### 4. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` — **verified: `src/receipts/merchants/`
does not exist, this is greenfield.** Inject verified few-shot examples with
**images first, target receipt last**; hints always end with "trust the image".
Measure top-10-merchant accuracy before/after. **Five things unblock here:**
wire semantic merchant+date+total dedupe into `process_receipt`; pass the same
hints/few-shot values into `_attempt_prompt_hash` or the stored hash drifts; set
`merchant_default_currency` at the marked plug-in point (**verified at
`pipeline.py:227`**); address the `image_phash` gap (a receipt that fails after
ingest keeps `""` and can never serve as a dedupe **original** — see MEMORY.md's
dated correction for the precise mechanism); and increment
`Merchant.receipt_count`, which **nothing in `src/` writes today (verified)**.
Merchant `VAT Reg. TIN` is the strongest fingerprint on this corpus.

### 5. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (**verified at `extract/extractor.py:295`, zero
references in `pipeline.py`**) into the pipeline for handwritten /
low-legibility receipts, and feed disputed fields into scoring. **Gate on
`triage.is_handwritten`, never on `document_type`** — this corpus is `INVOICE` +
`MIXED`. Consistency runs are never cached.

### 6. Phase 8 — calibration & eval-harness honesty

- **P3.T6 / P8.T1** — sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data into
  `config/rules.yaml`. **Blocked on ISSUE-001.**
- **P8.T2** — grow the held-out set until a ≥99% claim has a credible confidence
  interval. `receipts calibrate` refuses below `_MIN_APPROVED_SAMPLE` (5), so
  with 3 golden labels it correctly refuses today.
- **P8.T3 — close the artifact ban properly.** An **all-failed** eval run still
  persists `"auto_approval_precision": 1.0` to the results JSON even though the
  terminal prints `n/a`. Widening the field ripples into `_report_to_dict`, the
  committed schema, and `calibration_curve`. Also consider excluding `meta.*`
  from `field_accuracy`'s denominator.

### 7. Still open from earlier phases

- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing produces. Options: have the model return the
  text it read / a cheap OCR pass / drop the rules. **This also gates bbox
  highlighting in the review UI** — an OCR pass would supply both.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — declared at **`extract/schema.py:201`
  (verified)**, referenced only in prompts. The §3 "reject garbage before you
  pay for extraction" gate does not exist. It returned `False` for valid
  invoices on both smoke-run receipts, so when the gate is built it must **not**
  hard-reject on it; route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.

### 8. Parked, with rulings (see the ledgers)

**Two queued PAN scoped decisions — raise each as its own decision, do not fold
them into other work:**

- **The grouping residual** (ADR-0020): 76 of 97 band shapes still store a
  whole card. Two priced routes: a shape table with a per-entry two-instance
  gate, or a candidate-then-validate scan loop at O(n²) (~1715 ms on 40 KB).
- **The separator surface** (ADR-0020's 2026-08-02 correction): `{1,2}` admits
  36 two-character spellings, 30 mixed, all pinned as accepted today; narrowing
  (e.g. to doubling only) would re-silence the mixed spellings at the cost of a
  more complex class and a battery update.

**Parked from the PAN grouping close (bundle with the next legitimate edit of
`tests/test_repository.py`):** the range-guard docstring's "about 30x"
multiplier (measured 19.6x — its own absolute figures contradict it); the mixed
pairs' coverage rationale says "width changing mid-run" where the sweep joins
every gap with the same spelling (they actually cover heterogeneous
two-character gaps); pin `len(_ALL_SEPARATOR_SPELLINGS) == 42` so the 42/36/30
counts in prose fail loudly on a widening; the module docstring's "a digit run
that reaches thirteen masks" is exact only within the 16-hex domain (a run
past 19 does not mask); ADR-0018's References still name the nonexistent
`MUST_MASK`/`MUST_STAY_SILENT` battery (0020's correction discloses the real
identifiers; 0018 is immutable — a future dated correction may add a pointer).

ADR-0018's **accepted false positives** remain: a 13–19 digit all-numeric
identifier; column-scale amounts side by side in one free-text value (the
`{1,2}` cap widened this surface — see above); ~1-in-200 random 16-char hex
hashes, which is why **no hash is ever routed through `redact_pan`**; a
whole-number 13–19 digit modifier amount. A reviewer confirming a 13–19-digit
`receipt.number` will see it masked and a spurious `corrections` row minted —
inherent to the policy. Leak (b) — a run of more than four groups leaving its
remainder in the clear — stays **accepted by ruling**, its four pinned cases
unchanged.

Also parked: an auto-approving reprocess closes a review task a reviewer had
already claimed. **No login rate limiting**, and each attempt costs a full
scrypt derivation (~16 MB, ~57 ms), so `POST /auth/login` is an unauthenticated
CPU/memory amplifier as well as an enumeration surface. `receipts eval`/
`calibrate` still traceback without the `pipeline` extra while the other six
commands degrade cleanly. Reprocessing a `reviewed` receipt records **no**
`extraction_runs` — the transaction rolls back. The `superclaude`
stdout-clipping attribution is **unproven** — re-measure before writing it
anywhere as fact.

### 9. LAST — ISSUE-001, deferred by the user until the system is built

**Run the first real baseline.** Read `docs/KNOWN_ISSUES.md`; do not re-derive.
The smoke run proved the pipeline works end to end and that the safety machinery
does not auto-approve garbage — a bad extraction scored `0.000` and routed
urgent. It also proved `granite3.2-vision:2b` on CPU is too slow *and* too weak:
314 s triage + 1057 s extract at `max_edge=768`, extraction effectively empty.
Fix: point the baseline at a hosted tool-capable model (the commented-out Gemini
block in `.env` — **rotate that key first**, it was echoed in terminal output).
Until this runs there are **no measured accuracy numbers**, calibration stays
blocked, and **no precision claim is real**.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution. One fresh **`general-purpose`** implementer per task,
briefed to read the real signatures first, work TDD, keep both suites green +
`python -m ruff` clean, and stage only its own files. After each task: review the
diff yourself, re-run the gates **independently**, then a task review, then
commit and append to the ledger. At the end of a milestone: a whole-branch review
on the strongest model, **one** consolidated fix wave, one scoped re-review, then
fast-forward merge — **and refresh `docs/MEMORY.md` + this prompt in the same
session (ADR-0019).** **If a session ends mid-branch, refresh the pair anyway and
push the branch (ADR-0021).** Merged branches and SDD workspaces are **kept**.

**Probe before dispatching.** Phase 5's plan was wrong about existing code
**eleven times**; the PAN hardening plan repeated it; the PAN grouping plan
finished at **six** (a lint-breaking snippet, a miscounted prose list, a
nonexistent import, a control row that was never in the table, a sentence
quantifying over a table the plan grew without re-measuring, and an unqualified
hash claim in a file the plan never searched). All six were the controller's;
all were caught by implementers or probes that read the artefacts first. A
controller dispatch prompt introduced a seventh of the same class ("random"
attached to crafted probe values) — caught by the implementer measuring. The
plan's prose is reliable; its claims about existing artefacts are not.

## Review standards this project learned the hard way — hold all of them

1. **Reviewers reproduce, they do not reason.** Every finding that mattered came
   from executing something.
2. **Every new test must be proven to fail** with its fix reverted.
3. **A test that asserts the absence of breakage cannot be proven by a RED run** —
   revert each guarantee separately instead.
4. **A mutation must change exactly one thing, or the result names the wrong
   cause.**
5. **If a number can change without its sentence changing, it does not go in the
   comment.**
6. **A claim about what your own artefacts say is itself a claim requiring a
   command.** Grep for the word; do not recall it.
7. **Do not credit a tool with settling a question you have not put to it.**
8. **A stub that does not reflect the write is a fixture bug that lies dormant
   until something reads the reply.**
9. **Test a guard with two instances of what it guards in one input.**
10. **A battery you write agrees with you.** Replay the *committed* battery in
    both directions before trusting a change.
11. **Coverage and cross-boundary risk move together** (ADR-0020).
12. **Adding rows to a prose table also changes every sentence that quantifies
    over the table** — the falsified sentence is an unchanged line, invisible to
    `git diff` and every gate. Re-measure or narrow those sentences with the
    rows (found when Task 3's new rows silently extended the `payment.method`
    claim; closed by measuring all eight spellings on that path too).

And the environment lesson: **a green suite is not evidence that installed
software works.** Anything with an entry point gets run from outside the
repository as part of verification.

## Blocked on me (the user) — surface these, do not guess

1. **Do the public golden labels need scrubbing?** The repo is public and
   `eval/golden/labels/r00*.json` carry real third-party business names, TINs
   and addresses — which are also the exact values the PAN silent-case tests
   pin, so scrubbing is not free.
2. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001,
   and therefore for all calibration.
3. **R060/R061 grounding (P2.T2)** — which also gates bbox highlighting.
4. **Whether GitHub Actions should run again** — `.github/workflows/ci.yml` is
   untracked, so nothing runs the frontend gates remotely. If yes, the workflow
   should call `scripts/verify.py` rather than re-listing the gates.
5. **Whether to close the PAN grouping residual**, and by which of the two
   priced routes — see task 8.
6. **Whether to narrow the `{1,2}` separator** now that its real surface is
   measured and pinned — see task 8. Related to, but separable from, item 5.

**Today's goal:** <FILL THIS IN — the default is "task 1: bound the machine-path
`currency` write.">
