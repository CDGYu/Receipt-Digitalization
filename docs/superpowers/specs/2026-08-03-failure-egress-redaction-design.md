# Failure-egress redaction: no raw model text leaves the process in a failure

**Date:** 2026-08-03
**Branch:** `feat/failure-egress-redaction`
**Baseline:** `main @ 3c5a86d` (last code commit `f04aa65`)
**Governing ADRs:** 0006 (the `ValueError` boundary — unchanged; only the text
hygiene of what escapes it changes), 0007 (the original redaction decision;
superseded on the masking rule by 0018), 0011 (the terminal-state contract —
untouched; this branch changes no control flow), 0017 (what "passing" means),
0018 (the sink-redaction philosophy this extends one level out). A new
**ADR-0022** records the egress rule (§8).

One defect class, surfaced by the 2026-08-03 whole-branch review of the
currency-bound branch as an out-of-scope, **pre-existing and live-reachable**
finding, then mapped in full by this brainstorm's probes. Scoped by user
rulings (2026-08-03): **the full egress class** is closed on one branch; the
failure log keeps its traceback **rendered and redacted** rather than dropped
or raw; the design was approved as presented, all four guarantees included.

---

## 1. The chain, measured

### 1.1 Producers — exception text that quotes raw model values

- The reviewed-row guard (`repository.py:613-618`) interpolates
  `merchant={extraction.merchant.name!r}` **and** `total={extraction.totals.total}`
  into its `ValueError`. **Live-reachable**: `POST /upload` writes the
  `pending` row before queueing, so a reviewer can re-key the receipt off the
  paper before the worker arrives (`process_receipt`'s own docstring names
  this race), and `receipts reprocess` of a reviewed row takes the same path
  (`cli.py:950-958` exists precisely to report it).
- `_bounded_optional_text` (`repository.py:1064-1070`) quotes the overlong
  value that tripped it. Live-unreachable today (measured at the
  currency-bound close, revert-proof 7(b)); reachable for direct callers.
- **Any library exception the stage wrapper catches.** The sharpest instance:
  SQLAlchemy appends `[parameters: (...)]` — raw statement values, which on
  this schema are model text — to every wrapped DBAPI error, and
  `make_engine` (`session.py:37`) builds a bare `create_engine(resolved)`.
  Measured on this machine (2026-08-03, SQLite in-memory): a unique-violation
  `IntegrityError` from a plain engine **contains the PAN-valued parameter in
  `str(exc)`**; with `create_engine(..., hide_parameters=True)` it does not,
  and the message carries SQLAlchemy's parameters-hidden notice instead.

### 1.2 The carrier

`_StageFailure.__str__` is `f"{stage}: {type(cause).__name__}: {cause}"`
(`pipeline.py:356-358`). `_persist_failure` mints
`reason = _truncate(str(failure), _MAX_REASON_CHARS)` (`pipeline.py:761`,
limit 400 at `:103-105`, `_truncate` at `:844-845`) — **raw** — and also logs
`log.warning("Receipt %s failed at stage %r: %s", job.id, failure.stage,
failure.cause, exc_info=failure.cause)` (`:762-763`) — the raw cause **twice**,
since a rendered traceback embeds the exception's own message again.

### 1.3 The sinks

| Sink | Path | State at this baseline |
|---|---|---|
| `review_tasks.reason` | `enqueue_review` (`queue.py:180`) | **Redacted** — the one covered sink, §18 comment at `queue.py:176-179`, pinned by `test_enqueue_review_redacts_a_pan_inside_the_reason` |
| CLI stdout | `ProcessResult.reason` → `cli.py:857` (`process --inline`), `:957` and `:960` (`reprocess`) | Raw |
| **RQ result store (Redis, durable)** | `ProcessResult.reason` → `result_to_payload` (`worker.py:112-127`, its own docstring: "as something RQ's result store can hold") returned by `process_receipt_job` (`worker.py:216`) | Raw |
| Log file | the `log.warning` above, message + `exc_info` traceback | Raw, twice |
| **RQ failed registry (Redis, durable)** + CLI stdout | the nothing-could-be-written re-raise out of `_persist_failure` → RQ records the traceback; `cli.py:860` prints `f"{job.id}  failed  {exc}"` (`_UNCONTAINED` is only `(KeyboardInterrupt, SystemExit)`, `cli.py:240`) | Raw |

The review named the CLI stdout and the log; the probes added the two
durable Redis copies and the parameter-echo vector. Safe by construction and
untouched here: `route()`'s reasons are fixed §12 vocabulary
(`confidence.py:265-275`), the duplicate reason is
`f"duplicate of receipt {existing_id}"` (`pipeline.py:620`), ingest-rejection
reasons are system-minted (`ingest.py:107-135`), and the whole DB side (§18
blanket pass, `raw_response`, serializers) is already covered by ADR-0018.

## 2. The decision: four guarantees, one per egress

The mechanism is the one already recorded in the tree at `queue.py:176-179` —
"reasons are built from exception text… Redacting here covers every producer,
present and future" — applied to the three egresses that comment's sink does
not cover. Producers stay untouched (§3). No new machinery: no logging
filters, no wrappers, four point edits.

### 2.1 G1 — the carrier (`pipeline.py:761`)

```python
    redacted = redact_pan(str(failure))
    reason = _truncate(redacted, _MAX_REASON_CHARS)
```

`redact_pan` joins the existing `.persist.repository` import block
(`pipeline.py:62-69`). **Redact before truncate**: truncating first can cut a
PAN mid-shape into something `_PAN_RE` no longer matches, so the digits that
survive the cut pass the sink's redaction in the clear; redacting the full
string first retires that case everywhere downstream, including the queue
sink (whose input today is pre-truncated). Covers, in one line: both CLI stdout
sites, the reprocess refusal line, the Redis result-store copy, and every
future `ProcessResult.reason` consumer.

### 2.2 G2 — the failure log (`pipeline.py:762-763`)

```python
    log.warning(
        "Receipt %s failed at stage %r: %s\n%s",
        job.id, failure.stage, redacted,
        redact_pan("".join(traceback.format_exception(failure.cause))),
    )
```

No `exc_info`. The message logs the **untruncated** redacted failure text
(truncation is a review-UI concern, not a log concern) plus the full
traceback, rendered by stdlib `traceback.format_exception` (single-argument
form; this is Python 3.14) and redacted as text — the user's ruling: full
stack fidelity, zero raw model text. `import traceback` joins the stdlib
import block.

### 2.3 G3 — the engine (`session.py:37`)

```python
    engine = create_engine(resolved, hide_parameters=True)
```

Every runtime engine funnels through `make_engine` — verified callers:
`cli.py:141/1610`, `worker.py:41` + `build_deps` (`worker.py:175`),
`users.py:185/195`, `scripts/seed_review_e2e.py:145/167/293/295`,
`scripts/serve_review_e2e.py:73/90`, and the lazy `persist/__init__` surface
(`:55/:72/:95`). One flag therefore cleans the parameter echo out of every
SQLAlchemy error string this system can raise: the ones the stage wrapper
folds into `reason` (G1's input), the ones G2 renders in tracebacks, and the
ones the re-raise path hands to RQ's failed registry — the one durable sink
this branch cannot redact from our side (§5). Debuggability cost is the one
SQLAlchemy designed for: the error message itself says parameters are hidden
and names the flag.

### 2.4 G4 — the uncontained print (`cli.py:860`)

```python
            print(f"{job.id}  failed  {redact_pan(str(exc))}")
```

`_UNCONTAINED` is only `(KeyboardInterrupt, SystemExit)` (`cli.py:240`), so
every exception `process_receipt` re-raises — the nothing-could-be-written
class — lands on this line. With G3 those are parameter-clean already;
redacting the print is the belt for a non-SQLAlchemy infra exception that
embeds model text some other way. `redact_pan` joins `cli.py:140`'s existing
`.persist.repository` import.

## 3. What must not change

- **`enqueue_review`'s own redaction stays** (`queue.py:180`), as does its
  pinned test. It guards every *other* caller of `enqueue_review`, present
  and future; re-redacting G1's pre-redacted text is harmless by construction
  (masking can only mask — there is nothing left for a second pass to leak).
- **Producer messages stay.** The guard keeps quoting `merchant.name` and
  `totals.total`: that is recorded policy (`queue.py:176-179` and the queue
  test's docstring — "patching every producer would miss the next one"), and
  the redacted quote is deliberately useful to the reviewer reading
  `review_tasks.reason`.
- The §18 blanket pass, `_MAX_REASON_CHARS`, the `STAGES` vocabulary,
  `route()`'s reason strings, `_StageFailure.__str__`, and ADR-0011's
  raise/terminal semantics. **Zero control-flow change anywhere** — every
  edit replaces text with redacted text on an existing path.
- Test-local engines built directly with `sa.create_engine` and
  `alembic/env.py`'s own engine are not runtime egress and are out of scope.

## 4. The consumer-and-assertion sweep (the currency-bound branch's lesson, applied up front)

That branch's defect #7 was a suite-internal caller the design reasoned about
abstractly without grepping for; this design swept first (2026-08-03):

- In-suite assertions on failure text: `stage in result.reason`
  (`test_process_receipt.py:647`), `"cost" in result.reason.lower()` (`:806`),
  `failed_stage` equality checks (`:636/:646/:897/:930`,
  `test_worker.py:210/:230`), and the reprocess stdout tests
  (`test_cli_pipeline.py` around `:699-:760`). All are redaction-stable:
  stage names and words survive `redact_pan` untouched, and none of those
  fixtures puts PAN-shaped text into the failing path.
- Reasons that embed receipt UUIDs are stable too, and this is **already
  measured in the tree**: `test_enqueue_review_redacts_a_pan_inside_the_reason`
  passes an all-digit-UUID-bearing reason through `redact_pan` and asserts
  only the PAN moved.
- **No test pins the failure log's shape**: zero `caplog`/`exc_info` hits in
  `test_process_receipt.py`, `test_cli_pipeline.py`, `test_worker.py`. G2
  breaks nothing in-suite.
- Nothing in `tests/` relies on SQLAlchemy's `[parameters: …]` echo (the one
  `parameters` hit, `test_api_write.py:789`, is an event-listener signature,
  which `hide_parameters` does not affect).

## 5. Residuals, accepted and recorded

- **RQ renders the failed-registry traceback from the raw exception object**;
  that rendering is RQ's, not ours. G3 removes the known model-text vector
  (statement parameters); an infra exception that embeds model text by some
  other route would still reach that registry raw. Accepted.
- `redact_pan`'s accepted false positives (ADR-0018: ~1-in-200 16-hex tokens,
  13–19-digit runs, `4-4-4-N`-shaped groupings) now apply to log and
  traceback text. In a log line this is cosmetic; nothing parses these
  strings.
- stdout is ephemeral only until a service manager journals it — which is why
  G1/G4 treat it as an egress, not a display.

## 6. Tests

Standards 2/3/9 held: every failing-capable test proven RED with exactly its
own guarantee reverted, one variable at a time; the PAN fixture carries **two
instances in one value**.

1. **T1 (G1), end-to-end through the live-reachable producer:** a receipt
   whose row is `reviewed`, re-run through `process_receipt` with a scripted
   client whose extraction's `merchant.name` holds two PANs in one string.
   The guard fires at `persist`; assert `result.failed_stage == "persist"`,
   `result.reason` contains both masks and no run of 13+ raw digits, and the
   reason still respects `_MAX_REASON_CHARS`. **RED:** revert only G1's line
   (raw PAN appears in `result.reason`).
2. **T2 (G2), same run under `caplog`** (house pattern:
   `test_image_ops.py:157-168`): the WARNING record's rendered text contains
   the stage name and `Traceback (most recent call last)` — fidelity kept —
   and no raw PAN digits. **RED:** revert only G2 (G1 intact): the traceback
   text leaks the raw quote.
3. **T3 (G3):** an engine built by the real `make_engine`, a genuine
   unique-violation whose parameter carries a PAN; assert `str(exc)` contains
   no raw PAN and does contain SQLAlchemy's parameters-hidden notice.
   **RED:** revert the flag (the parameter echo returns — measured in both
   directions during this brainstorm).
4. **T4 (G4):** drive `cmd_process` through its injection seams so
   `process_receipt` re-raises a PAN-bearing exception (a session factory
   that serves ingest, then raises), and assert via capsys that the
   `failed` line masks it. **RED:** revert only G4. *Stop condition:* if the
   uncontained path cannot be reached through the existing seams without
   contortions, stop and report rather than adding a seam for the test.
5. **Absence of breakage:** the full suite (920 at baseline) — §4's swept
   assertions are the ones that would move if this design were wrong about
   redaction-stability, and they must not.

## 7. Verification

`python scripts/verify.py` all five gates; pytest counts from junitxml (the
piped summary line clips in this environment); `python -m ruff check .`;
outside-repo import of the changed modules. No frontend file moves, so the
Vitest count must not move from 170.

## 8. ADRs

**Mint ADR-0022 — "Failure text is redacted at every process egress"** — as
its own early branch commit, before the implementation tasks (the
design→ADR→plan order the PAN-grouping milestone used). It records: the four
guarantees and their one-line shapes; the extension relationship to ADR-0018
(whose Consequences bound its own surface to "the detector, the redaction
boundary, and the review-reason sink" — this is a new decision about a new
surface, the same relationship ADR-0020 had to 0018, so a new ADR rather
than a dated correction); the measured parameter echo in both directions;
the residuals of §5; and the standing rule that **any future egress for
failure text — a new log site, an API field, a queue payload — goes through
`redact_pan`**. ADR-0018 is not edited at all on this branch.
