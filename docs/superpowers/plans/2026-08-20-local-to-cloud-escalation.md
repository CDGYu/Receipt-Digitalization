# Local-to-Cloud Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one eval run use a cheap local model for triage and fall back from a local extract to a cloud extract when the local one does not work, and record which rung produced the kept extraction.

**Architecture:** A "tier" is a `(model, use_tools)` pair on the shared Ollama endpoint, not a provider — the local daemon proxies `:cloud` models, so switching rungs is the model string. Triage gets one rung; extract gets two. The ladder is a parameter on `run_receipt` and never on `process_receipt`, which is what keeps it off the production path. The fallback trigger reuses ADR-0040's path grouping rather than growing a second definition of "what the model read".

**Tech Stack:** Python 3.11/3.13, pydantic Settings, pytest. No new dependencies. No frontend changes.

**Spec:** `docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` — **read it first, including its dated correction in §3**, which records that the original trigger predicate could never have fired.

## Global Constraints

- **Ollama only, no hosted APIs.** Standing user ruling (2026-08-14). No new provider id is added.
- **Egress is eval-path only.** `process_receipt` gains no ladder parameter. Spec §5.
- **Nothing set means today's behaviour, exactly.** With no new settings, exactly one client is built and `run_receipt` behaves as it does now. Pinned in Task 4 and Task 5.
- **`pyproject.toml` sets `addopts = "-q"`.** So `python -m pytest -q` is `-qq` and prints no pass count, and `-v` nets to dot output. **Use bare `python -m pytest <path>`.**
- **`pytest -k` matches substrings, not words.** Every `-k` in this plan is a claim about the test names in this same plan; run the exact node ids given instead where one is supplied.
- **Stage by explicit path, never `git add -A`.** Verify with `git diff --cached --stat` before committing.
- **Use the Write/Edit tools for any file containing non-ASCII** — PowerShell `Get-Content`/`Set-Content` corrupts em dashes and `§` on the read.
- **Gates:** `python scripts/verify.py` is what "passing" means (ADR-0017). It exceeds a 2-minute tool timeout — background it, and do not edit source or tests while it runs.
- **Money stays `Decimal`; null beats a confident guess.** Nothing in this plan converts either.
- **A pin is not a pin until it has been proven red**, and the mutated tree must still compile — a red from a syntax error proves nothing.

---

## File Structure

| file | responsibility | task |
|---|---|---|
| `src/receipts/extract/paths.py` | gains the path grouping (moved from `eval/`) and the read-nothing predicate. Already owns `flatten`/`count_nulls`, so "what is a field" stays in one place | 1, 2 |
| `eval/metrics.py` | loses the private grouping, imports it from `paths.py` under the same local names so its call sites do not move | 1 |
| `config/settings.py` | three new optional settings | 3 |
| `src/receipts/extract/clients/factory.py` | one tool-use resolution function used at both ends; `PassClients` and `make_pass_clients` | 3, 4 |
| `src/receipts/pipeline.py` | `RunOutcome`, `PassAttempt`, the extract ladder in `run_receipt`, attribution collection in `build_eval_pipeline` | 5, 7 |
| `eval/metrics.py`, `eval/harness.py`, `eval/run_baseline.py` | per-rung counts on the report, in the JSON, and printed beside accuracy | 7 |
| `tests/test_paths.py`, `tests/test_client_factory.py`, `tests/test_pipeline.py`, `tests/test_eval_metrics.py` | the pins | all |

---

### Task 1: Move the path grouping into `src`, unchanged

**Files:**
- Modify: `src/receipts/extract/paths.py`
- Modify: `eval/metrics.py:62-117` (the block being moved) and `eval/metrics.py:32` (the import)
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `receipts.extract.paths.group_of(path: str) -> str` returning `"self_report" | "line_items" | "core"`; `receipts.extract.paths.is_filled(value: object) -> bool`; `receipts.extract.paths.SELF_REPORT_LEAVES: frozenset[str]`.

**Why a move and not a copy:** the predicate is needed in `src`, `eval/` imports from `src` (not the reverse), and a second copy would reproduce ISSUE-008 — two identical predicates with nothing binding them — which is already open in this repository for exactly that shape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_paths.py` if it does not exist; otherwise append.

```python
from receipts.extract.paths import SELF_REPORT_LEAVES, group_of, is_filled


def test_group_of_reads_the_path_string_only() -> None:
    assert group_of("meta.notes") == "self_report"
    assert group_of("line_items") == "line_items"
    assert group_of("line_items[0].qty") == "line_items"
    assert group_of("totals.total") == "core"
    assert group_of("receipt.decimal_convention") == "core"


def test_self_report_leaves_are_checked_before_their_prefix() -> None:
    # `is_template_row` lives under `line_items[i].`, which would otherwise
    # claim it. The set is consulted first, and that ordering is the guarantee.
    assert "is_template_row" in SELF_REPORT_LEAVES
    assert group_of("line_items[0].is_template_row") == "self_report"


def test_is_filled_rejects_none_and_empty_containers_only() -> None:
    assert is_filled("SUPERMART") is True
    assert is_filled(0) is True          # a read zero is content
    assert is_filled(False) is True      # so is a read false
    assert is_filled(None) is False
    assert is_filled([]) is False
    assert is_filled({}) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_paths.py`
Expected: FAIL with `ImportError: cannot import name 'group_of' from 'receipts.extract.paths'`.

- [ ] **Step 3: Move the block into `paths.py`**

Append to `src/receipts/extract/paths.py`, copying the bodies from `eval/metrics.py:62-117` **verbatim** — including their comments, which carry the admission rule for `SELF_REPORT_LEAVES` and the reason `is_filled` avoids `in (None, [], {})`. Rename `_group` to `group_of` and `_is_filled` to `is_filled`; the leading underscore was module-private and these are now shared.

```python
#: Where the ``meta.`` self-report prefix and the line-items prefix live. Moved
#: here from ``eval/metrics.py`` (ADR-0040) so the pipeline and the eval harness
#: share one definition of what counts as content the model read, rather than
#: growing a second one that can drift.
_META_PREFIX = "meta."
_LINE_ITEMS = "line_items"

#: The self-report leaves that do **not** live under ``meta.``. One declaration,
#: read by :func:`group_of` and by nothing else.
#:
#: The admission rule, and the whole of it: a leaf belongs here when it records
#: the model's **claim about the paper** -- the state of the document, or of the
#: model's own reading of it -- rather than a transcription of content printed
#: on it. ``is_template_row`` says "this pre-printed row was left blank"; the
#: paper nowhere reads "false", and a model that looks at nothing is right on
#: every row that is not blank, which is a free point per line item inside a
#: group that averages.
#:
#: ``receipt.decimal_convention`` is the near miss on the other side of that
#: line and is deliberately **not** here: it also rests at a usually-correct
#: default, but it names a convention the document prints, so it is something
#: the model had to read.
SELF_REPORT_LEAVES = frozenset({"is_template_row"})


def group_of(path: str) -> str:
    """Which family a dotted path belongs to: ``self_report``, ``line_items`` or ``core``.

    Read from the path string alone -- never from either side's value.

    ``self_report`` is reached two ways, and there are exactly these two:
    everything under the ``meta.`` prefix, and the leaves declared in
    :data:`SELF_REPORT_LEAVES`. The set is checked **first**, because the
    leaves in it live under prefixes that would otherwise claim them.
    """
    if path.rsplit(".", 1)[-1] in SELF_REPORT_LEAVES:
        return "self_report"
    if path.startswith(_META_PREFIX):
        return "self_report"
    if path == _LINE_ITEMS or path.startswith(f"{_LINE_ITEMS}["):
        return "line_items"
    return "core"


def is_filled(value: object) -> bool:
    """True when a leaf carries information the model could have read.

    ``None`` is not filled, and neither is an empty container. ``flatten``
    emits ``[]``/``{}`` as leaves deliberately, so that "had none" is visible
    rather than absent -- but a receipt whose ``totals.tax_breakdown`` is empty
    has no tax breakdown to transcribe, so it is not a point anyone can earn.

    Written with ``isinstance``/``len`` rather than ``value in (None, [], {})``:
    that form compares with ``==``, and equality against a container is not a
    test this rule should rest on.
    """
    if value is None:
        return False
    return not (isinstance(value, (list, dict)) and len(value) == 0)
```

- [ ] **Step 4: Delete the originals and re-import in `eval/metrics.py`**

Delete `_META_PREFIX`, `_LINE_ITEMS`, `_SELF_REPORT_LEAVES`, `_group` and `_is_filled` from `eval/metrics.py` (the block at lines 62-117, including the `#:` comment block above `_SELF_REPORT_LEAVES`). Replace the import at line 32:

```python
from receipts.extract.paths import (
    SELF_REPORT_LEAVES as _SELF_REPORT_LEAVES,
    flatten,
    group_of as _group,
    is_filled as _is_filled,
)
```

**Alias deliberately.** The three call sites at `eval/metrics.py:274`, `:275` and `:282` keep the names they already use, so this move changes no logic anywhere. The docstring references at `:90` and `:203` name `_SELF_REPORT_LEAVES`; `:90` goes with the moved block, and `:203` stays and still resolves because the alias is bound in this module.

- [ ] **Step 5: Run the new test and the eval metrics suite**

Run: `python -m pytest tests/test_paths.py tests/test_eval_metrics.py`
Expected: PASS. **The eval suite passing unchanged is the behaviour-preserving proof** — this task must not move a single metric.

- [ ] **Step 6: Prove the move is behaviour-preserving, not merely green**

Run the whole suite: `python -m pytest`
Expected: PASS with the same count as before the task. If any eval test fails, the move changed behaviour and must be corrected rather than the test adjusted.

- [ ] **Step 7: Commit**

```bash
git add src/receipts/extract/paths.py eval/metrics.py tests/test_paths.py
git diff --cached --stat
git commit -m "refactor(paths): one definition of what the model read, reachable from src"
```

---

### Task 2: The read-nothing predicate

**Files:**
- Modify: `src/receipts/extract/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `group_of`, `is_filled`, `flatten` from Task 1.
- Produces: `receipts.extract.paths.read_nothing(extraction) -> bool`.

**The definition, and why it is not "everything is null":** a default-constructed `ReceiptExtraction()` has one filled `core` leaf, `receipt.decimal_convention = 'point'`, so an emptiness test never fires. Comparing against the default instead is schema-derived in both directions — a field added later with a default is excluded automatically, and a field the model fills is counted automatically.

- [ ] **Step 1: Write the failing test**

```python
from decimal import Decimal

from receipts.extract.paths import read_nothing
from receipts.extract.schema import ReceiptExtraction


def test_a_default_extraction_read_nothing() -> None:
    # This is what `_evaluate` produces when a response does not parse
    # (`response.parsed or ReceiptExtraction()`), so the parse-failure case is
    # covered here rather than as a separate clause.
    assert read_nothing(ReceiptExtraction()) is True


def test_any_transcribed_core_field_means_something_was_read() -> None:
    with_merchant = ReceiptExtraction()
    with_merchant.merchant.name = "SUPERMART INC."
    assert read_nothing(with_merchant) is False

    with_total = ReceiptExtraction()
    with_total.totals.total = Decimal("224.00")
    assert read_nothing(with_total) is False


def test_a_default_valued_field_read_differently_counts() -> None:
    # `decimal_convention` rests at 'point' by default, but it names a
    # convention the document prints. A model that read 'comma' read something.
    read_as_comma = ReceiptExtraction()
    read_as_comma.receipt.decimal_convention = "comma"
    assert read_nothing(read_as_comma) is False


def test_self_report_alone_is_not_content() -> None:
    # The model describing its own reading is not a transcription from the
    # paper, so a difference confined to `meta.` still reads as nothing.
    only_meta = ReceiptExtraction()
    only_meta.meta.is_handwritten = True
    assert read_nothing(only_meta) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_paths.py`
Expected: FAIL with `ImportError: cannot import name 'read_nothing'`.

- [ ] **Step 3: Implement it**

```python
def _content_paths(extraction: Any) -> dict[str, Any]:
    """The filled ``core`` and ``line_items`` leaves of one extraction."""
    return {
        path: value
        for path, value in flatten(extraction).items()
        if group_of(path) in ("core", "line_items") and is_filled(value)
    }


def read_nothing(extraction: Any) -> bool:
    """True when an extraction transcribed nothing from the paper.

    Compared against a **default-constructed** extraction rather than against
    emptiness, because emptiness is unreachable: ``ReceiptExtraction()`` carries
    ``receipt.decimal_convention = 'point'``, which is ``core`` by design --
    the convention is something the document prints, so a model is expected to
    read it (``group_of``'s own note says so).

    Comparing to the default is what keeps this schema-derived in both
    directions: a field added later that rests at a default is excluded without
    anybody deciding, and a field the model actually fills is counted the same
    way.

    Covers the no-parse case without a clause of its own -- ``_evaluate``
    resolves a failed parse to exactly ``ReceiptExtraction()``.
    """
    return _content_paths(extraction) == _content_paths(ReceiptExtraction())
```

with `from .schema import ReceiptExtraction` added to the **module-level**
imports at the top of `paths.py`.

**There is no import cycle, so do not write a local import.** An earlier version
of this step had `from .schema import ReceiptExtraction  # local: avoids an
import cycle` inside the function. That comment was false and is exactly the
defect species Task 1 caught — a correct-looking instruction carrying an invented
reason. Verified before dispatch: `schema.py` imports only stdlib and pydantic,
and `src/receipts/extract/__init__.py` is empty, so no route from `schema` back
to `paths` exists.

**Consider caching the baseline.** `_content_paths(ReceiptExtraction())` is
recomputed on every call and is a constant. A module-level constant is the
obvious form; whether it is worth it is the implementer's call, and either
answer is fine provided the tests pass. Say which you chose and why.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_paths.py`
Expected: PASS, 6 tests (3 from Task 1, 4 from this task — note that is 7; if the count surprises you, read the names rather than trusting this sentence).

- [ ] **Step 5: Prove the predicate can fail, one clause at a time**

Mutate `group_of` to return `"core"` for everything and re-run: `test_self_report_alone_is_not_content` must fail. Revert. Then mutate `read_nothing` to `return not _content_paths(extraction)` (the emptiness form the spec's correction rejects) and re-run: `test_a_default_extraction_read_nothing` must fail. Revert.

**Confirm the mutated tree still imports** each time (`python -c "import receipts.extract.paths"`) — a red from a broken module proves nothing about the predicate.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/extract/paths.py tests/test_paths.py
git diff --cached --stat
git commit -m "feat(paths): read_nothing, measured against the schema's own default"
```

---

### Task 3: Settings and one tool-use resolution

**Files:**
- Modify: `config/settings.py:39-53` (the `vlm_*` block)
- Modify: `src/receipts/extract/clients/factory.py`
- Test: `tests/test_client_factory.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Settings.vlm_model_extract_fallback: str | None`, `Settings.vlm_use_tools_triage: bool | None`, `Settings.vlm_use_tools_fallback: bool | None`; and `receipts.extract.clients.factory.resolve_use_tools(provider: str, *, explicit: bool | None, global_default: bool | None) -> bool`.

**Why one function:** `_TOOLS_OFF_BY_DEFAULT` is keyed on the provider while the exception is per model, which ADR-0002's 2026-08-18 correction recorded and left for this milestone. A ladder that answered the question its own way would be a second mechanism that must agree with `make_client` — review standard 19 says state one bounded property and enforce it at both ends.

- [ ] **Step 1: Write the failing test**

```python
from receipts.extract.clients.factory import resolve_use_tools


def test_an_explicit_per_rung_value_wins_over_everything() -> None:
    assert resolve_use_tools("ollama", explicit=True, global_default=False) is True
    assert resolve_use_tools("vllm", explicit=False, global_default=True) is False


def test_the_global_default_wins_when_the_rung_says_nothing() -> None:
    assert resolve_use_tools("ollama", explicit=None, global_default=True) is True
    assert resolve_use_tools("vllm", explicit=None, global_default=False) is False


def test_the_provider_decides_when_nothing_is_configured() -> None:
    # Ollama is the one provider whose servers cannot be assumed to accept a
    # tools payload, so it alone defaults off.
    assert resolve_use_tools("ollama", explicit=None, global_default=None) is False
    assert resolve_use_tools("vllm", explicit=None, global_default=None) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_client_factory.py`
Expected: FAIL with `ImportError: cannot import name 'resolve_use_tools'`.

- [ ] **Step 3: Add the settings**

In `config/settings.py`, beside the existing `vlm_use_tools`:

```python
    #: The second extract rung. Unset means there is no fallback and the ladder
    #: has exactly one rung, which is today's behaviour.
    vlm_model_extract_fallback: str | None = None
    #: Tool use for the triage rung. Not optional convenience: ISSUE-001 tells a
    #: reader to set VLM_USE_TOOLS=true for the cloud tier, and that is a
    #: process-wide default -- it would turn tools on for triage too, where
    #: granite is measured to lose `merchant_name_guess` entirely, which is the
    #: field ADR-0043 decision 1's hint path keys off.
    vlm_use_tools_triage: bool | None = None
    #: Tool use for the fallback rung.
    vlm_use_tools_fallback: bool | None = None
```

- [ ] **Step 4: Add `resolve_use_tools` and route `make_client` through it**

In `factory.py`, below `_TOOLS_OFF_BY_DEFAULT`:

```python
def resolve_use_tools(
    provider: str, *, explicit: bool | None, global_default: bool | None
) -> bool:
    """Whether one rung sends a ``tools`` payload.

    Precedence, and the only precedence: the rung's own explicit value, then the
    process-wide ``VLM_USE_TOOLS``, then the provider default. The same chain
    ``make_client`` already used, with one level added in front so a per-model
    exception can be expressed -- ``granite3.2-vision:2b`` and ``gemma4:cloud``
    are both provider ``ollama`` and want opposite answers.
    """
    if explicit is not None:
        return explicit
    if global_default is not None:
        return global_default
    return provider not in _TOOLS_OFF_BY_DEFAULT
```

Then replace the inline chain inside `make_client`'s OpenAI-family branch:

```python
        use_tools = resolve_use_tools(
            provider, explicit=None, global_default=settings.vlm_use_tools
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_factory.py`
Expected: PASS. **Every pre-existing test in this file must pass unmodified** — `make_client`'s behaviour has not changed, only where the decision is written. If one needs editing, stop and report rather than editing it.

- [ ] **Step 6: Commit**

```bash
git add config/settings.py src/receipts/extract/clients/factory.py tests/test_client_factory.py
git diff --cached --stat
git commit -m "feat(factory): one tool-use precedence chain, with room for a per-rung answer"
```

---

### Task 4: `PassClients` and `make_pass_clients`

**Files:**
- Modify: `src/receipts/extract/clients/factory.py`
- Test: `tests/test_client_factory.py`

**Interfaces:**
- Consumes: `resolve_use_tools` (Task 3), `make_client`.
- Produces: `receipts.extract.clients.factory.PassClients` — a frozen dataclass with `triage: VLMClient` and `extract_rungs: tuple[VLMClient, ...]` — and `make_pass_clients(settings: Settings) -> PassClients`.

**Deliberate bound:** `extract_rungs` is a tuple so the shape generalises, but this milestone builds **at most two** rungs. A third is a new decision and is not earned by anything measured.

- [ ] **Step 1: Write the failing test**

```python
from config.settings import Settings
from receipts.extract.clients.factory import make_pass_clients


def _settings(**kw: object) -> Settings:
    base = {"vlm_provider": "fake"}
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_with_nothing_configured_there_is_exactly_one_rung() -> None:
    # The whole-behaviour guarantee: an unconfigured deployment gets what it
    # got before this milestone existed.
    tiers = make_pass_clients(_settings())
    assert len(tiers.extract_rungs) == 1


def test_a_fallback_model_adds_a_second_rung() -> None:
    tiers = make_pass_clients(
        _settings(vlm_model_extract="local-a", vlm_model_extract_fallback="cloud-b")
    )
    assert len(tiers.extract_rungs) == 2


def test_the_triage_rung_can_name_its_own_model() -> None:
    tiers = make_pass_clients(
        _settings(vlm_model_extract="extract-model", vlm_model_triage="triage-model")
    )
    # `fake` ignores the model id, so assert on what the factory resolved rather
    # than on the client's own attribute.
    assert tiers.triage is not tiers.extract_rungs[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_client_factory.py`
Expected: FAIL with `ImportError: cannot import name 'make_pass_clients'`.

- [ ] **Step 3: Implement it**

```python
@dataclass(frozen=True)
class PassClients:
    """One client per pass, with the extract pass carrying a rung ladder.

    Built **only** by the eval path. ``make_client`` still returns exactly one
    client and is what every production entry point uses, which is what keeps
    the ladder off that path (design §5).
    """

    triage: VLMClient
    extract_rungs: tuple[VLMClient, ...]


def _client_for(settings: Settings, *, model: str | None, use_tools: bool) -> VLMClient:
    """One rung, built through ``make_client`` rather than beside it.

    Reusing the factory means the provider dispatch, the lazy SDK imports and
    the missing-configuration errors have exactly one implementation. Only the
    model and the tools flag differ between rungs -- on Ollama both rungs share
    the endpoint, because the local daemon proxies ``:cloud`` models.
    """
    return make_client(
        settings.model_copy(
            update={"vlm_model_extract": model, "vlm_use_tools": use_tools}
        )
    )


def make_pass_clients(settings: Settings) -> PassClients:
    """Build the per-pass clients for an eval run.

    With no new settings configured this returns one triage client and one
    extract rung, both equivalent to ``make_client(settings)``.
    """
    provider = settings.vlm_provider.strip().lower()

    triage = _client_for(
        settings,
        model=settings.vlm_model_triage or settings.vlm_model_extract,
        use_tools=resolve_use_tools(
            provider,
            explicit=settings.vlm_use_tools_triage,
            global_default=settings.vlm_use_tools,
        ),
    )

    rungs = [
        _client_for(
            settings,
            model=settings.vlm_model_extract,
            use_tools=resolve_use_tools(
                provider, explicit=None, global_default=settings.vlm_use_tools
            ),
        )
    ]
    if settings.vlm_model_extract_fallback:
        rungs.append(
            _client_for(
                settings,
                model=settings.vlm_model_extract_fallback,
                use_tools=resolve_use_tools(
                    provider,
                    explicit=settings.vlm_use_tools_fallback,
                    global_default=settings.vlm_use_tools,
                ),
            )
        )

    return PassClients(triage=triage, extract_rungs=tuple(rungs))
```

Add `from dataclasses import dataclass` to the imports if it is not already present.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_factory.py`
Expected: PASS.

- [ ] **Step 5: Prove the one-rung guarantee is real**

Mutate `make_pass_clients` so the fallback rung is appended unconditionally, and re-run: `test_with_nothing_configured_there_is_exactly_one_rung` must fail. Revert, and confirm the module still imports.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/extract/clients/factory.py tests/test_client_factory.py
git diff --cached --stat
git commit -m "feat(factory): per-pass clients, with the extract ladder built only for eval"
```

---

### Task 5: `RunOutcome`, attribution, and the ladder in `run_receipt`

**Files:**
- Modify: `src/receipts/pipeline.py:184-239` (`run_receipt`) and `:287-290` (`build_eval_pipeline`'s unpack)
- Modify: `tests/test_pipeline.py:109`, `:133`, `:145` (the three tests that unpack the triple)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `read_nothing` (Task 2).
- Produces: `receipts.pipeline.PassAttempt` — frozen dataclass with `pass_name: str`, `model_id: str`, `rung: int`, `kept: bool` — and `receipts.pipeline.RunOutcome` — frozen dataclass with `extraction: ReceiptExtraction`, `report: ValidationReport`, `triage: TriageResult`, `attribution: tuple[PassAttempt, ...]`. `run_receipt` returns `RunOutcome` and takes two new keyword-only parameters, `triage_client: VLMClient | None = None` and `extract_fallback_client: VLMClient | None = None`.

**`process_receipt` gains nothing.** That is the egress boundary and it is enforced in Task 6.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_fallback_is_not_called_when_the_first_rung_reads_something(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _good()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    assert fallback.calls == []
    assert outcome.extraction.merchant.name == "SUPERMART INC."
    kept = [a for a in outcome.attribution if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["local"]


def test_the_fallback_runs_when_the_first_rung_reads_nothing(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    # An unparseable extract response leaves `ReceiptExtraction()`, which is
    # exactly what "read nothing" means.
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    assert len(fallback.calls) == 1
    assert outcome.extraction.merchant.name == "SUPERMART INC."
    kept = [a for a in outcome.attribution if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["cloud"]
    # ...and the discarded rung is still recorded, so an eval can see it ran.
    discarded = [a for a in outcome.attribution if a.pass_name == "extract" and not a.kept]
    assert [a.model_id for a in discarded] == ["local"]


def test_triage_runs_on_its_own_client_when_one_is_given(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    extract_client = FakeVLMClient([_good()], model_id="extract-model")

    outcome = run_receipt(png, extract_client, CTX, triage_client=triage_client)

    assert len(triage_client.calls) == 1
    assert triage_client.calls[0]["schema"] == "TriageResult"
    assert len(extract_client.calls) == 1
    assert extract_client.calls[0]["schema"] == "ReceiptExtraction"


def test_a_raising_first_rung_falls_back_rather_than_propagating(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = _RaisingClient(model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, triage_client=FakeVLMClient([_triage()]),
                          extract_fallback_client=fallback)

    assert outcome.extraction.merchant.name == "SUPERMART INC."


def test_a_raising_last_rung_still_propagates(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    with pytest.raises(VLMTransientError):
        run_receipt(png, _RaisingClient(model_id="only"), CTX,
                    triage_client=FakeVLMClient([_triage()]))


def test_only_the_final_rung_spends_its_repair_budget(tmp_path):
    # Spec §2.1. The first rung reads nothing, so it is discarded -- and it must
    # not have spent a repair round getting there. One extract call, no repair.
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    run_receipt(png, first, CTX, extract_fallback_client=fallback, max_attempts=3)

    # Two calls on the first client: the triage and exactly one extract. A
    # repair round (or a re-extract) would make it three.
    assert len(first.calls) == 2, (
        "the discarded rung spent a repair budget it was never going to use"
    )


def test_with_no_fallback_the_only_rung_still_repairs(tmp_path):
    # The other half of the same rule, reverted separately: one rung is the
    # final rung, so `max_attempts` still buys repair rounds. This is the
    # "nothing configured means today's behaviour" guarantee at the repair level.
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _unparseable(), _good()], model_id="only")

    outcome = run_receipt(png, client, CTX, max_attempts=2)

    assert len(client.calls) == 3, "the sole rung did not get its repair round"
    assert outcome.extraction.merchant.name == "SUPERMART INC."
```

Add the two helpers this needs near the other fixtures in `tests/test_pipeline.py`:

```python
class _RaisingClient(VLMClient):
    """A client whose every call is a transport failure."""

    def __init__(self, model_id: str = "raiser") -> None:
        self.model_id = model_id
        self.calls: list[dict] = []

    def complete_json(self, **kwargs: object) -> VLMResponse:
        self.calls.append(dict(kwargs))
        raise VLMTransientError("the endpoint is unreachable")


def _unparseable() -> str:
    """A scripted response body that will not coerce to ReceiptExtraction."""
    return "not json at all"
```

**Verified against `src/receipts/extract/clients/fake.py`, so `_unparseable` is
correct as written.** That class's own docstring states the contract: "Each
entry is either a model instance (returned as `parsed`), a **string** (treated
as a `parse_error`), or a callable taking the call index." A plain string
therefore yields `parsed=None` with `parse_error` set, which `_evaluate` turns
into a default-constructed `ReceiptExtraction()` — exactly the read-nothing case
Task 2 defines.

**Two ways to get this wrong**, both worth knowing before editing these tests:
scripting *fewer* responses than the run makes calls raises `AssertionError`
("FakeVLMClient exhausted"), which is a test-authoring bug rather than a
parse failure; and a *callable* entry is invoked with the call index, so a
helper that returns a function behaves differently from one that returns a
string.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py`
Expected: FAIL — `run_receipt() got an unexpected keyword argument 'extract_fallback_client'`, plus `AttributeError` on `outcome.extraction` in the tests that expect a `RunOutcome`.

- [ ] **Step 3: Add the dataclasses**

Above `run_receipt` in `pipeline.py`:

```python
@dataclass(frozen=True)
class PassAttempt:
    """One model call's provenance: which pass, which rung, which model, kept or not.

    ``extraction_runs.model_id`` already records the model for every call the
    *service* path makes. The eval path touches no database, so attribution
    travels out through the return value instead.
    """

    pass_name: str
    model_id: str
    rung: int
    kept: bool


@dataclass(frozen=True)
class RunOutcome:
    """What one eval-path run produced, plus who produced it.

    Replaces the ``(extraction, report, triage)`` triple: a fourth positional
    element is where a tuple stops being readable, and this module already uses
    result dataclasses (``ProcessResult``, ``BatchResult``) for the same reason.
    """

    extraction: ReceiptExtraction
    report: ValidationReport
    triage: TriageResult
    attribution: tuple[PassAttempt, ...]
```

- [ ] **Step 4: Implement the ladder**

Replace `run_receipt`'s body (keeping its docstring and updating the "Returns" paragraph to describe `RunOutcome`):

```python
    image = prepare_image(image_path)

    triage_source = triage_client or client
    triage_result, _triage_response = triage(image, triage_source)
    attribution = [
        PassAttempt("triage", triage_source.model_id, rung=0, kept=True)
    ]

    rungs: list[VLMClient] = [client]
    if extract_fallback_client is not None:
        rungs.append(extract_fallback_client)

    outcome = None
    for index, rung in enumerate(rungs):
        is_last = index == len(rungs) - 1
        try:
            candidate = extract_with_repair(
                image,
                rung,
                triage_result=triage_result,
                ctx=ctx,
                # Spec §2.1: a non-final rung is a probe. `extract_with_repair`
                # bundles the extract and its repair rounds into one call, so
                # there is no way to keep a rung first and repair it after --
                # and repairs on a rung that may be discarded are spent
                # re-asking a model that already failed. With no fallback
                # configured there is one rung, it is final, and it gets the
                # configured budget: today's behaviour, unchanged.
                max_repairs=max(0, max_attempts - 1) if is_last else 0,
            )
        except VLMError:
            # The last rung's failure is the run's failure: there is nothing
            # left to fall back to, and swallowing it would report a success
            # nobody achieved.
            if is_last:
                raise
            attribution.append(
                PassAttempt("extract", rung.model_id, rung=index, kept=False)
            )
            continue

        if is_last or not read_nothing(candidate.extraction):
            outcome = candidate
            attribution.append(
                PassAttempt("extract", rung.model_id, rung=index, kept=True)
            )
            break

        attribution.append(
            PassAttempt("extract", rung.model_id, rung=index, kept=False)
        )

    assert outcome is not None  # the last rung either returns or raises

    normalized = normalize(
        outcome.extraction, system_default_currency=default_currency
    )
    return RunOutcome(
        extraction=normalized,
        report=outcome.report,
        triage=triage_result,
        attribution=tuple(attribution),
    )
```

Update the signature:

```python
def run_receipt(
    image_path: Path,
    client: VLMClient,
    ctx: ValidationContext,
    *,
    max_attempts: int = 1,
    default_currency: str | None = None,
    triage_client: VLMClient | None = None,
    extract_fallback_client: VLMClient | None = None,
) -> RunOutcome:
```

Add `VLMError` to the imports from `.extract.clients.base` and `read_nothing` from `.extract.paths`.

**`read_nothing` runs on `outcome.extraction`, before `normalize`.** `normalize` fills `currency` from `DEFAULT_CURRENCY`, and granite's measured output was every field null with `currency: PHP` supplied that way — testing after normalization would read that `PHP` as content the model produced and the fallback would never fire.

- [ ] **Step 5: Update the three existing tests and `build_eval_pipeline`**

In `tests/test_pipeline.py`, the three call sites at `:109`, `:133` and `:145` change from tuple unpacking to attribute access, e.g.:

```python
    outcome = run_receipt(png, client, CTX)
    extraction, report, triage_result = outcome.extraction, outcome.report, outcome.triage
```

In `pipeline.py`'s `build_eval_pipeline`:

```python
        run = run_receipt(
            image_path, client, ctx, default_currency=default_currency
        )
        confidence = score_confidence(
            run.extraction, run.report, run.triage, consistency=None
        )
        return run.extraction, confidence
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py`
Expected: PASS.

- [ ] **Step 7: Prove the fallback pin is real**

Mutate the loop condition to `if is_last or True:` (always keep the first rung) and re-run: `test_the_fallback_runs_when_the_first_rung_reads_nothing` must fail on `fallback.calls`, not on an import error. Revert. Then mutate it to `if False:` and re-run: `test_the_fallback_is_not_called_when_the_first_rung_reads_something` must fail. Revert.

**Confirm the mutated tree still imports each time.**

- [ ] **Step 8: Commit**

```bash
git add src/receipts/pipeline.py tests/test_pipeline.py
git diff --cached --stat
git commit -m "feat(pipeline): an extract ladder on the eval path, with per-rung attribution"
```

---

### Task 6: The egress boundary, enumerated

**Files:**
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `run_receipt`'s new signature (Task 5).
- Produces: nothing — this task is a guarantee, not a component.

**A universal claim is answered by an enumeration, not an argument** (review standard 17). The claim is: no production entry point can construct or pass an extract ladder.

- [ ] **Step 1: Write the failing test**

```python
import inspect

from receipts import pipeline


def test_process_receipt_has_no_ladder_parameter() -> None:
    """The egress boundary, stated over the built signature.

    The user's 2026-08-20 ruling is that a production upload must not be able to
    reach the cloud through the escalation. Every production entry --
    `worker.process_receipt_job` and both `cli.py` call sites -- calls
    `process_receipt`, and the only non-test caller of `run_receipt` is
    `build_eval_pipeline`. So the boundary is that `process_receipt` has no
    parameter to pass a rung through.

    This does NOT claim production cannot reach a cloud model at all: pointing
    the single client at one by configuration was possible before this milestone
    and still is. The claim is only that *this mechanism* is unreachable.
    """
    params = set(inspect.signature(pipeline.process_receipt).parameters)
    for forbidden in ("extract_fallback_client", "triage_client", "extract_rungs"):
        assert forbidden not in params, (
            f"process_receipt grew {forbidden!r}: the escalation is reachable "
            f"from the production path, which the 2026-08-20 ruling forbids"
        )


def test_the_production_modules_do_not_build_a_ladder() -> None:
    """`make_pass_clients` is the only way to get more than one rung, and no
    production module may call it."""
    import receipts.cli
    import receipts.worker

    for module in (receipts.cli, receipts.worker):
        source = inspect.getsource(module)
        assert "make_pass_clients" not in source, (
            f"{module.__name__} constructs a tier ladder"
        )
```

- [ ] **Step 2: Run the tests to verify they pass for the right reason**

Run: `python -m pytest tests/test_pipeline.py -k boundary` — **do not trust this filter**; `-k` matches substrings and neither test name contains "boundary". Run the two node ids instead:

```bash
python -m pytest "tests/test_pipeline.py::test_process_receipt_has_no_ladder_parameter" "tests/test_pipeline.py::test_the_production_modules_do_not_build_a_ladder"
```

Expected: PASS.

- [ ] **Step 3: Prove each guarantee separately**

Add `extract_fallback_client: VLMClient | None = None` to `process_receipt`'s signature and re-run: the first test must fail naming that parameter. Revert. Then add a bare `make_pass_clients` reference inside a docstring in `worker.py` and re-run: the second test must fail. Revert.

**The second mutation is deliberately weak** — it shows the guard reads source text, so a *comment* trips it too. Record that as a known bound rather than tightening it: an AST walk is a new component that can be wrong in new ways.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline.py
git diff --cached --stat
git commit -m "test(pipeline): the escalation is unreachable from the production path"
```

---

### Task 7: Report the rung beside the accuracy

**Files:**
- Modify: `src/receipts/pipeline.py` (`build_eval_pipeline`)
- Modify: `eval/metrics.py` (`EvalReport`)
- Modify: `eval/harness.py:130` (`_report_to_dict`)
- Modify: `eval/run_baseline.py` (`run_baseline`, `format_report`)
- Test: `tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: `RunOutcome.attribution` (Task 5).
- Produces: three new keyword-only parameters on `build_eval_pipeline` — `triage_client: VLMClient | None = None`, `extract_fallback_client: VLMClient | None = None`, `attribution_sink: list[PassAttempt] | None = None` — and `EvalReport.extract_rung_counts: dict[str, int] | None = None`.

**Why counts and not a rate:** ISSUE-001's stated fear is a good accuracy number hiding the fact that everything escalated. A count per rung answers that directly and cannot drift; a percentage is derived and can be computed from a stale denominator.

- [ ] **Step 1: Write the failing test**

```python
from eval.metrics import EvalReport


def test_the_rung_counts_default_to_none_when_unobservable() -> None:
    # Same rule as `cost_per_receipt`: a fact the injected pipeline_fn cannot
    # see stays None rather than defaulting to a number nobody measured.
    report = _minimal_report()
    assert report.extract_rung_counts is None
```

```python
def test_build_eval_pipeline_records_which_rung_was_kept(tmp_path):
    # In tests/test_pipeline.py -- the sink is how attribution leaves the
    # adapter without widening run_eval's PipelineFn contract.
    sink: list = []
    pipeline_fn = build_eval_pipeline(
        FakeVLMClient([_triage(), _good()], model_id="local"),
        CTX,
        images_dir=tmp_path,
        attribution_sink=sink,
    )
    _write_png(tmp_path / "r001.png")
    (tmp_path / "r001.json").write_text("{}", encoding="utf-8")

    pipeline_fn(tmp_path / "r001.json")

    kept = [a for a in sink if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["local"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_eval_metrics.py tests/test_pipeline.py`
Expected: FAIL — `AttributeError: 'EvalReport' object has no attribute 'extract_rung_counts'`, and `build_eval_pipeline() got an unexpected keyword argument 'attribution_sink'`.

- [ ] **Step 3: Add the field and the sink**

In `eval/metrics.py`'s `EvalReport`, beside `cost_per_receipt`:

```python
    #: How many receipts each extract rung produced the kept extraction for,
    #: keyed by model id. ``None`` when unobservable -- the same rule
    #: ``cost_per_receipt`` follows, and for the same reason: the injected
    #: ``pipeline_fn`` cannot see it, so a caller that measures the real
    #: pipeline fills it in.
    extract_rung_counts: dict[str, int] | None = None
```

In `pipeline.py`, `build_eval_pipeline` gains **three** parameters — the sink and
the two rung clients. Without the latter two the ladder built in Task 4 would
never reach a run, which is the "built, tested and never called" shape this repo
already carries deliberately for `few_shots_for` and must not acquire by
accident:

```python
def build_eval_pipeline(
    client: VLMClient,
    ctx: ValidationContext,
    images_dir: Path,
    *,
    image_suffixes: tuple[str, ...] = DEFAULT_IMAGE_SUFFIXES,
    default_currency: str | None = None,
    triage_client: VLMClient | None = None,
    extract_fallback_client: VLMClient | None = None,
    attribution_sink: list[PassAttempt] | None = None,
) -> Callable[[Path], tuple[ReceiptExtraction, Decimal]]:
```

and inside `pipeline_fn`, forward them and drain the attribution:

```python
        run = run_receipt(
            image_path,
            client,
            ctx,
            default_currency=default_currency,
            triage_client=triage_client,
            extract_fallback_client=extract_fallback_client,
        )
        if attribution_sink is not None:
            attribution_sink.extend(run.attribution)
        confidence = score_confidence(
            run.extraction, run.report, run.triage, consistency=None
        )
        return run.extraction, confidence
```

This supersedes the `run_receipt` call written in Task 5 Step 5 — that step
updated the unpack, this one adds the forwarding. Apply this version.

- [ ] **Step 4: Serialize and print it**

In `eval/harness.py`'s `_report_to_dict`, add `"extract_rung_counts": report.extract_rung_counts`.

In `eval/run_baseline.py`, build the ladder, own the sink, and fold the counts
in. **This is the only place the ladder is constructed**, which is what keeps it
on the eval path (design §5).

**`run_baseline` takes an injectable `client`, and that contract must survive.**
Its signature is `run_baseline(golden_dir=None, *, client=None, ctx=None,
results_dir=None, default_currency=None)`, and callers that pass their own
client — tests and scripts — are **not** opting into a ladder. Building the
ladder unconditionally would override an injected client and break them.

Replace the `if client is None:` block and the `build_eval_pipeline` call that
follows it:

```python
    if client is None:
        if settings.vlm_provider.strip().lower() == "fake":
            raise RuntimeError(_FAKE_PROVIDER_HINT)
        tiers = make_pass_clients(settings)
    else:
        # An injected client is one rung, used for every pass -- exactly what
        # this function did before the ladder existed.
        tiers = PassClients(triage=client, extract_rungs=(client,))

    if ctx is None:
        ctx = ValidationContext()

    if default_currency is None:
        default_currency = settings.default_currency

    attribution: list[PassAttempt] = []
    pipeline_fn = build_eval_pipeline(
        tiers.extract_rungs[0],
        ctx,
        golden_dir / "images",
        default_currency=default_currency,
        triage_client=tiers.triage,
        extract_fallback_client=(
            tiers.extract_rungs[1] if len(tiers.extract_rungs) > 1 else None
        ),
        attribution_sink=attribution,
    )
    report = run_eval(golden_dir, pipeline_fn, results_dir=results_dir)

    counts: dict[str, int] = {}
    for entry in attribution:
        if entry.pass_name == "extract" and entry.kept:
            counts[entry.model_id] = counts.get(entry.model_id, 0) + 1
    report.extract_rung_counts = counts or None
    return report
```

Update the import at `eval/run_baseline.py:33` to bring in `make_pass_clients`
and `PassClients` alongside (or instead of) `make_client`, and add `PassAttempt`
to the `receipts.pipeline` import.

**Verified against the tree, so these are not assumptions:** the third
positional argument really is `golden_dir / "images"`; `EvalReport` is a plain
`@dataclass` and **not** frozen, so the `report.extract_rung_counts = ...`
assignment is legal; and the `fake` provider refusal is existing behaviour that
must stay on the `client is None` branch only.

In `format_report`, print the counts **immediately after the accuracy block**, not in a trailing section:

```python
    if report.extract_rung_counts:
        lines.append("  extraction by rung:")
        for model_id, count in sorted(report.extract_rung_counts.items()):
            lines.append(f"    {model_id:32s} {count}")
```

**`EvalReport` is a plain `@dataclass`, not frozen** — verified, so the
assignment above is legal and no `dataclasses.replace` dance is needed. If a
later change freezes it, this line is where that breaks.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_eval_metrics.py tests/test_pipeline.py`
Expected: PASS.

- [ ] **Step 6: Run the whole suite and the gates**

```bash
python -m pytest
python scripts/verify.py   # background it; exceeds a 2-minute tool timeout
```

Expected: all five gates PASS.

- [ ] **Step 7: Commit**

```bash
git add src/receipts/pipeline.py eval/metrics.py eval/harness.py eval/run_baseline.py tests/
git diff --cached --stat
git commit -m "feat(eval): report which rung produced each kept extraction"
```

---

## What this plan does not do

- **It produces no accuracy number.** That is step 6, and it needs repeats and a spread — cloud inference is not deterministic at `temperature=0`.
- **It adds no FK from `receipts` to `extraction_runs`.** The eval path has no database; production provenance is a separate decision.
- **It does not wire `few_shots_for`.** ADR-0043 recorded that deliberately.
- **It does not decide the default ladder.** Whether granite is a real first rung depends on the `max_edge=2048` experiment ISSUE-001 calls the empirical decider, which is outstanding.

## The ADR

An ADR is required and is **not** a task above, because it should record what was built rather than what was planned. Write it at the close, carrying: the per-pass ladder, the trigger predicate and its correction, the move of the grouping into `src`, the egress boundary **with its stated limit**, and the provenance route. It changes what "the provider" means, which ADR-0002 treats as a single runtime choice, and it closes the granularity defect ADR-0002's own 2026-08-18 correction recorded.

## Dated defect log

*(Append here as defects in this plan are found. Every milestone in this repository has found some, and every one was the plan author's.)*

- **2026-08-20, before dispatch:** the spec's original trigger predicate could never have fired. Recorded in the spec's own §3 correction; this plan is written against the corrected version.
- **2026-08-20, before dispatch, RESOLVED:** `_unparseable()` in Task 5 Step 1 was a guess at `FakeVLMClient`'s scripted-response shape. Checked: a string entry *is* treated as a `parse_error`, so the guess was right and the step now states the contract instead of flagging it.
- **2026-08-20, second pre-flight pass, three more:**
  1. **`run_baseline` takes an injectable `client`, and Task 7 would have overridden it.** Its signature is `run_baseline(golden_dir=None, *, client=None, ctx=None, results_dir=None, default_currency=None)`, and tests and scripts pass their own client without opting into a ladder. Building the ladder unconditionally would have broken every one of them. The ladder is now built only on the `client is None` branch, with an injected client wrapped as a single rung.
  2. **The third positional argument to `build_eval_pipeline` is `golden_dir / "images"`**, not a bare `images_dir` — the plan's earlier code named a variable that does not exist at that call site.
  3. **`EvalReport` is not frozen** — checked rather than left as a caveat for the implementer to resolve mid-task.
- **Coverage note, not a defect:** `tests/test_paths.py` does not exist yet; Task 1 creates it. The only existing coverage that touches `paths.py` is `tests/test_eval_floor.py`, which is where a duplicate would otherwise be written.

### Task 1, as executed — five more, all in the plan

Found by the implementer, verified by the controller before acceptance. Task 1
shipped green: `82c1351`, suite 1252 -> 1255, five gates PASS, no existing test
edited.

1. **Step 4's justification for the `_SELF_REPORT_LEAVES` alias named the wrong
   dependency, and following it would have broken a test.** The step said the
   alias matters because of `:data:` docstring references at `:90` and `:203`. A
   docstring reference binds nothing at runtime. The real reader is
   `tests/test_eval_metrics.py:146`, `from eval.metrics import
   _SELF_REPORT_LEAVES, _group`, which the plan never mentions. An implementer
   reasoning from the stated justification would have dropped the import as
   cosmetic.
   **Reproduced by the controller**: alias removed, mutated module confirmed to
   still import, then `test_the_grouping_reads_the_declared_leaf_set_rather_than_names_of_its_own`
   fails with `ImportError`. Restored.
2. **Step 3 said "verbatim" and then supplied a block that was not.** It
   substituted invented prose for the `#:` comment above `_META_PREFIX`. The
   real one states the prefix test is structural *on purpose* — "a list of field
   names would silently let it through (review standard 19 — an enumerated
   defence never converges)" — and the replacement said only where the prefixes
   live. In a task whose whole property is "a move, not a change", the plan
   would have deleted the rationale. Also rendered every em dash as `--`.
   **Verified** against `2de924c:eval/metrics.py`.
3. **Step 4's deletion range orphaned a comment.** It named lines 62-117, but
   the `#:` block documenting `_META_PREFIX`/`_LINE_ITEMS` sits at 56-61, above
   that range. Taken literally it would have survived in `eval/metrics.py`
   describing two constants no longer there. **Verified**: the comment is now in
   `paths.py` and absent from `eval/metrics.py`.
4. **Step 4's import block fails this repo's own ruff gate, two ways.** `I001`,
   because isort here has `combine-as-imports = false` and an aliased member may
   not share a parenthesised statement with a plain one; and `F401`, because
   after the move `_SELF_REPORT_LEAVES` has no *code* reader left in
   `eval/metrics.py`. Shipped as four single-line imports with a `noqa` and a
   comment saying why. Consistent with the ruff gate passing.
5. **Step 2's predicted failure named the wrong symbol** — `group_of`, where
   Python reports the first name in the import list, `SELF_REPORT_LEAVES`.
   Cosmetic, and still a plan claim that was false.

**The shape worth carrying into the remaining tasks:** four of these five are
the plan asserting something about code it had read and summarised. The one that
would have caused real damage is the one where the plan explained *why* a thing
mattered and got the reason wrong — a correct instruction with a false rationale
is more dangerous than a missing one, because it invites an implementer to
"simplify" on the strength of it.

### Task 2, as executed — a never-fires hole in the predicate itself

Task 2 shipped green (`7b1dc3f`, 1255 -> 1259, five gates PASS, both mutations
proven with the mutated tree confirmed importable). Its implementer then
reported a hole **in the spec's definition**, not in their implementation of it,
and it is the dangerous kind.

**`line_items: [{}]` read as content.** `LineItem()` rests at `position=0` and
`description_raw=""`, both of which `is_filled` accepts, so one blank row
compared against a zero-row baseline came out `read_nothing -> False`. The
fallback would not have fired, and no test would have noticed. Reproduced by the
controller before acting on it.

Closed by giving the baseline the same shape as the extraction — same rows, each
mirroring its counterpart's `position`. Spec §3.1 carries the correction, and
four tests were added: the single blank row, blank rows however numbered, the
other direction (a row with one real value is still content), and a pin that the
baseline is non-empty so the comparison cannot silently collapse into the
emptiness form. The first two were proven red before the fix.

**Three plan defects came with it**, all the same species as Task 1's:

1. **Step 1's test block would fail this repo's ruff gate if appended
   literally** — it presents its imports as though the file is new, but Task 1
   created `tests/test_paths.py`, so appending puts imports mid-file and emits
   `E402` three times. Proved by the implementer with `ruff --isolated`, not
   asserted.
2. **Step 4's test count.** The real number was 7. The sentence predicted 6 and
   corrected itself mid-sentence.
3. **Step 5 stated each mutation as if exactly one test fails, and neither
   does.** Mutation A also fails the two Task 1 pins; Mutation B also fails the
   self-report test, because both rest on the same baseline. The property holds;
   the prose was false, and "must fail" read as "only this fails" sends an
   implementer hunting.

**Two rationales were checked and held**: the no-import-cycle claim, and that
`_evaluate` resolves a failed parse to `ReceiptExtraction()` at
`extractor.py:278`. Worth recording — the lesson is to check rationales, not to
assume they are all false.

### Task 6, as executed — the ruling was enforced by prose, and now is not

Task 6 shipped green (`851ef63`, 1276 -> 1278) and its two tests pin what they
say. They pinned **less than the spec claimed.** §5 makes two claims; only the
first was enforced:

| claim | pinned? |
|---|---|
| the ladder is a parameter on `run_receipt`, never on `process_receipt` | yes, test 1 |
| the only non-test caller of `run_receipt` is `build_eval_pipeline` | **nothing** |

**Reproduced by the controller**: a function in `worker.py` calling
`run_receipt(..., extract_fallback_client=...)` left **all sixteen tests green**
and, with the whole suite run, all 1278. Production could reach the ladder.

The implementer **declined to patch it** by adding `"run_receipt"` to the text
guard's string list, correctly: that closes the shape found and re-claims the
class. Closed instead by a follow-up task (`8d88340`) stating one bounded
property — *the non-test call sites of `run_receipt` are exactly
`{build_eval_pipeline}`* — enumerated from the AST. **Controller-verified both
ways**: a real call reddens it naming file, line and enclosing function; a
**comment mentioning `run_receipt` leaves it green**, which is the whole
distinction from the text guard beside it.

**That follow-up found a defect in its own first draft**, via a mutation nobody
asked for: pinning the *inner closure* name meant renaming `pipeline_fn` would
fail with a message accusing the developer of breaking the user's ruling — a
false claim of the ADR-0032 kind, sitting in a failure message where it reads as
authoritative. The tightness protected nothing (anything nested inside
`build_eval_pipeline` is reachable only through it). Reverted to the outermost
enclosing def, and every mutation re-run afterwards.

**Other findings from Task 6:**

- **`**kwargs` defeats a three-name check.** `signature.bind(...)` accepts
  `extract_fallback_client=4` while the plan's assertion passes. Closed with a
  bounded property — the signature stays closed — rather than a longer list.
- **`process_receipt` has four non-test callers, not three.** `process_batch` is
  a fourth. The plan and spec both said three.
- **`scripts/try_one_receipt.py` reaches a model without either function**
  (`make_client` -> `triage` -> `extract_with_repair`). It cannot build a ladder,
  so the ruling holds, but "every production entry calls `process_receipt`" is
  not a complete account of how model calls are made here.
- **The whole Python surface is provably 114 tracked files** — 70 in the five
  source roots, 44 in `tests/`, none elsewhere. Stated with its query, per
  ADR-0028.

**Bound, stated and deliberately not chased:** static reach ends at a name, so
`getattr`, `globals()` and importlib routes pass. The implementer measured
**zero** false positives for a string-literal check across all 70 modules — so
cost was not the reason to decline it; it closes one spelling of a route with
unboundedly many.

**Closed transitively, worth a reviewer's eye:** the `PassClients(...)` route is
not flagged, but is now inert — using a ladder requires `run_receipt` (pinned)
or a `process_receipt` parameter (pinned, no `**kwargs`).

### Task 5, as executed — two lines that were deletable with every gate green

Task 5 shipped green (`114b769`, 1269 -> 1276, five gates PASS). Its implementer
ran **three mutations the plan did not ask for**, and two of them found the
plan's tests leaving real code unpinned.

- **Dropping the failed rung's `PassAttempt`** left the whole suite green with a
  discarded rung erased from the record.
- **Dropping the triage `PassAttempt`** did the same. **Reproduced by the
  controller**: with `attribution` seeded empty the tree still imports and
  exactly one test fails — the one the implementer *strengthened*. Under the
  plan as written, nothing would have caught it. Task 7 folds the eval report's
  per-rung counts out of `attribution`, so this would have shipped a silently
  empty provenance record: the exact figure ISSUE-001 asked for, and the exact
  failure it warned about.

**The repair-budget pin was real but could not print its own message.** Under the
plan's two-response script it reddened on `FakeVLMClient exhausted: call 3 but
only 2 response(s) scripted` rather than on its own assertion. A pin that fails
for the wrong reason is review standard 15's case. Fixed with a deliberately
surplus scripted response that correct behaviour never consumes.

**`assert outcome is not None` cannot fire** — confirmed and left in place with a
comment. `rungs` always holds at least one client, so the loop always runs and
the final rung either raises or assigns. Mutation B proves it from the other
side: removing `is_last or` from the keep condition is what makes it fire.

**Discrepancies (5):** the append-tests species for the **fifth** time, exactly
as predicted, again with `F811`; Step 7's second mutation stated as one failing
test when eleven do, and failing on a different assertion than named; the
repair-budget fixture above; `:287-290` being one line short of the unpack; and
"the three call sites at `:109`, `:133`, `:145`" naming `def` lines rather than
call sites.

**Rationales checked that held: eleven**, including one the plan never states but
both repair tests rest on — that R001 is `Severity.ERROR` (`rules.py:299`),
which is what makes a parse failure buy a repair round at all.

**Open, reported not fixed, for the whole-branch review:** `frozen=True` on
`PassAttempt`, `RunOutcome` **and** `PassClients` is pinned by nothing; and
`PassAttempt.rung` is unpinned for extract rungs — a ladder recording `rung=0`
for every rung would still be green, because Task 7 reads only `pass_name`,
`model_id` and `kept`.

### Task 4, as executed — an assertion that could not fail, and a test that read `.env`

Task 4 shipped green (`f0051d2`, 1266 -> 1269, five gates PASS). Both headline
findings were reproduced by the controller before acceptance.

**D3 — the plan's third assertion could not fail.** Step 1 asserted
`tiers.triage is not tiers.extract_rungs[0]`. `make_client` returns a **fresh**
`FakeVLMClient` on every call, so two calls are always distinct objects and the
assertion held whether or not `VLM_MODEL_TRIAGE` was honoured. Replaced with an
assertion on the resolved model ids. **Reproduced**: with `make_pass_clients`
mutated to ignore the triage model, the tree still imports and the replacement
fails `assert 'extract-model' == 'triage-model'`; the original would have
passed. That is the **fourth** can't-fail assertion in this repository's
history, and the first caught before it landed.

**D2 — the plan's `_settings()` helper read the developer's `.env`.** It omitted
`_env_file=None`, so `Settings(vlm_provider="fake")` resolves
`vlm_model_extract='gemma4:cloud'` and `vlm_use_tools=True` here. "With nothing
configured" was therefore false, and the test passed **only because
`VLM_MODEL_EXTRACT_FALLBACK` happens to be absent from this `.env`** — one line
added there and the pin reddens for reasons unrelated to the code. Four
pre-existing tests in the same file already pass `_env_file=None`; the plan
ignored the file's own convention. **Verified** by the controller.

**D1 — the ruff/import defect, fourth instance**, now with `F811` as well as
`E402` because the plan re-imports `Settings`, which the file already has. The
pattern named after Task 3 held exactly as predicted.

**Rationales checked that held: eight**, including that
`model_copy(update=...)` genuinely takes effect (proven by reading the field
back on the copy, and pinned behaviourally by asserting on both rungs' model ids
rather than on a count, which an ignored update would not have moved).

**Open, reported not fixed:** `PassClients`' `frozen=True` is pinned by nothing —
dropping it leaves all five gates green. A stated interface property with no
test behind it, which is the class ADR-0046 decision 5 and the `_resolve_merchant`
rollback both belong to. Outside Task 4's proof obligations; **for the
whole-branch review.**

### Task 3, as executed — two defects, and five rationales that held

Task 3 shipped green (`a9bc61c`, 1263 -> 1266, five gates PASS). The
"is the refactor cosmetic?" mutation was reproduced by the controller: with
`resolve_use_tools` forced to `True` the tree still imports and **two
pre-existing tests fail** — `test_ollama_provider_disables_tools_by_default` and
`test_explicit_use_tools_overrides_provider_default` — both of which build a
real client through `make_client`. The routing is real.

The implementer went further than asked and established the no-behaviour-change
claim **differentially**: the committed factory loaded side by side with the new
one, compared across the full cross-product of nine provider spellings and three
`vlm_use_tools` values, 27/27 identical including the error branches. That is a
stronger form of proof than this plan asked for and is worth copying.

**Defects (2):**

1. **A test block that would fail the ruff gate if appended literally — the
   third instance of this exact species**, after Task 1 #4 and Task 2 #1. The
   plan writes new-file-style imports into a file that already has an import
   block, giving `E402`. `tests/test_client_factory.py` has no `per-file-ignores`
   entry. **This is now a pattern in the plan, not three accidents:** every task
   that appends tests to an existing file has it, so Tasks 5-7 should be assumed
   to have it too.
2. **Step 3's settings block used Sphinx `#:` comment syntax**, which
   `config/settings.py` uses nowhere — all ~20 of its field comments are plain
   `#`.

**Rationales checked that held (5):** ADR-0002's correction saying the
granularity fix belongs to this milestone; ISSUE-001 telling a reader to set
`VLM_USE_TOOLS=true`; granite losing `merchant_name_guess` with tools on; that
field being ADR-0043 decision 1's key; and the precedence chain being unchanged.

**Reported and correctly not fixed:** `_TOOLS_OFF_BY_DEFAULT`'s comment carries a
pre-existing stale claim — "Ollama returns a hard 400 for a `tools` payload …
that 400 kills the very first (triage) call" — which ADR-0002 and
`docs/KNOWN_ISSUES.md` both now contradict ("does not reproduce"). The 2026-08-18
edit removed the granite half and left this. The same claim also sits in a test
comment. Out of Task 3's scope; belongs with the ADR.

**Controller correction to the implementer's report:** they wrote that §7.2's
trap "is already live on this box". It is not, not harmfully. `.env` here
resolves `vlm_use_tools=True` **and** `vlm_model_triage=gemma4:cloud`, and tools
on is *correct* for that model. The trap arms only when `VLM_MODEL_TRIAGE` moves
to granite without `VLM_USE_TOOLS_TRIAGE=false`. A live flag is not a live
defect.

### Task 2, before dispatch — the same defect species, one task later

**Task 2's Step 3 carried `from .schema import ReceiptExtraction  # local:
avoids an import cycle`. There is no cycle.** Verified structurally:
`src/receipts/extract/schema.py` imports only stdlib and pydantic, and
`src/receipts/extract/__init__.py` is empty, so no route runs from `schema` back
to `paths`.

This was written **into the next task after Task 1 caught the identical
species** — an instruction whose *reason* is invented. It is worth stating
plainly: the author who recorded that lesson then repeated it within the hour,
which is why the defence is a check by whoever runs the code, not the author's
resolve to be careful. Step 3 now specifies a module-level import and says why
there is no cycle.
- **2026-08-20, self-review, three findings:**
  1. **`make_pass_clients` was built in Task 4 and consumed by nothing.** The ladder would have been implemented, tested and never reached by an eval run — the shape this repo carries *deliberately* for `few_shots_for` and would have acquired here by accident. Fixed by giving `build_eval_pipeline` the two rung parameters and switching `run_baseline` from `make_client` to `make_pass_clients`.
  2. **Task 7 Step 4 contained a literal `...` standing in for the `build_eval_pipeline` call.** A placeholder that a keyword scan for "TBD"/"TODO" does not catch. Replaced with the real call, plus an instruction to read the surrounding argument names rather than trust this plan's.
  3. **Spec §9's repair pin had no task, and the plan's code contradicted the spec's rationale** — every rung was given the full repair budget, including rungs about to be discarded. This exposed that the spec's own repair row described a decomposition `extract_with_repair` does not offer. The spec gained §2.1 and the rule became "non-final rungs run with `max_repairs=0`"; two tests were added, reverted separately.
