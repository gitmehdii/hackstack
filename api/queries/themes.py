"""Requêtes SQL sur les thèmes (Étape 4).

Les thèmes vivent dans une taxonomie fermée (pipeline/normalize/themes.yaml) : elle fournit
le libellé et la description ; la base fournit les agrégats (volume, gagnants, stacks). Le
slug est validé contre la taxonomie côté routeur (404 si inconnu).

Le taux de victoire par thème est biaisé (nombre de prix, tracks sponsorisées, cf.
PROJECT.md). Ces requêtes renvoient les chiffres bruts ; l'avertissement méthodologique est
porté par le modèle de réponse. Le pool utilise `dict_row` : les lignes sont des dicts.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def theme_counts(conn: AsyncConnection) -> dict[str, tuple[int, int]]:
    """slug -> (nombre de projets, nombre de gagnants), pour les thèmes présents en base."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT tag, count(*) AS n, count(*) FILTER (WHERE is_winner) AS w
            FROM projects, unnest(theme_tags) AS tag
            GROUP BY tag
            """
        )
        rows = await cur.fetchall()
    return {str(r["tag"]): (int(r["n"]), int(r["w"])) for r in rows}


async def get_theme_stats(conn: AsyncConnection, slug: str) -> tuple[int, int]:
    """(nombre de projets, nombre de gagnants) pour un thème."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) AS n, count(*) FILTER (WHERE is_winner) AS w "
            "FROM projects WHERE theme_tags @> ARRAY[%s]",
            (slug,),
        )
        row = await cur.fetchone()
    return (int(row["n"]), int(row["w"])) if row else (0, 0)


async def get_theme_top_stacks(
    conn: AsyncConnection, slug: str, limit: int = 15
) -> list[dict[str, Any]]:
    """Technologies les plus fréquentes parmi les projets d'un thème."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT tech, count(*) AS n
            FROM projects, unnest(tech_stack) AS tech
            WHERE theme_tags @> ARRAY[%s]
            GROUP BY tech
            ORDER BY n DESC, tech ASC
            LIMIT %s
            """,
            (slug, limit),
        )
        rows = await cur.fetchall()
    return [{"name": str(r["tech"]), "count": int(r["n"])} for r in rows]


async def get_projects_for_theme(
    conn: AsyncConnection, slug: str, limit: int = 60
) -> list[dict[str, Any]]:
    """Projets d'un thème, gagnants d'abord (pour l'affichage de la page /theme)."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, source, source_url, title, placement, raw_placement,
                   is_winner, prize_track, team_name, tech_stack, repo_url, demo_url
            FROM projects
            WHERE theme_tags @> ARRAY[%s]
            ORDER BY is_winner DESC, placement ASC NULLS LAST, title ASC
            LIMIT %s
            """,
            (slug, limit),
        )
        rows = await cur.fetchall()
    return rows  # type: ignore[return-value]
