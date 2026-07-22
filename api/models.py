"""Modèles de réponse (Pydantic). Ils définissent le contrat public de l'API.

Aucun de ces modèles n'expose la description intégrale, le vecteur d'embedding
ni le tsvector : uniquement des métadonnées et un extrait de description.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ProjectSummary(BaseModel):
    """Vue courte d'un projet, pour les listes (palmarès d'un hackathon)."""

    id: str
    source: str
    source_url: str
    title: str
    placement: int | None
    raw_placement: str | None
    is_winner: bool
    prize_track: str | None
    team_name: str | None
    tech_stack: list[str]
    repo_url: str | None
    demo_url: str | None


class ProjectDetail(BaseModel):
    """Vue détaillée d'un projet (page `/project/[id]`)."""

    id: str
    source: str
    source_url: str

    hackathon_slug: str
    hackathon_name: str
    hackathon_date: date | None

    theme_tags: list[str]

    title: str
    description_excerpt: str | None
    is_excerpt_truncated: bool

    placement: int | None
    raw_placement: str | None
    is_winner: bool
    prize_track: str | None

    tech_stack: list[str]
    stack_source: str

    team_size: int | None
    team_name: str | None

    repo_url: str | None
    demo_url: str | None

    scraped_at: datetime


class HackathonAlternative(BaseModel):
    """Autre hackathon partageant le même slug (autre source)."""

    source: str
    slug: str
    name: str
    project_count: int


class HackathonDetail(BaseModel):
    """Vue détaillée d'un hackathon avec son palmarès (page `/hackathon/[slug]`)."""

    source: str
    slug: str
    name: str
    hackathon_date: date | None
    url: str | None
    project_count: int
    projects: list[ProjectSummary]
    # Rempli quand le slug demandé existe sur plusieurs sources : les autres candidats.
    alternatives: list[HackathonAlternative]
