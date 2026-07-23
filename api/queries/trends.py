"""Requêtes SQL agrégées pour les Trends (Étape 5).

Chaque fonction renvoie des chiffres bruts (dicts, pool en `dict_row`). L'assemblage en
modèles de réponse, l'application des seuils statistiques et le choix des statuts
(disponible / en attente du backfill des dates / indisponible dans le corpus) vivent dans
le routeur. On ne présente jamais un chiffre biaisé comme une conclusion (cf. PROJECT.md) :
les notes méthodologiques accompagnent les analyses concernées.

État des données à l'Étape 5 (voir STATE.md) :
  - `hackathon_date` NULL partout → analyses temporelles (saturation, cycle de vie) vides,
    activées automatiquement au backfill de l'Étape 6.
  - `team_size` NULL partout → corrélation équipe/classement indisponible.
  - corpus quasi entièrement gagnant (~99 %) → lift des stacks gagnantes ≈ 1, à lire avec
    la note de biais.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def date_coverage(conn: AsyncConnection) -> tuple[int, int]:
    """(projets avec date, projets totaux) — décide si les analyses temporelles sont prêtes."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT count(*) FILTER (WHERE hackathon_date IS NOT NULL) AS d, count(*) AS n "
            "FROM projects"
        )
        row = await cur.fetchone()
    return (int(row["d"]), int(row["n"])) if row else (0, 0)


async def theme_saturation(conn: AsyncConnection, theme: str | None) -> list[dict[str, Any]]:
    """Analyse 1 — volume par trimestre + taux de victoire, pour un thème (ou tout le corpus).

    Requête correcte dès que `hackathon_date` sera renseignée (Étape 6) ; renvoie une liste
    vide tant que les dates sont NULL. Le filtre thème est optionnel (None = corpus entier).
    """
    where = "WHERE hackathon_date IS NOT NULL"
    params: list[Any] = []
    if theme is not None:
        where += " AND theme_tags @> ARRAY[%s]"
        params.append(theme)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            SELECT
                to_char(date_trunc('quarter', hackathon_date), 'YYYY"Q"Q') AS quarter,
                count(*) AS n,
                count(*) FILTER (WHERE is_winner) AS w
            FROM projects
            {where}
            GROUP BY date_trunc('quarter', hackathon_date)
            ORDER BY date_trunc('quarter', hackathon_date)
            """,
            params,
        )
        rows = await cur.fetchall()
    return [
        {"quarter": str(r["quarter"]), "count": int(r["n"]), "winner_count": int(r["w"])}
        for r in rows
    ]


async def theme_win_rates(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Analyse 5 — par thème : volume, gagnants, taux de victoire. Trié par volume décroissant.

    Le taux de victoire est biaisé (nombre de prix, tracks sponsorisées, corpus quasi
    entièrement gagnant). Le routeur y attache la note de biais ; l'interprétation
    « fort volume / faible taux » est laissée à l'affichage.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT tag AS slug, count(*) AS n, count(*) FILTER (WHERE is_winner) AS w
            FROM projects, unnest(theme_tags) AS tag
            GROUP BY tag
            ORDER BY n DESC, tag ASC
            """
        )
        rows = await cur.fetchall()
    return [
        {"slug": str(r["slug"]), "project_count": int(r["n"]), "winner_count": int(r["w"])}
        for r in rows
    ]


async def stack_winner_vs_rest(
    conn: AsyncConnection, theme: str | None, min_count: int, winners_only: bool = False
) -> dict[str, Any]:
    """Analyse 3 — par techno : comptes chez les gagnants, non-gagnants et l'ensemble.

    Renvoie aussi les totaux (gagnants / non-gagnants / ensemble) nécessaires au test z.
    Le filtre thème est optionnel. `min_count` écarte les technos trop rares pour être lues.
    `winners_only` restreint la population aux seuls gagnants (l'ensemble devient les gagnants).
    """
    where = "WHERE array_length(tech_stack, 1) > 0"
    params: list[Any] = []
    if theme is not None:
        where += " AND theme_tags @> ARRAY[%s]"
        params.append(theme)
    if winners_only:
        where += " AND is_winner"

    async with conn.cursor(row_factory=dict_row) as cur:
        # Totaux : dénominateurs des proportions (projets ayant au moins une techno).
        await cur.execute(
            f"""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE is_winner) AS winners,
                count(*) FILTER (WHERE NOT is_winner) AS losers
            FROM projects
            {where}
            """,
            params,
        )
        totals = await cur.fetchone()

        await cur.execute(
            f"""
            SELECT tech,
                   count(*) AS n,
                   count(*) FILTER (WHERE is_winner) AS w,
                   count(*) FILTER (WHERE NOT is_winner) AS l
            FROM projects, unnest(tech_stack) AS tech
            {where}
            GROUP BY tech
            HAVING count(*) >= %s
            ORDER BY count(*) DESC, tech ASC
            """,
            [*params, min_count],
        )
        rows = await cur.fetchall()

    return {
        "total": int(totals["total"]) if totals else 0,
        "winners": int(totals["winners"]) if totals else 0,
        "losers": int(totals["losers"]) if totals else 0,
        "techs": [
            {
                "name": str(r["tech"]),
                "count": int(r["n"]),
                "winner_count": int(r["w"]),
                "loser_count": int(r["l"]),
            }
            for r in rows
        ],
    }
