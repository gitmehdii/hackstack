"""Routeur `/stats` : quelques chiffres pour la page d'accueil."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel

from api.deps import get_conn
from api.queries.stats import get_stats

router = APIRouter(prefix="/stats", tags=["stats"])


class Stats(BaseModel):
    projects: int
    winners: int
    hackathons: int
    sources: int


@router.get("", response_model=Stats)
async def read_stats(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> Stats:
    row = await get_stats(conn)
    return Stats(**row)
