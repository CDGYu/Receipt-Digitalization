"""Validation result types.

A Finding's `message` is written to be read by the REPAIR MODEL, not by a
developer. Every arithmetic finding names the specific numbers involved —
a generic "please check your math" does almost nothing.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    ERROR = "error"  # blocks auto-approval, triggers a repair pass
    WARN = "warn"  # reduces confidence, does not block
    INFO = "info"  # recorded only

    @property
    def rank(self) -> int:
        return {"info": 0, "warn": 1, "error": 2}[self.value]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    message: str
    field_paths: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    resolved_by_repair: bool = False

    def render(self) -> str:
        return f"[{self.rule_id}] {self.message}"


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list)

    # ---------------- summary properties ---------------- #

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.WARN)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.INFO)

    @property
    def rule_ids(self) -> list[str]:
        return [f.rule_id for f in self.findings]

    # ---------------- lookups ---------------- #

    def by_rule(self, rule_id: str) -> list[Finding]:
        return [f for f in self.findings if f.rule_id == rule_id]

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    def touching(self, field_path: str) -> list[Finding]:
        """Findings that implicate a given dotted field path."""
        return [f for f in self.findings if field_path in f.field_paths]

    def fired(self, rule_id: str) -> bool:
        return any(f.rule_id == rule_id for f in self.findings)

    # ---------------- rendering ---------------- #

    def render_for_repair_prompt(self, max_findings: int = 12) -> str:
        """Only ERROR and WARN go to the model. INFO is noise that dilutes the
        signal and wastes tokens.

        Findings are ordered most-severe-first and truncated, because a repair
        prompt with thirty complaints performs worse than one with five.
        """
        relevant = [f for f in self.findings if f.severity is not Severity.INFO]
        relevant.sort(key=lambda f: (-f.severity.rank, f.rule_id))
        lines = [f.render() for f in relevant[:max_findings]]
        if len(relevant) > max_findings:
            lines.append(f"... and {len(relevant) - max_findings} further problems.")
        return "\n".join(lines) if lines else "(no problems)"

    def summary(self) -> str:
        return (
            f"{self.error_count} error(s), {self.warn_count} warning(s), "
            f"{self.info_count} info: {', '.join(sorted(set(self.rule_ids))) or 'clean'}"
        )
