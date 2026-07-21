"""Schéma unifié des projets et fonctions d'identité.

Ce module est la source de vérité pour la forme d'un projet normalisé, indépendamment
de la source. Les scrapers et l'import produisent des `Project` ; le load les écrit
en staging.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Source = Literal["lablab", "devpost", "ethglobal"]
StackSource = Literal["github", "llm", "scraped", "none"]


def project_id(source: str, slug: str) -> str:
    """Identifiant déterministe d'un projet : sha256(source:slug).

    Déterministe pour que les rescrapes mettent à jour au lieu de dupliquer.
    """
    digest = hashlib.sha256(f"{source}:{slug}".encode()).hexdigest()
    return digest


@dataclass(slots=True)
class Hackathon:
    source: Source
    slug: str
    name: str
    hackathon_date: date | None = None
    url: str | None = None


@dataclass(slots=True)
class Project:
    id: str
    source: Source
    source_url: str

    hackathon_slug: str
    hackathon_name: str
    hackathon_date: date | None = None

    theme_tags: list[str] = field(default_factory=list)

    title: str = ""
    description: str | None = None
    short_description: str | None = None

    placement: int | None = None
    raw_placement: str | None = None
    is_winner: bool = False
    prize_track: str | None = None

    tech_stack: list[str] = field(default_factory=list)
    stack_source: StackSource = "none"

    team_size: int | None = None
    team_name: str | None = None

    repo_url: str | None = None
    demo_url: str | None = None

    scraped_at: datetime = field(default_factory=lambda: datetime.now())


@dataclass(slots=True)
class RawTech:
    """Tag technologique brut, non normalisé (préservé pour l'Étape 4)."""

    project_id: str
    source: Source
    tech_name: str
    tech_slug: str | None = None
