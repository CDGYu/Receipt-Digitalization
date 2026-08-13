# Dangling Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair nine citations that name commits no ref can reach, and enforce
one bounded property so the class cannot silently reopen.

**Architecture:** A single pytest module walks every tracked text file, extracts
each backticked seven-character hex token, and asserts it resolves to a commit
**reachable from a ref** — not merely present in the object store. Two subprocess
calls do the whole job. Three separate guarantees live in the module: the
property itself, a shallow-clone refusal, and a pin on git's abbreviation width.

**Tech Stack:** Python 3.11+, pytest, `git` on `PATH`, GitHub Actions.

**Design:** `docs/superpowers/specs/2026-08-13-dangling-citations-design.md` —
read §2 (the measurements), §4 (why reachability and why seven characters) and
§6 (what gets repaired) before starting.

---

## Global Constraints

- **Never write a dead commit's abbreviation in single backticks.** A backticked
  seven-hex token is what the guard reads as a citation. In this plan and in
  everything it produces, name an unreachable commit **bare** (5a7fc58) or by
  full oid. `git grep -n "5a7fc58"` with the token in double quotes is safe. The
  only safe backticked example is a commit that really resolves.
- **`ruff` selects `E,F,I,B,UP`, line length 100.** `I001` (import order) is on
  and has failed this repo's gates before, on a function-local import. Keep all
  imports at module top, correctly ordered.
- **`pyproject.toml` sets `addopts = "-q"`.** So `python -m pytest -q` is `-qq`
  and prints no pass count. Use bare `python -m pytest`.
- **`python scripts/verify.py` exceeds a two-minute tool timeout — background
  it, and do not edit any file while it runs.** A backgrounded run during an
  edit once reported a phantom `FAIL build`.
- **Stage by explicit path. Never `git add -A`.** Verify with
  `git diff --cached --stat` before committing.
- **The working tree is mixed CRLF/LF.** Read bytes before anchoring on them;
  use the Read/Write/Edit tools rather than PowerShell `Get-Content` for
  anything non-ASCII, which is nearly every file here.
- **Stage a new file BEFORE you verify it, not after.** The guard's scan set is
  `git ls-files`, which lists tracked **and staged** files but not untracked
  ones. A brand-new document therefore passes the guard while untracked and
  fails on the *next* task's run, after it has been committed. Measured
  2026-08-13, and it is why every task below stages first and runs the guard
  second. This bit the prototype of this very test.
- **Report, don't work around.** Every plan defect across the last eleven
  milestones was the controller's. If a claim below does not match the real
  file, that is a plan defect and I want it reported, not patched around.

---

## File Structure

| file | responsibility |
|---|---|
| `tests/test_sha_citations.py` | **new.** The property and its three guarantees. Follows `tests/test_no_float_in_money_path.py` and `tests/test_import_isolation.py`, the two existing tree-wide guards. |
| `docs/adr/0041-the-review-outcome-takes-focus.md` | one citation remapped |
| `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` | four citations remapped |
| `docs/superpowers/plans/2026-08-12-review-outcome-focus.md` | four citations remapped, plus a defect-log entry recording it |
| `.github/workflows/ci.yml` | `fetch-depth: 0` on both checkout steps |
| `docs/adr/0042-a-cited-commit-must-stay-reachable.md` | **new.** The decision. |
| `docs/adr/0032-a-document-cannot-certify-itself.md` | dated correction to decision 3 |
| `docs/adr/README.md` | one index row |
| `docs/MEMORY.md` + `docs/NEXT_SESSION_PROMPT.md` | the pair — **Task 4, alone** |

---

## The two remappings, verified

Both replacements were confirmed by comparing **patches, not subjects**:

```
diff <(git show 5a7fc58 --format=) <(git show 99f0207 --format=)   # empty
diff <(git show d2fffc0 --format=) <(git show e0481f4 --format=)   # empty
```

| dead (bare, deliberately) | live | subject |
|---|---|---|
| 5a7fc58 | `99f0207` | `fix: the review outcome takes focus, so a 403 is not invisible` |
| d2fffc0 | `e0481f4` | `docs: design for the review outcome taking focus (I5)` |

**Both dead commits are unreachable but not yet pruned**, so `git show` on them
still works today. Do not rely on that lasting.

---

### Task 1: The guard, and the nine repairs that make it pass

**Files:**
- Create: `tests/test_sha_citations.py`
- Modify: `docs/adr/0041-the-review-outcome-takes-focus.md`
- Modify: `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`
- Modify: `docs/superpowers/plans/2026-08-12-review-outcome-focus.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/test_sha_citations.py` with three test functions —
  `test_the_repository_history_is_not_shallow()`,
  `test_git_still_abbreviates_to_seven_characters()`, and
  `test_every_cited_commit_is_reachable_from_a_ref()`. Task 2 cites the first by
  name in a CI comment; Task 3's ADR cites all three.

**Why the test and the repair are one task:** the repair is the minimal change
that makes the test pass, so splitting them would leave a committed red suite.
The RED proof is not synthetic — the tree holds nine genuinely broken citations
right now.

- [ ] **Step 1: Write the guard**

Create `tests/test_sha_citations.py` with exactly this content. It was executed
against this tree before this plan was written; the docstring's numbers are
measured, not estimated.

```python
"""Global-constraint guard: a commit this repository cites must stay reachable.

Documents here anchor their measurements to a commit -- *"derived at ``e698aca``"*,
*"probed at ``e698aca``, not recalled"*. That example names a real, reachable
commit deliberately: the rule below means a docstring cannot show the citation
form without instantiating it, so the only safe illustration is one that
resolves. ADR-0032 decision 3 called that kind of
anchor "true forever". It is not. On 2026-08-12 a branch was replayed onto
``main`` rather than merged, and nine citations in three tracked files were left
naming commits that no ref can reach. The claims stayed true; they stopped being
checkable, and after ``git gc`` the tokens name nothing at all. ADR-0042 is the
decision this guard enforces.

Why reachability and not existence
----------------------------------
``git cat-file -e`` succeeds on an orphaned commit until it is pruned, so an
existence check would have been green through the entire defect and would first
go red on whatever day somebody ran ``git gc``. The property is reachability.

Why any ref and not ``main``
----------------------------
An ADR records the tree it was derived from and is committed *before* the merge,
so it legitimately cites a commit that is on the branch and not yet on ``main``.
CI fires on every push (ADR-0037), so a ``main``-anchored rule would fail every
branch that documents its own work. Reachable-from-any-ref passes there and
still catches a replay, which orphans commits from *every* ref.

Why exactly seven hex characters
--------------------------------
Measured over the tracked tree at ``e698aca``: all 112 genuine commit citations
are exactly seven characters, and all six backticked hex tokens that are *not*
commits are 8, 10, 12 or 20 -- PAN digit-strings, a date, an Alembic revision id.
So the rule needs no exclusion list, which is what makes it a property rather
than an enumerated defence (review standard 19). Its one silent-drift path --
``core.abbrev`` is auto and git widens it as the object count grows -- is pinned
by ``test_git_still_abbreviates_to_seven_characters``.

A consequence worth knowing before editing any document about a dead commit: the
seven-character backticked form IS the citation, so a document discussing an
unreachable commit must name it bare or at full oid length. A sentence cannot
show an example of the form without instantiating it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A citation as this repository writes one: a backticked seven-character hex
#: token. Anchored deliberately at seven -- see the module docstring.
_SHA_PATTERN = re.compile(r"`([0-9a-f]{7})`")

#: Binary and generated files carry hex that is not a citation.
_SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".woff", ".woff2", ".lock",
)


def _git(*args: str) -> str:
    """Run git at the repository root and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return result.stdout


def _tracked_text_files() -> list[Path]:
    return [
        REPO_ROOT / line
        for line in _git("ls-files").splitlines()
        if line and not line.lower().endswith(_SKIP_SUFFIXES)
    ]


def _citations() -> dict[str, list[str]]:
    """Map each cited seven-hex token to the ``path:line`` places citing it."""
    found: dict[str, list[str]] = {}
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(body.splitlines(), 1):
            for token in _SHA_PATTERN.findall(line):
                found.setdefault(token, []).append(f"{rel}:{lineno}")
    return found


def _resolve(tokens: list[str]) -> dict[str, str]:
    """Resolve abbreviations to full oids in one git call.

    Returns ``{token: oid}`` for tokens that name a commit, and ``{token: ""}``
    for anything git reports as ``missing`` or ``ambiguous``.
    """
    if not tokens:
        return {}
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=str(REPO_ROOT),
        input="\n".join(tokens) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    lines = proc.stdout.splitlines()
    if len(lines) != len(tokens):
        raise AssertionError(
            f"git cat-file answered {len(lines)} line(s) for {len(tokens)} token(s); "
            "the batch-check contract changed and this helper cannot pair them up"
        )
    resolved: dict[str, str] = {}
    for token, line in zip(tokens, lines, strict=True):
        parts = line.split()
        resolved[token] = parts[0] if len(parts) == 2 and parts[1] == "commit" else ""
    return resolved


def test_the_repository_history_is_not_shallow() -> None:
    """A shallow clone cannot answer this file's question, so it must not pass.

    ``actions/checkout`` defaults to ``fetch-depth: 1``. Under that, every cited
    commit resolves as missing and this module would either fail for the wrong
    reason or -- worse -- be made to skip, which reads as coverage it does not
    have. It fails loudly and names the fix instead.
    """
    shallow = _git("rev-parse", "--is-shallow-repository").strip()
    assert shallow == "false", (
        "the repository history is shallow, so cited commits cannot be resolved. "
        "Set `fetch-depth: 0` on the checkout step; see ADR-0042."
    )


def test_git_still_abbreviates_to_seven_characters() -> None:
    """Pin the assumption the citation pattern rests on.

    ``core.abbrev`` is unset, so git chooses a width from the object count and
    widens it as the repository grows. On the day it reaches eight, new
    citations stop matching ``_SHA_PATTERN`` and this guard silently checks
    less. This makes that day loud.
    """
    short = _git("rev-parse", "--short", "HEAD").strip()
    assert len(short) == 7, (
        f"git now abbreviates to {len(short)} characters ({short!r}), so the "
        "seven-character citation pattern no longer matches newly written "
        "citations. Widen the pattern and re-derive the false-positive "
        "measurement in this module's docstring."
    )


def test_every_cited_commit_is_reachable_from_a_ref() -> None:
    """The property: a cited commit is reachable, not merely present.

    An unreachable commit is one ``git gc`` away from naming nothing, and a
    reader cannot check the claim built on it today.
    """
    citations = _citations()
    if not citations:
        pytest.fail(
            "no citations found at all, which means the pattern stopped "
            "matching rather than that the tree is clean"
        )

    reachable = set(_git("rev-list", "--all").split())
    resolved = _resolve(sorted(citations))

    broken: list[str] = []
    for token in sorted(citations):
        oid = resolved[token]
        if not oid:
            reason = "does not name a commit"
        elif oid not in reachable:
            reason = f"names {oid[:12]}, which no ref can reach"
        else:
            continue
        broken.append(
            f"  `{token}` {reason}\n"
            + "".join(f"      {place}\n" for place in citations[token])
        )

    assert not broken, (
        f"{len(broken)} cited commit(s) cannot be reached from any ref:\n"
        + "".join(broken)
        + "\nA replay, rebase, amend or force-push severs a citation without "
        "touching the citing document. Remap each to the live commit (compare "
        "patches, not subjects) or remove the anchor. See ADR-0042."
    )
```

- [ ] **Step 2: Run it and confirm it fails for the right reason (RED, guarantee 1)**

Run: `python -m pytest tests/test_sha_citations.py`

Expected: **1 failed, 2 passed.**
`test_every_cited_commit_is_reachable_from_a_ref` fails naming **two tokens**
and **nine places** — one in `docs/adr/0041-…`, four in the browser-pass spec,
four in the review-outcome-focus plan.

**Read the failure list before continuing.** If it names a different number of
places, the tree moved after this plan was written; report it rather than
adjusting the plan. If it fails on an `activeElement`-style unrelated error, or
errors instead of failing, stop and report.

- [ ] **Step 3: Prove guarantee 2 red — the shallow refusal**

```bash
REPO="$(git rev-parse --show-toplevel)"
cd "$(mktemp -d)"
git clone --depth 1 "file:///$REPO" shallow
cd shallow && git rev-parse --is-shallow-repository && git rev-list --all | wc -l
```

Expected: `true`, then `1`.

**The `file://` prefix is required, with three slashes.** `git clone --depth 1
<plain path>` silently ignores `--depth` and hardlinks the full history,
producing a non-shallow clone that proves nothing. Verified 2026-08-13 on this
machine, where `git rev-parse --show-toplevel` yields `C:/Users/…` so
`file:///$REPO` is well-formed; check the URL git echoes if the clone behaves
unexpectedly on yours.

The clone will not have this task's new test file, so copy it in and run it
there; expect `test_the_repository_history_is_not_shallow` to **fail naming
`fetch-depth`**, not skip and not error. Record the observed message.

- [ ] **Step 4: Prove guarantee 3 red — the abbreviation pin**

This one is driven red **directly**. `_git()` runs with `cwd=REPO_ROOT`, so it
reads `.git/config`; setting `core.abbrev` there changes the value the assertion
reads.

```bash
git config core.abbrev 8
python -m pytest tests/test_sha_citations.py::test_git_still_abbreviates_to_seven_characters
git config --unset core.abbrev
git config core.abbrev            # must print nothing and exit 1
python -m pytest tests/test_sha_citations.py::test_git_still_abbreviates_to_seven_characters
```

Expected: **FAIL** naming *"git now abbreviates to 8 characters"*, then — after
the unset — **PASS**.

**Unset it even if the test run crashes.** A left-behind `core.abbrev` makes this
test fail permanently and will look like a real defect to the next task. The
fourth command above is the check that it is gone; do not skip it. Verified
2026-08-13: `git config core.abbrev 8` turns `git rev-parse --short HEAD` from
seven characters into eight, and unsetting restores it.

Do not use `git -c core.abbrev=8 python …` — the `-c` binds to that one git
invocation and is not inherited by the test's own subprocess, which would
demonstrate the knob without driving the assertion.

- [ ] **Step 5: Remap the five citations of 5a7fc58**

Find them: `git grep -n "5a7fc58"`

Replace the token with `99f0207` in:
- `docs/adr/0041-the-review-outcome-takes-focus.md` — the sentence reads
  *"Derived 2026-08-12 on `feat/review-outcome-focus` at …"*. **Both halves were
  wrong together**: the branch was replayed, so the old token is on neither the
  branch nor `main`. `99f0207` is on both, so the whole sentence becomes true
  again.
- `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` — four places:
  the error-states row of the §2 table, the I5 row of the finding index, the
  superseded-note paragraph, and the `***FIXED …***` line of I5's own entry.

Leave every surrounding word alone. This is a pointer change, not a claim change.

- [ ] **Step 6: Remap the four citations of d2fffc0**

Find them: `git grep -n "d2fffc0"`

Replace the token with `e0481f4` in
`docs/superpowers/plans/2026-08-12-review-outcome-focus.md` — the probe-anchor
bullet near the top, the import-line measurement, the pre-existing-test note,
and the ADR-table check.

**The last one is worth reading after you change it.** It says the ADR count and
the index row count "were 40 and 40" at that commit. That stays true of the
commit, and the two commands beside it answer higher today — which is the check
in that very sentence working as intended. Do not update the 40s: they are
correctly closed to a commit that now resolves. **And do not write today's
figure either** — Task 3 of this plan adds an ADR and an index row, so any
number written here rots before the branch merges.

- [ ] **Step 7: Record the remap in that plan's dated defect log**

The plan is a dated historical record that does not self-amend, so the body edit
is logged rather than left silent. Append to its **"Dated defect log"** section:

```markdown
### 2026-08-13 — the probe anchor was orphaned by the merge replay

Every d2fffc0 in the body above now reads `e0481f4` — the dead token is written
bare here for the reason ADR-0042 gives. The two are the same
change — `git show` of each produces byte-identical patches — but the branch was
replayed onto `main` at the merge rather than fast-forwarded, so the original
commit is reachable from no ref and the four citations named nothing a reader
could look up.

**No claim in this plan changed.** A citation is a pointer, and it now points at
the commit that carries the tree the probes were run against. The counts in the
ADR-table step are deliberately untouched: 40 and 40 were correct at that commit
and are higher today, which is that step's check working.

The general rule is ADR-0042, and `tests/test_sha_citations.py` enforces it.
```

- [ ] **Step 8: Stage everything, THEN run the guard (GREEN)**

```bash
git add tests/test_sha_citations.py \
        docs/adr/0041-the-review-outcome-takes-focus.md \
        docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md \
        docs/superpowers/plans/2026-08-12-review-outcome-focus.md
git diff --cached --stat
python -m pytest tests/test_sha_citations.py
```

Expected: **3 passed**, with four files staged.

**Staging first is not tidiness.** The guard scans `git ls-files`, so an
untracked `tests/test_sha_citations.py` is invisible to itself — it would pass
here, get committed at Step 10, and fail during Task 3 instead. Staging puts it
in the scan set now. If the run fails naming a token inside the new test file's
own docstring, that is the trap firing and the docstring needs a reachable
example commit, not an exemption.

- [ ] **Step 9: Run the full gates**

Run `python scripts/verify.py` **in the background** and wait for it. Do not edit
any file while it runs.

Expected: all five PASS. pytest rises by exactly **3** from its pre-task count —
record both numbers. Vitest must be **unmoved**; no frontend file is in this
task's file set.

- [ ] **Step 10: Commit**

Everything is already staged from Step 8, and Step 9 confirmed the gates on that
exact staged content.

```bash
git diff --cached --stat
git commit -m "test: a cited commit must be reachable, and nine were not"
```

---

### Task 2: CI stops checking out one commit

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `test_the_repository_history_is_not_shallow` from Task 1.
- Produces: nothing later tasks read.

**Why separate from Task 1:** a reviewer could reasonably approve the guard and
reject full-history clones in CI. It is its own decision.

- [ ] **Step 1: Read the file first**

Run: `git grep -n "actions/checkout" -- .github/workflows/ci.yml`

Expected: **two** hits — one in the `gates` job, one in the `image` job. Neither
currently has a `with:` block. If either already has one, report it.

- [ ] **Step 2: Add `fetch-depth: 0` to both checkout steps**

Both, not just `gates`. The two jobs checking out differently is a difference
somebody will later have to explain, and the cost is a few seconds on a 398-commit
repository.

In the `gates` job:

```yaml
      - name: Check out repository
        uses: actions/checkout@v4
        # Full history, not the default single commit. `tests/test_sha_citations.py`
        # resolves every commit the documentation cites and asserts it is still
        # reachable from a ref (ADR-0042). Under `fetch-depth: 1` every citation
        # resolves as missing, so that test refuses to run rather than passing
        # vacuously -- which is the failure mode ADR-0037 was written about.
        with:
          fetch-depth: 0
```

In the `image` job:

```yaml
      - name: Check out repository
        uses: actions/checkout@v4
        # Matched to the `gates` job deliberately: two jobs checking out
        # differently is a difference a future reader has to explain.
        with:
          fetch-depth: 0
```

- [ ] **Step 3: Confirm the YAML still parses**

```bash
python -c "import yaml,io; d=yaml.safe_load(io.open('.github/workflows/ci.yml',encoding='utf-8')); print(sorted(d['jobs']))"
```

Expected: `['gates', 'image']`.

If `yaml` is not installed, say so and fall back to
`python -c "import json,subprocess"`-free inspection by reading the file — do
**not** add a dependency for this.

- [ ] **Step 4: Confirm both steps changed, and that you changed the right ones**

```bash
git diff -U2 .github/workflows/ci.yml | grep -c "fetch-depth: 0"
```

Expected: `2`. Confirming a change landed is not confirming it landed where you
meant (review standard 16) — also re-run the Step 1 grep and check both hits now
have a `with:` beneath them.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git diff --cached --stat
git commit -m "ci: full history, so the citation guard is not vacuous on GitHub"
```

---

### Task 3: ADR-0042, and the correction to ADR-0032

**Files:**
- Create: `docs/adr/0042-a-cited-commit-must-stay-reachable.md`
- Modify: `docs/adr/0032-a-document-cannot-certify-itself.md`
- Modify: `docs/adr/README.md`

**Interfaces:**
- Consumes: the three test names from Task 1; the CI change from Task 2.
- Produces: the ADR number `0042`, which Task 4's MEMORY.md edit references.

**This task touches `docs/adr/` only.** Every `docs/MEMORY.md` edit belongs to
Task 4, so that the pair lands in a commit touching nothing else (ADR-0033).

- [ ] **Step 1: Confirm 0042 is genuinely the next number**

```bash
ls docs/adr/*.md | grep -v README | wc -l
grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md
```

Expected: **41** and **41** at the time this plan was written. If they disagree
with each other, say so — that table has silently fallen behind before. If they
are both 42, an ADR landed after this plan and you need a different number.

- [ ] **Step 2: Write ADR-0042**

Follow the house structure — read `docs/adr/0041-the-review-outcome-takes-focus.md`
for the shape. It must record, at minimum:

1. **The decision.** Every backticked seven-character hex token in a tracked
   file resolves to a commit reachable from some ref, enforced by
   `tests/test_sha_citations.py`.
2. **Why reachability, not existence** — `git cat-file -e` succeeded on both
   orphans at the time of writing, so an existence check would have been green
   through the whole defect and would first go red at some unrelated `git gc`.
3. **Why any ref, not `main`** — an ADR is committed before its merge and
   legitimately cites a branch commit; CI fires on every push. Measured at
   `e698aca`: tokens reachable only from a branch, **0**.
4. **Why exactly seven characters**, with the measurement: 112 genuine citations
   all seven characters, six non-commit tokens all 8/10/12/20, no exclusion
   list needed. And that `core.abbrev` is auto, which is why the width is pinned.
5. **The naming rule for dead commits** — a document about an unreachable commit
   names it bare or at full oid length, because the backticked short form is the
   citation. Note the constraint that a sentence cannot show an example of the
   form without instantiating it, so the only safe example is a live commit.
6. **What this does not decide** — `path:NNN` citations (existence is
   mechanical, accuracy is not); whether the citation *sweep* becomes a script,
   which stands at *no*; the six non-commit hex tokens, which the rule does not
   match and which stay as they are.
7. **What it cost** — the design document failed the guard it specifies, at five
   citations, on the first run.

**Do not write either dead token in backticks anywhere in this file.**

- [ ] **Step 3: Append the dated correction to ADR-0032**

ADR-0032's decision 3 says a closed anchor is *"True forever. Safe."* Add a
`## Correction (2026-08-13)` section in the style of ADR-0028's existing
correction — read that one first for the house form.

It must say: the claim stays true, the **retrievability** does not; a replay,
rebase, amend or force-push severs it without touching the citing document and
without anything going red; nine citations in this repository demonstrated it;
and decision 3's three-way ordering **survives, qualified** — a closed SHA is
still better than a moving ref, it is simply not permanent. Point at ADR-0042.

**Do not edit decision 3's body.** ADR-0032 decision 1 is that a sentence about
a document's own trustworthiness gets deleted rather than rewritten, but this is
a claim about anchors, not about the document — and the repo's form for a wrong
Accepted decision is a dated correction, not an edit. Three ADRs already carry
one.

- [ ] **Step 4: Find every copy of the claim — and do not grep the phrase**

```bash
git grep -n "forever" -- docs
```

**Measured 2026-08-13:** `git grep "true forever" -- docs` finds **one** hit and
`git grep -i "true forever"` also finds **one**, because ADR-0032's copy wraps
between `True` at end of line and `forever.` at the start of the next. Grepping
the phrase corrects `docs/MEMORY.md` and misses the Accepted ADR.

The `docs/MEMORY.md` copy is **Task 4's**, not this task's. Confirm here that you
have found it and that there is no third copy; then leave it.

- [ ] **Step 5: Add the index row**

Append a row to `docs/adr/README.md`'s table in the existing format:

```markdown
| [0042](0042-a-cited-commit-must-stay-reachable.md) | A cited commit must stay reachable, and a rewrite carries its citations | Accepted |
```

Re-run Step 1's two commands: both must now read **42**.

- [ ] **Step 6: Stage first, THEN run the guard and the full gates**

```bash
git add docs/adr/0042-a-cited-commit-must-stay-reachable.md \
        docs/adr/0032-a-document-cannot-certify-itself.md \
        docs/adr/README.md
git diff --cached --stat
python -m pytest tests/test_sha_citations.py
```

Expected: **3 passed.** ADR-0042 is a brand-new file, so it is invisible to the
guard until staged — see the Global Constraints. If it cited a dead token in
backticks, this is where it says so, and the fix is to write the token bare, not
to exempt the file.

Then run `python scripts/verify.py` in the background. Expected: all five PASS,
pytest unmoved from Task 1's count (this task adds no test).

- [ ] **Step 7: Commit**

```bash
git diff --cached --stat
git commit -m "docs: ADR-0042, and ADR-0032's closed anchors are not true forever"
```

---

### Task 4: The handoff pair, alone

**Files:**
- Modify: `docs/MEMORY.md`
- Modify: `docs/NEXT_SESSION_PROMPT.md`

**Interfaces:**
- Consumes: ADR-0042's number and title from Task 3.
- Produces: nothing.

**This commit touches these two files and nothing else** (ADR-0033 §1, review
standard 25). The freshness check excludes exactly these two paths and watches
`docs` otherwise, so bundling them with an ADR makes the pair list itself as
stale. That happened three times in one session.

- [ ] **Step 1: Correct review standard 24's copy of the closed-anchor claim**

In `docs/MEMORY.md`, standard 24's third bullet reads *"Closed anchors (a fixed
SHA) are true forever; open ones … rot silently"*. Find it with
`git grep -n "Closed anchors" -- docs/MEMORY.md`.

Rewrite the bullet so it says a closed anchor is durable only while its commit
stays reachable, that a replay/rebase/amend/force-push severs it silently, and
that the ordering still holds — a closed SHA beats a moving ref, it is just not
permanent. Point at ADR-0042 and name `tests/test_sha_citations.py`.

- [ ] **Step 2: Replace the ADR range with the commands that derive it**

Find all three stale sentences:

```bash
git grep -n -E "0001[^0-9]*0040|40 rows" -- docs
```

**The character class is not optional.** The range uses an **en dash** (U+2013,
bytes `e2 80 93`) and `git grep`'s `.` matches one *byte*, so `0001.0040` returns
zero hits — measured, after this milestone's design document shipped exactly that
broken pattern. The range half alone finds only **two** of the three; the row
count is its own sentence.

Expected: two hits in `docs/MEMORY.md`, one in `docs/NEXT_SESSION_PROMPT.md`.

Replace the range and the row count with the two commands, compared **to each
other** rather than to any written number:

```
ls docs/adr/*.md | grep -v README | wc -l          # how many ADRs
grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md    # how many index rows
```

- [ ] **Step 3: Delete the self-certifying sentence**

`docs/NEXT_SESSION_PROMPT.md` claims *"**This** file's range has tracked each ADR
as it landed"*. Its own range falsifies it. **Delete it rather than correcting
it** — its subject is the document's own trustworthiness, and rewriting such a
sentence is the enumerated defence (ADR-0032 decision 1). Headings are sentences
too; check there is no heading carrying the same claim.

- [ ] **Step 4: Confirm nothing else is staged**

```bash
git add docs/MEMORY.md docs/NEXT_SESSION_PROMPT.md
git diff --cached --stat
```

Expected: exactly **two** files. If a third appears, unstage it — this commit
must touch nothing else.

- [ ] **Step 5: Run the guard and the gates**

Run: `python -m pytest tests/test_sha_citations.py` → **3 passed.**

Then `python scripts/verify.py` in the background → all five PASS.

- [ ] **Step 6: Commit**

```bash
git commit -m "docs: a closed anchor is only as durable as its commit's reachability"
```

**Note for the close:** this is *not* the session-end pair refresh. That is a
separate, later, also-alone commit that re-stamps the freshness anchor once the
branch is merged.

---

## Verification at the close

Before the whole-branch review, re-derive rather than trusting this plan:

| check | command | expected |
|---|---|---|
| no dangling citations | `python -m pytest tests/test_sha_citations.py` | 3 passed |
| the guard actually kills something | remap one citation back to its dead token, run, confirm it fails naming that file, revert | fails, then passes |
| both dead tokens gone from citation form | `git grep -nE '\x60(5a7fc58\|d2fffc0)\x60'` | no hits |
| the tokens still appear as prose where they should | `git grep -c "5a7fc58"` | non-zero in the defect log and ADR-0042 |
| ADR count agrees with the index | the two commands in Task 3 Step 1 | 42 and 42 |
| gates | `python scripts/verify.py` | five PASS |

**The mutation in row 2 is the one that matters** — a pin never proven red is not
a pin (review standard 14), and the free RED in Task 1 Step 2 proves the guard
catches *today's* nine, not that it catches a *new* one.

---

## Dated defect log

*(This plan's claims about existing artefacts were probed at `42e8483` — read
the real file before trusting any line above that describes one, and report the
discrepancy rather than working around it. Every defect below is the plan
author's.)*

### 2026-08-13 — plan defects

**1. The abbreviation pin was never driven red.** Task 1 Step 4 originally
demonstrated that `git -c core.abbrev=8 rev-parse --short HEAD` returns eight
characters — which shows the knob moves the value without ever making the
assertion fail. That is review standard 14: a pin never proven red is not a pin.
Found by the pre-flight scan, before any implementer was dispatched. Measured
fix: `_git()` runs with `cwd=REPO_ROOT` and so reads `.git/config`, so
`git config core.abbrev 8` drives the assertion red directly. Step 4 rewritten,
including an unset-and-verify.

**2. The docstring's "six" stated a population it did not match.** The block in
Step 1 read *"all six backticked hex tokens that are not commits are 8, 10, 12 or
20"*. Re-derived at `e698aca`: **49** backticked all-hex tokens tree-wide are not
commits. Six is the count only inside a 7-to-40-character window the sentence
never stated. Review standard 23.

**3. And it asserted the converse of what was measured.** *"All 112 genuine
commit citations are exactly seven characters"* is a claim about commit citations
at other lengths. What was actually measured — and what carries "no exclusion
list needed" — is that all 112 backticked seven-hex tokens **are** commits, zero
false positives. Measured during the fix round to close the gap: 18 backticked
hex tokens of 4-6 characters exist and **none** resolves to a commit.

**4. Three tokens were misdescribed as PAN digit-strings.** `0000000000`,
`1111111111` and `9999999999` are **Fira Code tabular-figure width samples** —
ADR-0027 records that each "measure[s] exactly 96px at 16px, so a transposed
digit does break the column". Found by the implementer re-deriving rather than
trusting the block, and confirmed by the re-review independently.

**5. `_git()` discarded `returncode` and `stderr`**, so any git failure became
the wrong-reason failure the module exists to avoid. Reproduced against a real
exit 128: the pre-fix module reported *"no citations found at all, which means
the pattern stopped matching"* — blaming the regex for a `safe.directory`
refusal. Both raise paths were then executed, not asserted.

**6. Task 3 Step 3's "Three ADRs already carry one" was never true.** Measured
with `git grep -l "^## Correction" -- docs/adr`: **8** files at `c58531d` and
**7** at `e698aca`, `main`'s tip when this branch opened. Three is not a count
this repository has had. The sentence wraps between `carry` and `one`, so an
exact-phrase grep does not reach it — the same failure mode this branch kept
paying for. Found by the whole-branch review rather than by execution: the
step's *instruction* was right, so nothing an implementer did would have gone
red.

**7. Task 3 Step 4's "true forever" count rotted inside the commit that carried
it.** The block claims `git grep "true forever" -- docs` finds **one** hit and
`git grep -i "true forever"` also **one**. True at `e698aca`: one each. Already
false at `5736a55`, this plan's own commit — `git grep -c "true forever" -- docs`
totals **8** hits over three files and `git grep -ic "true forever" -- docs`
totals **10**, because the plan carries the phrase five times and the design
twice. At `c58531d` those same two queries total **8** and **11**. The
number was never anchored; *"Measured 2026-08-13"* names a day, not a tree. The
wrap explanation and the advice it supports — grep one distinctive word, not the
phrase — are both sound and stand. This is ADR-0032 decision 2 happening to the
plan that cites it: a correctly-derived claim falsified by its own commit.

### 2026-08-13 — where this document now diverges from what shipped

**Step 1's embedded code block is NOT the docstring that shipped.** Defects 2, 3
and 4 were fixed in `tests/test_sha_citations.py` during fix round 1 and the
block above was deliberately left as it was issued, so the record of what was
instructed survives. **Read the file, not the block.**

**Step 6's guidance and Step 7's defect-log template were edited after Task 1
consumed them.** Both carried "41 and 41", a count this plan's own Task 3
falsifies by adding an ADR and an index row — a claim that rots before the branch
merges, inside the milestone that exists to stop that. The same claim had four
copies: one in the file Task 1 repaired, two here, one in the design document.
All four are now de-numbered (ADR-0033: a correction goes to every copy).
Recorded rather than silent, because editing already-consumed step text changes
the record of what was instructed.
