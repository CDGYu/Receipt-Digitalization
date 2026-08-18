# Architecture Decision Records

Short, dated records of decisions made **during implementation** that are not
already captured in `RECEIPT_SYSTEM_SPEC.md`. Each ADR is immutable once
Accepted; supersede it with a new ADR rather than editing history.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-decimal-money-path.md) | `Decimal` everywhere on the money path | Accepted |
| [0002](0002-provider-abstraction-and-runtime-config.md) | VLM provider abstraction + env-based runtime config | Accepted |
| [0003](0003-confidence-additive-penalty-model.md) | Confidence as an additive penalty model | Accepted |
| [0004](0004-portable-persistence-and-docker-postgres.md) | Portable persistence (Postgres/SQLite) + Docker | Accepted |
| [0005](0005-tooling-layout-and-offline-test-strategy.md) | Tooling, src-layout, and offline test strategy | Accepted |
| [0006](0006-repository-conventions.md) | Repository conventions: injected session, caller commits, `ValueError` boundary | Accepted |
| [0007](0007-pan-redaction-and-money-integrity.md) | PAN redaction and money integrity at the persistence boundary | Accepted |
| [0008](0008-review-queue-concurrency.md) | Review-queue concurrency and idempotency | Accepted |
| [0009](0009-lazy-persistence-package-surface.md) | Lazy `receipts.persist` surface so a base install can migrate | Accepted |
| [0010](0010-export-decoupled-from-persistence.md) | Export stays decoupled from persistence (`ReceiptExportRow`) | Accepted |
| [0011](0011-terminal-state-contract-and-vlm-guards.md) | Terminal-state contract + concurrency/cost guards on model calls | Accepted |
| [0012](0012-review-api-auth-and-identity.md) | Review API: identity, the pending row, and the persisted confidence breakdown | Accepted |
| [0013](0013-cli-contract.md) | CLI contract: one work list, no overrides, no prompts | Accepted |
| [0014](0014-optional-dependency-import-discipline.md) | Optional dependencies stay out of every import path | Accepted |
| [0015](0015-review-ui-same-origin-and-app-prefix.md) | The review UI is served same-origin under `/app` | Accepted |
| [0016](0016-review-next-resumes-the-callers-task.md) | `GET /review/next` resumes the caller's own in-progress task | Accepted |
| [0017](0017-two-suites-and-the-gate-runner.md) | Two test suites, and `scripts/verify.py` is what "passing" means | Accepted |
| [0018](0018-pan-masking-policy.md) | The PAN masking policy | Accepted |
| [0019](0019-session-continuity-and-handoff.md) | Session continuity: the handoff pair, the ledgers, and where rulings must live | Accepted |
| [0020](0020-pan-grouping-coverage.md) | PAN detector: which groupings are covered, and why not more | Accepted |
| [0021](0021-handing-off-mid-milestone.md) | Handing off mid-milestone: the unfinished branch needs a record | Accepted |
| [0022](0022-failure-egress-redaction.md) | Failure text is redacted at every process egress | Accepted |
| [0023](0023-parallel-task-agents-share-one-worktree.md) | Parallel task agents share one worktree, so uncommitted work is not durable | Accepted |
| [0024](0024-review-ui-error-recovery-contract.md) | The review UI's error-recovery contract | Accepted |
| [0025](0025-admin-release-for-a-claimed-task.md) | Admin release for a claimed review task | Accepted |
| [0026](0026-admin-ui-backend-routes.md) | The admin UI's backend routes: whoami, and a scoped task listing | Accepted |
| [0027](0027-review-ui-design-system.md) | The review UI's design system: tokens, themes, fonts, and `null` ≠ `0` | Accepted |
| [0028](0028-claims-about-the-tree-are-re-derived.md) | Claims about the tree are re-derived, not restated | Accepted |
| [0029](0029-what-the-gates-certify.md) | What the gates certify, and what they cannot | Accepted |
| [0030](0030-a-finding-is-a-claim.md) | A finding is a claim, and a fix wave verifies before it fixes | Accepted |
| [0031](0031-the-corrections-read-route.md) | The corrections read route: who may see a receipt's attribution | Accepted |
| [0032](0032-a-document-cannot-certify-itself.md) | A document cannot certify itself, and a derived claim can rot inside its own commit | Accepted |
| [0033](0033-the-handoff-pair-goes-last-and-alone.md) | The handoff pair goes last and alone, and a correction goes to every copy | Accepted |
| [0034](0034-the-shared-page-bound.md) | The shared page bound | Accepted |
| [0035](0035-the-asgi-entry-point.md) | The ASGI entry point, and what it refuses to start on | Accepted |
| [0036](0036-one-image-two-commands.md) | One image, two commands | Accepted |
| [0037](0037-ci-runs-the-gate-runner.md) | CI runs, and it runs the gate runner | Accepted |
| [0038](0038-the-theme-control.md) | The theme control, and one key in browser storage | Accepted |
| [0039](0039-the-local-path-is-a-liveness-check.md) | The local path is a liveness check, not a measurement | Accepted |
| [0040](0040-what-field-accuracy-counts.md) | What eval field accuracy counts, and the three things it used to average | Accepted |
| [0041](0041-the-review-outcome-takes-focus.md) | The review outcome takes focus, so a 403 is not invisible | Accepted |
| [0042](0042-a-cited-commit-must-stay-reachable.md) | A cited commit must stay reachable, and a rewrite carries its citations | Accepted |
| [0043](0043-merchant-identity-is-two-phase.md) | Merchant identity is two-phase: a guess retrieves, a TIN commits | Accepted |
| [0044](0044-the-model-facing-surface-is-two-channels.md) | The model-facing surface is two channels, and a prose guarantee is held lexically | Accepted |
| [0045](0045-a-brief-is-a-claim-about-the-tree.md) | A brief is a claim about the tree, and relaying one makes it yours | Accepted |

Read **0001** first: it is the invariant everything else defers to. **0007** is
the one to read before touching anything that writes card data or money, and
**0018** then **0020** before touching `_PAN_RE` — 0020 is the current record of
which card groupings the detector covers, and of the residual it deliberately
leaves. **0017** is the one to read before believing a green test run — `npm
test` does not type-check, and that trap fired three times in one milestone.
**0026** is the one to read before writing anything that can leave a review task
`OPEN`: `GET /review/tasks` discloses no reviewer's name to another reviewer only
because every existing `OPEN`-producer clears or never sets `assigned_to`, and
nothing in the schema enforces that. **0027** is the one to read before writing
any CSS or rendering any extracted value: it carries the token vocabulary, the
light/dark contract, and the rule that `null` must never look like `0` — the
prime directive reaching the last inch of the UI. **0028** is the one to read
before writing any sentence that quantifies over this codebase — *every*, *the
only*, *all N*, *none*. Four such claims were found false in one day; it records
the enumeration methods and why citations here carry no line numbers. **Read its
`## Correction (2026-08-07)` with it** — the motivating story in its Context
section was itself false and is withdrawn there. **0029** is the one to read
before saying "the gates pass" about anything visual: four fixes — three
Critical — once reverted with all five green, and it states exactly what a green
run now certifies and what it still cannot. **0030** is the one to read before
acting on a review finding, or writing a fix wave's brief: two of six findings
in one wave were false, and a fix wave may return *"this finding is wrong"*.
**0031** is the one to read before changing who can see correction attribution —
or before scoping `GET /receipts/{receipt_id}`, whose being *unscoped* is the
premise its 403-not-404 rests on. It also records the limit the schema forces:
`review_tasks.receipt_id` is UNIQUE, so a released or reopened task takes a
reviewer's own correction history away from them.
**0032** is the one to read before writing a fix wave's prose, or any sentence
about how well a document was checked: on one milestone, five of nine
false-claim defects were introduced *by fix rounds*, four of them in
consecutive rounds of one task. It gives the bounded property that closed it —
a sentence stays only if its subject is the system and a reader can check it
without trusting the author — and records how a correctly-derived claim rotted
inside the commit that carried it.
**0033** is the one to read before refreshing the handoff pair or fixing a
sentence that appears more than once: the pair is committed **last and alone**
(three repair commits in one session are why), a correction goes to **every**
copy — `docs/MEMORY.md` states the current milestone twice by design — and a
count anchored to the ledger is falsified by recording a finding about it there.
**0034** is the one to read before adding a paginated route or changing a page
window: all three declare `limit` and `offset` through one shared `PageLimit` /
`PageOffset`, an out-of-range offset is a 422 from request validation rather
than the `OverflowError` 500 ADR-0031 reported, and the pin is stated over the
built app so a fourth route cannot re-declare its way around it.
**0035** is the one to read before deploying the service or changing how it
boots: `uvicorn receipts.asgi:app` is the supported entry point, importing the
module builds nothing, and it refuses to start on four misconfigurations whose
symptom would otherwise be silent — chief among them an unset `DATABASE_URL`,
which would serve production off a local SQLite file.
**0036** is the one to read before changing how the service is packaged or run:
one image runs both halves (`api` takes the default `CMD`, the worker overrides
it), the image builds the review UI itself so a stale `dist` cannot ship,
migrations are a documented operator step rather than an entrypoint, and the
whole thing was verified by building and running it. `docs/DEPLOYMENT.md` is the
guide.
**0037** is the one to read before touching CI: the workflow runs
`scripts/verify.py` rather than re-listing gates (the previous one drifted three
gates out of date and ran none of the frontend ones), it fires on every branch
because merges here are local fast-forwards, and it guards against the false
green that `pytest.importorskip` makes possible. It reverses the 2026-07-29
decision to untrack `.github/workflows/` and corrects ADR-0017's Context, and it
is candid that the workflow itself was unverified when written.
**0038** is the one to read before touching the theme, the header, or anything
that wants browser storage: three states (`system` removes the attribute rather
than setting a third value, so ADR-0027's precedence rule stays reachable in
both directions), a pre-paint script in `index.html` whose duplicated storage
key is pinned by a text-reading test, and the **narrowing of ADR-0024** that
permits exactly one key — which nothing else inherits.
**0039** is the one to read before running the eval harness or believing its
output: a local run is a **liveness check**, not a measurement — it prints the
six §16 metrics but licenses only "the pipeline completes". Liveness artefacts
stay out of `eval/results/`, and the local timing is **not** to be re-derived
(measured twice, seven weeks apart, and it got slower).
**0040** is the one to read before quoting any eval field-accuracy number, or
before fixing a claim that appears in more than one place. Metric 4 was one
scalar averaging three unlike things — what the model read, what it correctly
left empty, and what it said about itself — and an extraction containing
*nothing* scored 42.50% / 37.50% / 36.59% against the three golden labels; it is
now a set of ratios and counts over one classifier that reads *filled* from the
truth side only, so a model cannot enlarge its own denominator by hallucinating,
and no class named for agreement holds a path the per-path map scores wrong. Its
**decision 5** generalises beyond eval: a token grep scoped to the change cannot
reach the sentences about the changed behaviour that live in files the fixing
commit never opens, which is verified there against two commits and their
ancestry.
**0041** is the one to read before adding a state to the review screen's submit
chain, or before putting any new element in `ReviewScreen`'s tail. The outcome
of a submit — the backend-down explanation, the summary alert, the terminal
card — rendered at the end of a long document while the ⌘↵ chord is bound to
`window`, so a 403 pressed from the top of the form changed nothing a sighted
reviewer could see, in the one case where *the write landed and the task is
gone*. It is now one `<section tabIndex={-1}>` that takes focus whenever it
appears, and the browser does the scrolling. The condition is the **complement**
of the pending states, so a state added later defaults *into* the region
instead of having to be added to a list; the region carries **no role**, which
extends ADR-0024's decision 4 rather than reopening it; and it is a `<section>`
because `.screen > div` is the image pane's positional selector. Focus rather
than `scrollIntoView` because `scrollIntoView` is `undefined` in jsdom — so the
gates can certify that focus moved, and that two elements sit inside the region
— the summary alert in `failed`, the terminal card's heading in `lost`.
Containment is pinned nowhere else: not on the backend-down explanation, and not
on a future outcome rendered as a sibling (measured, both leave the suite
green). The inline field error is deliberately outside the region per ADR-0024
decision 5, and nothing can certify that anything was *seen*.
**0042** is the one to read before citing a commit, before rewriting history
that other documents cite, or before writing about a commit no ref can reach. A
branch replayed onto `main` rather than merged left nine citations in three
tracked files naming commits nothing could resolve — every claim still true, and
none of them checkable. `tests/test_sha_citations.py` now requires every
backticked seven-character hex token in a tracked file to name a commit
**reachable from some ref**: reachability and not existence, because `git
cat-file -e` succeeds on an orphan until someone runs `git gc`, so an existence
check would have been green through the whole defect; any ref and not `main`,
because an ADR is committed before its merge and legitimately cites its own
branch. **Decision 5 is the one that bites while you write** — the backticked
short form *is* the citation, so a document about a dead commit names it bare or
at full oid length, and a sentence cannot show an example of the form without
instantiating it, which leaves a live commit as the only safe illustration.
**Read it with ADR-0032's `## Correction (2026-08-13)`**, which **corrects**
decision 3 rather than overturning it: a closed anchor's claim is permanent, its
retrievability is not, and decision 3's ordering survives, qualified — a closed
SHA is still better than a moving ref, it is simply not permanent.

Primary sources these build on: `RECEIPT_SYSTEM_SPEC.md` (build spec),
`README.md` (§5 design decisions), `VLM_AND_DATA.md`, and the always-on
`.kiro/steering/receipt-system.md` (load-bearing rules).
