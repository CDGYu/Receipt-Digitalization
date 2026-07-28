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

Read **0001** first: it is the invariant everything else defers to. **0007** is
the one to read before touching anything that writes card data or money.

Primary sources these build on: `RECEIPT_SYSTEM_SPEC.md` (build spec),
`README.md` (§5 design decisions), `VLM_AND_DATA.md`, and the always-on
`.kiro/steering/receipt-system.md` (load-bearing rules).
