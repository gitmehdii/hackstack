"""Tests de l'export dataset (invariant légal : jamais le texte intégral)."""

from __future__ import annotations

import pytest

from pipeline.export.dataset import (
    DERIVED_COLUMNS,
    FORBIDDEN_COLUMNS,
    HACKATHON_COLUMNS,
    HACKATHON_SCHEMA,
    PROJECT_COLUMNS,
    PROJECT_SCHEMA,
    check_columns,
    render_card,
)

_STATS = {
    "version": "2026q3",
    "exported_at": "2026-07-25",
    "n_projects": 21027,
    "n_hackathons": 812,
    "n_embeddings": 21027,
    "pct_date": 0,
    "pct_theme": 85,
    "pct_embedding": 100,
}


def test_published_columns_contain_no_free_text() -> None:
    check_columns(PROJECT_COLUMNS)


@pytest.mark.parametrize("column", sorted(FORBIDDEN_COLUMNS))
def test_forbidden_column_is_rejected(column: str) -> None:
    with pytest.raises(ValueError, match=column):
        check_columns((*PROJECT_COLUMNS, column))


def test_declared_schema_matches_selected_columns() -> None:
    # Le schéma parquet est déclaré à la main : il doit suivre la liste des colonnes SQL,
    # sinon `_fetch` échoue seulement au moment de l'export, contre la base.
    assert list(PROJECT_SCHEMA) == [*PROJECT_COLUMNS, *DERIVED_COLUMNS]
    assert list(HACKATHON_SCHEMA) == list(HACKATHON_COLUMNS)


def test_card_states_license_and_sources() -> None:
    card = render_card(_STATS)
    assert card.startswith("---\nlicense: cc-by-sa-4.0\n")
    for source in ("lablab.ai", "Devpost", "ETHGlobal"):
        assert source in card


def test_card_reports_coverage_figures() -> None:
    card = render_card(_STATS)
    assert "21027 projets" in card
    assert "812 hackathons" in card
    assert "2026q3" in card
