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

from pipeline.embed.embed import EMBEDDED_TEXT_COLS
from pipeline.load.db import connect

_PROJECT_COLS = (
    "id, source, source_url, hackathon_slug, hackathon_name, hackathon_date, "
    "theme_tags, title, description, short_description, placement, raw_placement, "
    "is_winner, prize_track, tech_stack, stack_source, team_size, team_name, "
    "repo_url, demo_url, scraped_at"
)


def project_upsert_sql() -> str:
    """UPSERT projects_staging -> projects, avec invalidation de l'embedding.

    `embedding` n'est pas dans `_PROJECT_COLS` : à l'INSERT il reste donc NULL (l'étape
    embed le remplira), et à l'UPDATE il serait conservé tel quel. Or un re-scrape peut
    enrichir le texte d'un projet déjà en base (devpost, qui n'a longtemps eu que
    `short_description`) : le vecteur conservé aurait alors été calculé sur l'ANCIEN
    texte, et `pipeline.embed.embed` ne le rattraperait jamais (il ne traite que
    `WHERE embedding IS NULL`). On le remet donc à NULL — mais uniquement si le texte
    encodé change réellement, réencoder tout le corpus coûtant des heures de CPU.

    Le CASE est évalué sur la ligne d'AVANT mise à jour (sémantique ON CONFLICT de
    Postgres), donc la comparaison `projects.x IS DISTINCT FROM EXCLUDED.x` reste
    valide bien que `x` soit écrasé par le même ordre.
    """
    cols = [c.strip() for c in _PROJECT_COLS.split(",")]
    assignments = [f"{c} = EXCLUDED.{c}" for c in cols if c != "id"]
    text_changed = " OR ".join(
        f"projects.{c} IS DISTINCT FROM EXCLUDED.{c}" for c in EMBEDDED_TEXT_COLS
    )
    assignments.append(
        f"embedding = CASE WHEN {text_changed} THEN NULL ELSE projects.embedding END"
    )
    return (
        f"INSERT INTO projects ({_PROJECT_COLS}) "
        f"SELECT {_PROJECT_COLS} FROM projects_staging WHERE scrape_run_id = %s "
        f"ON CONFLICT (id) DO UPDATE SET {', '.join(assignments)}"
    )


def _latest_validated_run(cur: psycopg.Cursor) -> int:
    cur.execute("SELECT id FROM scrape_runs WHERE status='validated' ORDER BY id DESC LIMIT 1")
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

            # 2. Projets. À l'insertion embedding reste NULL, à la mise à jour il est
            #    invalidé si le texte encodé change (cf. project_upsert_sql) ; dans les
            #    deux cas c'est l'étape embed qui le (re)calcule. fts est généré
            #    automatiquement.
            cur.execute(project_upsert_sql(), (run_id,))
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
