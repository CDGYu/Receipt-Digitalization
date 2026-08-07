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

> **⚠ WITHDRAWN 2026-08-07. The paragraph above is false, and it was this ADR's
> motivating story.** The route comment was *complete and correct* on the day it
> was written; it rotted four days later. Nobody asked the wrong question — the
> two 13s are unrelated. See `## Correction (2026-08-07)`, which replaces it with
> the derived account.

**One was never true at all.** The `api.py` sentence arrived in `130b202`
(2026-07-29); `GET /health` had been in that same file since `b7a2966` the day
before. It was false the day it was written, and survived **eight days** of edits
and an explicit review because every reader treated an inventory as evidence.
*(Corrected 2026-08-07 from "nine months": `130b202` is 2026-07-29 and the fix
`bbb5366` is 2026-08-06.)*

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

**The guard qualnames are three, not two** (added 2026-08-07): `require_user`,
`require_role.<locals>.dependency`, and **`require_upload`** — which guards
`POST /upload`, calls `require_user` inside its own body, and is therefore
invisible to a walk looking only for the first two. Do not hard-code the list:
match `require_` and print what you find, because a fourth guard added later is
the same trap again. Missing this one is what made §4's corroboration fail to
reproduce; see `## Correction (2026-08-07)`.

### 4. A security-relevant claim needs two independent methods that agree

The unauthenticated-route set was settled by **(a)** a static walk of each
route's resolved dependant tree and **(b)** an empirical call of every route with
no cookie, reading the status. Both returned the same five, and the same nine
with `DOCS_ENABLED=true`. One method is a hypothesis; two that agree is a
measurement. Where they disagree, the empirical one wins — it is what a caller
sees.

> **The static half only agrees if it knows all three guard names** (added
> 2026-08-07). With the two §3 originally recorded it returns 6 and 10. The five
> and the nine are unchanged and the empirical half reproduces exactly; see
> `## Correction (2026-08-07)`. **A corroboration whose method is written down
> incompletely is not corroboration** — which is this rule turned on itself.

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
  words and false for **eight days** (corrected 2026-08-07 from "nine months").
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

## Correction (2026-08-07)

Three corrections, all raised at this milestone's close and all re-derived here
before being written (rule 1). **The decision section stands unchanged; §3 gains
a name it was missing.** The first is the serious one: this ADR's motivating
story was wrong, and wrong in the exact way the ADR exists to name.

### 1. The motivating story is withdrawn — the route comment was right when written

The Context section said the old `vite.config.ts` list "listed exactly **13**,
and 13 is exactly what a *flat* walk of `app.routes` returns", and concluded it
was "a correct-looking answer from the wrong question". **Both halves fail.**

**It cannot have come from a flat walk.** The old list contains `POST /auth/login`
and `POST /auth/logout`. A flat walk of `app.routes` yields **zero** `/auth/*`
paths — as §3 of this same ADR states, four sentences of its own text away. Both
numbers are 13. **They are different 13s**, and a shared count was read as a
shared cause.

**And the list was not wrong when it was written.** Derived 2026-08-07:

| | |
|---|---|
| The comment arrived in | `e692070`, **2026-07-30** |
| Routes registered at `e692070` | **exactly 13** — 11 on `app`, 2 on the auth router |
| The 13 it listed | **exactly those 13** |
| `POST /review/{task_id}/release` added | `9ab152c`, 2026-08-04 |
| `GET /auth/me` added | `f49f695`, 2026-08-05 |
| `GET /review/tasks` added | `000d55d`, 2026-08-05 |

```
git show e692070:src/receipts/review/api.py  | grep -oE '@app\.(get|post|patch)\("[^"]+"'
git show e692070:src/receipts/review/auth.py | grep -oE '@router\.(get|post)\("[^"]+"'
```

*(`git log -S` finds none of these three. The pickaxe fails on them exactly as it
failed on "one unauthenticated route" — use `-G`.)*

**So the defect was rot, not a wrong question.** The comment was accurate for five
days and became false when the admin-UI milestone added three routes without
touching it. Nobody miscounted; the tree moved.

**This makes the ADR stronger, not weaker.** Its four motivating claims are now:
one never true (`api.py`), one **rotted from correct** (`vite.config.ts`), and two
overreaching enumerations (ADR-0027's "all 17", design §9's "all four"). Rot is
the same failure as a stale line citation, which is what §5 and §7 already
legislate — so the through-line is not "people ask the wrong question" but
**a derived sentence keeps its authority long after it stops being true.** §2's
remedy — record the method beside the result — is aimed correctly, and is the
only one of the seven rules that would have prevented this instance.

**And the finding that produced this correction was itself an instance.** The
same review reported ADR-0027's "35 custom properties" as borrowed from a
`@font-face` count, on the strength of two 35s. Re-derived: the token count is
right, the two 35s describe different artefacts, and the reviewer built a causal
story on a coincidence of counts — the identical mistake, in the same document,
in the same session. See ADR-0027's `## Correction (2026-08-07)`.

### 2. §3 is missing a guard name, and §4's corroboration does not reproduce

§4 says the static and empirical halves "both returned the same five, and the same
nine". **Re-run 2026-08-07: following §3's recorded method they return 6 and 10.**

§3 names `require_role` → `require_user` and says to detect a transitively-called
guard by qualname. It does not name **`require_upload`**, which guards `POST
/upload`, is a third qualname, and calls `require_user` inside its own body — so a
dependant-tree walk that looks only for the two names §3 records counts `/upload`
as unguarded. Add `require_upload` and the static half returns **5 and 9**,
matching the empirical half exactly.

| Guard qualnames present | `require_user`, `require_role.<locals>.dependency`, **`require_upload`** |
|---|---|
| Unguarded, §3's two names | 6 · 10 with `DOCS_ENABLED=true` |
| Unguarded, all three | **5 · 9** — agrees with the empirical half |

**No security conclusion changes.** The five are unchanged, §4's own tiebreak
already says the empirical method wins where they disagree, and the empirical half
reproduces exactly. What failed is the corroboration — which is precisely the
thing §4 exists to provide, so the fix belongs in §3's method rather than in §4's
result. `api.py`'s docstring is unaffected: it records no guard names, so its
"the static dependant tree and the empirical call agree" is true for any walk that
looks for every `require_*`.

### 3. Smaller

- **"nine months" → "eight days"**, in Context and in Consequences. `130b202` is
  2026-07-29; `bbb5366` is 2026-08-06. Both corrected in place.
- **References said "review standards, 1–20".** There are **22**; 21 and 22 were
  promoted on 2026-08-06, and 21 — *a citation is a claim too* — is this ADR's
  own §7. De-numbered below rather than repointed.

## References

`docs/MEMORY.md` (the review standards);
`src/receipts/review/api.py` (the signed-blob docstring, and the enumeration it
records); `frontend/vite.config.ts` (the route list and its method);
`docs/adr/0027-review-ui-design-system.md` (its `## Correction (2026-08-06)`,
and that correction's own de-numbered citation);
`docs/superpowers/specs/2026-08-05-review-ui-design-system.md` §9;
ADR-0017, ADR-0019, ADR-0021, ADR-0023, ADR-0026.
