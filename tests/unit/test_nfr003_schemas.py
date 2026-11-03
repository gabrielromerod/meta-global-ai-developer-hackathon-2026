"""NFR-003: no identity or biometric fields in the person-related schemas.

The person-related models in ``vigil/models.py`` (track, event, position, subject,
appearance, visit, expected window, check-in), and every model nested inside them, must
have no field whose name or alias **contains** one of the banned stems below. Substring
matching is deliberately strict (``username`` and ``face_id`` both fail); the only
exceptions are listed in ``ALLOWED`` with the reason, and the allowlist itself is checked
so it cannot go stale or hide a new field.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import BaseModel, create_model

from vigil import models

BANNED = (
    "face", "age", "gender", "skin", "ethnic", "race", "height", "gait", "body",
    "measure", "voice", "name",
)  # fmt: skip

PERSON_MODELS: tuple[type[BaseModel], ...] = (
    models.Track,
    models.Event,
    models.Position,
    models.Subject,
    models.Appearance,
    models.Visit,
    models.ExpectedWindow,
    models.CheckIn,
)

ALLOWED: dict[tuple[str, str], str] = {
    ("Appearance", "vehicle_body"): (
        "the vehicle's body style (sedan, suv, pickup, ...), an enum describing a car, "
        "never a person's body or body measurements"
    ),
}


def _nested_models(annotation: object) -> list[type[BaseModel]]:
    """Pydantic models reachable from a field annotation (list[X], X | None, dict[k, X])."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    out: list[type[BaseModel]] = []
    for arg in typing.get_args(annotation):
        out += _nested_models(arg)
    return out


def _closure(roots: tuple[type[BaseModel], ...]) -> list[type[BaseModel]]:
    seen: dict[str, type[BaseModel]] = {}
    stack = list(roots)
    while stack:
        m = stack.pop()
        if m.__name__ in seen:
            continue
        seen[m.__name__] = m
        for f in m.model_fields.values():
            stack += _nested_models(f.annotation)
    return [seen[k] for k in sorted(seen)]


def _field_names(model: type[BaseModel]) -> list[str]:
    names: list[str] = []
    for name, f in model.model_fields.items():
        names.append(name)
        for alias in (f.alias, f.validation_alias, f.serialization_alias):
            if isinstance(alias, str) and alias != name:
                names.append(alias)
    return names


def _violations(roots: tuple[type[BaseModel], ...]) -> list[tuple[str, str, str]]:
    out = []
    for m in _closure(roots):
        for name in _field_names(m):
            for stem in BANNED:
                if stem in name.lower() and (m.__name__, name) not in ALLOWED:
                    out.append((m.__name__, name, stem))
    return out


def test_person_schemas_have_no_identity_fields() -> None:
    assert _violations(PERSON_MODELS) == []


def test_nested_person_schemas_are_checked_too() -> None:
    # Track -> TrackFrame -> Box, Visit -> StorySentence: nested models are in scope.
    names = {m.__name__ for m in _closure(PERSON_MODELS)}
    assert {"TrackFrame", "Box", "StorySentence"} <= names
    assert set(m.__name__ for m in PERSON_MODELS) <= names


def test_allowlist_is_exact_and_still_needed() -> None:
    """Every allowlisted field exists, still matches a banned stem, and has a reason."""
    by_name = {m.__name__: m for m in _closure(PERSON_MODELS)}
    for (model_name, field), reason in ALLOWED.items():
        assert model_name in by_name, f"allowlisted model {model_name} is not person-related"
        assert field in _field_names(by_name[model_name]), f"{model_name}.{field} is gone"
        assert any(s in field.lower() for s in BANNED), f"{model_name}.{field} needs no entry"
        assert reason.strip()


@pytest.mark.parametrize(
    "field",
    ["face_embedding", "age_range", "gender", "skin_tone", "ethnicity", "race",
     "height_cm", "gait_signature", "body_build", "measurements", "voice_print",
     "display_name", "username"],
)  # fmt: skip
def test_checker_catches_a_planted_field(field: str) -> None:
    """The check is not vacuous: a person model with a banned field fails it."""
    model = create_model("PlantedPerson", track_id=(str, ...), **{field: (str | None, None)})
    hits = {n for _, n, _ in _violations((model,))}
    assert hits == {field}
