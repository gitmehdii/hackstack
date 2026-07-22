"""Routeur `/themes` (Étape 4).

Source de vérité des thèmes : la taxonomie fermée (pipeline/normalize/themes.yaml), qui
donne libellé et description. La base fournit les agrégats. Un slug absent de la taxonomie
renvoie 404, même s'il n'apparaît pas (encore) en base — l'index reste complet et stable.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from api.deps import get_conn
from api.models import (
    WIN_RATE_BIAS_NOTE,
    ProjectSummary,
    StackCount,
    ThemeDetail,
    ThemeListResponse,
    ThemeSummary,
)
from api.queries.themes import (
    get_projects_for_theme,
    get_theme_stats,
    get_theme_top_stacks,
    theme_counts,
)
from pipeline.normalize.taxonomy import load_taxonomy

router = APIRouter(prefix="/themes", tags=["themes"])


def _to_summary(row: dict[str, Any]) -> ProjectSummary:
    return ProjectSummary(
        id=row["id"],
        source=row["source"],
        source_url=row["source_url"],
        title=row["title"],
        placement=row["placement"],
        raw_placement=row["raw_placement"],
        is_winner=row["is_winner"],
        prize_track=row["prize_track"],
        team_name=row["team_name"],
        tech_stack=row["tech_stack"],
        repo_url=row["repo_url"],
        demo_url=row["demo_url"],
    )


@router.get("", response_model=ThemeListResponse)
async def list_themes(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> ThemeListResponse:
    tax = load_taxonomy()
    counts = await theme_counts(conn)
    summaries = [
        ThemeSummary(
            slug=t.slug,
            label=t.label,
            description=t.description,
            project_count=counts.get(t.slug, (0, 0))[0],
            winner_count=counts.get(t.slug, (0, 0))[1],
        )
        for t in tax.themes
    ]
    # Les plus fournis d'abord ; à volume égal, ordre alphabétique du libellé.
    summaries.sort(key=lambda s: (-s.project_count, s.label))
    return ThemeListResponse(themes=summaries)


@router.get("/{slug}", response_model=ThemeDetail)
async def read_theme(slug: str, conn: Annotated[AsyncConnection, Depends(get_conn)]) -> ThemeDetail:
    theme = load_taxonomy().theme(slug)
    if theme is None:
        raise HTTPException(status_code=404, detail="Thème inconnu")

    project_count, winner_count = await get_theme_stats(conn, slug)
    win_rate = winner_count / project_count if project_count else None
    top_stacks = await get_theme_top_stacks(conn, slug)
    project_rows = await get_projects_for_theme(conn, slug)

    return ThemeDetail(
        slug=theme.slug,
        label=theme.label,
        description=theme.description,
        project_count=project_count,
        winner_count=winner_count,
        win_rate=win_rate,
        top_stacks=[StackCount(**s) for s in top_stacks],
        projects=[_to_summary(r) for r in project_rows],
        methodology_note=WIN_RATE_BIAS_NOTE,
    )
