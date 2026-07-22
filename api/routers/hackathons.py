"""Routeur `/hackathons`."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from api.deps import get_conn
from api.models import HackathonAlternative, HackathonDetail, ProjectSummary
from api.queries.hackathons import get_hackathons_by_slug
from api.queries.projects import get_projects_for_hackathon

router = APIRouter(prefix="/hackathons", tags=["hackathons"])


def to_summary(row: dict[str, Any]) -> ProjectSummary:
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


@router.get("/{slug}", response_model=HackathonDetail)
async def read_hackathon(
    slug: str, conn: Annotated[AsyncConnection, Depends(get_conn)]
) -> HackathonDetail:
    candidates = await get_hackathons_by_slug(conn, slug)
    if not candidates:
        raise HTTPException(status_code=404, detail="Hackathon introuvable")

    # Candidat principal : le plus fourni (déjà trié par la requête). Les éventuels
    # autres (même slug, autre source) sont exposés en alternatives.
    main = candidates[0]
    alternatives = [
        HackathonAlternative(
            source=c["source"],
            slug=c["slug"],
            name=c["name"],
            project_count=c["project_count"],
        )
        for c in candidates[1:]
    ]

    project_rows = await get_projects_for_hackathon(conn, main["source"], main["slug"])
    return HackathonDetail(
        source=main["source"],
        slug=main["slug"],
        name=main["name"],
        hackathon_date=main["hackathon_date"],
        url=main["url"],
        project_count=main["project_count"],
        projects=[to_summary(r) for r in project_rows],
        alternatives=alternatives,
    )
