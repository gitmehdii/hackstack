"""Écriture en zone de staging — chemin unique partagé par l'import et les scrapers.

Rien n'écrit jamais direct dans `projects` (invariant PROJECT.md). Tout scrape/import
atterrit ici ; la promotion vers `projects` est une étape séparée et conditionnée à la
validation (Étape 7).
"""

from __future__ import annotations

import psycopg

from pipeline.normalize.schema import Hackathon, Project, RawTech

_PROJECT_COLUMNS = (
    "scrape_run_id, id, source, source_url, hackathon_slug, hackathon_name, "
    "hackathon_date, theme_tags, title, description, short_description, "
    "placement, raw_placement, is_winner, prize_track, tech_stack, "
    "stack_source, team_size, team_name, repo_url, demo_url, scraped_at"
)


def open_run(conn: psycopg.Connection, *, source: str | None, kind: str, n_scraped: int) -> int:
    """Crée une ligne scrape_runs 'running' et renvoie son id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_runs (source, kind, status, n_scraped) "
            "VALUES (%s, %s, 'running', %s) RETURNING id",
            (source, kind, n_scraped),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def finish_run(
    conn: psycopg.Connection, run_id: int, *, status: str, notes: str | None = None
) -> None:
    """Marque un run terminé (scraped/validated/failed/blocked...) avec finished_at."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_runs SET status=%s, finished_at=now(), notes=%s WHERE id=%s",
            (status, notes, run_id),
        )


def write_staging_batch(
    conn: psycopg.Connection,
    run_id: int,
    projects: list[Project],
    hackathons: list[Hackathon],
    raw_techs: list[RawTech],
) -> None:
    """Écrit un lot (projets + hackathons + tech brute) en staging pour un run donné.

    raw_project_tech est global (pas de scrape_run) : on ne le remplace PAS ici (l'import
    le fait dans son propre flux) ; on insère en ON CONFLICT DO NOTHING.
    """
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO hackathons_staging "
            "(scrape_run_id, source, slug, name, hackathon_date, url) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(run_id, h.source, h.slug, h.name, h.hackathon_date, h.url) for h in hackathons],
        )

        cur.executemany(
            f"INSERT INTO projects_staging ({_PROJECT_COLUMNS}) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s) ON CONFLICT (scrape_run_id, id) DO NOTHING",
            [
                (
                    run_id,
                    p.id,
                    p.source,
                    p.source_url,
                    p.hackathon_slug,
                    p.hackathon_name,
                    p.hackathon_date,
                    p.theme_tags,
                    p.title,
                    p.description,
                    p.short_description,
                    p.placement,
                    p.raw_placement,
                    p.is_winner,
                    p.prize_track,
                    p.tech_stack,
                    p.stack_source,
                    p.team_size,
                    p.team_name,
                    p.repo_url,
                    p.demo_url,
                    p.scraped_at,
                )
                for p in projects
            ],
        )

        cur.executemany(
            "INSERT INTO raw_project_tech (project_id, source, tech_name, tech_slug) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(t.project_id, t.source, t.tech_name, t.tech_slug) for t in raw_techs],
        )
