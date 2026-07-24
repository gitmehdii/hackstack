"""Tests de contrat ETHGlobal : invariants sur le parsing RSC de fixtures live figées.

L'invariant clé : `event.startTime` produit une `hackathon_date` — la donnée que
`/trends` (Étape 5) attend pour allumer les analyses temporelles. Invariants revérifiés
chaque semaine par le Niveau 1 du mainteneur (Étape 9).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pipeline.scrapers.ethglobal import (
    _parse_start_date,
    extract_rsc_payloads,
    parse_listing,
    parse_project,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHOWCASE = (FIXTURES / "ethglobal_showcase.html").read_text(encoding="utf-8")
PROJECT = (FIXTURES / "ethglobal_project.html").read_text(encoding="utf-8")
# Projet dont la description est une *référence* RSC ("$28"), pas du texte inline.
PROJECT_REF_DESC = (FIXTURES / "ethglobal_project_ref_desc.html").read_text(encoding="utf-8")


def test_rsc_payloads_extracted() -> None:
    assert len(extract_rsc_payloads(SHOWCASE)) > 0


def test_listing_captures_all_projects_with_prize_flag() -> None:
    listing = parse_listing(SHOWCASE)
    assert listing, "le showcase doit lister des projets"
    for item in listing:
        assert item.uuid and item.slug and item.name
        assert isinstance(item.has_prizes, bool)
    # au moins un projet primé (les gagnants) est marqué
    assert any(item.has_prizes for item in listing)


def test_project_has_event_date() -> None:
    p = parse_project(PROJECT)
    assert p is not None
    # invariant central de l'Étape 6 : la date d'événement est présente
    assert p.event_date is not None
    assert isinstance(p.event_date, date)
    assert p.event_slug and p.event_name


def test_project_winner_and_repo() -> None:
    p = parse_project(PROJECT)
    assert p is not None
    assert p.is_winner is True  # présent dans le showcase = au moins un prix
    assert p.prize_track  # libellé de prix
    assert "\\u" not in (p.prize_track or "")  # unicode dé-échappé
    if p.repo_url:
        assert p.repo_url.startswith("http")


def test_project_has_description() -> None:
    p = parse_project(PROJECT)
    assert p is not None and p.description
    assert len(p.description) > 80


def test_reference_description_resolves_to_text() -> None:
    # Le champ description vaut "$28" (référence RSC) : on doit résoudre le vrai texte,
    # jamais laisser fuiter la référence brute.
    p = parse_project(PROJECT_REF_DESC)
    assert p is not None and p.description
    assert not p.description.startswith("$")
    assert len(p.description) > 200


def test_parse_start_date_iso_forms() -> None:
    assert _parse_start_date("2026-06-12T00:00:00.000Z") == date(2026, 6, 12)
    assert _parse_start_date("2024-11-15") == date(2024, 11, 15)
    assert _parse_start_date(None) is None
    assert _parse_start_date("not-a-date") is None
