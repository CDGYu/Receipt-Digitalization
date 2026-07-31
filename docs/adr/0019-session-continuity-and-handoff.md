# ADR 0019 — Session continuity: the handoff pair, the ledgers, and where rulings must live

**Status:** Accepted (2026-07-31)

## Context

This project is built across many sessions, each starting with no memory of the
last. Five milestones have shipped this way (foundations through the review UI,
then PAN hardening), and a continuity system grew up around them organically:

- **`docs/MEMORY.md`** — the agent's durable working memory: state, decisions
  already made, environment quirks, deferred items.
- **`docs/NEXT_SESSION_PROMPT.md`** — the kickoff prompt: a reading order and
  the ordered task list, pasted as the next session's first message.
- **Per-milestone design docs and plans** — tracked, under
  `docs/superpowers/specs/` and `docs/superpowers/plans/`.
- **Per-milestone SDD ledgers** — `.superpowers/sdd/<milestone>/progress.md`,
  carrying every measurement, adjudication and ruling. **Gitignored.**
- **Harness-local memory** — outside the repository entirely.

Two failure modes have now been measured, not merely feared:

1. **The handoff pair goes stale.** Commits `10166ec` and `395151b` exist
   solely to mark it stale mid-milestone. Worse, the PAN hardening milestone
   merged and pushed (2026-07-31, `main` at `7deb3fb`) without refreshing the
   pair, so the next session opened with both documents one whole milestone
   behind — still presenting PAN hardening as "the next task, already scoped"
   and quoting the pre-milestone test count, while the work sat merged on
   `main` with its follow-ups recorded only in a gitignored ledger.
2. **A rule that lives only in a ledger is invisible.** `.superpowers/` is
   gitignored: nothing in it can be found by searching the tracked tree, so a
   ruling recorded only there does not exist for any reader — human, agent or
   subagent — who does not already know the file path.

A third, adjacent lesson is already project law: volatile numbers embedded in
prose rot silently (one citation drifted `61 → 81 → 94 → 101`, once inside the
commit documenting the drift).

## Decision

1. **The tracked pair `docs/MEMORY.md` + `docs/NEXT_SESSION_PROMPT.md` is the
   authoritative cross-session handoff.** `MEMORY.md` answers "what is true"
   (state, decisions, environment); `NEXT_SESSION_PROMPT.md` answers "what to
   do and what to read, in order". Everything else — ledgers, design docs,
   harness memory — is an archive or a pointer, never the primary handoff.
2. **Closing a milestone includes refreshing the pair.** The refresh lands in
   the same session as the merge, stamped with the date and `main @ <sha>`. A
   merge whose handoff pair still describes the previous milestone is an
   unfinished close — this ADR exists because that happened once.
3. **The kickoff verifies, never trusts.** The next session's first duty is to
   check the stamp against `git log` and re-run the gates. The prompt says so
   explicitly, and stays that way: a stamp only helps when compared.
4. **The promotion rule.** Any ruling, decision or constraint that must outlive
   its milestone is promoted out of the gitignored ledger into the tracked
   tree before the close: an ADR for decisions, `MEMORY.md` for state, tests
   and code comments for behaviour. The ledger remains the full evidentiary
   record, but it is never the only home of a live rule.
5. **Volatile numbers live only in the stamped pair.** Test counts, commit
   SHAs and dates belong in the two handoff documents, next to their stamp —
   never in code comments or ADR bodies, per the drift rule. ADRs stay
   immutable once Accepted; corrections are dated appendices (the ADR-0007
   practice).
6. **Harness-local memory holds pointers and machine-local facts only** (paths,
   environment quirks, the location of this pair) — never the sole copy of a
   project decision.

## Consequences

- A fresh session needs exactly two documents to start, and staleness is
  detectable in one command: compare the stamp to `git log -1`.
- Every live rule is findable by searching the tracked tree; the ledgers keep
  their full detail without being load-bearing.
- Closing a milestone now costs a docs-refresh commit every time. That is the
  price, and it is accepted: the alternative was measured — a session that
  opened one milestone behind reality.
- State appears in both documents of the pair, so a refresh must touch both
  coherently; refreshing one and not the other is the exact failure mode
  commits `10166ec`/`395151b` record.
- The pair can still be wrong the moment something merges without the refresh —
  which is why decision 3 keeps the kickoff verification mandatory even when
  the documents look fresh.

## References

`docs/MEMORY.md`; `docs/NEXT_SESSION_PROMPT.md`; `docs/adr/README.md` (ADR
immutability and the dated-correction practice); ADR-0006 and ADR-0017 as the
precedent for recording process decisions as ADRs;
`.superpowers/sdd/<milestone>/progress.md` (the ledgers this ADR scopes);
commits `10166ec` / `395151b` (stale-handoff markers), `31943bb` / `446df20` /
`cd464d5` (the Phase 5 refresh, the pattern this ADR makes mandatory).
