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

The file declares **36 tokens** — 15 colours, 2 faces, 3 radii, 2 shadows, 7
spaces, 6 type sizes. Most of this refresh is **values on names that already
exist**, which is why it touches almost nothing downstream.

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
`null` ≠ `0` ≠ empty. What changes is **values**, plus five new token names. The
correct form is therefore **a new ADR extending 0027, with a dated correction on
0027 itself** — the shape ADR-0043→0011 and ADR-0044→0040 already use here.

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
