"""Modèles de réponse (Pydantic). Ils définissent le contrat public de l'API.

Aucun de ces modèles n'expose la description intégrale, le vecteur d'embedding
ni le tsvector : uniquement des métadonnées et un extrait de description.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

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
    "un indicateur, pas comme une conclusion. La normalisation par nombre de prix, idéale, "
    "n'est pas possible ici : le corpus ne contient pas cette information."
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


# --- Trends (Étape 5) -------------------------------------------------------------------

# Statut d'une analyse. On distingue explicitement deux formes d'indisponibilité (le front
# ne les affiche pas pareil) :
#   - "awaiting_date_backfill" : la donnée arrivera au backfill du rescrape (Étape 6).
#   - "unavailable_in_corpus"  : la donnée n'est dans aucune source et le rescrape ne la
#     récupérera peut-être jamais partout — ne rien promettre.
AnalysisStatus = Literal["available", "awaiting_date_backfill", "unavailable_in_corpus"]

# Les analyses temporelles (saturation, cycle de vie) dépendent de `hackathon_date`, NULL
# dans tout le corpus actuel. Elles s'activeront seules quand les dates seront backfillées.
DATE_BACKFILL_NOTE = (
    "Cette analyse dépend de la date de l'événement (hackathon_date), absente du corpus "
    "actuel. Elle sera renseignée par le backfill du rescrape (Étape 6) et l'analyse "
    "s'activera automatiquement à ce moment-là."
)

# La composition d'équipe n'est présente dans aucune source importée — statut distinct du
# simple « en attente » : rien ne garantit que le rescrape la fournisse partout.
TEAM_SIZE_UNAVAILABLE_NOTE = (
    "La taille des équipes (team_size) n'est présente dans aucune des sources importées, et "
    "le rescrape ne la récupérera pas nécessairement partout. Analyse indisponible tant "
    "qu'une source fiable ne fournit pas cette information — ce n'est pas une simple attente "
    "de backfill."
)

# Le corpus est quasi entièrement composé de gagnants (devpost et ethglobal n'ont que des
# gagnants ; les rares non-gagnants viennent tous de lablab). Deux pièges cumulés : (1) le
# lift vaut ~1 par construction, et (2) un test « significatif » ne mesure pas un effet de
# victoire mais un effet de source (les non-gagnants sont d'une seule plateforme, à la
# composition tech différente). Le vrai contraste arrivera avec des non-gagnants variés.
WINNER_STACKS_CAVEAT = (
    "Le corpus est composé à ~99 % de gagnants : la stack « des gagnants » et celle « de "
    "l'ensemble » sont presque identiques, donc le lift est proche de 1. Surtout, les rares "
    "non-gagnants proviennent tous d'une seule source (lablab), à la composition tech "
    "différente : une différence « statistiquement significative » reflète alors cet écart "
    "de source, pas un effet de victoire. À lire comme une base de référence, pas comme une "
    "conclusion — le contraste deviendra interprétable quand le rescrape (Étape 6) ajoutera "
    "des projets non primés sur toutes les sources."
)


class SaturationPoint(BaseModel):
    """Un trimestre : volume et nombre de gagnants (analyse 1)."""

    quarter: str
    count: int
    winner_count: int


class SaturationSeries(BaseModel):
    """Analyse 1 — fréquence d'un thème par trimestre, superposée au taux de victoire.

    `theme` None = tout le corpus. `points` est vide tant que `status` n'est pas
    "available" (dates NULL) ; le contrat reste correct pour l'activation à l'Étape 6.
    """

    status: AnalysisStatus
    note: str
    theme: str | None
    points: list[SaturationPoint]


class LifecycleReport(BaseModel):
    """Analyse 2 — durée de vie d'une tendance : premier trimestre, pic, dernier.

    Vide (statut "awaiting_date_backfill") tant que `hackathon_date` est NULL.
    """

    status: AnalysisStatus
    note: str
    theme: str | None
    first_quarter: str | None
    peak_quarter: str | None
    last_quarter: str | None


class StackLift(BaseModel):
    """Une techno : sur-représentation chez les gagnants vs l'ensemble (analyse 3).

    `winner_share` = P(techno | gagnant), `baseline_share` = P(techno | tout projet).
    `lift` = winner_share / baseline_share (≈ 1 sur le corpus actuel). `p_value` provient
    d'un test z gagnants vs non-gagnants ; None si incalculable (trop peu de non-gagnants).
    """

    name: str
    count: int
    winner_count: int
    loser_count: int
    winner_share: float
    baseline_share: float
    lift: float
    p_value: float | None
    significant: bool | None


class WinningStacks(BaseModel):
    """Analyse 3 — stacks des gagnants vs l'ensemble, avec test statistique.

    Toujours accompagnée de `caveat` (corpus quasi entièrement gagnant).
    """

    status: AnalysisStatus
    note: str
    caveat: str
    theme: str | None
    winners_total: int
    losers_total: int
    projects_total: int
    techs: list[StackLift]


class TeamSizeCorrelation(BaseModel):
    """Analyse 4 — corrélation taille d'équipe / classement. Indisponible dans le corpus."""

    status: AnalysisStatus
    note: str


class ThemeWinRate(BaseModel):
    """Un thème : volume et taux de victoire (analyse 5)."""

    slug: str
    label: str
    project_count: int
    winner_count: int
    win_rate: float | None


class ThemeWinRates(BaseModel):
    """Analyse 5 — thèmes à fort volume et faible taux de victoire.

    `themes` est trié par volume décroissant ; l'interprétation « fort volume / faible taux »
    est portée par l'affichage. `methodology_note` = biais du taux de victoire.
    """

    status: AnalysisStatus
    methodology_note: str
    themes: list[ThemeWinRate]


class TrendsOverview(BaseModel):
    """Charge utile du tableau de bord `/trends` : les cinq analyses, chacune avec son statut.

    Les analyses dont la donnée manque portent un statut explicite et une note, jamais un
    graphe vide sans explication (contrainte PROJECT.md : pas de chiffre biaisé présenté
    comme une conclusion).
    """

    saturation: SaturationSeries
    lifecycle: LifecycleReport
    winning_stacks: WinningStacks
    team_size: TeamSizeCorrelation
    theme_win_rates: ThemeWinRates
