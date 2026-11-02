"""Contract tests for vigil.models and the package skeleton."""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from pydantic import ValidationError

import vigil
from vigil.models import (
    Appearance,
    Box,
    Config,
    ModelCall,
    StoryDraft,
)


def test_every_module_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(vigil.__path__, "vigil.")]
    assert len(names) > 40
    for name in names:
        importlib.import_module(name)


def test_sample_config_parses(sample_config: Config) -> None:
    assert {c.id for c in sample_config.cameras} == {"front", "side_left", "side_right", "backyard"}
    assert sample_config.camera("side_left").lines["side_gate"]
    assert sample_config.blind_regions[0].id == "shed_back"
    assert any(e.from_ == "shed_back" for e in sample_config.topology)


def test_box_iou() -> None:
    a = Box(x1=0, y1=0, x2=10, y2=10)
    assert a.iou(a) == pytest.approx(1.0)
    assert a.iou(Box(x1=5, y1=0, x2=15, y2=10)) == pytest.approx(50 / 150)
    assert a.iou(Box(x1=20, y1=20, x2=30, y2=30)) == 0.0


def test_appearance_has_no_sensitive_fields() -> None:
    banned = {"face", "age", "gender", "sex", "skin", "ethnicity", "race"}
    assert not banned & set(Appearance.model_fields)
    with pytest.raises(ValidationError):
        Appearance.model_validate({"tag": "T1", "class": "person", "gender": "x"})
    with pytest.raises(ValidationError):
        Appearance.model_validate({"tag": "T1", "class": "person", "upper_color": "chartreuse"})


def test_contributor_models_forbidden() -> None:
    with pytest.raises(ValidationError):
        ModelCall(id="c1", model="muse-spark-1.3-contributor", purpose="x", req_hash="h")


def test_story_proposal_cannot_be_needs_attention() -> None:
    with pytest.raises(ValidationError):
        StoryDraft.model_validate({"verdict_proposal": "needs_attention", "sentences": []})


def test_cli_help() -> None:
    from typer.testing import CliRunner

    from vigil.cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "spatial" in result.output
