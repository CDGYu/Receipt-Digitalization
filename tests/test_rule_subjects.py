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
Where it cannot account for the context at all it raises, so the one thing it
never does is answer with a silent partial set.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap

import pytest

import receipts.validate.rules as rules_module
from receipts.validate.context import (
    REVIEW_RECONSTRUCTIBLE,
    ValidationContext,
    unreconstructible_context,
)
from receipts.validate.rules import RULES, Subject

#: ``ctx`` attributes that are methods rather than fields, mapped to the fields
#: they read. Pinned below, so a new method reddens rather than sneaking past.
CTX_METHODS = {"tol": {"config"}}

FIELDS = {f.name for f in dataclasses.fields(ValidationContext)}


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _annotates_context(annotation: object) -> bool:
    """True when a parameter is annotated ``ValidationContext``.

    ``rules.py`` uses ``from __future__ import annotations``, so what
    :func:`inspect.signature` hands back is the SOURCE STRING, not the class.
    """
    if annotation is ValidationContext:
        return True
    return isinstance(annotation, str) and annotation.rsplit(".", 1)[-1] == "ValidationContext"


def _context_parameter(fn) -> str:
    """The name ``fn`` binds the context to.

    By annotation, falling back to the name ``ctx`` for an unannotated
    parameter -- every rule method is ``(self, r, ctx)`` and annotates none of
    them. **Never by position.** Reading the last parameter is what let
    ``def helper(ctx, r)`` hide every read inside it. Zero candidates or two
    raise rather than guessing.
    """
    parameters = inspect.signature(fn).parameters
    named = [
        name
        for name, parameter in parameters.items()
        if _annotates_context(parameter.annotation)
        or (parameter.annotation is inspect.Parameter.empty and name == "ctx")
    ]
    if len(named) != 1:
        raise AssertionError(
            f"{fn.__qualname__}{inspect.signature(fn)} has {len(named)} parameters "
            f"this scan can identify as the ValidationContext ({named}), not one. "
            f"Annotate it, or name it ``ctx``."
        )
    return named[0]


def _bound_parameter(fn, target: int | str) -> str:
    """The parameter of ``fn`` that the argument at ``target`` binds to.

    The call site decides, not the callee's shape, so a helper that takes the
    context first is followed as correctly as one that takes it last.
    """
    parameters = list(inspect.signature(fn).parameters.values())
    positional_kinds = (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    if isinstance(target, int):
        positional = [p for p in parameters if p.kind in positional_kinds]
        if target >= len(positional):
            raise AssertionError(
                f"the context is argument {target} of {fn.__qualname__}"
                f"{inspect.signature(fn)}, which this scan cannot map to a parameter."
            )
        return positional[target].name
    named = {
        p.name
        for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    if target not in named:
        raise AssertionError(
            f"the context is keyword {target!r} of {fn.__qualname__}"
            f"{inspect.signature(fn)}, which has no such parameter."
        )
    return target


def _context_arguments(call: ast.Call, ctx_name: str) -> list[tuple[int | str, ast.Name]]:
    """Each argument of ``call`` that is the bare context, as (target, node).

    ``target`` is the argument's index or its keyword. Only a **bare** ``Name``
    in a position this scan can map is returned: a context inside a starred
    list, a ``**`` mapping, or any argument after a starred one has no single
    parameter to bind to, so it is left unexplained and :func:`_ctx_reads`
    raises on it.
    """
    found: list[tuple[int | str, ast.Name]] = []
    for index, argument in enumerate(call.args):
        if isinstance(argument, ast.Starred):
            break
        if isinstance(argument, ast.Name) and argument.id == ctx_name:
            found.append((index, argument))
    for keyword in call.keywords:
        if (
            keyword.arg is not None
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == ctx_name
        ):
            found.append((keyword.arg, keyword.value))
    return found


def _ctx_reads(fn, _seen: frozenset[str] = frozenset(), ctx_name: str | None = None) -> set[str]:
    """Every ``ValidationContext`` field ``fn`` can read.

    One property, and every mention of the context has to satisfy it: **it is
    either read as ``ctx.field``, or handed to a module-level helper as an
    argument this scan can map to a parameter -- and anything else raises.**
    Aliasing it, starring it, unpacking it, returning it, or handing it to
    something unfollowable is an error, never a zero.

    That single rule is deliberately not a list of known bad shapes. A partial
    answer is the whole danger -- a read this scan cannot see certifies a RUN
    rule as CONTENT -- so the scan must account for the context everywhere it
    appears, and a shape nobody has thought of fails the accounting like any
    other.
    """
    if fn.__qualname__ in _seen:
        return set()
    _seen = _seen | {fn.__qualname__}

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    ctx_name = ctx_name or _context_parameter(fn)
    reads: set[str] = set()
    explained: set[int] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == ctx_name
        ):
            explained.add(id(node.value))
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
        elif isinstance(node, ast.Call):
            for target, argument in _context_arguments(node, ctx_name):
                helper = getattr(rules_module, _callee(node) or "", None)
                if helper is None or not inspect.isfunction(helper):
                    raise AssertionError(
                        f"{fn.__qualname__} hands the bare context to "
                        f"{_callee(node)!r}, which this scan cannot follow. An "
                        f"unfollowable helper is how a RUN rule gets certified "
                        f"as CONTENT."
                    )
                explained.add(id(argument))
                reads |= _ctx_reads(helper, _seen, _bound_parameter(helper, target))

    unexplained = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == ctx_name and id(node) not in explained
    ]
    if unexplained:
        raise AssertionError(
            f"{fn.__qualname__} mentions the context at line {unexplained[0].lineno} of "
            f"its own source without reading a field off it or passing it as a mappable "
            f"argument -- aliased, starred, unpacked or returned. This scan cannot see "
            f"through that, and a read it cannot see is how a RUN rule gets certified "
            f"as CONTENT."
        )
    return reads


# --------------------------------------------------------------------------- #
# The scan's own contract, on synthetic rules. Every shape below returned an
# empty set and raised nothing while the scan named the context by position and
# looked only at ``call.args`` -- reading NOTHING, silently, which is exactly
# how a RUN rule gets certified as CONTENT.
# --------------------------------------------------------------------------- #


def _nowhere(*args, **kwargs) -> bool:
    """A callee absent from ``rules_module``, so the scan cannot follow it."""
    return False


def _by_keyword(r, ctx) -> bool:
    return _nowhere(ctx=ctx)


def _aliased(r, ctx) -> bool:
    c = ctx
    return bool(c.ocr_text)


def _starred(r, ctx) -> bool:
    return _nowhere(*[ctx])


def _unpacked(r, ctx) -> bool:
    return _nowhere(**{"ctx": ctx})


def _after_starred(r, ctx) -> bool:
    return _nowhere(*[r], ctx)


def _returned(r, ctx) -> ValidationContext:
    return ctx


def _context_first(ctx, r) -> bool:
    """A helper taking the context FIRST -- what a positional guess lost."""
    return bool(ctx.ocr_text)


def _calls_context_first(r, ctx) -> bool:
    return _context_first(ctx, r)


def _calls_context_first_by_keyword(r, ctx) -> bool:
    return _context_first(ctx=ctx, r=r)


@pytest.mark.parametrize(
    "shape",
    [_by_keyword, _aliased, _starred, _unpacked, _after_starred, _returned],
    ids=lambda fn: fn.__name__,
)
def test_a_context_binding_this_scan_cannot_account_for_is_an_error(shape) -> None:
    """The fail-safe half: an unaccountable binding raises, never returns.

    These are six shapes of one property, not six rules. The scan explains
    every mention of the context or refuses to answer, so a sixth shape nobody
    has written yet fails the same accounting.
    """
    with pytest.raises(AssertionError):
        _ctx_reads(shape)


@pytest.mark.parametrize(
    "caller",
    [_calls_context_first, _calls_context_first_by_keyword],
    ids=lambda fn: fn.__name__,
)
def test_a_followable_helper_is_read_wherever_the_context_sits(caller, monkeypatch) -> None:
    """The other half: a binding the scan CAN map must actually be followed.

    The parameter comes from the call site, so ``_grounded(ctx, r)`` is read as
    exactly as ``expects_a_buyer(ctx)``. Raising here instead would be safe and
    useless -- it would reject a legal helper for the position of its arguments.
    """
    monkeypatch.setattr(rules_module, "_context_first", _context_first, raising=False)
    assert _ctx_reads(caller) == {"ocr_text"}


def test_the_context_parameter_is_found_by_name_not_by_position() -> None:
    """The same for an entry point, which has no call site to be read from."""
    assert _ctx_reads(_context_first) == {"ocr_text"}


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_a_content_rule_reads_no_unreconstructible_context(rule) -> None:
    """The binding. A CONTENT rule must answer from the persisted receipt alone."""
    if rule.subject is not Subject.CONTENT:
        return
    unsafe = unreconstructible_context() & (
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
    assert declared == {"R001", "R013", "R060", "R061", "R070", "R071"}
