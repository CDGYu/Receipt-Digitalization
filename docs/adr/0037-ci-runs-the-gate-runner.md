# ADR 0037 — CI runs, and it runs the gate runner

**Status:** Accepted (2026-08-11)
**Reverses:** the 2026-07-29 decision to untrack `.github/workflows/`, and with
it ADR-0017's Context claim that this repository "cannot use" a CI workflow
**Builds on:** ADR-0017 (two suites and the gate runner), ADR-0036 (the image)
**Relates to:** ADR-0032 §3 (anchors are where rot lives), review standard 20

Derived 2026-08-11 against `feat/ci-workflow`. **Re-derive rather than quote**
(ADR-0028 rule 1).

## Context

GitHub Actions ran here once. `.github/workflows/ci.yml` was added in `5ef37ad`,
amended in `9536f96` to install the `pipeline` extra, and untracked in `5e4d708`
("chore: untrack local-only tooling config") **at the user's request**.

ADR-0017 then built an argument on its absence:

> A CI workflow would be the conventional home for a gate list. This repository
> cannot use one: `.github/workflows/ci.yml` is gitignored and untracked at the
> user's request, and GitHub Actions does not run. **A tracked workflow that
> cannot execute is a false signal — worse than none, because it reads as
> coverage.**

The bolded sentence is still right, and is the reason this ADR exists only now
that the user has reversed the request rather than as a speculative addition.

### The file that was left behind

The untracked `ci.yml` survived on disk and is what a naive "turn CI back on"
would have committed. It was stale in three ways:

* **Python 3.11 and 3.12**, chosen before the image existed.
* **It ran none of the three frontend gates.** No Node, no `npm test`, no
  `typecheck`, no `build` — so a green run said far less than it looked like it
  said. ADR-0017 exists *because* two defects reached a green Vitest run and
  were caught only by `tsc -b`.
* **It re-listed the gates** — pytest, ruff, mypy — rather than calling the
  runner that defines them.

## Decision

### 1. The workflow does not list gates. It runs `scripts/verify.py`

One command. `scripts/verify.py` is the definition of "did this pass"
(ADR-0017), and a second copy of the list in YAML is one more thing to keep in
agreement — which the old file demonstrated by drifting three gates out of date.

### 2. Every branch, and no `pull_request:` trigger

`on: [push]`, unscoped.

Feature branches here are pushed and then merged into `main` by **local
fast-forward**, so a workflow scoped to `main` would only ever report *after*
the merge it was supposed to gate. There is no `pull_request:` trigger because
this repository does not use PRs; adding one would produce no runs and read as
coverage that does not exist — the same failure ADR-0017 names.

### 3. Python 3.11 and 3.13

3.11 is the floor `requires-python` declares; 3.13 is what ADR-0036's image
ships. Between them the advertised contract and the shipped artefact are both
covered.

**3.14.4, the development interpreter, is deliberately absent.** It is the one
exercised locally on every run, so a break there surfaces immediately without
CI. This is a stated gap rather than an oversight.

### 4. A guard against the false green

`pytest.importorskip` turns a missing optional dependency into a **silent
skip**. An install that quietly dropped an extra would leave the suite green
while covering less — precisely the "reads as coverage" failure, arriving by a
different route.

So the workflow asserts the extras are importable before running anything:

```
python -c "import fastapi, cv2, openpyxl, pypdfium2, pillow_heif"
```

That list is **derived from the tests**, not copied from the old workflow: it is
every target of an `importorskip` under `tests/`. It is a membership check
rather than a count, so it does not rot as the suite grows (ADR-0032 §3).
Measured: it exits 0 as installed, and raises `ModuleNotFoundError` when a name
is missing.

Nothing under `tests/` hard-imports `rq`, `redis` or `boto3`, so the `worker`
and provider extras are not installed.

### 5. CI builds the image, and checks it boots

`docker build` is its own job. The Dockerfile is an artefact nothing else
exercises — without this it is known-good only on the day somebody last built it
by hand, and the first sign of a break would be a deployment.

Two assertions beyond "it built", both run against the real image locally before
being written into the workflow:

* an **unconfigured** container prints `refuses to start` and names
  `DATABASE_URL` (ADR-0035's boot contract);
* `receipts --help` resolves inside the image, which is the measurement that
  closed the §1.6 question. If it stops resolving, packaging really has broken.

The container exits non-zero by design; in `cmd | grep` the pipeline's status is
grep's, so these assert "the output contained this", not "the container
succeeded".

**Nothing is pushed to a registry.** No image-promotion decision is being taken
here.

## What is NOT verified

**This workflow has never run.** GitHub Actions executes on GitHub, and it could
not be executed from the machine that wrote it. That is a weaker position than
ADR-0036, whose image was built and run before it was written, and it is stated
here rather than left for a reader to discover.

What *was* checked locally, and what it does and does not tell you:

| checked | how | covers |
|---|---|---|
| the YAML parses | `yaml.safe_load` | syntax, not semantics |
| every step is named and has exactly one of `uses`/`run` | assertion over the parsed document | shape, not correctness |
| both image-job greps | run against the real image | those two steps exactly |
| `receipts --help` in the image | run against the real image | that step exactly |
| the extras guard | run, and run again with a bogus name | that step, both directions |
| `python scripts/verify.py` | run many times on this machine | the command, not the runner |

**Unverified until the first run:** that `actions/setup-python` offers 3.11 and
3.13 on `ubuntu-latest`; that `pip install -e ".[dev,pipeline,api]"` resolves on
Linux for both; that `npm ci` succeeds from the committed lockfile; and that the
suite passes on a Linux runner at all — it has only ever been run on Windows
here, and `tests/` contains path handling that has never met a case-sensitive
filesystem.

**The first red run is expected to be informative rather than alarming**, and
should be read before anything is "fixed".

## Consequences

- **ADR-0017's Context is now wrong** where it says the repository cannot use a
  workflow. Its *decision* is untouched and is in fact strengthened: the gate
  list still lives in exactly one place, and CI is now a consumer of it. A
  correction is recorded there.
- **`.gitignore` no longer hides `.github/workflows/`**, and says why, with the
  dates it was hidden between.
- **A green run means more than the old one did** — five gates on two Pythons,
  plus an image that builds and boots — and it can still be less than it looks
  if a step is added that does not gate. That is the standing risk of a
  workflow, and the reason the gate list is not duplicated here.
- **CI minutes are now spent on a public repository.** Two matrix jobs plus an
  image build, on every push to every branch.

## What this ADR does not decide

Whether CI should publish anything: no registry, no image tags beyond the local
`receipts:ci`, no releases, no deployment trigger. Nor branch protection, nor
whether a red run should block a local fast-forward merge — today nothing
enforces that, and the merge happens on a developer's machine.

Nor Playwright. The acceptance run is deliberately not a gate (ADR-0017,
ADR-0029), and CI does not change that; making it a sixth gate is a separate
open question.

## References

`.github/workflows/ci.yml`; `scripts/verify.py`;
`docs/adr/0017-two-suites-and-the-gate-runner.md` and its correction;
`docs/adr/0036-one-image-two-commands.md`;
`docs/adr/0035-the-asgi-entry-point.md` (the boot contract the image job
asserts); `5ef37ad`, `9536f96`, `5e4d708` (the workflow's first life).
