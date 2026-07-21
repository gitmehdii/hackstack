"""Tests unitaires des fonctions de normalisation (pures, sans DB ni réseau)."""

from __future__ import annotations

from pipeline.load.import_sqlite import LABLAB_MAP, _clean, _dedup, _parse_place
from pipeline.normalize.schema import Project, project_id


def test_project_id_deterministic() -> None:
    assert project_id("lablab", "foo") == project_id("lablab", "foo")


def test_project_id_source_sensitive() -> None:
    assert project_id("lablab", "foo") != project_id("devpost", "foo")


def test_parse_place() -> None:
    assert _parse_place("2nd place") == 2
    assert _parse_place("Best Use of X — 3rd place") == 3
    assert _parse_place("1st place") == 1
    assert _parse_place("Pool Prize — Pool Prize") is None
    assert _parse_place(None) is None
    assert _parse_place("") is None


def test_lablab_map() -> None:
    assert LABLAB_MAP["WINNERS"] == (1, True)
    assert LABLAB_MAP["TOP_2"] == (2, True)
    assert LABLAB_MAP["TOP_3"] == (3, True)
    assert LABLAB_MAP["FINALISTS"] == (None, False)
    assert LABLAB_MAP["OTHER"] == (None, False)


def test_clean() -> None:
    assert _clean("  hi  ") == "hi"
    assert _clean("") is None
    assert _clean("   ") is None
    assert _clean(None) is None


def _proj(pid: str) -> Project:
    return Project(
        id=pid,
        source="lablab",
        source_url="u",
        hackathon_slug="h",
        hackathon_name="H",
        title="t",
    )


def test_dedup_first_wins() -> None:
    a, b, c = _proj("x"), _proj("x"), _proj("y")
    unique, collisions = _dedup([a, b, c])
    assert collisions == 1
    assert {p.id for p in unique} == {"x", "y"}
