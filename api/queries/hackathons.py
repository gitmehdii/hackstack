"""Requêtes SQL sur `hackathons`.

Le slug n'est pas unique globalement (PK = (source, slug)) : deux slugs du corpus
existent sur deux sources. `get_hackathons_by_slug` renvoie donc *tous* les candidats,
le routeur choisit le principal et expose les autres en `alternatives`.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection


async def get_hackathons_by_slug(conn: AsyncConnection, slug: str) -> list[dict[str, Any]]:
    """Tous les hackathons portant ce slug, avec leur nombre de projets.

    Trié par nombre de projets décroissant : le premier est le candidat principal
    en cas d'ambiguïté (choix déterministe).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT h.source, h.slug, h.name, h.hackathon_date, h.url,
                   count(p.id) AS project_count
            FROM hackathons h
            LEFT JOIN projects p ON p.source = h.source AND p.hackathon_slug = h.slug
            WHERE h.slug = %s
            GROUP BY h.source, h.slug, h.name, h.hackathon_date, h.url
            ORDER BY project_count DESC, h.source ASC
            """,
            (slug,),
        )
        rows = await cur.fetchall()
    return rows  # type: ignore[return-value]
