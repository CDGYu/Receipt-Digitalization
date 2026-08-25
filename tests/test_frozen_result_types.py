"""`frozen=True` is a stated interface property, pinned once over a set.

ISSUE-014. Measured 2026-08-21, one mutation at a time: **dropping
`frozen=True` from `PassAttempt`, `RunOutcome` or `PassClients` left the whole
suite green — `1291 passed` on all three runs.** More broadly,
`git grep "dataclass(frozen=True)" -- src eval` found declarations and
`git grep FrozenInstanceError -- tests` found none. Immutability was a promise
the declarations made and nothing checked.

## Why this is two tests and not eleven

The issue names the trap directly: ten near-identical
`pytest.raises(FrozenInstanceError)` tests are the enumerated defence of review
standard 19, and the list grows with the eleventh dataclass anyone declares.
What converges is **one bounded property enforced at both ends**:

* every type named below actually refuses mutation — which catches
  `frozen=True` being *removed*;
* the names below are exactly the frozen dataclasses the tree declares — which
  catches a new one being *added* and left unguarded.

**Either half alone is a hole, and the second half is the non-obvious one.** A
set derived by scanning the source would look rigorous and catch nothing:
delete `frozen=True` from a class and it simply drops out of the derived set,
leaving the test green on the exact mutation it exists to fail. So the set is
stated here, by import, and the scan is what audits the statement.

**No count is written in this docstring on purpose.** The number of frozen
dataclasses moves whenever anyone declares one — the issue's own "10", measured
2026-08-21, is already wrong — and a count in prose is a second thing to
maintain that guards nothing the assertions do not.
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from eval.metrics import FieldBreakdown
from receipts.export.xlsx import ReceiptExportRow
from receipts.extract.clients.factory import PassClients
from receipts.persist.repository import _PlannedChange
from receipts.pipeline import BatchResult, PassAttempt, ProcessResult, RunOutcome
from receipts.progress import ProgressEvent
from receipts.review.auth import SessionUser
from receipts.review.queue import QueueStats

#: The types whose immutability is part of what they promise a caller.
#:
#: Stated by import rather than discovered, for the reason in the module
#: docstring: a discovered set cannot notice a type leaving it. **A new
#: `@dataclass(frozen=True)` anywhere under `src/` or `eval/` must be added
#: here**, and the second test below is what says so rather than a convention
#: anyone has to remember.
FROZEN_RESULT_TYPES = (
    FieldBreakdown,
    ReceiptExportRow,
    PassClients,
    _PlannedChange,
    PassAttempt,
    RunOutcome,
    ProcessResult,
    BatchResult,
    ProgressEvent,
    SessionUser,
    QueueStats,
)

_ROOT = Path(__file__).resolve().parents[1]
_TREES = ("src", "eval")

#: `@dataclass(frozen=True)` and the class it decorates. Tolerates other
#: decorators and blank lines between the two, which is why it is not a
#: two-line match.
_FROZEN_DECL = re.compile(
    r"@dataclass\(\s*frozen\s*=\s*True\s*\)(?:\s*@\w[\w.]*(?:\([^)]*\))?)*\s*"
    r"class\s+(\w+)",
    re.MULTILINE,
)


def _declared_frozen_names() -> set[str]:
    """Every frozen dataclass the tree declares, by class name.

    A source scan rather than an import-and-introspect sweep: importing every
    module under `src/` to look at it would drag the optional extras several
    of them guard against, and this file must stay runnable without them.
    """
    found: set[str] = set()
    for tree in _TREES:
        for path in sorted((_ROOT / tree).rglob("*.py")):
            found |= set(_FROZEN_DECL.findall(path.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("cls", FROZEN_RESULT_TYPES, ids=lambda c: c.__name__)
def test_a_result_type_refuses_mutation(cls: type) -> None:
    """The declaration, checked by doing the thing it forbids.

    `object.__new__` sidesteps `__init__` deliberately: a frozen dataclass
    raises from `__setattr__` whatever state the instance is in, so this needs
    no valid constructor arguments for eleven different types — and a fixture
    per type is the maintenance the enumerated version would have carried.
    """
    instance = object.__new__(cls)
    with pytest.raises(FrozenInstanceError):
        instance.pinned_by_issue_014 = "no"


def test_the_named_set_is_every_frozen_dataclass_in_the_tree() -> None:
    """The other end: a frozen dataclass nobody named would go unguarded.

    Compares the stated set against what `src/` and `eval/` actually declare.
    Equality, not containment, and both directions have a distinct meaning:

    * declared but not named — a new frozen type arrived and no test covers it;
    * named but not declared — the name here is stale, or the type stopped
      being frozen and the parametrised test above is the louder failure.
    """
    declared = _declared_frozen_names()
    assert declared, (
        "no `@dataclass(frozen=True)` found under src/ or eval/ -- the scan is "
        "broken, and every assertion in this module would pass vacuously"
    )

    named = {cls.__name__ for cls in FROZEN_RESULT_TYPES}
    assert named == declared, (
        f"declared frozen but not named in FROZEN_RESULT_TYPES: "
        f"{sorted(declared - named)}; named here but not declared frozen in the "
        f"tree: {sorted(named - declared)}"
    )
