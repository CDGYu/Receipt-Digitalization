# PAN Grouping Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `_PAN_RE` mask a card number written in five further group shapes
and with a doubled separator, so those spellings stop being stored in the clear.

**Architecture:** Five fixed-shape alternatives are added to the existing
alternation and the separator class gains a `{1,2}` repetition. Nothing else in
the redaction path changes. Two new structural tests pin the properties the
change must not break — that no match starts at a 3-digit group (the corpus-TIN
guarantee) and that no match holds a digit count outside 13–19 (the guarantee
`_mask_pan`'s unreachable branch rests on).

**Tech Stack:** Python 3.14, `re`, pytest, SQLAlchemy 2.x, FastAPI TestClient,
React 19 + Vite + TypeScript, Vitest.

**Design doc:** `docs/superpowers/specs/2026-07-31-pan-grouping-design.md`
**ADR:** `docs/adr/0020-pan-grouping-coverage.md` (already written and committed)

## Global Constraints

- **A full PAN is never persisted.** SPEC §18. This is the invariant the whole
  task serves.
- **`Decimal` on the money path, never `float`** (ADR-0001). Nothing here
  touches money; do not introduce arithmetic.
- **`redact_pan` stays pure and recursive**, never mutating its input, never
  raising.
- **Never relax the group-shape requirement toward "any run of 13+ digits."**
  Three of the four real corpus merchant TINs are 14 digits and are silent only
  because they print `3-3-3-N` (ADR-0018, ADR-0020).
- **Do not renumber rule IDs**; none are touched here.
- **Two test suites.** `python -m pytest` (offline, Node-free) and Vitest in
  `frontend/`. `npm test` does **not** type-check — run `npm run typecheck` too
  (ADR-0017).
- **`python scripts/verify.py` is what "passing" means** — pytest, ruff,
  typecheck, vitest, build.
- Lint is `python -m ruff check .`; bare `ruff` is not on PATH.
- Piped pytest output can lose its final summary line in this environment. Use
  `--junitxml` and read counts from the XML.
- **Volatile numbers (test counts, SHAs, line numbers) never go in code comments
  or ADR bodies** (ADR-0019). They belong in the design doc and the handoff pair.
- **Stage only the files your task names.** `var/` is gitignored and holds real
  receipt images — never stage anything under it.
- Every new test must be **proven to fail** with its fix reverted. For a test
  that asserts the *absence* of breakage, revert each guarantee separately
  (review standard 3), using the exact mutations given in Task 2.

## File Structure

| File | Responsibility in this change |
|---|---|
| `src/receipts/persist/repository.py` | `_PAN_RE`: five new alternatives, `{1,2}` separator. Its `#:` comment block: three falsified passages rewritten. |
| `tests/test_repository.py` | New behavioural tests (groupings, doubled separator, two-instance), two new structural tests, the ADR-0018 worked example pin, the residual pin, and the doubled-separator TIN case. |
| `frontend/src/review/ReceiptForm.tsx` | Header comment only: "the two shapes" becomes seven, and the measured `PATCH` table gains rows. No behaviour change. |
| `docs/adr/0007-pan-redaction-and-money-integrity.md` | Its existing dated-correction section gains the "a hash" qualification. |

No new files. No new dependencies.

---

### Task 1: The detector, its behavioural tests, and the prose it falsifies

**Files:**
- Modify: `src/receipts/persist/repository.py` — the `#:` comment block ending at
  line 181 and `_PAN_RE` at lines 182–193
- Test: `tests/test_repository.py` — append to the PAN battery, which begins
  around line 1030

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_PAN_RE` with eight alternatives. Task 2's structural tests import
  it (`from receipts.persist.repository import _PAN_RE`) — it is a module-level
  `re.Pattern[str]` and that import already exists in the test module's
  neighbourhood. Task 3 depends on the runtime behaviour only.

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/persist/repository.py` lines 100–225. You need the whole `#:`
comment block above `_PAN_RE`, the pattern itself, and `_mask_pan`. Confirm for
yourself that `_PAN_MIN_DIGITS = 13` and `_PAN_MAX_DIGITS = 19` are defined near
line 82, and that `_mask_pan` returns `match.group(0)` unchanged when the digit
count is outside that range.

Then read `docs/adr/0018-pan-masking-policy.md` and
`docs/adr/0020-pan-grouping-coverage.md` in full. ADR-0020 is the decision you
are implementing.

- [ ] **Step 2: Write the failing test for the five groupings**

Append to `tests/test_repository.py`. The module already defines `_SEPARATORS`
(line 1035), `_SEPARATOR_IDS` (1036) and `_masked` (1050) — reuse them, do not
redefine them.

```python
#: Groupings a card is printed or written in that are NOT 4-4-4-N or 4-6-5.
#: Each stored a whole card number in the clear until ADR-0020. The shapes are
#: real products -- Diners Club prints 4-6-4, Maestro and legacy Visa print
#: 4-4-5 -- and the 5- and 6-lead forms are what a hand-filled slip produces,
#: which is what this corpus is.
_NON_CANONICAL_GROUPINGS = [
    ("3055", "930902", "5904"),
    ("6759", "4111", "00005"),
    ("41111", "1111", "1111", "2345"),
    ("411111", "1111", "1111", "2345"),
    ("4111", "11111", "1111", "2345"),
]
_NON_CANONICAL_IDS = ["diners-4-6-4", "maestro-4-4-5", "5-4-4-4", "6-4-4-4", "4-5-4-4"]


@pytest.mark.parametrize("separator", _SEPARATORS, ids=_SEPARATOR_IDS)
@pytest.mark.parametrize("groups", _NON_CANONICAL_GROUPINGS, ids=_NON_CANONICAL_IDS)
def test_redact_pan_masks_a_card_grouped_outside_the_two_canonical_shapes(
    groups: tuple[str, ...], separator: str
) -> None:
    """A card grouped outside 4-4-4-N and 4-6-5 used to be stored WHOLE.

    Not a partial mask and not a near miss: the pattern matched no part of the
    run, so ``_mask_pan`` was never called and ``save_extraction`` copied the
    card number into the column verbatim -- the same invariant violation as
    leak (a). Measured before the fix: ``redact_pan('41111 1111 1111 2345')``
    returned its input unchanged.
    """
    printed = separator.join(groups)
    expected = _masked("".join(groups))

    assert redact_pan(f"CARD {printed} OK") == f"CARD {expected} OK"
```

- [ ] **Step 3: Run it and confirm it fails**

```
python -m pytest tests/test_repository.py -k "grouped_outside_the_two_canonical" -q
```

Expected: **30 failures** (5 groupings × 6 separators), each an `AssertionError`
showing the input returned unchanged where a masked value was expected. If any
case passes before you change the pattern, stop and report — that means the
shape was already covered and this plan's premise is wrong for it.

- [ ] **Step 4: Write the failing test for the doubled separator**

```python
@pytest.mark.parametrize(
    "printed",
    [
        "4111  1111  1111  1111",
        "4111--1111--1111--1111",
        "4111..1111..1111..1111",
        "3782  822463  10005",
        "3055  930902  5904",
        "4111 1111  1111 1111",
    ],
    ids=["double-space", "double-hyphen", "double-dot", "amex", "diners", "mixed-width"],
)
def test_redact_pan_masks_a_card_whose_groups_are_separated_by_two_characters(
    printed: str,
) -> None:
    """One separator character was the whole class, so a second space stored the
    card whole.

    ``[ .\\-_/,]`` matches exactly one character, so every separated
    alternative failed on ``'4111  1111  1111  1111'`` -- the likeliest
    spelling in a hand-written corpus, and this corpus is hand-filled. The
    class is capped at two rather than left open: ``+`` additionally fires on
    amount columns aligned with three or more spaces (ADR-0020).
    """
    expected = _masked("".join(ch for ch in printed if ch.isdigit()))

    assert redact_pan(f"CARD {printed} OK") == f"CARD {expected} OK"
```

- [ ] **Step 5: Run it and confirm it fails**

```
python -m pytest tests/test_repository.py -k "separated_by_two_characters" -q
```

Expected: **6 failures**, each returning the input unchanged.

- [ ] **Step 6: Write the failing two-instance test**

This is review standard 9. A scanner's failure mode lives at the boundary
*between* two hits, and a single-instance battery cannot see it. That blind spot
let a full second PAN through a green suite twice in this project.

```python
@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        (
            "3055 930902 5904 and 3056 930902 5905",
            "**********5904 and **********5905",
        ),
        (
            "41111 1111 1111 2345 / 51111 1111 1111 6789",
            "*************2345 / *************6789",
        ),
        (
            "4111 1111 1111 1111 then 3055 930902 5904",
            "************1111 then **********5904",
        ),
        (
            "3055 930902 5904 then 4111 1111 1111 1111",
            "**********5904 then ************1111",
        ),
        (
            "6759 4111 00005 6760 4111 00006",
            "*********0005 *********0006",
        ),
        (
            "4111  1111  1111  1111  5555  5555  5555  4444",
            "************1111  ************4444",
        ),
    ],
    ids=["two-diners", "two-5-lead", "canonical-then-diners",
         "diners-then-canonical", "two-maestro", "two-double-space"],
)
def test_redact_pan_masks_both_cards_when_a_new_grouping_appears_twice(
    printed: str, expected: str
) -> None:
    """Two instances of what the guard guards, inside one input.

    The alternatives added for ADR-0020 are fixed shapes precisely so they
    cannot tile across the gap between two adjacent card numbers. A
    generalised alternative was measured doing exactly that: on two Amex
    numbers it matched a 4-6-5-4 span of nineteen digits -- inside the accepted
    range, so ``_mask_pan`` accepted it -- and because ``re.sub`` never rescans
    inside a match it has already made, eleven digits of the second card
    survived in the clear. Coverage and cross-boundary risk move together, so
    any shape added here is re-checked against this test (ADR-0020).
    """
    assert redact_pan(printed) == expected
```

- [ ] **Step 7: Run it and confirm it fails**

```
python -m pytest tests/test_repository.py -k "both_cards_when_a_new_grouping" -q
```

Expected: **6 failures**. Note which cases fail and how: `two-double-space` will
show both cards unchanged, and `canonical-then-diners` will show the first card
masked and the Diners card whole. That asymmetry is the defect.

- [ ] **Step 8: Change the pattern**

Replace lines 182–193 of `src/receipts/persist/repository.py`. The separator
class is repeated inline rather than factored into a constant, matching the
existing style of this module — the pattern is `re.VERBOSE` and reads as a
table.

```python
_PAN_RE = re.compile(
    r"""
    (?<!\d)(?<!\d\.)                                     # not mid-number, not a decimal fraction
    (?:
        \d{4}(?:[ .\-_/,]{1,2}\d{4}){2}[ .\-_/,]{1,2}\d{1,7}   # 4-4-4-N  13-19  Visa, Mastercard
      | \d{4}[ .\-_/,]{1,2}\d{6}[ .\-_/,]{1,2}\d{5}            # 4-6-5    15     Amex
      | \d{4}[ .\-_/,]{1,2}\d{6}[ .\-_/,]{1,2}\d{4}            # 4-6-4    14     Diners Club
      | \d{4}[ .\-_/,]{1,2}\d{4}[ .\-_/,]{1,2}\d{5}            # 4-4-5    13     Maestro, legacy Visa
      | \d{5}(?:[ .\-_/,]{1,2}\d{4}){3}                        # 5-4-4-4  17
      | \d{6}(?:[ .\-_/,]{1,2}\d{4}){3}                        # 6-4-4-4  18
      | \d{4}[ .\-_/,]{1,2}\d{5}(?:[ .\-_/,]{1,2}\d{4}){2}     # 4-5-4-4  17
      | \d{13,19}(?!\.\d)                                      # unseparated, and not an integer part
    )
    (?!\d)
    """,
    re.VERBOSE,
)
```

Do not touch `_mask_pan`, `_redact_number`, `redact_pan`, `_last4`,
`_coerce_money`, `_bounded_optional_text`, `_plan_change`, `save_extraction` or
anything in `review/`.

- [ ] **Step 9: Run all three new tests plus the whole committed battery**

```
python -m pytest tests/test_repository.py -k "pan or redact" -q
```

Expected: all green. The committed battery is 110 tests before your additions;
your three tests add 42 cases (30 + 6 + 6). If any pre-existing test fails, the
pattern is wrong — do not adjust the pre-existing test, fix the pattern.
`test_redact_pan_leaves_a_run_of_more_than_four_groups_partly_masked` in
particular must stay green **untouched**: leak (b) is accepted by user ruling and
its four pinned cases were measured to be unchanged by this fix.

- [ ] **Step 10: Rewrite the three falsified passages in the `#:` comment**

The comment block above `_PAN_RE` makes three claims your change makes false.
This project treats a knowingly-false comment as its own defect class.

**10a.** The passage that currently reads:

```
#: the leading match -- when the remainder itself happens to be shaped as a
#: recognised 4-4-4-N or 4-6-5 run, it gets its own separate match instead
```

Change `4-4-4-N or 4-6-5` to name the seven separated shapes, or refer to "any
shape in the alternation below" — do not leave a two-item list.

**10b.** The passage that currently reads:

```
#: when the remainder is grouped outside those two canonical shapes -- the
#: positional clause above already says nothing outside them matches at all
#: -- that it stays whole, and it can then be an entire, undetected card
#: number: measured, ``redact_pan('4111 1111 1111 1111 41111 1111 1111
#: 2345')`` returns ``'************1111 41111 1111 1111 2345'``, a full
#: 17-digit PAN in 5-4-4-4 grouping, untouched.
```

This worked example is now wrong: `5-4-4-4` is covered. **Re-measure it, do not
edit it by hand.** Run:

```
python -c "import sys; sys.path.insert(0,'src'); from receipts.persist.repository import redact_pan; print(repr(redact_pan('4111 1111 1111 1111 41111 1111 1111 2345')))"
```

Paste the real output into the comment. Then replace the example with one that
is *still* whole after the fix, so the passage keeps demonstrating the residual
rather than a closed gap. Pick a shape from ADR-0020's residual list — `4-4-6`,
`4-5-4`, `5-4-4`, `6-6-4` or `5-5-4-4` — and measure that one the same way.

**10c.** Add a short paragraph recording what ADR-0020 decided: the five shapes,
the `{1,2}` separator cap, that each new alternative has a fixed digit total
inside 13–19 so `_mask_pan`'s length check stays unreachable by construction,
that alternation order is **not** load-bearing because the trailing `(?!\d)`
rejects a truncated match, and that coverage and cross-boundary risk move
together so a new shape requires the two-instance check. Point at
`docs/adr/0020-pan-grouping-coverage.md`.

**Do not put counts, percentages, SHAs or line numbers in the comment** — those
live in the design doc (ADR-0019). "The residual is listed in ADR-0020" is
correct; "76 of 97 shapes" in a comment is a number that will rot.

- [ ] **Step 11: Run the gates**

```
python -m pytest --junitxml=var/junit_task1.xml -q
python -m ruff check .
```

Expected: 0 failures in the XML (`<testsuite ... failures="0" errors="0">`), ruff
clean. The suite was 864 tests before this task.

- [ ] **Step 12: Prove each new test fails with the fix reverted**

Revert only the pattern (keep the tests), re-run the three new test selections,
confirm they fail, then restore the pattern. Record the failure counts in your
report. Do not commit the reverted state.

- [ ] **Step 13: Commit**

```bash
git add src/receipts/persist/repository.py tests/test_repository.py
git commit -m "fix(persist): mask a card grouped outside the two canonical shapes

Diners 4-6-4, Maestro 4-4-5, and the 5-lead, 6-lead and 4-5-4-4 forms matched
neither separated alternative, so the whole card number was stored in the clear
-- the same invariant violation as leak (a), never covered by any battery. A
doubled separator defeated every separated alternative on its own, which is the
likeliest spelling in a hand-filled corpus.

Five fixed-shape alternatives and a {1,2} separator cap. Each new alternative
has a fixed digit total inside 13-19, so _mask_pan's length check stays
unreachable by construction. Two-instance cases are pinned: the shapes are fixed
precisely so they cannot tile across the gap between two adjacent cards, which
is how a measured generalisation leaked a second Amex. ADR-0020."
```

---

### Task 2: The structural guards, the worked-example pin, and the residual pin

**Files:**
- Test: `tests/test_repository.py` — append after Task 1's tests; also edit the
  docstring and parameters of
  `test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints`
  (around line 1375)

**Interfaces:**
- Consumes: `_PAN_RE` from Task 1 — a module-level `re.Pattern[str]` in
  `receipts.persist.repository`.
- Produces: no new callables. Tests only.

- [ ] **Step 1: Add the import and the shape-space helper**

`itertools` and `re` are needed. Check the top of `tests/test_repository.py` for
existing imports and add only what is missing — do not duplicate. `_PAN_RE` is
private, so import it explicitly:

```python
from receipts.persist.repository import _PAN_RE
```

Then add the helper next to the new tests:

```python
#: Every group shape a separated digit run can take, for the two structural
#: guards below: 2 to 5 groups, each 1 to 8 digits. Built once because both
#: guards sweep it.
_ALL_SHAPES = [
    shape
    for count in (2, 3, 4, 5)
    for shape in itertools.product(range(1, 9), repeat=count)
]

#: The single and doubled separators the pattern accepts.
_SWEEP_SEPARATORS = [*_SEPARATORS, "  "]


def _printed(shape: tuple[int, ...], separator: str) -> str:
    """``(4, 6, 4)`` and ``' '`` -> ``'1111 111111 1111'``."""
    return separator.join("1" * width for width in shape)
```

- [ ] **Step 2: Write the TIN structural guard**

```python
def test_pan_re_never_starts_a_match_at_a_three_digit_group() -> None:
    """The corpus-TIN guarantee, pinned across the shape space not the samples.

    Three of the four real merchant ``VAT Reg. TIN`` values on this corpus hold
    **fourteen** digits -- inside the 13-19 window a PAN occupies -- and are
    silent only because they print 3-3-3-N. What actually protects them is an
    asymmetry: every real card grouping opens with a group of at least four
    digits, and every corpus TIN opens with three.

    Pinning the four samples would survive a widening that happened to miss
    those four. This pins the property instead: no alternative may begin a
    match at a three-digit group, whatever follows it. ``match`` rather than
    ``search`` because a canonical card embedded later in a longer run is a
    legitimate hit -- what must never happen is a match *starting* at the
    3-digit group.
    """
    for shape in _ALL_SHAPES:
        if shape[0] != 3:
            continue
        for separator in _SWEEP_SEPARATORS:
            text = _printed(shape, separator)
            assert _PAN_RE.match(text) is None, (shape, separator, text)
```

- [ ] **Step 3: Write the digit-range structural guard**

```python
def test_every_pan_re_match_holds_between_thirteen_and_nineteen_digits() -> None:
    """``_mask_pan``'s length check stays unreachable from ``_PAN_RE``.

    ``_mask_pan`` returns its match unchanged when the digit count falls outside
    13-19, and ``re.sub`` never rescans inside a match it has already made -- so
    a match that is rejected for length is a span nothing will look at again.
    Every alternative is bounded so that cannot happen: 4-4-4-N spans 13 to 19,
    Amex 4-6-5 is fixed at 15, and the five shapes ADR-0020 added are fixed at
    14, 13, 17, 18 and 17. The unseparated form is ``\\d{13,19}`` outright.

    That arithmetic is a claim about the pattern, so it is checked against the
    pattern rather than restated. ADR-0018 keeps the guard anyway, as defence in
    depth for whatever alternative is added next -- this test is what tells the
    person adding it that they have made the guard reachable.
    """
    for shape in _ALL_SHAPES:
        for separator in _SWEEP_SEPARATORS:
            text = _printed(shape, separator)
            for match in _PAN_RE.finditer(text):
                digits = re.sub(r"\D", "", match.group(0))
                assert _PAN_MIN_DIGITS <= len(digits) <= _PAN_MAX_DIGITS, (
                    shape,
                    separator,
                    match.group(0),
                    len(digits),
                )
```

Import `_PAN_MIN_DIGITS` and `_PAN_MAX_DIGITS` alongside `_PAN_RE` rather than
writing `13` and `19` — the constants exist near line 82 of `repository.py` and
reading them is what keeps the test and the function from drifting.

- [ ] **Step 4: Run both structural guards and confirm they pass**

```
python -m pytest tests/test_repository.py -k "never_starts_a_match or holds_between_thirteen" -q
```

Expected: 2 passed. The range guard sweeps 262,080 `finditer` calls and takes
about 1 second; the TIN guard sweeps 32,760 and takes well under a tenth of
that. If either is slower than a few seconds, you have changed the sweep — check
`range(1, 9)`.

- [ ] **Step 5: Prove the TIN guard discriminates — mutation A only**

These two tests assert the *absence* of breakage, so a single RED run cannot
prove them (review standard 3). Revert each guarantee separately, and change
exactly one thing per mutation (review standard 4).

Temporarily add **one** alternative to `_PAN_RE`, as the *first* branch:

```
        \d{3}(?:[ .\-_/,]{1,2}\d{3}){2}[ .\-_/,]{1,2}\d{5}
```

That is `3-3-3-5` — fourteen digits, so it is *inside* the accepted range and
therefore isolates the TIN guard from the range guard.

```
python -m pytest tests/test_repository.py -k "never_starts_a_match or holds_between_thirteen or merchant_tax_ids" -q
```

Expected: `never_starts_a_match` **FAILS**, `holds_between_thirteen` **PASSES**,
and `merchant_tax_ids` **FAILS**. Confirm the TIN test's failure shows a real
corpus TIN being masked — measured, `'221 193 789 09013'` becomes
`'**********9013'`. Then remove the mutation.

- [ ] **Step 6: Prove the range guard discriminates — mutation B only**

Temporarily replace the whole separated half of the alternation with the
generalised form ADR-0020 refused:

```
        \d{4,6}(?:[ .\-_/,]{1,2}\d{4,7}){1,2}[ .\-_/,]{1,2}\d{1,7}
```

```
python -m pytest tests/test_repository.py -k "never_starts_a_match or holds_between_thirteen" -q
```

Expected: `holds_between_thirteen` **FAILS**, `never_starts_a_match` **PASSES** —
the mutation isolates the range guard. Then remove the mutation and confirm both
pass again.

- [ ] **Step 7: Extend the TIN test with the doubled-separator spelling**

Edit `test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints`.
Its docstring currently says the TINs are silent "only because ``_PAN_RE``
requires 4-4-4-N or 4-6-5 grouping" — now false, seven separated shapes exist.
Rewrite that sentence to name the real reason: the leading group must be at
least four digits, and every corpus TIN leads with three. Point at the
structural guard by name.

Add the doubled spelling to the assertions, since the separator class now
accepts two characters:

```python
    assert redact_pan(tax_id) == tax_id
    assert redact_pan(f"VAT Reg. TIN {tax_id}") == f"VAT Reg. TIN {tax_id}"
    # The separator class accepts two characters as of ADR-0020, so the doubled
    # spelling of a TIN is a new way for this false positive to appear.
    doubled = tax_id.replace(" ", "  ").replace("-", "--")
    assert redact_pan(doubled) == doubled
```

- [ ] **Step 8: Pin ADR-0018's worked example**

This is ledger follow-up 5. The existing leak-(b) tests use uniform digits, so
they cannot distinguish "the matched region's last four" from "the card's true
last four" — the worked example could be falsified without failing anything.

```python
def test_redact_pan_leaves_mid_card_digits_where_the_last_four_belong() -> None:
    """ADR-0018's worked example, pinned.

    When leak (b)'s run is a single 19-digit card, the four digits standing in
    the last-four position are digits 13-16 of the run, not the card's own tail:
    the visible ``2345`` here is not ``5678``. The leak-(b) cases already pinned
    use uniform digits and cannot tell those two readings apart, so this is the
    one case that binds the ADR's prose to behaviour.
    """
    assert redact_pan("4111 1111 1111 2345 678") == "************2345 678"
```

- [ ] **Step 9: Pin the residual**

```python
@pytest.mark.parametrize(
    "printed",
    [
        "4111 1111 111111",
        "4111 11111 1111",
        "41111 1111 1111",
        "411111 111111 1111",
        "41111 11111 1111 1111",
    ],
    ids=["4-4-6", "4-5-4", "5-4-4", "6-6-4", "5-5-4-4"],
)
def test_redact_pan_still_stores_some_groupings_whole(printed: str) -> None:
    """The residual ADR-0020 accepted, pinned so it is a decision not an oversight.

    ADR-0020 added five shapes; it did not close the class. These groupings are
    still stored entirely in the clear. They are not fixed here because the two
    measured routes to covering them cost more than they buy: a generalised
    alternative leaks a full second card when two are adjacent, and a
    candidate-then-validate scan loop was priced at O(n^2). If a later change
    closes one of these, this test fails -- which is the point. Update it and
    ADR-0020 together.
    """
    assert redact_pan(f"CARD {printed} OK") == f"CARD {printed} OK"
```

- [ ] **Step 10: Run the whole battery and the gates**

```
python -m pytest tests/test_repository.py -k "pan or redact" -q
python -m pytest --junitxml=var/junit_task2.xml -q
python -m ruff check .
```

Expected: all green, 0 failures and 0 errors in the XML, ruff clean.

- [ ] **Step 11: Commit**

```bash
git add tests/test_repository.py
git commit -m "test(persist): pin the PAN detector's TIN and digit-range properties

Two structural guards over the group-shape space rather than over samples: no
alternative may begin a match at a three-digit group, which is what actually
keeps the fourteen-digit corpus TINs silent, and every match holds 13-19 digits,
which is what keeps _mask_pan's length check unreachable. Each was proven to
discriminate with a single-variable mutation -- a 3-3-3-5 alternative trips the
first and not the second, the refused generalisation trips the second and not
the first.

Also pins ADR-0018's worked example, whose visible four digits are mid-card and
which no uniform-digit case can distinguish; the residual ADR-0020 accepted, so
it reads as a decision; and the doubled-separator spelling of a corpus TIN."
```

---

### Task 3: The frontend claim, re-measured through the real `PATCH` route

**Files:**
- Modify: `frontend/src/review/ReceiptForm.tsx` — the header comment only,
  roughly lines 30–82. **No code, no JSX, no behaviour.**

**Interfaces:**
- Consumes: the runtime behaviour of `redact_pan` from Task 1.
- Produces: nothing. Documentation only.

- [ ] **Step 1: Read the header comment in full**

Read `frontend/src/review/ReceiptForm.tsx` lines 1–90. Two things matter:

1. It says redaction does not fully mask one spelling, and names "the two shapes
   this masks (4-4-4-N, 4-6-5)". Seven separated shapes now exist.
2. It carries a table of `sent -> read` pairs and states they were measured
   through the real `PATCH` route on `receipt.date_raw`, one fresh receipt per
   row, read back with `GET /receipts/{id}`. Its own text warns that this claim
   has been wrong twice, both times by generalising past what was measured.

- [ ] **Step 2: Measure the new spellings through the real route**

**Do not copy values from the design doc or from a `redact_pan` call.** The
table's whole value is that it was measured end to end. Write a throwaway script
under `var/` (gitignored) that builds a `TestClient` exactly the way
`tests/test_api_write.py` does — read its `app`, `session_factory`, `storage`,
`settings` and `submitted` fixtures around lines 55–130 and reuse that shape —
then for each spelling below: create a receipt, `PATCH`
`receipt.date_raw` with the spelling, and `GET /receipts/{id}` to read back what
was stored.

```
4111  1111  1111  1111
3055 930902 5904
6759 4111 00005
41111 1111 1111 2345
411111 1111 1111 2345
4111 11111 1111 2345
```

Also re-measure two rows already in the table — `4111 1111 1111 1111` and
`3782 822463 10005` — to confirm the harness agrees with the committed values.
If it does not, stop and report: either the harness is wrong or something
regressed, and guessing which would put a false table back in the file.

- [ ] **Step 3: Update the comment**

Add the measured rows to the table in the file's existing format, aligned with
the existing rows. Fix the "two shapes" sentence to say what is now true: the
remainder of a more-than-four-group run stays whole when it is grouped outside
**any** shape in the alternation, and ADR-0020 lists which those are. Keep the
"what is masked is exactly the table below, and nothing is generalised from it"
discipline — that sentence is why this file has been right since the last time
it was wrong.

Add ADR-0020 to whatever ADR references the comment already carries.

- [ ] **Step 4: Delete the throwaway script**

```bash
Remove-Item var/<your-script>.py
```

- [ ] **Step 5: Run the frontend gates**

```
cd frontend
npm run typecheck
npm test
```

Expected: typecheck clean, 170 Vitest tests passing. A comment-only change must
not move either. `npm test` does **not** type-check, which is why both run.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/review/ReceiptForm.tsx
git commit -m "docs(frontend): re-measure ReceiptForm's redaction table for ADR-0020

The comment named 'the two shapes this masks (4-4-4-N, 4-6-5)'; there are now
seven separated shapes. The table is the file's binding claim and states it was
measured through the real PATCH route, so the new rows were measured that way
too, not copied from a probe -- the two previous versions of this claim were
both wrong by generalising past what had been measured."
```

---

### Task 4: ADR-0007's unqualified "a hash"

**Files:**
- Modify: `docs/adr/0007-pan-redaction-and-money-integrity.md` — the
  `## Consequences` section and the existing `## Correction (2026-07-31)`
  section

**Interfaces:** none. Documentation only.

- [ ] **Step 1: Read the ADR and confirm the defect**

Read `docs/adr/0007-pan-redaction-and-money-integrity.md` in full. Its
`## Correction (2026-07-31)` section already explains that "never fires on a
hash" is not an enforceable property — roughly 1 in 200 random 16-character hex
hashes mask, so **no** hash may be routed through `redact_pan`. But the
`## Consequences` section below it still reads:

```
- **The silent-case tests are as important as the firing ones.** A redaction rule
  that fires on money, a hash, a 4-digit last4, a date, or `555-1234` is worse
  than no rule.
```

A reader who jumps to Consequences takes "a hash" at face value. This is ledger
follow-up 6.

- [ ] **Step 2: Verify the claim before writing about it**

Review standard 6: a claim about what your own artefacts say is itself a claim
requiring a command.

```
python -c "import sys; sys.path.insert(0,'src'); from receipts.persist.repository import redact_pan; [print(repr(h), '->', repr(redact_pan(h))) for h in ('0123456789abcdef','1234567890123abc','a123456789012345','0000000000000000')]"
```

- [ ] **Step 3: Add the qualification**

ADRs are immutable once Accepted and corrections are dated appendices, so do
**not** rewrite the Consequences bullet's history. Append a dated line to the
existing `## Correction (2026-07-31)` section naming the Consequences bullet
explicitly, and add a short parenthetical pointer in the bullet itself — enough
that a reader landing there is sent to the correction, without editing away what
the ADR originally claimed. Reference ADR-0018 for the measured rate and
ADR-0020 for the current detector shape.

- [ ] **Step 4: Check nothing else repeats the unqualified claim**

Review standard 6 again — grep, do not recall:

```
python -m pytest tests/test_repository.py -k "silent_on_money_hashes_and_last4" -q
```

Expected: pass, untouched. That test's own hash cases are short digit runs, which
is why it passes and always did; leave it alone.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0007-pan-redaction-and-money-integrity.md
git commit -m "docs(adr): qualify ADR-0007's unqualified 'a hash' in Consequences

The 2026-07-31 correction already records that masking a hash is not something
this function can be asked to avoid -- roughly 1 in 200 random 16-character hex
values mask -- but the Consequences bullet below it still lists 'a hash'
alongside money and card_last4 without qualification, so a reader who jumps
straight there misses it. Dated appendix, per ADR immutability."
```

---

## Verification, after all four tasks

- [ ] `python scripts/verify.py` — all five gates PASS (pytest, ruff, typecheck,
      vitest, build). This is what "passing" means (ADR-0017).
- [ ] `python -m pytest --junitxml=var/junit_final.xml -q` and read the counts
      from the XML, not from stdout — the summary line can be lost here.
- [ ] `git status` clean, and `git log --stat` over the branch shows **no** file
      under `var/`, `eval/golden/images/` or `.github/` was ever staged.
- [ ] The six defect cases from the design doc's §1 table all mask, run from
      **outside** the repository — a green suite is not evidence that installed
      software works.

## Self-review notes

Spec coverage checked section by section: §2 pattern → Task 1 Step 8; §2.2
separator cap → Task 1 Steps 4–5 and its docstring; §2.3 order not load-bearing →
Task 1 Step 10c; §4.2 TIN property → Task 2 Steps 2 and 5; §4.3 digit range →
Task 2 Steps 3 and 6; §4.4 two-instance → Task 1 Step 6; §5 residual → Task 2
Step 9; §6 tests 1–8 → Task 1 Steps 2/4/6 and Task 2 Steps 2/3/7/8/9; §7 prose
a/b → Task 1 Step 10, §7 c → Task 3, §7 d → Task 4; §8 ADR-0020 already
committed.

Design §6 lists eight tests and all eight have a step. The two structural ones
carry the separate-revert requirement of review standard 3, with a
single-variable mutation each per review standard 4, and both mutations were
verified to discriminate before this plan was written.
