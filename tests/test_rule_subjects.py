"""Every rule's declared subject, checked against what it actually reads.

A rule may be re-run on a corrected receipt only if it can answer from the
persisted receipt alone. Rules that read the extraction RUN -- the raw OCR text,
the triage result, the repeated-run agreement, the JSON parse error -- cannot: a
review route rebuilds the receipt from the ``receipts`` and ``line_items`` tables
(``review.serializers._export_extraction``), and none of that evidence is a
column on either, so a re-run at review time sees it absent.

**Declared and then bound, never declared alone.** A hand-kept list of
"review-safe rules" drifts the moment a rule is added. The scan below is what
makes the declaration a property.

**Static, and therefore over-reporting.** It counts a ``ctx`` read on a branch
that may never execute. A dynamic recording proxy would under-report -- it sees
only the branches a fixture reaches -- and under-reporting means certifying a
rule that then lies to a reviewer. Over-reporting costs coverage and never lies.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap

import pytest

import receipts.validate.rules as rules_module
from receipts.validate.context import REVIEW_RECONSTRUCTIBLE, ValidationContext
from receipts.validate.rules import RULES, Subject

#: ``ctx`` attributes that are methods rather than fields, mapped to the fields
#: they read. Pinned below, so a new method reddens rather than sneaking past.
CTX_METHODS = {"tol": {"config"}}

FIELDS = {f.name for f in dataclasses.fields(ValidationContext)}


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _ctx_reads(fn, _seen: frozenset[str] = frozenset()) -> set[str]:
    """Every ``ValidationContext`` field ``fn`` can read.

    Follows the bare context into module-level helpers. **An unfollowable
    callable raises** rather than returning a partial answer: a helper this
    scan cannot see into is exactly the hole it exists to close, and a silent
    pass there would certify a rule nobody checked.
    """
    if fn.__qualname__ in _seen:
        return set()
    _seen = _seen | {fn.__qualname__}

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    ctx_name = list(inspect.signature(fn).parameters)[-1]
    reads: set[str] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == ctx_name
        ):
            if node.attr in FIELDS:
                reads.add(node.attr)
            elif node.attr in CTX_METHODS:
                reads |= CTX_METHODS[node.attr]
            else:
                raise AssertionError(
                    f"{fn.__qualname__} reads ctx.{node.attr}, which is neither a "
                    f"ValidationContext field nor a method in CTX_METHODS. Teach "
                    f"this scan what it reads, or the subject below is a guess."
                )
        if isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id == ctx_name:
                    helper = getattr(rules_module, _callee(node) or "", None)
                    if helper is None or not inspect.isfunction(helper):
                        raise AssertionError(
                            f"{fn.__qualname__} hands the bare context to "
                            f"{_callee(node)!r}, which this scan cannot follow. An "
                            f"unfollowable helper is how a RUN rule gets certified "
                            f"as CONTENT."
                        )
                    reads |= _ctx_reads(helper, _seen)
    return reads


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_a_content_rule_reads_no_unreconstructible_context(rule) -> None:
    """The binding. A CONTENT rule must answer from the persisted receipt alone."""
    if rule.subject is not Subject.CONTENT:
        return
    unsafe = (FIELDS - REVIEW_RECONSTRUCTIBLE) & (
        _ctx_reads(type(rule).applies) | _ctx_reads(type(rule).check)
    )
    assert not unsafe, (
        f"{rule.id} is declared CONTENT but reads {sorted(unsafe)}, which a review "
        f"route cannot reconstruct. Declare it Subject.RUN, or persist what it reads."
    )


def test_the_unsafe_set_is_the_complement_and_not_a_literal() -> None:
    """A context field added later must be unsafe by DEFAULT.

    Taking the complement is the whole mechanism: a field that nobody thought
    about is unreconstructible until somebody deliberately says otherwise. A
    written-out unsafe list would silently admit it instead.
    """
    from receipts.validate.context import unreconstructible_context

    assert unreconstructible_context() == FIELDS - REVIEW_RECONSTRUCTIBLE
    assert REVIEW_RECONSTRUCTIBLE <= FIELDS, (
        "the allow-list names a field ValidationContext does not have: "
        f"{sorted(REVIEW_RECONSTRUCTIBLE - FIELDS)}"
    )


def test_every_ctx_method_a_rule_calls_is_one_this_scan_knows() -> None:
    """``CTX_METHODS`` is small and must stay honest.

    ``ctx.tol(...)`` reads ``config`` and nothing else. A second method added to
    ValidationContext and called from a rule reddens the scan itself (it raises)
    rather than being counted as reading nothing.
    """
    method_names = {
        name
        for name, member in inspect.getmembers(ValidationContext, inspect.isfunction)
        if not name.startswith("_")
    }
    assert method_names == set(CTX_METHODS), (
        f"ValidationContext's public methods are {sorted(method_names)} but this "
        f"scan knows {sorted(CTX_METHODS)}. Map the new one to the fields it reads."
    )
    tol_src = textwrap.dedent(inspect.getsource(ValidationContext.tol))
    read = {
        node.attr
        for node in ast.walk(ast.parse(tol_src))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert read == CTX_METHODS["tol"], f"ctx.tol reads {sorted(read)}, not config alone"


def test_the_run_rules_are_exactly_those_reading_unreconstructible_context() -> None:
    """Stated both ways so neither side can drift alone.

    ``test_a_content_rule_reads_no_unreconstructible_context`` derives one
    direction from the code: nothing declared CONTENT may read run-only context.
    This pins the other by id, so a rule cannot be moved into the RUN set -- or
    registered already in it -- without saying so here.

    R013 is here and its subject is genuinely content -- "at least one line item
    was extracted". Its ``applies()`` reads ``ctx.triage`` to suppress the rule
    when triage expected zero items, and without triage it would fire on a
    receipt that legitimately has none. Marking it RUN loses a check; marking it
    CONTENT ships a rule that fires wrongly. The loss is deliberate and recorded
    here.
    """
    declared = {rule.id for rule in RULES if rule.subject is Subject.RUN}
    assert declared == {"R001", "R013", "R060", "R061", "R070"}
