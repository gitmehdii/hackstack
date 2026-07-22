"""Routeur `/projects`."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from api.config import excerpt_max_chars
from api.deps import get_conn
from api.excerpt import make_excerpt
from api.models import ProjectDetail, SimilarProject
from api.queries.projects import get_project, get_similar_projects

router = APIRouter(prefix="/projects", tags=["projects"])


def to_detail(row: dict[str, Any]) -> ProjectDetail:
    excerpt, truncated = make_excerpt(
        row["description"], row["short_description"], excerpt_max_chars()
    )
    return ProjectDetail(
        id=row["id"],
        source=row["source"],
        source_url=row["source_url"],
        hackathon_slug=row["hackathon_slug"],
        hackathon_name=row["hackathon_name"],
        hackathon_date=row["hackathon_date"],
        theme_tags=row["theme_tags"],
        title=row["title"],
        description_excerpt=excerpt,
        is_excerpt_truncated=truncated,
        placement=row["placement"],
        raw_placement=row["raw_placement"],
        is_winner=row["is_winner"],
        prize_track=row["prize_track"],
        tech_stack=row["tech_stack"],
        stack_source=row["stack_source"],
        team_size=row["team_size"],
        team_name=row["team_name"],
        repo_url=row["repo_url"],
        demo_url=row["demo_url"],
        scraped_at=row["scraped_at"],
    )


@router.get("/{project_id}", response_model=ProjectDetail)
async def read_project(
    project_id: str, conn: Annotated[AsyncConnection, Depends(get_conn)]
) -> ProjectDetail:
    row = await get_project(conn, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return to_detail(row)


def to_similar(row: dict[str, Any]) -> SimilarProject:
    return SimilarProject(
        id=row["id"],
        source=row["source"],
        source_url=row["source_url"],
        title=row["title"],
        hackathon_slug=row["hackathon_slug"],
        hackathon_name=row["hackathon_name"],
        is_winner=row["is_winner"],
        placement=row["placement"],
        tech_stack=row["tech_stack"],
        distance=float(row["distance"]),
    )


@router.get("/{project_id}/similar", response_model=list[SimilarProject])
async def read_similar(
    project_id: str,
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=24)] = 6,
) -> list[SimilarProject]:
    # Pas de 404 : un projet sans voisin (embedding absent) renvoie une liste vide,
    # ce qui laisse la page projet masquer proprement la section.
    rows = await get_similar_projects(conn, project_id, limit)
    return [to_similar(r) for r in rows]
