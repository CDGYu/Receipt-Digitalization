# ADR 0028 — Claims about the tree are re-derived, not restated

**Status:** Accepted (2026-08-06)
**Builds on:** ADR-0019 and ADR-0021 (session continuity, and why a snapshot is
verified rather than trusted), ADR-0017 (what "passing" means)
**Relates to:** review standards 5, 6, 12, 17 and 20

## Context

On 2026-08-06 four prose claims about this codebase were found false in a single
session. They are not four unrelated mistakes; they are one shape.

| Where | The claim | The measurement |
|---|---|---|
| ADR-0027, Consequences | "every one of the 17 correctable paths is an `<input>`" | 16 inputs and one `<select>`; `placeholder` reaches **14** |
| design spec §9 | "Rulings — all four settled 2026-08-05" | the four questions open at *drafting*, not an index of decisions since |
| `vite.config.ts` | "Cross-checked against every route `create_app` registers" | listed **13** of 16, plus the `/app` mount |
| `api.py`, signed-blob handler | "This is the one unauthenticated route in the service" | one of **five**; **nine** with `DOCS_ENABLED=true` |

**Three of the four were written by someone who had checked something.** The
most instructive is the route comment: it listed exactly **13**, and 13 is
exactly what a *flat* walk of `app.routes` returns, because `include_router`
wraps the auth router in an `_IncludedRouter` and hides `/auth/*` behind it.
Whoever wrote that comment almost certainly ran a query, read 13, and believed
it. The defect was not laziness. It was a correct-looking answer from the wrong
question.

**One was never true at all.** The `api.py` sentence arrived in `130b202`
(2026-07-29); `GET /health` had been in that same file since `b7a2966` the day
before. It was false the day it was written, and survived nine months of edits
and an explicit review because every reader treated an inventory as evidence.

**And the repair rotted within hours.** ADR-0027's own dated correction cited
`ReceiptForm.tsx:221-224` for the checkbox rationale. That was correct when
written at `46eb965` — verified by reading the file at that commit — and was
stale by `bdbfd03` the same day, when a later task inserted four lines above it.
A correction about a claim that stopped being true itself stopped being true,
inside one session.

The through-line: **an enumeration in prose inherits the authority of the thing
it enumerates.** A reader trusts it precisely because it looks derived, so it is
the one kind of sentence that is never re-checked.

## Decision

### 1. A list in prose is a claim, and writing one obliges you to derive it

Not to recall it, and not to copy it from a neighbouring document. If a sentence
quantifies over the codebase — *every*, *the only*, *all N*, *none* — it is
answered by running something. Review standard 17 already said a universal claim
is answered by an enumeration rather than an argument; **standard 20 adds that
writing one is itself making the claim.**

### 2. Record the method beside the result, so the next reader re-runs it

A number without its derivation is a number the next reader must either trust or
re-invent. `vite.config.ts` and `api.py` now both carry the query that produced
their lists and an explicit instruction to re-run it. The counts will go stale;
the method will not.

### 3. Enumerate from the artefact, never from the source text

For routes that means building the app and walking `app.routes`, **recursing
through `.original_router.routes`** — a flat walk yields 13 routes with **zero**
`/auth/*` paths. Grepping decorators is the weaker method and is what left the
trap in place. A transitively-called guard (`require_role` → `require_user`) is
invisible at runtime too: it is plain Python, not a nested `Depends`, so a
dependant-tree walk must detect it by qualname.

### 4. A security-relevant claim needs two independent methods that agree

The unauthenticated-route set was settled by **(a)** a static walk of each
route's resolved dependant tree and **(b)** an empirical call of every route with
no cookie, reading the status. Both returned the same five, and the same nine
with `DOCS_ENABLED=true`. One method is a hypothesis; two that agree is a
measurement. Where they disagree, the empirical one wins — it is what a caller
sees.

### 5. Citations carry no line numbers

Quote the text to search for, or name the symbol. `:221-224` was right when
written and wrong the same day. Repointing a rotted citation at fresh line
numbers only schedules the next rot. This is review standard 5 — *if a number
can change without its sentence changing, it does not go in the comment* — in a
sharper form: **the number was correct when written and rotted anyway.**

### 6. Prefer the claim that cannot rot

`api.py` no longer says "the one unauthenticated route". It says **"the one
route that serves receipt data without a session"** — narrower, true, and stable
against anyone adding a health check. The enumeration sits beside it as dated
evidence rather than as the load-bearing sentence. Where a stable phrasing
exists, it is worth more than an accurate count.

### 7. A citation is a claim too

Closing an instance ages every sentence that cited it. Fixing `vite.config.ts`
made three tracked claims stale immediately — **two of them inside review
standard 20's own text**, which would have shipped an instance of the defect
inside the standard that names it. Fixing `api.py` aged four more. Both were
caught by grepping for every claim about the artefact rather than recalling
where they were.

## Consequences

- **Prose gets longer.** `api.py`'s docstring grew by 20 lines to carry a set,
  a method and a warning. That is the price; the sentence it replaced was four
  words and false for nine months.
- **Some claims should not be written at all.** Design spec §9 now says
  explicitly that it is *not* an index of every decision since — the cheapest
  fix for a list that reads as complete is often to say what it is not.
- **Grep by one distinctive word, never by the phrase.** `git grep "one
  unauthenticated route"` returns nothing: the sentence wraps mid-phrase across
  two lines. The residual was very nearly recorded as already fixed on the
  strength of that empty result. The same trap defeated a `git log -S` pickaxe
  in the same session.
- **This ADR is itself subject to rule 1.** Its table is dated 2026-08-06 and
  its counts are re-derivable by the methods in §3 and §4. If you are reading it
  to learn the current unauthenticated set, **run the enumeration** — do not
  quote the table.

## What this ADR does not decide

Whether these checks belong in CI. Every measurement here was run by hand
because the claims live in prose, and no gate reads prose. A test that pins
`api.py`'s docstring against the live route table is possible and is not
proposed; it would couple a docstring to a fixture, and the failure mode it
prevents has now been made loud instead.

## References

`docs/MEMORY.md` (review standards, 1–20);
`src/receipts/review/api.py` (the signed-blob docstring, and the enumeration it
records); `frontend/vite.config.ts` (the route list and its method);
`docs/adr/0027-review-ui-design-system.md` (its `## Correction (2026-08-06)`,
and that correction's own de-numbered citation);
`docs/superpowers/specs/2026-08-05-review-ui-design-system.md` §9;
ADR-0017, ADR-0019, ADR-0021, ADR-0023, ADR-0026.
