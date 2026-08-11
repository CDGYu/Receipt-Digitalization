# ADR 0017 — Two test suites, and `scripts/verify.py` is what "passing" means

**Status:** Accepted (Phase 5, 2026-07-31)

## Context

Until Phase 5 this repository had one test suite. `python -m pytest` was the
whole answer to "did this pass", and ADR-0005 records why it stays offline —
fake client, SQLite, no Redis, no network.

Phase 5 added a React 19 + Vite + TypeScript frontend, and with it a **second
suite** (Vitest) plus a type-checker and a bundler. That is three new gates, and
one of them fails in a way the others cannot see:

**`npm test` does not type-check.** Vitest transpiles without checking types, so
a TypeScript error is invisible to it. This is not a theoretical hazard — it
fired three times in one milestone:

- Two defects taken verbatim from a plan snippet (`SubmitError` written with
  constructor parameter properties, which `erasableSyntaxOnly: true` rejects as
  `TS1294`) broke `npm run build` while **every Vitest test passed**.
- A later measurement of the same trap was itself wrong. A comment claimed the
  runner catches "9 of the 10 tests" — re-measured single-variable, the answer
  is **10 of 10 pass**: the runner catches *nothing* of that class. The original
  figure came from a mutation that changed two things at once.

A CI workflow would be the conventional home for a gate list. This repository
cannot use one: `.github/workflows/ci.yml` is gitignored and untracked at the
user's request, and GitHub Actions does not run. A tracked workflow that cannot
execute is a false signal — worse than none, because it reads as coverage.

> **Correction (2026-08-11).** The paragraph above is no longer true of the
> repository. The user reversed the request, `.github/workflows/` is tracked
> again, and CI runs — **ADR-0037**.
>
> **The decision below is untouched, and CI strengthens rather than replaces
> it.** The workflow does not list gates; it runs `scripts/verify.py`, so the
> gate list still lives in exactly one place and CI is a consumer of it. The
> previous workflow did the opposite — it re-listed pytest, ruff and mypy, ran
> **none** of the three frontend gates, and drifted three gates out of date
> while looking like coverage. That is this ADR's own argument, demonstrated.
>
> The last sentence above stands unchanged and is worth keeping: a tracked
> workflow that cannot execute is worse than none. It is why ADR-0037 exists
> only now that Actions is switched back on.

## Decision

**There are two suites, and neither alone is a gate.**

`python -m pytest` stays offline and **Node-free**: it must pass on a machine
with no `npm`, and it adds no Node dependency. Verified by measurement, not
assertion — with the nodejs directory stripped from `PATH`, the suite passes
unchanged.

**`scripts/verify.py` is the definition of "did this pass".** It runs five gates
in order and reports each by name:

```
python -m pytest        python -m ruff check .        npm run typecheck  (tsc -b)
npm test  (vitest)      npm run build
```

Two properties are load-bearing:

- **It fails loudly, naming the gate.** A failing gate produces
  `FAILED: pytest, typecheck` and a non-zero exit. Nothing is swallowed; there
  is no `try`/`except` anywhere in the file, so a broken toolchain surfaces as a
  traceback rather than a pass.
- **A missing `npm` is announced per gate, never silent.** Each Node gate prints
  `SKIPPED: npm not found on PATH -- <gate> did not run`, and the Python half
  still gates, exit 0. This is ADR-0014's discipline applied to a toolchain
  instead of an import: absent optional tooling degrades visibly, and a clone
  without Node stays usable.

**`npm run lint` (oxlint) is deliberately not a gate.** Its exit status cannot
distinguish "clean" from "warned" — it exits 0 while printing warnings, which is
what its own configuration asks for. Promoting it needs a decision about what a
warning means, which nobody has made. `scripts/verify.py`'s docstring says so
explicitly rather than leaving the list to read as exhaustive.

## Consequences

- **Running `npm test` and seeing green is not evidence the frontend builds.**
  Any change touching `frontend/` must run `npm run typecheck` as well, or use
  `scripts/verify.py`. This is the single most repeated defect of Phase 5 and
  the reason this ADR exists.
- **Nothing runs the frontend gates on GitHub.** `scripts/verify.py` is a local
  gate. If Actions is ever re-enabled, the workflow should call this script
  rather than re-listing the gates, so the two cannot drift.
- The Playwright e2e is **not** in `verify.py`. It needs a seeded database, a
  built frontend and a running server, and it downloads a browser binary. It is
  run deliberately (`cd frontend && npx playwright test`), not as part of the
  ordinary gate sweep.
- A future third suite inherits the same obligation: add it to `verify.py`, or
  it is not a gate.

## References

ADR-0005 (tooling, src-layout, and the offline test strategy this extends);
ADR-0014 (the skip-it-when-it-is-absent discipline, applied to imports);
ADR-0015 (the review UI, which introduced the second suite);
`scripts/verify.py`; `tests/test_verify_script.py` (its own tests — seven
single-variable mutations, each tripping the test that names its cause);
`frontend/tests/no-float-in-money-path.test.ts` (a source-scanning guard that is
run *by* Vitest and is therefore subject to the same blindness — it has no rule
that can fire on arithmetic, so it cannot settle whether a given expression
violates ADR-0001; read the code for that).
