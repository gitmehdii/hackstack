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


class SearchHit(BaseModel):
    """Un résultat de recherche : une vue courte du projet + le score de fusion.

    `score` est le score de Reciprocal Rank Fusion (sans unité, croissant = plus
    pertinent), fourni pour le tri et le débogage, pas pour un affichage brut.
    """

    id: str
    source: str
    source_url: str
    title: str
    description_excerpt: str | None
    hackathon_slug: str
    hackathon_name: str
    is_winner: bool
    placement: int | None
    tech_stack: list[str]
    score: float


class SearchResponse(BaseModel):
    """Réponse de `/search` : la requête normalisée et les résultats ordonnés."""

    query: str
    total: int
    hits: list[SearchHit]


class SimilarProject(BaseModel):
    """Projet voisin (page projet, section « projets similaires »).

    `distance` est la distance cosine (0 = identique, 2 = opposé) issue de pgvector.
    """

    id: str
    source: str
    source_url: str
    title: str
    hackathon_slug: str
    hackathon_name: str
    is_winner: bool
    placement: int | None
    tech_stack: list[str]
    distance: float


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


# Avertissement méthodologique porté par toute réponse exposant un taux de victoire par
# thème (contrainte PROJECT.md : ne jamais présenter un chiffre biaisé comme une conclusion).
WIN_RATE_BIAS_NOTE = (
    "Le taux de victoire par thème est biaisé : il dépend du nombre de prix et des tracks "
    "sponsorisées de chaque événement, pas seulement de la qualité des projets. À lire comme "
    "un indicateur, pas comme une conclusion. Normalisation par prix prévue à l'Étape 5."
)


class StackCount(BaseModel):
    """Une techno et son nombre d'occurrences dans un thème."""

    name: str
    count: int


class ThemeSummary(BaseModel):
    """Vue courte d'un thème pour l'index (`/themes`)."""

    slug: str
    label: str
    description: str
    project_count: int
    winner_count: int


class ThemeListResponse(BaseModel):
    """Réponse de `/themes` : la taxonomie complète avec les volumes observés."""

    themes: list[ThemeSummary]


class ThemeDetail(BaseModel):
    """Vue détaillée d'un thème (page `/theme/[slug]`).

    `win_rate` est la part de gagnants (0–1) ou None si le thème n'a aucun projet. Toujours
    accompagné de `methodology_note` : le chiffre est biaisé (cf. WIN_RATE_BIAS_NOTE).
    """

    slug: str
    label: str
    description: str
    project_count: int
    winner_count: int
    win_rate: float | None
    top_stacks: list[StackCount]
    projects: list[ProjectSummary]
    methodology_note: str
