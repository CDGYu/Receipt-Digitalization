"""Rule runner.

Guarantees, all of which are tested:
  * never mutates the extraction
  * never makes a network call
  * never raises — a rule that throws is recorded as an INFO finding
  * deterministic: same inputs always produce the same report
"""

from __future__ import annotations

import logging

from ..extract.schema import ReceiptExtraction
from .context import RuleConfig, ValidationContext
from .report import Finding, Severity, ValidationReport
from .rules import RULES, Rule

log = logging.getLogger(__name__)

__all__ = [
    "validate",
    "ValidationContext",
    "RuleConfig",
    "ValidationReport",
    "Finding",
    "Severity",
    "RULES",
]


def validate(
    receipt: ReceiptExtraction,
    ctx: ValidationContext | None = None,
) -> ValidationReport:
    """Run every registered rule and collect findings."""
    ctx = ctx or ValidationContext()
    findings: list[Finding] = []

    for rule in RULES:
        try:
            if not rule.applies(receipt, ctx):
                continue
        except Exception as exc:  # a broken applies() must not stop the run
            findings.append(_crash_finding(rule, exc, "applies"))
            continue

        try:
            findings.extend(rule.check(receipt, ctx))
        except Exception as exc:
            findings.append(_crash_finding(rule, exc, "check"))

    return ValidationReport(findings=findings)


def _crash_finding(rule: Rule, exc: Exception, phase: str) -> Finding:
    log.exception("Rule %s crashed in %s()", rule.id, phase)
    return Finding(
        rule_id=f"{rule.id}.crashed",
        severity=Severity.INFO,
        message=f"Rule {rule.id} crashed during {phase}(): {exc!r}",
        context={"rule": rule.id, "phase": phase, "error": repr(exc)},
    )


def rule_catalogue() -> list[dict[str, str]]:
    """Machine-readable list of registered rules. Used by docs and the review UI
    to show a reviewer what a given rule ID means."""
    return [
        {"id": r.id, "severity": r.severity.value, "description": r.description}
        for r in RULES
    ]
