"""Shared fixtures (integrator-owned). Synthetic scenarios A, B and C build on these.

Workstream tests may add their own fixtures in their own files; changes here go through
the integrator so every module agrees on the same cameras, objects and rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vigil.models import ActiveWindow, Box, Config, ProtectedObject, Rule, RuleTarget

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_config() -> Config:
    """The sample config/cameras.yaml parsed straight into the contract (no loader logic)."""
    raw = yaml.safe_load((REPO_ROOT / "config" / "cameras.yaml").read_text(encoding="utf-8"))
    return Config.model_validate(raw)


@pytest.fixture
def po_side_gate() -> ProtectedObject:
    """The protected side gate from scenario C (UC-06)."""
    return ProtectedObject(
        id="po_side_gate",
        camera_id="side_left",
        label="side gate",
        bbox=Box(x1=800, y1=400, x2=880, y2=660),
    )


@pytest.fixture
def rule_r7() -> Rule:
    """Owner rule r7 from spec 9.4: anyone touches the side gate 22:00 to 06:00."""
    return Rule(
        id="r7",
        name="Side gate after 10 PM",
        target=RuleTarget(kind="protected_object", id="po_side_gate"),
        trigger="touch",
        active=ActiveWindow(start="22:00", end="06:00"),
        severity="needs_attention",
    )
