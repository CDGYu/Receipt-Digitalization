# Golden set (Milestone 0)

The golden set is the highest-value work in the project. Every later decision —
model choice, prompt wording, confidence threshold — is tuned against it. Build
it *before* any pipeline code (spec §15, M0).

This directory is the on-ramp: drop in hand-labelled receipts and the validator
tells you whether they are schema-valid and whether the set is the right size
and mix.

**Working through a stack of receipts?** `RUN_SHEET.md` beside this file is the
same procedure in the order you do it, with the mistakes that have actually been
made and the arithmetic of what is still to collect.

## Layout

```
eval/golden/
  labels/{id}.json        one hand-label per receipt (`r` tracked, `p` ignored)
  images/                 the source photos (GIT-IGNORED — receipts hold PII)
  manifest.json           id -> {"category", "holdout", "withheld"} sidecar
  manifest.example.json   a worked example of the manifest
  TEMPLATE.json           a schema-valid worked label to copy
```

Public labels are committed; images are not (`eval/golden/images/` is in
`.gitignore`), and neither is a private label — see "Public or private?" below.
Keep each image next to its label by filename stem — `images/{id}.jpg` pairs with
`labels/{id}.json`.

## How to label a receipt

1. Photograph the receipt the way it will really be captured: phone camera,
   indoor light, slightly crumpled. Save it as `images/{id}.<ext>`.
2. Copy `TEMPLATE.json` to `labels/{id}.json`. **The `{id}` you type here is the
   privacy decision** — `p` for a real third party's receipt, `r` for one you may
   publish. Read "Public or private?" below before you name the file.
3. Replace **every** value with exactly what the image shows. Transcribe the
   printed values even if they do not add up — do not "fix" the receipt. Read
   "Where a label may come from" below first: where you got a value is as much
   a rule as what the value is.
   - **Money is a JSON string**, e.g. `"761.60"` (not `761.60`). The string keeps
     the Decimal scale; a bare number collapses `761.60` to `761.6`.
   - Use `null` for anything the receipt does not show or you cannot read. A
     wrong value is far worse than a missing one.
   - Dates are ISO `YYYY-MM-DD`; keep the verbatim printed form in `date_raw`
     when it is ambiguous.
4. Record the receipt's category and holdout flag in `manifest.json`
   (see `manifest.example.json`).

## Where a label may come from

**Decide this before you start typing, not after.** A label is never seeded
from the pipeline's own output for any field being measured. Do not produce one
by running the extractor and correcting what it returns.

The shortcut is obvious, and that is exactly the danger, because its failure is
silent: every field the corrector does not catch is enshrined as truth *and*
scored as correct. The measurement would certify itself.

`r003` is the worked example. In the committed `2026-08-22-cloud-only` baseline
the model reads **2 of its 18 fields** — 11.11%, on all five repeats. A label
seeded from that output would be near-empty, and the model would then score
**100%** against it: a perfect figure describing nothing.

**Nothing checks this, and no gate can.** Nothing checks a label against its
photograph either — a known and accepted gap — and seeding from model output is
what would turn that gap from latent into load-bearing. See the 2026-08-22
growing-the-golden-set design, section 5.

## Public or private?

**Decide this before you write the label, not after.** A label is committed in
full or not at all — there is no partly-redacted label, because nulling a PII
field in the truth makes a model that reads the real value score as having
*hallucinated* it (measured; see the 2026-08-22 growing-the-golden-set design,
section 3).

| the receipt is… | name it | what happens |
|---|---|---|
| a real third party's, with their name, address or tax id on it | `p{id}.json` | gitignored — scored here, absent from the repo |
| yours, synthetic, or the owner has consented to publication | `r{id}.json` | committed, as the existing three are |

**When in doubt, use `p`.** A label committed by mistake is in git history
permanently; a private label can always be published later.

Record the receipt in `manifest.json` either way — an id, a category and a
holdout flag carry no personal data, and keeping every receipt there is what
lets `composition_stats` report the real mix. A clone that lacks the label
simply does not count it.

### `withheld` — say what you left out, and it must be nothing

Every manifest entry carries a `withheld` list naming the label paths you did
not fill in for privacy reasons:

```json
"r001": { "category": "handwritten", "holdout": false, "withheld": [] },
"p006": { "category": "printed_clean", "holdout": false,
          "withheld": ["merchant.tax_id", "buyer.name"] }
```

**For every `r*` label this list must be empty, and a test enforces it.** That
is "committed in full or not at all", written down where a gate can read it.
Until 2026-08-25 the rule lived only in this file and in ADR-0050 decision 1,
and a tracked label with its merchant and buyer nulled passed every gate
(ISSUE-019).

The list is here rather than in the label because **the label cannot express the
difference**. Step 3 above tells you to write `null` for anything the receipt
does not show — so `merchant.tax_id: null` is correct for a receipt with no
printed tax ID and wrong for one where you removed it, and nothing in the file
can tell those apart. The manifest can.

The key is required, and empty is not the same as absent: a missing `withheld`
reads as "nothing withheld" while asserting nothing, so the test refuses it.

**If you find yourself wanting a non-empty `withheld` on an `r*` label, the
label is a `p*` label.** Rename it. That keeps one boundary — the same `p`
prefix `.gitignore` uses — rather than a second, quieter way of saying private.

## Composition targets (spec §15)

Collect **50–100** receipts. Aim for this mix:

| Category           | Target | Meaning                                             |
| ------------------ | ------ | --------------------------------------------------- |
| `printed_clean`    | 60%    | machine-printed, good condition                     |
| `printed_degraded` | 15%    | faded thermal, folded, glare                        |
| `handwritten`      | 20%    | handwritten receipts                                |
| `adversarial`      | 5%     | not a receipt, two in frame, upside down, half cut  |

Hold out **20–30%** of the set (`"holdout": true`) as an untouched test split so
threshold calibration is not measured on data it was tuned against.

## Validate your set

Run from the repo root:

```bash
python -c "from pathlib import Path; from eval.golden_set import validate_labels, composition_stats; print(validate_labels(Path('eval/golden/labels'))); print(composition_stats(Path('eval/golden/labels'), Path('eval/golden/manifest.json')))"
```

- `validate_labels` returns a list of `"{file}: {reason}"` strings for labels
  that fail schema validation — an empty list `[]` means every label is valid.
- `composition_stats` reports `total`, `meets_minimum` (>= 50), the per-category
  breakdown and holdout count from the manifest, and the target mix above.
