"""Verdict truth table: every combination of floor x gap x proposal x cited (FR-016)."""

from __future__ import annotations

import itertools

import pytest

from vigil.reasoning.verdict import ORDER, compose

FLOORS = ["normal", "noteworthy", "needs_attention"]
GAPS = [False, True]
PROPOSALS = [None, "normal", "noteworthy"]
CITED = [False, True]

# Written out by hand from the FR-016 sentences, not computed from compose():
#  - only a rule (floor) can produce needs_attention;
#  - an unresolved gap with no needs_attention rule gives cant_confirm;
#  - a cited noteworthy proposal may raise normal to noteworthy, never lower anything;
#  - otherwise the floor stands.
# Key: (floor, unresolved_gap, proposal, proposal_cited) -> verdict
N, W, A, C = "normal", "noteworthy", "needs_attention", "cant_confirm"
EXPECTED: dict[tuple[str, bool, str | None, bool], str] = {
    # floor normal, no gap
    (N, False, None, False): N,
    (N, False, None, True): N,
    (N, False, "normal", False): N,
    (N, False, "normal", True): N,
    (N, False, "noteworthy", False): N,  # uncited proposal is ignored
    (N, False, "noteworthy", True): W,  # Wonder raises normal to noteworthy
    # floor normal, unresolved gap
    (N, True, None, False): C,
    (N, True, None, True): C,
    (N, True, "normal", False): C,
    (N, True, "normal", True): C,
    (N, True, "noteworthy", False): C,
    (N, True, "noteworthy", True): C,
    # floor noteworthy (e.g. protected touch with no rule), no gap
    (W, False, None, False): W,
    (W, False, None, True): W,
    (W, False, "normal", False): W,
    (W, False, "normal", True): W,  # Wonder can never lower the floor
    (W, False, "noteworthy", False): W,
    (W, False, "noteworthy", True): W,
    # floor noteworthy, unresolved gap
    (W, True, None, False): C,
    (W, True, None, True): C,
    (W, True, "normal", False): C,
    (W, True, "normal", True): C,
    (W, True, "noteworthy", False): C,
    (W, True, "noteworthy", True): C,
    # floor needs_attention (a rule fired): nothing else matters
    (A, False, None, False): A,
    (A, False, None, True): A,
    (A, False, "normal", False): A,
    (A, False, "normal", True): A,
    (A, False, "noteworthy", False): A,
    (A, False, "noteworthy", True): A,
    (A, True, None, False): A,
    (A, True, None, True): A,
    (A, True, "normal", False): A,
    (A, True, "normal", True): A,
    (A, True, "noteworthy", False): A,
    (A, True, "noteworthy", True): A,
}


def test_truth_table_is_exhaustive() -> None:
    combos = set(itertools.product(FLOORS, GAPS, PROPOSALS, CITED))
    assert set(EXPECTED) == combos
    assert len(combos) == 36


@pytest.mark.parametrize(("args", "expected"), sorted(EXPECTED.items(), key=str))
def test_compose_truth_table(args: tuple, expected: str) -> None:
    assert compose(*args) == expected


@pytest.mark.parametrize(
    ("floor", "gap", "proposal", "cited"), list(itertools.product(FLOORS, GAPS, PROPOSALS, CITED))
)
def test_invariants(floor: str, gap: bool, proposal: str | None, cited: bool) -> None:
    v = compose(floor, gap, proposal, cited)
    assert (v == "needs_attention") == (floor == "needs_attention")
    if v != "cant_confirm":
        assert ORDER[v] >= ORDER[floor]


def test_model_cannot_propose_needs_attention() -> None:
    # Wonder's schema forbids it; even if it slipped through, only rules decide.
    for floor in ("normal", "noteworthy"):
        assert compose(floor, False, "needs_attention", True) == floor
