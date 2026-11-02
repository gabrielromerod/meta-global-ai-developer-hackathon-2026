"""FR-012: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Event, Rule, RuleResult, Visit


def evaluate_rules(visit: Visit, events: list[Event], rules: list[Rule], tz: str) -> RuleResult:
    """Stub."""
    raise NotImplementedError("FR-012 not implemented")
