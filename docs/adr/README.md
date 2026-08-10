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

Primary sources these build on: `RECEIPT_SYSTEM_SPEC.md` (build spec),
`README.md` (§5 design decisions), `VLM_AND_DATA.md`, and the always-on
`.kiro/steering/receipt-system.md` (load-bearing rules).
