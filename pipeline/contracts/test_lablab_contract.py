"""Tests de contrat lablab : invariants sur le parsing d'une réponse API figée.

Ces invariants sont ceux que le Niveau 1 du mainteneur (Étape 9) revérifiera chaque
semaine sur l'échantillon figé.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.normalize.schema import project_id
from pipeline.scrapers.lablab import ingest_archive, parse_submissions

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "lablab_submissions.json").read_text(encoding="utf-8"))


def test_parses_all_submissions() -> None:
    result = parse_submissions(PAYLOAD)
    assert len(result.projects) == len(PAYLOAD["submissions"])
    assert result.hackathons  # au moins un hackathon dérivé


def test_required_fields_present() -> None:
    for p in parse_submissions(PAYLOAD).projects:
        assert p.source == "lablab"
        assert p.id == project_id("lablab", p.source_url.rsplit("/", 1)[-1])
        assert p.source_url.startswith("https://lablab.ai/p/")
        assert p.title
        assert p.hackathon_slug and p.hackathon_name


def test_event_position_maps_to_winner_flag() -> None:
    by_raw = {p.raw_placement: p for p in parse_submissions(PAYLOAD).projects}
    assert by_raw["WINNERS"].is_winner is True
    assert by_raw["WINNERS"].placement == 1
    assert by_raw["TOP_2"].placement == 2
    assert by_raw["FINALISTS"].is_winner is False
    assert by_raw["FINALISTS"].placement is None


def test_tech_in_becomes_raw_tech() -> None:
    result = parse_submissions(PAYLOAD)
    assert result.raw_techs, "au moins une techno brute attendue"
    for t in result.raw_techs:
        assert t.source == "lablab"
        assert t.tech_name
        # chaque raw_tech pointe vers un projet du lot
        assert t.project_id in {p.id for p in result.projects}


def test_ingest_archive_matches_direct_parse(tmp_path: Path) -> None:
    path = tmp_path / "winners.json"
    path.write_text(json.dumps(PAYLOAD), encoding="utf-8")
    assert len(ingest_archive(path).projects) == len(PAYLOAD["submissions"])
