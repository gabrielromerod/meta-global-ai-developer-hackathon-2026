"""Determinism (spec 12.1 "Integration: determinism"; NFR-011).

Two runs of the pipeline on the same recorded inputs give byte-identical ``visits.json``,
whatever order the windows arrive in.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from tests.fixtures.scenarios.builders import SCENARIOS, run_golden
from vigil.models import Config, ProtectedObject, Rule
from vigil.pipeline import FLOAT_DIGITS, write_visits_json
from vigil.reasoning.rules import load_rules


@pytest.mark.parametrize("sid", ["A", "B", "C"])
def test_two_runs_give_byte_identical_visits_json(
    sid: str,
    tmp_path: Path,
    sample_config: Config,
    po_side_gate: ProtectedObject,
    rule_r7: Rule,
) -> None:
    rules = [*load_rules(), rule_r7]
    paths = []
    for run in range(2):
        sc = SCENARIOS[sid]()  # fresh fakes and inputs each run
        if run == 1:
            random.Random(7).shuffle(sc.windows)  # arrival order must not matter
        result = run_golden(sc, sample_config, rules, [po_side_gate])
        paths.append(write_visits_json(result, tmp_path / f"run{run}" / "visits.json"))
    a, b = (p.read_bytes() for p in paths)
    assert a == b
    assert a.endswith(b"\n")
    assert b"\r\n" not in a


def test_visits_json_is_canonical(
    tmp_path: Path, sample_config: Config, po_side_gate: ProtectedObject, rule_r7: Rule
) -> None:
    sc = SCENARIOS["C"]()
    result = run_golden(sc, sample_config, [*load_rules(), rule_r7], [po_side_gate])
    path = write_visits_json(result, tmp_path / "visits.json")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    # sorted keys at every level
    assert json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n" == text

    def floats(x):
        if isinstance(x, float):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from floats(v)
        elif isinstance(x, list):
            for v in x:
                yield from floats(v)

    assert all(round(f, FLOAT_DIGITS) == f for f in floats(data))
    assert data["visits"][0]["verdict"] == "needs_attention"
