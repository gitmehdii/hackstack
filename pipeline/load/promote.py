"""Promotion staging -> projects (Étape 1 : bootstrap sans baseline).

Rien n'écrit dans `projects` en dehors de cette étape. Pour l'import initial il n'existe
pas encore de run sain de référence : la validation est donc sautée (bootstrap). À partir
de l'Étape 6, la promotion sera conditionnée aux tests de contrat (pipeline/contracts/).

Usage:
    python -m pipeline.load.promote            # promeut le dernier run 'validated'
    python -m pipeline.load.promote --run 3    # promeut un run précis
"""

from __future__ import annotations

import argparse

import psycopg

from pipeline.load.db import connect

_PROJECT_COLS = (
    "id, source, source_url, hackathon_slug, hackathon_name, hackathon_date, "
    "theme_tags, title, description, short_description, placement, raw_placement, "
    "is_winner, prize_track, tech_stack, stack_source, team_size, team_name, "
    "repo_url, demo_url, scraped_at"
)


def _latest_validated_run(cur: psycopg.Cursor) -> int:
    cur.execute(
        "SELECT id FROM scrape_runs WHERE status='validated' ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Aucun run 'validated' à promouvoir.")
    return int(row[0])


def promote(run_id: int | None) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            if run_id is None:
                run_id = _latest_validated_run(cur)

            # 1. Hackathons d'abord (les projets y font référence via FK).
            cur.execute(
                "INSERT INTO hackathons (source, slug, name, hackathon_date, url) "
                "SELECT source, slug, name, hackathon_date, url "
                "FROM hackathons_staging WHERE scrape_run_id = %s "
                "ON CONFLICT (source, slug) DO UPDATE SET "
                "  name = EXCLUDED.name, "
                "  hackathon_date = COALESCE(EXCLUDED.hackathon_date, hackathons.hackathon_date), "
                "  scraped_at = now()",
                (run_id,),
            )

            # 2. Projets. embedding reste NULL (rempli par l'étape embed) ;
            #    fts est généré automatiquement.
            set_clause = ", ".join(
                f"{c} = EXCLUDED.{c}"
                for c in _PROJECT_COLS.replace(" ", "").split(",")
                if c != "id"
            )
            cur.execute(
                f"INSERT INTO projects ({_PROJECT_COLS}) "
                f"SELECT {_PROJECT_COLS} FROM projects_staging WHERE scrape_run_id = %s "
                f"ON CONFLICT (id) DO UPDATE SET {set_clause}",
                (run_id,),
            )
            promoted = cur.rowcount

            cur.execute(
                "UPDATE scrape_runs SET status='promoted', n_promoted=%s, finished_at=now() "
                "WHERE id=%s",
                (promoted, run_id),
            )
        conn.commit()

    print(f"Run #{run_id} promu : {promoted} projets dans `projects`.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=None)
    args = ap.parse_args()
    promote(args.run)


if __name__ == "__main__":
    main()
