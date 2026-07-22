"""Tests du constructeur de filtres de la recherche hybride (fonction pure, sans DB)."""

from __future__ import annotations

from datetime import date

from api.queries.search import _build_filters


def test_no_filters() -> None:
    sql, params = _build_filters(None, False, None, None)
    assert sql == ""
    assert params == {}


def test_sources_and_winners() -> None:
    sql, params = _build_filters(["lablab", "ethglobal"], True, None, None)
    assert sql.startswith("AND ")
    assert "source = ANY(%(sources)s)" in sql
    assert "is_winner" in sql
    assert params == {"sources": ["lablab", "ethglobal"]}


def test_winners_only_has_no_bound_param() -> None:
    # `is_winner` est une condition booléenne directe : aucune valeur à lier.
    sql, params = _build_filters(None, True, None, None)
    assert sql == "AND is_winner"
    assert params == {}


def test_date_bounds() -> None:
    sql, params = _build_filters(None, False, date(2024, 1, 1), date(2024, 12, 31))
    assert "hackathon_date >= %(since)s" in sql
    assert "hackathon_date <= %(until)s" in sql
    assert params == {"since": date(2024, 1, 1), "until": date(2024, 12, 31)}


def test_clauses_joined_with_and() -> None:
    sql, _ = _build_filters(["devpost"], True, date(2024, 1, 1), None)
    # Trois conditions -> préfixe "AND " + deux séparateurs " AND " internes.
    assert sql.startswith("AND ")
    assert sql.count(" AND ") == 2
    assert sql.count("%(") == 2  # sources + since (winners n'a pas de param)
