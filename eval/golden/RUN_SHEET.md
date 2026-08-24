# Run sheet — collecting and labelling receipts

For working with a stack of receipts in front of you. `README.md` in this
directory is the reference and wins on any disagreement; this page is the order
to do things in and the mistakes that have actually been made.

ISSUE-001 step 7, Task 3. Controller-only: it needs your receipts, a camera and
your reading, and no code removes that.

---

## Where the set stands

Measured 2026-08-25 via `composition_stats`: **3 receipts, all `handwritten`,
1 held out.** Against a 20% handwritten target that is five times its intended
weight, in the hardest category — which is why ADR-0049's 60.00–61.43% describes
the hardest fifth of the intended mix and not the mix.

**Collecting toward the targets should move the measured figure with no model
change at all.** Do not read the change as a change in the system.

| category | target | at a 50-set | have | still to collect |
|---|---|---|---|---|
| `printed_clean` | 60% | 30 | 0 | **30** |
| `printed_degraded` | 15% | 7.5 | 0 | **8** |
| `handwritten` | 20% | 10 | 3 | **7** |
| `adversarial` | 5% | 2.5 | 0 | **3** |
| | | | | **48 more → a set of 51** |

Hold out **10–15** of those 51 (`"holdout": true`). One is held out today.

`adversarial` means not a receipt, two in frame, upside down, half cut off.
`printed_degraded` means faded thermal, folded, glare.

---

## Per receipt, in order

**1. Photograph it the way it will really be captured.** Phone camera, indoor
light, slightly crumpled. Save as `images/{id}.jpg`. Images are gitignored.

**2. Decide public or private BEFORE you type anything.**

| the receipt is… | name it | what happens |
|---|---|---|
| a real third party's — their name, address or tax id on it | `p{id}.json` | gitignored; scored here, absent from the repo |
| yours, synthetic, or the owner consented to publication | `r{id}.json` | committed, as `r001`–`r003` are |

**When in doubt, use `p`.** A label committed by mistake is in git history
permanently; a private label can be published later. There is no partly-redacted
label — nulling a PII field in the truth makes a model that reads the real value
score as having *hallucinated* it.

**3. Copy `TEMPLATE.json` to `labels/{id}.json` and replace every value with
what the image shows.**

- **Never seed a label from the pipeline's own output.** Not for any field being
  measured, not "and then correct it". Every field the corrector misses is
  enshrined as truth *and* scored as correct. `r003` is the worked example: the
  model reads 2 of its 18 fields, so a seeded label would be near-empty and the
  model would score 100% against it.
- **Money is a JSON string** — `"761.60"`, not `761.60`. A bare number collapses
  the Decimal scale to `761.6`.
- **`null` for anything the receipt does not show or you cannot read.** A wrong
  value is far worse than a missing one.
- **Write `null`, do not drop the key.** A dropped key is filled by a schema
  default that then reads as truth.
- **Spell every key exactly.** The schema is `extra='ignore'`, so a mistyped key
  is silently discarded and its field becomes null. `validate_labels` will not
  tell you (see below).
- **Transcribe what is printed even if it does not add up.** Do not fix the
  receipt.
- Dates are ISO `YYYY-MM-DD`; keep the printed form in `date_raw` when it is
  ambiguous. **A malformed date is accepted at load** — `receipt.date` is a
  plain string — so nothing will catch `"14/03/2026"` sitting in that field.

**4. Record it in `manifest.json`** — id, category, holdout. **Do this for `p`
receipts too.** An id, a category and a flag carry no personal data, and the
manifest is what lets `composition_stats` report the real mix.

---

## After every batch, not at the end

```bash
python -c "from pathlib import Path; from eval.golden_set import validate_labels, composition_stats; print(validate_labels(Path('eval/golden/labels'))); print(composition_stats(Path('eval/golden/labels'), Path('eval/golden/manifest.json')))"
python -m pytest
```

**`validate_labels` returning `[]` certifies much less than it looks like.**
Measured: it is `[]` for a label whose every key is misspelled, and for `{}`.
Both load as a fully-null truth. **The suite is the guard, not the validator** —
run all of it, not `tests/test_eval_floor.py` alone, because `tests/test_rules.py`
is what validates a new label against the validator and is not in that module.

**Count the real-label cases, not the total.** The corpus check carries two
synthetic calendar cases that pass whether or not a single label loaded. If you
add a label and the real-label cases do not go up, that is the bug, not luck.

**A label that will not parse aborts the whole run and names itself** — look for
`while loading golden label <name>`.

**A `p*` label reports its errors redacted** (ISSUE-033). You get the field path
and the error kind — `merchant.tax_id [string_type]` — and never the value, on
the terminal and in the traceback. The parser's line-and-column detail is lost
with it; if you need that, validate a copy with the values stripped.

**Nothing checks your label against the photograph.** ISSUE-004, known and
accepted. The images are gitignored, so a wrong transcription is invisible to CI
at any severity. Labelling accuracy is entirely on the reader — a printed-order
defect in `r001`/`r002` was once caught by a human reading a plan against the
images, and by nothing else.

---

## When the set is grown

```bash
python -m eval.run_repeats --run-id "$(date +%F)-cloud-only" --repeats 5
find eval/results -name "*.tmp"
git status --short
git add eval/results/ eval/golden/manifest.json
git diff --cached --stat
```

**Read that stat before committing. No `p*.json` may appear in it.**

Read `scored_receipts`, `n_failed` and `spread_omitted` before quoting any
figure, and **report min/max/median/n — never a single number.** Compare only to
a run over the same `scored_receipts`.

**Neither committed baseline carries that field**; it was added after both
landed. Derived 2026-08-25 from each repeat's `results[].receipt_id`:

| run | `scored_receipts` | repeats |
|---|---|---|
| `2026-08-22-cloud-only` | `{r001, r002, r003}`, identical across all five | 5, `n_failed: 0` |
| `ladder-probe` | **`{r002}` alone** | 1 |

So `ladder-probe` is not a weaker comparison to the baseline — it is a
different measurement over one receipt. Do not compare them.
