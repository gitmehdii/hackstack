"""Routeur `/search` : recherche hybride vecteur + full-text.

La requête texte est vectorisée à la volée (bge-m3, cf. api/search_encoder) puis fusionnée
avec le full-text par Reciprocal Rank Fusion dans une seule requête SQL (cf. queries/search).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from api.config import excerpt_max_chars
from api.deps import get_conn
from api.excerpt import make_excerpt
from api.models import SearchHit, SearchResponse
from api.queries.search import search_projects
from api.search_encoder import encode_query

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

_ALLOWED_SOURCES = {"lablab", "devpost", "ethglobal"}


def _to_hit(row: dict[str, Any]) -> SearchHit:
    excerpt, _ = make_excerpt(row["description"], row["short_description"], excerpt_max_chars())
    return SearchHit(
        id=row["id"],
        source=row["source"],
        source_url=row["source_url"],
        title=row["title"],
        description_excerpt=excerpt,
        hackathon_slug=row["hackathon_slug"],
        hackathon_name=row["hackathon_name"],
        is_winner=row["is_winner"],
        placement=row["placement"],
        tech_stack=row["tech_stack"],
        theme_tags=row["theme_tags"],
        score=float(row["score"]),
    )


@router.get("/search", response_model=SearchResponse)
async def search(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    q: Annotated[str, Query(min_length=1, max_length=300, description="Requête libre")],
    source: Annotated[list[str] | None, Query(description="Filtre source (répétable)")] = None,
    winners_only: Annotated[bool, Query(description="Ne garder que les projets primés")] = False,
    since: Annotated[date | None, Query(description="hackathon_date >= (inclus)")] = None,
    until: Annotated[date | None, Query(description="hackathon_date <= (inclus)")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    q = q.strip()
    # Filtre source : si `source` est fourni mais ne contient que des valeurs hors
    # taxonomie, on court-circuite à vide (le filtre ne matche rien), plutôt que de le
    # laisser retomber en « aucun filtre » (ce qui renverrait toutes les sources).
    if source is not None:
        sources = [s for s in source if s in _ALLOWED_SOURCES]
        if not sources:
            return SearchResponse(query=q, total=0, hits=[])
    else:
        sources = None

    # Dégradation gracieuse : si l'encodage de la requête échoue (modèle indisponible,
    # OOM…), on retombe sur le full-text seul (search_projects accepte query_vector=None)
    # au lieu de renvoyer un 500.
    try:
        query_vector: list[float] | None = await encode_query(q)
    except Exception:
        logger.warning("encode_query a échoué, repli sur le full-text seul", exc_info=True)
        query_vector = None

    rows = await search_projects(
        conn,
        q,
        query_vector,
        sources=sources,
        winners_only=winners_only,
        since=since,
        until=until,
        limit=limit,
    )
    hits = [_to_hit(r) for r in rows]
    return SearchResponse(query=q, total=len(hits), hits=hits)
