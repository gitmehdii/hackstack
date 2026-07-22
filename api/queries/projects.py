"""Requêtes SQL sur `projects`. On sélectionne explicitement les colonnes exposées :
jamais `embedding` ni `fts`, et la `description` intégrale ne sort que pour être
transformée en extrait côté service.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

# Colonnes de la vue détaillée. `description` est lue ici mais n'est jamais renvoyée
# telle quelle par l'API — elle sert à fabriquer l'extrait (cf. api/excerpt.py).
_DETAIL_COLUMNS = """
    id, source, source_url,
    hackathon_slug, hackathon_name, hackathon_date,
    theme_tags,
    title, description, short_description,
    placement, raw_placement, is_winner, prize_track,
    tech_stack, stack_source,
    team_size, team_name,
    repo_url, demo_url,
    scraped_at
"""

# Colonnes de la vue courte (palmarès).
_SUMMARY_COLUMNS = """
    id, source, source_url, title,
    placement, raw_placement, is_winner, prize_track,
    team_name, tech_stack, repo_url, demo_url
"""


async def get_project(conn: AsyncConnection, project_id: str) -> dict[str, Any] | None:
    async with conn.cursor() as cur:
        await cur.execute(
            f"SELECT {_DETAIL_COLUMNS} FROM projects WHERE id = %s",  # noqa: S608 (constante interne)
            (project_id,),
        )
        row = await cur.fetchone()
    return row  # type: ignore[return-value]


async def get_projects_for_hackathon(
    conn: AsyncConnection, source: str, slug: str
) -> list[dict[str, Any]]:
    """Palmarès : projets d'un hackathon, gagnants d'abord puis meilleur placement."""
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {_SUMMARY_COLUMNS}
            FROM projects
            WHERE source = %s AND hackathon_slug = %s
            ORDER BY
                is_winner DESC,
                placement ASC NULLS LAST,
                title ASC
            """,  # noqa: S608 (constante interne)
            (source, slug),
        )
        rows = await cur.fetchall()
    return rows  # type: ignore[return-value]
