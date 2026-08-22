# Growing the golden set — design

**Date:** 2026-08-22
**Status:** Proposed
**Closes:** `docs/KNOWN_ISSUES.md` ISSUE-001 **step 7**. ISSUE-017 is why it now
gates more than the model does.
**Rests on:** ADR-0040 (what `field_accuracy` counts), ADR-0049 (the first
baseline, and that it is a spread over receipts), ADR-0018 (PAN masking).

---

## §0. Where every figure in this document comes from

**Measured while writing this design, on `main` at `7b62644`.** Each is
reproducible from the probe named beside it:

- nulling a PII field in the truth turns a correct read into a **hallucination**
  (§3);
- `run_eval` globs **one** directory, `labels_dir.glob("*.json")` (§4);
- `.gitignore` currently excludes only `eval/golden/images/`; the labels
  directory tracks `.gitkeep` and `r001`–`r003` (§4);
- r003's `merchant.tax_id` appears in **4 tracked files outside the labels**, and
  the buyer name r001 and r003 share in **16** each, r002's different one in
  **3** (§2);
- every golden PII value is in git history, several in 12–14 commits (§2);
- r003 scores transcription **2/18** with **0 hallucinated**, 13 correctly
  empty, and confidence **0.000** (§1);
- a label's top-level keys are `buyer, line_items, merchant, meta, payment,
  receipt, totals`, and a real one validates as `ReceiptExtraction` (§5).

**Carried, not re-measured here.** `RECEIPT_SYSTEM_SPEC.md` §15 line 1530:
"Collect 50–100 real receipts… Photograph them the way they'll really be
captured… Hand-label each into the §7 schema."

---

## §1. What this delivers, and what it does not

**Delivers** a way to grow the golden set **without publishing any more real
businesses' names, addresses or tax IDs**, and without touching the metric
definitions, the PAN fixtures, or the existing three labels.

**Does not deliver** the receipts themselves — those are the owner's to supply —
and does not remove the existing exposure, which is in git history and unchanged
by anything here.

**A note on r003, because it shapes what "growing the set" is for.** r003 scores
2/18 with **zero hallucinations**, 13 fields correctly left empty, and confidence
`0.000`. That is the system doing what this project's non-negotiables demand:
null over confident-wrong, and route to review rather than auto-approve. **r003
is not evidence the model is broken; it is evidence that averaging three
receipts into one figure is.** Growing the set is how that stops being the only
thing the number can say.

---

## §2. The constraint, measured

The golden **labels are tracked and public**; only images are gitignored. Each
label carries `merchant.name`, `merchant.address`, `merchant.tax_id`,
`receipt.number` and `buyer.name`.

Two of those values are **load-bearing fixtures elsewhere in the tree**, which is
why scrubbing the existing three is a different and riskier job than keeping the
new ones clean:

| value | tracked files outside the labels |
|---|---|
| r003 `merchant.tax_id` | **4** — `docs/adr/0018-pan-masking-policy.md`, two PAN plans/specs, `tests/test_repository.py` |
| `buyer.name` on **r001 and r003**, which carry the *same* name | **16** each — frontend tests, the e2e spec, `scripts/seed_review_e2e.py`, eight backend test modules |
| `buyer.name` on **r002**, which is a different name | **3** |

*(The buyer figure was written as one "shared" name across all three during the
first draft, from both being twelve characters and two words. Checked rather
than inferred: r001 and r003 are identical, r002 is not. Two of the three, not
three of three.)*

And every value is already in history — 1 to 14 commits each. **Nothing in this
design removes that.** It stops the exposure growing; it does not undo it. The
existing decision (rewrite history / go private / accept it) stays where it is.

---

## §3. Why redaction is per receipt and not per field

The obvious design — publish the label with its PII fields nulled — **corrupts
the metric**, and not in the direction anyone would guess.

ADR-0040 reads *filled* from the truth side only. So a nulled field in the truth
does not merely leave the denominator; it moves the path into the **absent**
classes, where a prediction that fills it is **hallucinated**. Measured, with a
prediction that reads the merchant name correctly:

```
truth HAS the name    ->  transcription 2/2   hallucinated=0
truth name NULLED     ->  transcription 1/1   hallucinated=1
```

**A model that correctly reads the real merchant off the image would be scored as
inventing it.** A public CI run would report hallucinations that never happened.

Fixing that means changing `field_breakdown` to skip declared-redacted paths in
**every** class — and that is ADR-0040's published metric surface, where
narrowing "moves a published metric". The same warning `is_filled` carries.

**So the unit of redaction is the whole receipt.** A label is fully public or
fully private, never partially redacted.

---

## §4. The design

**One directory, two visibilities.** Private labels are named on a reserved
prefix and excluded by `.gitignore`; public ones keep today's `r` prefix.

```
eval/golden/labels/r001.json     tracked   (existing, untouched)
eval/golden/labels/p004.json     ignored   (new, carries real PII)
eval/golden/images/*             ignored   (already, unchanged)
```

**`eval/harness.py` needs no change.** `run_eval` already does
`sorted(labels_dir.glob("*.json"))` over a single directory, so a private label
beside a public one is scored here and is simply absent in a clone. No second
directory, no merge step, no contract change, and nothing new that can be wrong.

**What would fail if that were false:** the harness would need a second glob and
a precedence rule between two sources — the two-mechanisms-that-must-agree shape
this repository legislates against. It is worth stating precisely because the
absence of work is the load-bearing property.

**Coverage is recorded, not implied.** Each per-repeat results file already lists
`results[].receipt_id`, so which receipts a number covers is in the committed
artifact today. The aggregate gains one top-level count naming the public/private
split, **derived by comparing the scored ids against the tracked label names** —
never by restating the naming rule, because a second copy of that rule is one
that can drift. That is the shape `spread_omitted` already takes.

**A clone gets an honest refusal, not a misleading figure.** With only the three
public labels present, a fresh clone scores three receipts and says so. If a
clone has none, the CLI already refuses a zero-receipt run rather than writing a
well-formed artifact over nothing.

---

## §5. How a label is made, and the hazard that shapes it

Spec §15 says hand-label. A label validates as `ReceiptExtraction` and carries
`buyer, line_items, merchant, meta, payment, receipt, totals`.

**Labels are not seeded from the pipeline's own output for any field being
measured.** This is the decision most worth stating, because the shortcut is
obvious and its failure is silent: if a label is produced by running the model
and correcting it, every field the corrector does not catch is enshrined as
truth *and* scored as correct. The measurement would certify itself.

r003 is the worked example. It reads 2 of 18 fields. A label seeded from that
output would be near-empty, and the model would then score **100%** against it —
a perfect figure describing nothing. ISSUE-004 already records that nothing
checks a label against its photograph; this makes that gap load-bearing rather
than latent.

**What would fail if this were false:** nothing. No gate can see it, which is
exactly why it is a stated decision rather than an enforced one.

---

## §6. What this costs, stated plainly

- **A fresh clone cannot reproduce a number measured here.** It has three
  receipts; this machine will have more. The artifact says which.
- **The hand-labelling is the real bottleneck**, not the mechanism. Fifty to a
  hundred receipts into the §7 schema is substantial human work, and §5 rules out
  the shortcut that would make it cheap.
- **The existing three keep their exposure.** Unchanged, and out of scope here.

---

## §7. Testing

Offline, no network, no provider — the seam `run_baseline` already exposes.

1. **A private-prefixed label is scored when present.** Proven red by renaming it
   to a public prefix and showing the count is unchanged — which is the mutation
   that matters, because the naming rule is the whole mechanism.
2. **The public/private split in the aggregate matches the ids actually scored.**
   Proven red by hardcoding the count, the shape that has failed eight times on
   the previous milestone.
3. **`.gitignore` excludes the private prefix and nothing else.** Stated over
   `git check-ignore`, not over a reading of the file.
4. **A label with a PII field nulled is not silently scored** — the §3
   measurement, pinned, so nobody reintroduces field-level redaction believing it
   only shrinks a denominator.

---

## §7a. Correction, 2026-08-22 — most of this already exists

**Found during the plan's pre-flight, and it narrows this design considerably.**
`eval/golden/` already contains `README.md`, `TEMPLATE.json`, `manifest.json`
and `manifest.example.json`, all tracked. The README specifies the four-step
labelling procedure, the file-stem pairing between `labels/{id}.json` and
`images/{id}.<ext>`, the money-as-string rule, `null` over a guess, and the
composition targets from spec §15:

| category | target | actual today |
|---|---|---|
| `printed_clean` | 60% | **0** |
| `printed_degraded` | 15% | **0** |
| `handwritten` | 20% | **3 of 3 — 100%** |
| `adversarial` | 5% | **0** |

Hold out 20–30%; `manifest.json` marks r003 as the only holdout.

**Two consequences.**

**This design's contribution is narrower than §4–§5 imply**: everything except
the private-label mechanism already exists. §5's "labels are not seeded from the
pipeline's own output" remains a genuine addition — the README does not say it —
but the procedure it constrains is already written.

**And the composition is itself a finding.** The set is **100% handwritten
against a 20% target**, five times its intended weight, and handwritten is the
hardest category. ADR-0049's 60.00–61.43% is an average over three receipts
*all* drawn from the hardest fifth of the intended mix. Growing toward the
documented targets should move the measured figure substantially **with no model
change at all** — which is a further reason step 7 gates more than the model
does, and a reason not to read today's number as a ceiling.

**What still needs building** is only: the private-label naming convention and
its `.gitignore` entry, the README section documenting it, and whatever the
public/private split requires in the artifact.

---

## §7b. Correction, 2026-08-22 — the split count was superseded, and never built

**§4's "one top-level count naming the public/private split" does not exist, and
that is deliberate.** The plan resolved §9's question 2 the other way: the aggregate
carries `scored_receipts`, a **sorted union of the receipt ids actually scored**,
and no count of any kind. The reasoning is in
`docs/superpowers/plans/2026-08-22-growing-the-golden-set.md` under "The spec's
§9 questions, resolved" — a count of how many labels were private restates the
naming rule, and a second copy of a rule is one that can drift, which this
milestone had already paid for once.

**Three sentences in this document still describe the superseded shape.** They
are named here rather than silently edited, because this is a dated record and
§4 genuinely did specify a count when it was written:

- **§4**, "The aggregate gains one top-level count naming the public/private
  split, **derived by comparing the scored ids against the tracked label
  names**." Neither half shipped. `scored_receipts` is a list, not a count, and
  it is accumulated from `report.results` inside `eval/run_repeats.py`'s loop —
  it never reads a tracked label name, which is exactly what lets it restate
  nothing.
- **§7.2**, "The public/private split in the aggregate matches the ids actually
  scored. Proven red by hardcoding the count." **There is no count to
  hardcode.** What shipped is pinned instead by
  `tests/test_run_repeats.py::test_the_aggregate_names_the_receipts_it_scored`,
  proven red against an implementation that keeps only the first repeat's ids,
  one that keeps only the last's, and one that re-globs the labels directory at
  the end.
- **§7a**, "whatever the public/private split requires in the artifact." What it
  required was a list of ids.

**§4's load-bearing claim is untouched by this.** "Coverage is recorded, not
implied" is what shipped; only the form changed, from a count that restates the
naming rule to a list that restates nothing.

---

## §8. What this does not decide

- **Whether the repo goes private, or history is rewritten.** Unchanged, and
  still the owner's call.
- **Whether the existing three labels are scrubbed.** §2 is why that is a
  separate job.
- **How many receipts to collect, or which mix.** Spec §15 says 50–100 covering
  the real mix; nothing here narrows it.
- **Why r003 fails identically on every repeat.** ISSUE-017 records the fact;
  this design does not diagnose it.
- **Whether `field_breakdown` should learn about redacted paths.** §3 is the
  argument that it would have to for field-level redaction; this design avoids
  needing it.

---

## §9. Open questions for the plan

1. **The private prefix.** `p` is the obvious choice and collides with nothing
   today, but the plan must check it against every existing glob and fixture name
   before committing to it.
2. **Whether the split count belongs in the aggregate or only in the per-repeat
   files.** The per-repeat files already carry the ids; the aggregate count is a
   convenience that can drift from them, and this milestone has already paid for
   one derived count that drifted.
3. ~~**What a labelling run looks like operationally.**~~ **ANSWERED BY THE
   REPO, and this question should never have been asked.** Found during the
   plan's pre-flight: `eval/golden/README.md` already documents a four-step
   labelling procedure against `eval/golden/TEMPLATE.json`, `manifest.json`
   already carries `category` and `holdout` per receipt, and `validate_labels`
   and `composition_stats` are built and working (`validate_labels` returns `[]`
   today). See the correction below.
