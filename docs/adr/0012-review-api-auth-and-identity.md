# ADR 0012 — The review API: identity, the pending row, and the persisted confidence breakdown

**Status:** Accepted (implements SPEC §14.9; introduced with P4.T3)

## Context

The review API is where a human meets the pipeline. Four decisions had to be made
before a route could be written, and each of them turned on the same question:
what does this system owe a reviewer, and what does it owe the ledger?

## Decision

### Accounts live in a `users` table

Session auth was chosen over a shared key **specifically so
`corrections.corrected_by` names a real person**. A shared key cannot attribute a
correction to a reviewer, which would hollow out the audit trail the review UI
exists to produce. Env-declared users would make a password change a redeploy; an
external IdP would have blocked the task on infrastructure that does not exist.

Hashing is stdlib `hashlib.scrypt` (n=2¹⁴, r=8, p=1) with a per-user salt, encoded
`scrypt$n$r$p$salt$hash` — no passlib, no bcrypt, no new dependency. The dummy
hash for an unknown username is derived **once at import**: computing it per
request cost two derivations against a known user's one and made `POST
/auth/login` a username-enumeration oracle at 2.04× (measured 115.7 ms vs
56.7 ms).

`role` is a `String(16)`, not a database ENUM. The `compare_metadata` drift guard
runs on SQLite only and cannot see a new ENUM member, so an ENUM would pass
locally and fail on Postgres.

The cookie carries the **username only**; role and `is_active` are re-read per
request, so a demotion or deactivation takes effect on the next request rather
than at cookie expiry. `SESSION_TTL_S` is explicit (12h) because Starlette's
silent 14-day default is not a lifetime anyone chose for a bearer credential over
financial records. A stateless signed cookie cannot be revoked before it expires:
`deactivate(username)` is the revocation path, and logout only tells the
presenting client to drop its copy.

### The machine key does one thing

`X-API-Key` authorizes `POST /upload` and nothing else — it can neither read a
receipt nor write a correction. If `RECEIPTS_API_KEY` is unset, **every**
`X-API-Key` header is rejected, including an empty one: "unset config equals unset
header" is the standard way this becomes an open door. `admin` owns
`/export/xlsx` (bulk egress of every receipt's financials) and user management;
`reviewer` owns everything else.

### `POST /upload` writes a `pending` row before queueing

A job the queue loses would otherwise leave a blob on disk and nothing in the
database — a vanished upload, invisible to every query, findable only by diffing
storage against `receipts`. That is the silent drop §18 forbids. A `pending` row
is visible, queryable, and re-runnable.

The cost is that `save_extraction` became update-or-insert, and **that is where
the branch's one Critical defect came from**: the update branch applied its whole
field dict — `status` and every money column — over whatever was already there.
Combined with `apply_corrections`, which will patch a `pending` receipt to
`reviewed`, a reviewer who hand-keyed a backed-up receipt had their numbers
silently replaced by the worker and the receipt re-labelled `auto_approved`, with
the `corrections` audit trail left contradicting the row it described.

**A machine run therefore never overwrites a `reviewed` row.** `save_extraction`
refuses it, `_persist_failure` skips it, and `ProcessResult` reports the status and
confidence actually on the row rather than what the run intended. The receipt
still reaches a terminal state and a review task still names the attempt, so the
refusal is not itself a silent drop.

Neither per-task review could see this: it lives in the seam between the schema
task and the routes task. It was found by the whole-branch review, and the reason
it survived that long is that every stage-failure test built a fresh id and so
exercised only the *insert* branch — while production, after this decision, always
takes the *update* branch.

### The confidence breakdown is persisted, not recomputed

`explain_confidence` needs the `TriageResult` and `receipt.meta.ambiguous_fields`;
neither is persisted. A read-time recompute would systematically under-penalize
and hand a reviewer a breakdown that does not sum to the stored score — a
confident wrong number on the one screen where a human decides. So
`process_receipt` stores the `(reason, penalty)` pairs beside the score it
produced.

The column is **nullable on purpose**: `NULL` means "not recorded" (a row written
before the column existed, or a run that failed before scoring), `[]` means
"nothing lowered the score". Collapsing the two would let the API tell a reviewer
"no reasons" about a row that never captured them.

## Consequences

- Two routes exist that §14.9 did not list — `POST /auth/login` and `POST
  /auth/logout` — because session auth is unimplementable without them, plus a
  signed image blob sub-route. §14.9 has absorbed all three.
- Logout is deliberately **unguarded**: you can only clear your own cookie, and a
  401 on logout when a session has already expired is user-hostile.
- Image URLs are app-signed (HMAC over `receipt_id|variant|exp`) rather than
  `storage.url()`. `LocalStorage` returns a `file://` URI — unusable in a browser
  and a disclosure of server paths — while S3 presigns properly, so the two
  backends would otherwise behave differently in the UI. The signed message is
  `|`-joined without escaping, which is safe **only** because `receipt_id` is a
  parsed UUID, `variant` is a closed `Literal`, and `exp` is the trailing integer.
  Keep it that way.
- `/export/xlsx` returns an in-memory response rather than a `FileResponse`.
  Starlette's `FileResponse` returns early on a malformed `Range` header and skips
  its background cleanup, which left complete financial workbooks — with image
  URLs signed for 24 hours — in the shared OS temp directory. The trade-off is
  that the export no longer supports `Range` requests, which is acceptable on a
  workbook already capped at 5000 rows.
- `/docs`, `/redoc` and `/openapi.json` are **off by default** (`DOCS_ENABLED`).
  They are not a data leak, but they publish the write surface, including the
  `X-API-Key` header name, to anyone who can reach the service.
- Accepted limits, stated rather than dressed up: CSRF rests on `SameSite=Lax`
  plus a required JSON content-type; there is **no login rate limiting**, and each
  attempt costs a full scrypt derivation (~16 MB, ~57 ms), so `POST /auth/login`
  is an unauthenticated CPU/memory amplifier as well as an enumeration surface.
  Both want addressing before this faces anything wider than a LAN.
- Known follow-ups, recorded rather than fixed: `apply_corrections` redacts any
  coerced text (so a 13–19-digit `receipt.number` is masked when a reviewer merely
  confirms it) while `save_extraction` redacts only two columns — the two sides
  should agree; `_persist_failure` does not write `image_phash`, so a failed
  receipt can never later serve as a dedupe original; and closing a review task on
  an auto-approving reprocess also closes one a reviewer had claimed.

## References

SPEC §6.2/§6.5/§6.8 (schema), §14.9 (routes), §17 (config), §18 (silent drops,
PAN); ADR-0001 (`Decimal`), ADR-0006 (repository conventions), ADR-0007 (PAN
redaction and money integrity), ADR-0008 (review-queue concurrency), ADR-0011
(terminal-state contract);
`docs/superpowers/specs/2026-07-28-review-api-design.md`.
