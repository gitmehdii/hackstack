"""Statistiques agrégées légères pour la page d'accueil."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection


async def get_stats(conn: AsyncConnection) -> dict[str, Any]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                (SELECT count(*) FROM projects)                     AS projects,
                (SELECT count(*) FROM projects WHERE is_winner)     AS winners,
                (SELECT count(*) FROM hackathons)                   AS hackathons,
                (SELECT count(DISTINCT source) FROM projects)       AS sources
            """
        )
        row = await cur.fetchone()
    assert row is not None
    return row  # type: ignore[return-value]
