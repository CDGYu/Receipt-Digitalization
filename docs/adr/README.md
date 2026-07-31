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

Read **0001** first: it is the invariant everything else defers to. **0007** is
the one to read before touching anything that writes card data or money, and
**0018** then **0020** before touching `_PAN_RE` — 0020 is the current record of
which card groupings the detector covers, and of the residual it deliberately
leaves. **0017** is the one to read before believing a green test run — `npm
test` does not type-check, and that trap fired three times in one milestone.

Primary sources these build on: `RECEIPT_SYSTEM_SPEC.md` (build spec),
`README.md` (§5 design decisions), `VLM_AND_DATA.md`, and the always-on
`.kiro/steering/receipt-system.md` (load-bearing rules).
