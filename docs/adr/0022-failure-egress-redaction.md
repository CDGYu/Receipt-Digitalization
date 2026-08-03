# ADR 0022 — Failure text is redacted at every process egress

**Status:** Accepted (2026-08-03)
**Extends:** ADR-0018, which records redaction at the persistence boundary and
at the review-reason sink. This ADR covers the egresses 0018's surface
deliberately excluded — 0018's own Consequences bound it to "the detector, the
redaction boundary, and the review-reason sink", which is why this is a new
ADR rather than a dated correction (the same relationship ADR-0020 has to
0018).

## Context

The 2026-08-03 whole-branch review of the currency-bound branch surfaced a
pre-existing, live-reachable gap: failure reasons are built from exception
text, exception text interpolates raw model values, and only one of the five
places that text leaves the process redacts it.

The producers are by design. `save_extraction`'s reviewed-row guard quotes
`merchant.name` and `totals.total` so the review task can say what the
refused run produced; `_bounded_optional_text` quotes the overlong value that
tripped it. The recorded policy (`queue.py`, and the queue test's docstring)
is that producers may quote because the sink redacts — "patching every
producer would miss the next one." That policy was sound; its sink inventory
was one long.

`_persist_failure` mints `reason` from `str(failure)` and it flows raw to:
CLI stdout (`process --inline` and `reprocess`), RQ's result store in Redis
(durable, via `result_to_payload`), and the failure log — twice, since
`exc_info` renders a traceback that embeds the exception's own message again.
A fourth vector feeds all of them: SQLAlchemy appends `[parameters: (...)]`
— raw statement values, which on this schema are model text — to every
wrapped DBAPI error, and `make_engine` built a bare `create_engine`.
Measured (2026-08-03, SQLite): a unique-violation `IntegrityError` from a
plain engine contains its PAN-valued parameter in `str(exc)`; with
`hide_parameters=True` it does not, and the message says parameters are
hidden. The nothing-could-be-written re-raise carries the same exception
text to RQ's failed registry (durable) and the CLI's uncontained-failure
print.

## Decision

**Failure text is redacted at every egress — the places it leaves the
process — not at its producers.** Four guarantees, decided by user rulings
(2026-08-03: full class on one branch; tracebacks rendered and redacted
rather than dropped or raw):

1. **The carrier.** `_persist_failure` redacts `str(failure)` **before**
   truncating to `_MAX_REASON_CHARS` — truncating first can cut a PAN
   mid-shape into something `_PAN_RE` no longer matches, so the surviving
   digits would pass every later redaction in the clear. One line covers CLI
   stdout, the Redis result store, and every future `ProcessResult.reason`
   consumer.
2. **The failure log.** The `log.warning` logs the untruncated redacted
   failure text plus `redact_pan` over the traceback rendered by
   `traceback.format_exception(failure.cause)`, and drops `exc_info`. Full
   stack fidelity, no raw model text in log files.
3. **The engine.** `make_engine` passes `hide_parameters=True` to
   `create_engine`. Every runtime engine funnels through it (CLI, worker,
   users, both e2e scripts, the lazy `persist` surface), so statement
   parameters leave every SQLAlchemy error string this system raises —
   including the ones RQ's failed registry stores, the one durable sink this
   project cannot redact from its own side.
4. **The uncontained print.** `cmd_process`'s failed-job line prints
   `redact_pan(str(exc))`. `_UNCONTAINED` is only
   `(KeyboardInterrupt, SystemExit)`, so every re-raised
   nothing-could-be-written exception lands on that line.

**The standing rule this ADR exists to record: a new egress for failure text
— a new log site, an API field, a queue payload — goes through `redact_pan`
at the egress.** The sink inventory above is the complete list as of this
decision; whoever adds a sink extends it.

**What deliberately does not change.** `enqueue_review` keeps its own
redaction — it guards its other callers, and re-redacting pre-redacted text
cannot leak (masking only masks). Producers keep quoting raw values; the
quotes are useful to reviewers precisely because the egresses now redact.
No control flow moves anywhere: ADR-0011's terminal-state contract,
ADR-0006's raise convention, `_MAX_REASON_CHARS`, the `STAGES` vocabulary
and `route()`'s reason strings are all byte-identical.

## Correction (2026-08-03)

The Decision's closing claim — that the sink inventory above "is the complete
list as of this decision" — was falsified the same day it was written, twice,
by the whole-branch review. Both misses are recorded here rather than edited
into the Decision: the inventory was wrong, and an ADR that quietly grew a
fifth and sixth entry would hide that what failed was the design's sink map,
not the rule.

**(a) The enqueue loop's twin print.** Guarantee 4 covers `cmd_process`'s
inline loop. The *enqueue* branch of the same function had its own failed-job
print — the identical `id  failed  reason` line, reached when the broker
refuses a job rather than when the run fails — and the design's sink map
missed it. It is fixed in this branch's closing fix wave and carries its own
test, `test_an_enqueue_failure_prints_a_redacted_reason`. Measured exposure
before the fix: jobs on that path come from `_job_from_receipt`, whose fields
are provenance only — the variant filename `original.jpg` taken off a
UUID-keyed image key, a placeholder content type, a literal source — so what
that print could reach was broker error text, not model text. The fix is
rule-consistency, and robustness against the change `_job_from_receipt`'s own
docstring invites: whoever adds the real provenance columns feeds them
straight into that line. It is not a live leak closed.

**(b) `receipts reprocess`'s un-netted re-raise.** `cmd_reprocess` calls
`process_receipt` with no `try`, so the nothing-could-be-written re-raise that
`_persist_failure` documents propagates out of the command and the interpreter
renders the exception *chain* to stderr. The chain's `__context__` is this
project's own `_StageFailure`, whose message is `"{stage}: {type}: {cause}"` —
the raw producer text, upstream of every egress that redacts. Measured: the
reviewed-row guard's raw `merchant.name` quote reaches stderr this way. This
one is an accepted residual, not a fix in this wave; the mechanism is below.

The Context's "five places" undercounts accordingly — seven with these two.

**The accepted residual, re-attributed.** The Consequences below attribute the
failed-registry exposure to "an infra exception embedding model text by some
other route". That is the wrong mechanism. The ordinary route is this
project's own exception chain: `hide_parameters` cleans the SQLAlchemy segment
of a rendered chain and nothing else, and never touches the `_StageFailure`
message sitting in that chain's `__context__`. The residual is still accepted,
now with its mechanism stated rather than guessed. Closing it needs one of two
things this branch does not do: producer-side redaction, which reverses the
sinks-redact rule this ADR exists to record, or a rendering net in `main` and
the worker, which is the control-flow change this branch's constraints forbid.
Both were priced; neither was taken. The re-raise path remains the documented
raw-chain residual for **both** stderr (`reprocess`) and RQ's failed registry.

## Consequences

- Operators debugging a stage failure read a redacted traceback in the log
  instead of `exc_info`, and SQLAlchemy errors name the `hide_parameters`
  flag instead of echoing values. Both are the standard cost of not writing
  card numbers to disk, and both were ruled on with the costs stated.
- `redact_pan`'s accepted false positives (ADR-0018: ~1-in-200 16-hex
  tokens, 13–19-digit runs, `4-4-4-N`-shaped groupings) now apply to log and
  traceback text. Cosmetic; nothing parses these strings.
- **Accepted residual:** RQ renders failed-registry tracebacks from the raw
  exception object; `hide_parameters` removes the known model-text vector,
  and an infra exception embedding model text by some other route would
  still reach that registry raw. Test-local engines and `alembic/env.py`'s
  engine are not runtime egress and are out of scope.
- Guarantees pinned on this branch by
  `test_a_failed_run_never_leaks_raw_model_text_through_its_reason`,
  `test_the_failure_log_renders_a_redacted_traceback`,
  `test_engine_error_text_hides_statement_parameters`, and
  `test_an_uncontained_batch_failure_prints_a_redacted_reason`.

## References

`docs/superpowers/specs/2026-08-03-failure-egress-redaction-design.md` (the
measured map, the consumer sweep, and the residuals in full); ADR-0018 (the
policy this extends; the review-reason sink); ADR-0007 (bounded text / the
original redaction decision); ADR-0011 (the terminal-state contract the
failure path implements); `src/receipts/pipeline.py` (`_persist_failure`,
`_StageFailure`, `_truncate`); `src/receipts/persist/session.py`
(`make_engine`); `src/receipts/cli.py` (`cmd_process`, `_UNCONTAINED`);
`src/receipts/worker.py` (`result_to_payload`);
`src/receipts/review/queue.py` (`enqueue_review`, the sink comment).
