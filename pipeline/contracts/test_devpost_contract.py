"""Tests de contrat Devpost : invariants sur le parsing de fixtures live figées.

Fixtures capturées poliment (hackathon 'weatherwise-hack'). Ces invariants sont ceux que
le Niveau 1 du mainteneur (Étape 9) revérifiera chaque semaine.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pipeline.scrapers.devpost import (
    _parse_devpost_date,
    parse_gallery,
    parse_hackathon_list,
    parse_software_page,
)

FIXTURES = Path(__file__).parent / "fixtures"
HACKATHONS = json.loads((FIXTURES / "devpost_hackathons.json").read_text(encoding="utf-8"))
GALLERY = (FIXTURES / "devpost_gallery.html").read_text(encoding="utf-8")
SOFTWARE = (FIXTURES / "devpost_software.html").read_text(encoding="utf-8")


def test_hackathon_list_keeps_only_winners_announced() -> None:
    parsed = parse_hackathon_list(HACKATHONS)
    assert parsed, "au moins un hackathon avec gagnants annoncés"
    for hk in parsed:
        assert hk.slug and hk.title
        # slug dérivé du sous-domaine, jamais une URL
        assert "." not in hk.slug and "/" not in hk.slug


def test_devpost_date_formats() -> None:
    assert _parse_devpost_date("Apr 05 - 06, 2024") == date(2024, 4, 6)
    assert _parse_devpost_date("Jun 16 - Jul 16, 2026") == date(2026, 7, 16)
    assert _parse_devpost_date("Mar 3, 2025") == date(2025, 3, 3)
    assert _parse_devpost_date("TBD") is None
    assert _parse_devpost_date(None) is None


def test_gallery_captures_all_and_flags_winners() -> None:
    entries = parse_gallery(GALLERY)
    assert entries, "la gallery doit contenir des entrées"
    winners = [e for e in entries if e.is_winner]
    assert winners, "au moins un gagnant marqué"
    for e in entries:
        assert e.software_slug and "/" not in e.software_slug
        assert e.url.startswith("https://devpost.com/software/")
        assert e.title
        # prize_track seulement pour les gagnants ; jamais pour un non-gagnant
        if not e.is_winner:
            assert e.prize_track is None


def test_gallery_dedups_team_members() -> None:
    for e in parse_gallery(GALLERY):
        if e.team_name:
            names = [n.strip() for n in e.team_name.split(",")]
            assert len(names) == len(set(names))  # pas de doublon


def test_software_page_yields_full_description_repo_and_tech() -> None:
    detail = parse_software_page(SOFTWARE)
    # comble la dette « devpost = short_description seulement » : texte substantiel
    assert detail.description is not None and len(detail.description) > 200
    # champs autrefois jetés, maintenant captés
    assert detail.repo_url and detail.repo_url.startswith("https://github.com/")
    assert detail.tech, "la liste « Built With » doit alimenter le tech brut"
    assert all(t for t in detail.tech)
