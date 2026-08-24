# Upload, live processing, and the visual refresh — design

**Date:** 2026-08-23
**Status:** Draft, for review
**Supersedes:** nothing. **Extends:** ADR-0027 (the design system).
**Closes:** ISSUE-026 (no upload UI). **Bounded by:** ISSUE-027 (PDFs fail).

---

## §0. What this is, and the brief it answers

Three things ship together because they are one path:

1. **An upload screen** — today a receipt can only enter the system through a
   shell (ISSUE-026).
2. **Live processing feedback** — today nothing in the UI knows when a job
   finishes.
3. **A visual refresh** across every screen.

**The brief, in the owner's words, is that the system has to impress someone in
a live walkthrough that they drive.** That is not decoration: it fixes the hero
path as **upload → processing → review**, and it makes the ~25–60s of silence in
the middle a first-class design problem rather than a detail.

Every measurement below was taken on 2026-08-23 against
`feat/label-provenance-rule` at `dcb9f02`, **not** against `main` — the branch
is unmerged and `main` is at `791c356`. *(An earlier draft of this line said
"against `main` at `dcb9f02`", which is a commit `main` cannot reach. Caught by
this document's own self-review, with `git merge-base --is-ancestor`.)*

---

## §1. What the tree already dictates

Facts, measured, that bound everything after this:

- **`POST /upload` takes one file** (`file: UploadFile`) and returns
  `202 {receipt_id, image_key, status: "pending"}`.
- **`require_upload` is "the API key **or** any signed-in user"**, so a reviewer
  can upload. (The export button is admin-only and 403s for the seeded user —
  unchanged by this work, recorded in ISSUE-010.)
- **Accepted suffixes** are `.jpg .jpeg .png .webp .pdf .heic .heif`, bounded by
  `settings.max_upload_mb` (default 25). **The magic-byte sniff decides the
  type; the extension is a cheap first gate.**
- **Nothing in the UI polls.** `main.tsx`, `ReceiptsScreen` and `ReviewScreen`
  each say so in their own comments.
- **There is no client-side routing.** ADR-0027 decision 4: a pathname switch,
  and every route change is a real document navigation.
- **`_stage(name)` records no progress.** It is a context manager that tags an
  exception with the stage that raised it, so a failure in a nested hook still
  reports as `normalize` rather than the enclosing `extract`. Failure
  attribution only.
- **The ordered pipeline is** `load → preprocess → dedupe → triage → merchant →
  extract → score → persist`, with `normalize` and validation running *inside*
  the repair loop.
- **The escalation is eval-only.** `run_receipt`'s sole caller is
  `build_eval_pipeline`, pinned by an AST enumeration (ADR-0047 decision 5), and
  `extract_fallback_client` is documented as the eval path's rung parameter.
  `process_receipt` calls `extract_with_repair` with **one client and no
  ladder**.
- **`extract_with_repair` reports nothing.** It returns an `ExtractionOutcome`
  at the end and has no hook of any kind.

### §1a. A correction recorded here because it nearly shaped the design

An earlier draft of this design proposed narrating the escalation — *"granite
ran, was discarded, `gemma4:cloud` produced the answer"* — as the hero moment of
the processing screen. **That event cannot occur on the path a demo uses**, for
the reason above. The screen would have been built around a beat that never
fires. It was caught by checking `run_receipt`'s callers rather than by
reasoning about the feature, which is ADR-0045 decision 3 working as intended.

---

## §2. Progress: how it reaches the browser

### Decision 1 — progress lives in Redis, not in a column

`REDIS_URL` is already a boot requirement (ADR-0035 refuses to start without it)
and the worker already talks to it. Progress is interesting for thirty seconds
and noise forever after.

A `receipts.pipeline_stage` column would mean a migration, **a committed write
per stage on the hot path of every receipt**, and a permanent record of a
transient thing. A keyed Redis value with a TTL costs no migration and no
database write — which also keeps this change out of the persist path, where the
merchant-fingerprinting regression lived that all five gates were green on.

**What would fail if this reason were false:** if Redis were *not* already
mandatory, this design would be adding a new hard dependency to the boot path,
and the trade would flip. ADR-0035's refusal list is what makes it free.

### Decision 2 — a separate read route

`GET /receipts/{receipt_id}/progress`, returning the current stage and, while
`extract` is active, what it is doing. Separate rather than folded into
`GET /receipts/{receipt_id}` because it is ephemeral data with a different
lifetime and different caching. It is not paginated, so ADR-0034's `PageLimit`
and ADR-0046 decision 3's `PAGINATED_PATHS` do not apply.

### Decision 3 — progress is narration; **status is truth**

The screen polls the receipt's **status** to decide it has finished, and treats
progress purely as commentary. A receipt reaching `auto_approved` or
`needs_review` is done whether or not a single progress event ever arrived.

**This is the load-bearing decision of §2.** If Redis drops the key or the
worker dies, progress goes silent — and silence is indistinguishable from "still
working". A design that let progress decide when the screen is finished turns a
dead worker into an infinite spinner in front of an audience. **A failure must
surface as a failure.**

### Decision 4 — `extract_with_repair` gains one optional sink

An optional parameter defaulted to `None`, in the shape of the eval path's
`attribution_sink`, that the function pushes attempt events into.

**Optional and defaulted is not a style preference.** It is the only form of
this change in which every existing caller is unaffected *by construction*
rather than by inspection, and this function is on the hot path of every
receipt.

---

## §3. The upload screen

### Decision 5 — the drop zone always produces a list

A list of one is still a list. When it holds exactly one item, that item's
processing view fills the screen — so the single-receipt hero view is what the
demo gets, with no special case in the code. Multiple files upload sequentially,
because the route takes one file per request.

### Decision 6 — upload becomes processing **in place**, with no navigation

ADR-0027 decision 4 means a route change is a real document load. Navigating
after upload would put a page flash at exactly the wrong moment. The drop zone
is replaced by the processing view on the same route and the same mount. The
only real navigation is the deliberate one at the end, into review.

### Decision 7 — the client mirrors the server's bounds but never overrules them

The screen refuses files over `max_upload_mb` and unknown suffixes before
spending an upload. **A file that passes the client and fails the server shows
the server's reason**, because the client checks an extension and the server
checks bytes, and they can legitimately disagree. Inventing a client-side reason
for a server-side rejection is the species this repository keeps closing.

### Decision 8 — PDFs are refused at the door, pending ISSUE-027

Measured 2026-08-23: `validate_upload` **accepts** a PDF
(`content_type: application/pdf`) and `load_image` raises
`UnsupportedFormat: Unsupported file extension: '.pdf'`. `expand_pdf` exists and
has **zero callers**. So every PDF is accepted, stored, rowed, queued, and dies
at `preprocess`.

Silently accepting a file guaranteed to fail is the worst option available and
is a live demo landmine. Refusing with a plain reason is honest and reversible
the moment ISSUE-027 is decided. **This design does not fix ISSUE-027** — that
is a decision between wiring `expand_pdf` and dropping `.pdf` from
`_ALLOWED_SUFFIXES`, and §19 advertises PDF support either way.

### Decision 9 — HEIC degrades to a chip, not a broken image

Browsers cannot render HEIC in an `<img>`. The thumbnail falls back to a
filename and a type chip. iPhone photos are HEIC by default, so this is likelier
in a live demo than it sounds.


### Dated correction (2026-08-24) — §3 describes a screen that was not built

Decisions 5 and 9 above describe a drop zone, a list and a thumbnail. **None of
the three shipped**, and **plan 3 inherits this section**, so what was actually
built is recorded here rather than left for a reader to restore.

**What shipped instead**, re-derived on the checkout:

| §3 says | the tree |
|---|---|
| "the drop zone" (decisions 5 and 6) | No drop zone. Nothing under `frontend/src` handles a drag. |
| "always produces a list" | `UploadScreen` holds a single nullable value, not a list. |
| "Multiple files upload sequentially" | The input carries no `multiple`. One file per choice; the chooser is gone the moment there is something to watch. |
| "the thumbnail falls back to a filename and a type chip" (decision 9) | Neither screen renders a thumbnail at all. `ProcessingView`'s inputs are a receipt id and a file name; the image is a separate signed-URL call it never makes. |

Row 1 was derived by running, rather than by reading:

```
grep -rE "onDrop|onDragOver|dataTransfer" frontend/src   # nothing
grep -rniE "drop zone|dropzone" frontend/src             # one line
```

and that one line is the stylesheet comment saying there deliberately is not
one.

**Why — and it is a reason rather than an omission.** It lives
in `UploadScreen.module.css`: the chooser is *"deliberately NOT called a drop
zone anywhere: nothing here handles a drag, and a box that looks droppable and
is not is a worse lie than a plain one."* The list went the same way — the
input disappears the moment a receipt is accepted, so a second file cannot be
chosen and a length-two branch would be a screen nobody can reach, which this
project has shipped green before. Decision 9 then has nothing to attach to,
because a chip needs a thumbnail to degrade from.

**This correction exists because the reasoning lives in a stylesheet and the
plan still says otherwise.** `docs/superpowers/plans/2026-08-24-upload-and-processing-screen.md`
maps decision 5 to "Task 2 Step 7" as covered in its Self-Review, calls
`UploadScreen.tsx` "The drop zone, the list" in its File Structure, and opens
with "A drop zone produces a list of files". Those plans do not self-amend; a
plan-3 implementer reading them would restore a decision that was deliberately
dropped. The same note is in that plan's own defect log.

**Decision 9 is a gap rather than a rejection.** Nothing here decided HEIC
should render badly — there is no thumbnail on either screen to render it. If
plan 3's browser pass adds one, the chip is still the right fallback and this
decision is still live.

---

## §4. The processing screen

**Layout: receipt left, timeline right** — the same two-pane shape the review
screen already uses, so when extraction finishes the timeline is replaced by the
form and **the receipt never moves**. The alternatives (a stepper above, or the
receipt as a full-bleed canvas) both make the photograph jump at the moment the
audience should be looking at the extracted numbers.

**What it narrates.** Stages collapse to one quiet line with an elapsed time as
they complete; the active row is the only one carrying weight. Because
`extract` is where essentially all the wall clock goes, it expands while active
to show the real sequence:

```
attempt 1 → validate → findings → repair → attempt 2 → … → keep the BEST attempt
```

The audience watches the system find its own mistake and fix it — and then
watches it *decline* a repair that made things worse, because
`extract_with_repair` keeps the best attempt rather than the last. That is the
hero beat.


### Dated correction (2026-08-24) — §4 described a sequence nothing emits, and there is no elapsed time

Two claims in "What it narrates" above are wrong, and **plan 3 inherits this
section**, so they are corrected here rather than left for a reader to trip on.

**1. The sequence is not what the pipeline narrates.** The block above reads
`attempt 1 → validate → findings → repair → attempt 2 → … → keep the BEST
attempt`. That is `extract_with_repair`'s *internal control flow*. It is not
what reaches a screen.

Re-derived 2026-08-24 by counting every `ProgressEvent(...)` construction in
the tree — there are three that narrate, and one more that only rebuilds an
event from JSON:

| site | what it emits |
|---|---|
| `pipeline.py`, inside `_stage` | the stage name, **no detail** |
| `extractor.py`, `_report` | `attempt {n} ({pass}): {k} error(s)` |
| `extractor.py`, after `min(attempts)` | `kept attempt {n} of {m}` |
| `progress.py`, `decode` | not an emitter — reconstructs from JSON |

So **only `stage="extract"` ever carries a detail**, and `validate`, `findings`
and `repair` emit nothing at all. The real sequence a screen can show is:

```
attempt 1 (extract): 3 errors → attempt 2 (repair): 0 errors → kept attempt 2 of 2
```

**The hero beat survives intact** — the audience still watches the system find
its own mistake, fix it, and sometimes *decline* a repair that made things
worse, because `Attempt.rank()` sorts on error count and a worse repair loses.
Only the enumeration was wrong.

**2. "Stages collapse to one quiet line with an elapsed time" — there is no
elapsed time, and the screen ships without one.** `ProgressEvent` carries two
fields, `stage` and `detail`; no timestamp crosses the wire, and the worker is
asynchronous, so the only interval a browser can measure is between its own
asks.

That is not nothing — for a stage whose start *and* end were both observed, the
gap between first sightings is its observed dwell, bracketed by one poll
interval. But a stage shorter than the poll is invisible, and worse, it
silently inflates its predecessor's measured interval with no way to tell the
two cases apart. **Decision 10 already forbids presenting any of this as
latency**, and an invented figure is worse than a missing one — this repository
deleted one such figure before. The implementation therefore shows none and
records why.

**How both got here, since it is the same shape twice:** this section was
written from the pipeline's source, describing what the code *does*, and then
read as a description of what the code *reports*. Both were caught by an
implementer reading the emitter instead of the design, and confirmed
independently twice.

### Dated correction (2026-08-24) — §0's "~25–60s" is a figure nobody measured

§0 says the brief "makes the ~25–60s of silence in the middle a first-class
design problem". **There is no source for that range.** It is recorded here,
next to the argument it contradicts: the correction above says an invented
figure is worse than a missing one, and decision 10 below records one such
figure already invented and deleted in this repository.

Re-derived 2026-08-24 across the tree:

- The only measured pipeline timing is **25 seconds**, for `gemma4:cloud` on
  r002, against 30–39 minutes for granite locally — `docs/KNOWN_ISSUES.md`'s
  *Measurement (2026-08-18) — `gemma4:cloud` READS THE RECEIPT*, and the same
  measurement in `docs/MEMORY.md`.
- `VLM_AND_DATA.md` says 3–8 seconds is typical.
- **No "60s" in the tree is a pipeline time.** Enumerated 2026-08-24 with
  `git grep -nEI "60 ?s"` over every tracked file. Outside this document,
  fifteen are the review acceptance criterion for a human correction, or the
  argument that a scripted run makes it non-discriminating, and one is an e2e
  suite's own runtime (`2026-08-05-review-ui-browser-pass.md`) — **so the
  reviewer's phrasing, "every 60s in the tree is the review acceptance
  criterion", is not true and is not what is claimed here.**

So the 25 has a source, the 60 has none, and a range implies a distribution
nobody measured. **The figure is deleted rather than replaced**: the
implementation's copy of it, in `ProcessingView.tsx`'s opening line, now reads
"what a person watches while a receipt is processed", which costs nothing and
cannot rot. §0's body is left as written, the way §4's body above is — these
documents are dated records and are corrected here rather than amended.

**Plan 3 must not restore it.** Any elapsed or duration copy on these screens
needs a measurement taken at the time, not this range.

### Decision 10 — elapsed time is labelled as elapsed, never as latency

`VLM_TIMEOUT_S` bounds one HTTP attempt and the SDK retries (ADR-0047 decision
8), so every figure this screen can show covers an unknown number of attempts.
**There is no per-call measurement in this repository**, and one was invented and
deleted during a previous milestone.

### Decision 11 — no counts in the copy

The obvious line is "Checking 30 rules". The rule count moved this week. Rows
say what they are doing; the **findings produced** are the number worth showing,
because that one is derived at the moment it is displayed.

---

## §5. The visual system

**Direction: Editorial — document-forward, generous, hairline-ruled — with a
grotesque display face.** Both chosen by the owner on 2026-08-23. The second
choice was made against this design's recommendation, which is recorded here
because the tension it creates is real and is handled rather than ignored.

### Decision 12 — the neutral ramp cools a few steps toward true neutral

A hard geometric display face against a fully warm paper ground puts two
arguments on one screen. The ramp keeps Editorial's generosity, hairlines and
document framing, and gives the display face a ground it does not fight.

**Concretely, so this is not a mood:** the page background moves from cool Slate
toward neutral but stops short of paper, and **the warmth is carried by the
raised surfaces rather than by the background**. That keeps the receipt — a warm
white object — reading as the warmest thing on screen, which is the effect
Editorial is for, without tinting the whole field toward the reserved amber.

**And it has a cited reason beyond taste.** ADR-0027 decision 2 rejected an
amber-primary palette *outright*, on the ground that **"if amber is the brand
colour, a WARN finding has no colour left."** Severity colours are reserved. A
fully warm ramp travels along that same axis, so cooling it protects a ruling
that already exists rather than expressing a preference.

### What changes in `tokens.css`

The file declares **35 tokens** — 15 colours, 2 faces, 3 radii, 2 shadows, 7
spaces, 6 type sizes. Most of this refresh is **values on names that already
exist**, which is why it touches almost nothing downstream.

*Measured 2026-08-24*: strip `/* … */` from `frontend/src/styles/tokens.css`,
match `--name:` declarations, count the **distinct names** — 35, in exactly the
six groups above. (Counting *declarations* instead answers 65, because the two
dark blocks redeclare 15 colours each; `color-scheme` is not a custom property
and is not among either number.) This said **36** until 2026-08-24, against a
breakdown in its own sentence that sums to 35.

| change | why |
|---|---|
| A cooled-neutral ramp replacing cool Slate | Decision 12 |
| `--color-surface-raised` gets a value distinct from `--color-surface` | **They are both `#FFFFFF` today**, so nothing in light mode can sit raised. The flatness is in the tokens, not the components. |
| Warmer, longer shadows | `--shadow-sm/md` are untuned neutral black at `.05`/`.1`. The receipt should read as an object on a desk. |
| **New:** `--space-4xl`, `--space-5xl` | The scale stops at **32px**, which is why every screen reads tight. |
| **New:** `--text-3xl` | `xl 1.5rem → 2xl 2rem` is the entire display range, so there is no display step at all. |
| **New:** a display face via `@fontsource` | ADR-0027 decision 3 holds — self-hosted, never a CDN. Two subset weights. |

### Decision 13 — this extends ADR-0027; it does not replace it

All five of its decisions stand: light default, CSS Modules plus one
`tokens.css`, `@fontsource` never a CDN, a pathname switch not React Router, and
`null` ≠ `0` ≠ empty. What changes is **values**, plus the new token names the
table above adds: `--space-4xl`, `--space-5xl`, `--text-3xl`, and one for the
display face. (This said "five new token names" until 2026-08-24, against that
same table.) The correct form is therefore **a new ADR extending 0027, with a
dated correction on 0027 itself** — the shape ADR-0043→0011 and ADR-0044→0040
already use here.

---

## §6. Scope

**In:** a new upload/processing screen and its route; the progress sink, the
Redis record and the read route; `tokens.css`; a pass over `LoginPage`,
`ReviewScreen`, `AdminScreen` and `ReceiptsScreen` to adopt the new spacing,
type and elevation; and **the browser pass of decision 14**, which is part of
the work rather than a follow-up.

### §6a. This is more than one plan

Stated by this document's own self-review. The three parts are coherent as one
*design* and should not be one *implementation plan*: the progress mechanism is
backend work with its own pins, the upload and processing screen is a new
surface, and the refresh touches every existing screen. They also have different
risk profiles — only the first goes near the hot path. **Expect three plans, in
that order**, since the screen needs the mechanism and the refresh is
independent of both.

**Out, and deliberately:**

- **ISSUE-027 is not fixed.** PDFs are refused at the door; wiring `expand_pdf`
  is a separate decision.
- **Bounding boxes are not built.** They need a text layer with coordinates,
  which nothing in this stack produces. That is what the approved OCR pass would
  give, sequenced after the golden set grows.
- **No accessibility programme.** The 43 recorded undersized hit targets are not
  addressed; asserting a threshold would put an implementer's judgement in place
  of a design decision nobody has taken.
- **ISSUE-006's arithmetic residual** is untouched.

---

## §7. What no gate can see, and what to do about it

**`frontend/tests/stylesheets.test.ts` pins declarations by name and is silent
on values** — a stated bound of the census. Vitest sets `css: false`, so class
names come back as a proxy. jsdom lays nothing out.

**Therefore: every colour, every space and every type size in this refresh can
change with all five gates byte-identically green, and nobody having looked at
it.** That is ADR-0029's blind spot at full scale, and it is exactly how the
`auto-fit` regression shipped — tiles 35% narrower with a third of the row
blank at 1440, past five gates, five task reviews and five scoped re-reviews,
found only when the final reviewer measured a real browser.

### Dated correction (2026-08-24) — the colour half of §7 is gated, and the ramp is not free

**"Every colour … can change with all five gates byte-identically green" is
false, and believing it would send an implementer at a palette the suite
rejects.** Measured against `frontend/tests/stylesheets.test.ts` on 2026-08-24:
the same file that holds the census also computes WCAG relative luminance and
enforces a **4.5:1 floor across all three theme blocks** — for every rule that
sets `color` and `background` together, and for every inherited `color` token
against `--color-background` and `--color-surface`. It further requires every
colour token to be a plain `#RRGGBB`, because anything else makes the
arithmetic return `NaN` and `NaN >= 4.5` is false.

So the accurate statement is: **the ramp's brightness is gated; its hue is
not.** Spacing, radii, type sizes and shadows remain ungated, exactly as §7
says, and so does whether any of it looks right — which is what decision 14 is
for. Three surfaces are also outside the floor check: `--color-surface-raised`,
`--color-surface-active` and `--color-surface-sunken` are not in
`INHERITABLE_SURFACES`.

> **Superseded the same day, by this design's own browser pass.** Plan 3's Task 3
> put severity text on `--color-surface-raised`, the browser measured it at
> **4.39:1** in dark, and `0fe6be5` both darkened that token and **moved it
> inside `INHERITABLE_SURFACES`**. **Two** surfaces are outside now, not three.
> The paragraph above was true when written and is the reasoning that made the
> gap findable; it is annotated rather than edited for that reason.

**This constrains decision 12 more than decision 12 knew.** The reserved
severity colours already sit near the floor — `--color-severity-error`
`#DC2626` measures **4.62:1** on today's `--color-background` `#F8FAFC`, and
`--color-null` measures **4.55:1**. With 0.12 and 0.05 of headroom, the page
background **cannot get darker**; it can only change hue at roughly constant
luminance. That is a real bound on "moves from cool Slate toward neutral", and
the plan's values were measured under it rather than chosen and hoped for.

### Decision 14 — a browser pass is inside this milestone, not after it

At 1440, 768 and 375, in both themes, with a person reading the captures. On
this project that has never once failed to find something. The milestone is not
done when the gates pass; it is done when someone has looked.

---

## §8. Decisions taken, and by whom

| # | decision | who |
|---|---|---|
| — | Refresh goal is "impress someone" in a live walkthrough | owner, 2026-08-23 |
| — | Hero path is upload → processing → review, owner-driven | owner, 2026-08-23 |
| — | Real stage narration (not a spinner, not fake progress) | owner, 2026-08-23 |
| — | Editorial visual direction | owner, 2026-08-23 |
| — | Grotesque display + Fira body | owner, 2026-08-23, against this design's recommendation |
| 1–4 | Redis, a separate route, status-is-truth, an optional sink | this design |
| 5–9 | Upload behaviour, including refusing PDFs | this design |
| 10–11 | Elapsed not latency; no counts in copy | this design |
| 12–13 | Cooled ramp; extends ADR-0027 | this design |
| 14 | Browser pass inside the milestone | this design |

**A fabricated-progress shortcut was considered and is refused.** The UI could
narrate stages on a timer with the backend saying nothing. It would look
identical, cost almost nothing, and would keep saying "Extracting…" over a dead
worker. It is the same species as the rejected R060 option: a signal that has
not earned its meaning.

---

## §9. Open questions

1. **ISSUE-027** — wire `expand_pdf`, or drop `.pdf` from `_ALLOWED_SUFFIXES`?
   Until then the upload screen refuses PDFs.
2. **Ground warmth** — decision 12 cools the ramp against the owner's warm
   preference to protect ADR-0027's reserved severity colours. The owner may
   overrule and accept the tension.
3. **Demo runtime** — the full stack (Postgres, Redis, API, worker, Ollama Cloud)
   has never been exercised with a real upload through the worker; only the
   Ollama container was running when this was written. A dry run is worth
   scheduling well before demo day, and it is not part of this design.
