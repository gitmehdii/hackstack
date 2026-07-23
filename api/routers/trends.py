"""Routeur `/trends` (Étape 5) : les cinq analyses de tendances + note méthodologique.

Contrat PROJECT.md : `/trends/saturation?theme=` et `/trends/stacks?theme=&winners_only=`,
plus un tableau de bord agrégé `/trends` qui bundle les cinq analyses (comme `/themes/{slug}`
bundle tout ce dont la page a besoin).

Principe directeur de l'étape : ne jamais présenter un chiffre biaisé comme une conclusion.
Chaque analyse porte un statut explicite. Deux formes d'indisponibilité sont distinguées —
« en attente du backfill des dates » (Étape 6) et « donnée absente du corpus » (team_size,
que le rescrape ne récupérera peut-être jamais). Les analyses calculables sont livrées avec
leur note de biais.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from api.deps import get_conn
from api.models import (
    DATE_BACKFILL_NOTE,
    TEAM_SIZE_UNAVAILABLE_NOTE,
    WIN_RATE_BIAS_NOTE,
    WINNER_STACKS_CAVEAT,
    AnalysisStatus,
    LifecycleReport,
    SaturationPoint,
    SaturationSeries,
    StackLift,
    TeamSizeCorrelation,
    ThemeWinRate,
    ThemeWinRates,
    TrendsOverview,
    WinningStacks,
)
from api.queries.trends import (
    date_coverage,
    stack_winner_vs_rest,
    theme_saturation,
    theme_win_rates,
)
from api.stats_test import two_proportion_ztest
from pipeline.normalize.taxonomy import load_taxonomy

router = APIRouter(prefix="/trends", tags=["trends"])

# Nombre de technos renvoyées par l'analyse des stacks, et seuil de rareté.
_STACK_LIMIT = 25
_STACK_MIN_COUNT = 5


def _validate_theme(theme: str | None) -> None:
    """404 si un thème est fourni mais absent de la taxonomie fermée (source de vérité)."""
    if theme is not None and load_taxonomy().theme(theme) is None:
        raise HTTPException(status_code=404, detail="Thème inconnu")


async def _temporal_rows(
    conn: AsyncConnection, theme: str | None
) -> tuple[AnalysisStatus, list[dict[str, Any]] | None]:
    """Lecture temporelle partagée par les analyses 1 et 2 (une seule fois par requête).

    Renvoie (statut, lignes). `None` = dates absentes (statut "awaiting_date_backfill") ;
    saturation et cycle de vie dérivent tous deux de ce résultat, sans re-compter les dates
    ni ré-agréger les trimestres.
    """
    with_date, _ = await date_coverage(conn)
    if with_date == 0:
        return "awaiting_date_backfill", None
    return "available", await theme_saturation(conn, theme)


def _saturation_from(
    status: AnalysisStatus, rows: list[dict[str, Any]] | None, theme: str | None
) -> SaturationSeries:
    if rows is None:
        return SaturationSeries(status=status, note=DATE_BACKFILL_NOTE, theme=theme, points=[])
    return SaturationSeries(
        status="available",
        note="Volume par trimestre et part de gagnants.",
        theme=theme,
        points=[SaturationPoint(**r) for r in rows],
    )


def _lifecycle_from(
    status: AnalysisStatus, rows: list[dict[str, Any]] | None, theme: str | None
) -> LifecycleReport:
    if rows is None:
        return LifecycleReport(
            status=status,
            note=DATE_BACKFILL_NOTE,
            theme=theme,
            first_quarter=None,
            peak_quarter=None,
            last_quarter=None,
        )
    if not rows:
        return LifecycleReport(
            status="available",
            note="Aucun projet daté pour ce périmètre.",
            theme=theme,
            first_quarter=None,
            peak_quarter=None,
            last_quarter=None,
        )
    peak = max(rows, key=lambda r: int(r["count"]))
    return LifecycleReport(
        status="available",
        note="Premier trimestre observé, trimestre de pic (volume max) et dernier trimestre.",
        theme=theme,
        first_quarter=str(rows[0]["quarter"]),
        peak_quarter=str(peak["quarter"]),
        last_quarter=str(rows[-1]["quarter"]),
    )


async def _build_saturation(conn: AsyncConnection, theme: str | None) -> SaturationSeries:
    status, rows = await _temporal_rows(conn, theme)
    return _saturation_from(status, rows, theme)


async def _build_winning_stacks(
    conn: AsyncConnection, theme: str | None, winners_only: bool
) -> WinningStacks:
    data = await stack_winner_vs_rest(conn, theme, _STACK_MIN_COUNT, winners_only)
    total = int(data["total"])
    winners = int(data["winners"])
    losers = int(data["losers"])

    techs: list[StackLift] = []
    for t in data["techs"][:_STACK_LIMIT]:
        wc, lc, n = int(t["winner_count"]), int(t["loser_count"]), int(t["count"])
        winner_share = wc / winners if winners else 0.0
        baseline_share = n / total if total else 0.0
        lift = winner_share / baseline_share if baseline_share else 0.0
        # Test z : proportion de la techno chez les gagnants vs chez les non-gagnants.
        z = two_proportion_ztest(wc, winners, lc, losers)
        techs.append(
            StackLift(
                name=str(t["name"]),
                count=n,
                winner_count=wc,
                loser_count=lc,
                winner_share=winner_share,
                baseline_share=baseline_share,
                lift=lift,
                p_value=z.p_value,
                significant=z.significant,
            )
        )

    note = "Fréquence des technos chez les gagnants comparée à l'ensemble, avec test z."
    caveat = WINNER_STACKS_CAVEAT
    if winners_only:
        note = "Fréquence des technos parmi les seuls projets gagnants."
        # Pas de groupe de comparaison ici : le caveat gagnants-vs-ensemble ne s'applique pas.
        caveat = (
            "Vue restreinte aux gagnants : simple classement de popularité des technos, sans "
            "comparaison à un groupe non-gagnant — le lift vaut 1 et le test n'est pas "
            "calculé. Pour un contraste, utiliser la vue par défaut (winners_only=false)."
        )
    return WinningStacks(
        status="available",
        note=note,
        caveat=caveat,
        theme=theme,
        winners_total=winners,
        losers_total=losers,
        projects_total=total,
        techs=techs,
    )


async def _build_theme_win_rates(conn: AsyncConnection) -> ThemeWinRates:
    tax = load_taxonomy()
    labels = {t.slug: t.label for t in tax.themes}
    rows = await theme_win_rates(conn)
    themes = [
        ThemeWinRate(
            slug=str(r["slug"]),
            label=labels.get(str(r["slug"]), str(r["slug"])),
            project_count=int(r["project_count"]),
            winner_count=int(r["winner_count"]),
            win_rate=(int(r["winner_count"]) / int(r["project_count"]))
            if int(r["project_count"])
            else None,
        )
        for r in rows
    ]
    return ThemeWinRates(status="available", methodology_note=WIN_RATE_BIAS_NOTE, themes=themes)


def _team_size_section() -> TeamSizeCorrelation:
    # Statut distinct de « awaiting » : la donnée n'existe dans aucune source (cf. STATE.md).
    return TeamSizeCorrelation(status="unavailable_in_corpus", note=TEAM_SIZE_UNAVAILABLE_NOTE)


@router.get("", response_model=TrendsOverview)
async def read_trends(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> TrendsOverview:
    # Le temporel (dates + agrégation par trimestre) est lu une seule fois et partagé entre
    # les analyses 1 et 2, plutôt que recalculé par chacune.
    status, rows = await _temporal_rows(conn, None)
    return TrendsOverview(
        saturation=_saturation_from(status, rows, None),
        lifecycle=_lifecycle_from(status, rows, None),
        winning_stacks=await _build_winning_stacks(conn, None, winners_only=False),
        team_size=_team_size_section(),
        theme_win_rates=await _build_theme_win_rates(conn),
    )


@router.get("/saturation", response_model=SaturationSeries)
async def read_saturation(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    theme: Annotated[str | None, Query()] = None,
) -> SaturationSeries:
    _validate_theme(theme)
    return await _build_saturation(conn, theme)


@router.get("/stacks", response_model=WinningStacks)
async def read_stacks(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    theme: Annotated[str | None, Query()] = None,
    winners_only: Annotated[bool, Query()] = False,
) -> WinningStacks:
    _validate_theme(theme)
    return await _build_winning_stacks(conn, theme, winners_only)
