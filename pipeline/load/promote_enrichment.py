"""Promotion de l'enrichissement (Étape 4) : staging -> projects, étape explicite.

Fusionne les deux passes puis met à jour `projects`. C'est le SEUL chemin d'écriture de
tech_stack / theme_tags / stack_source dans `projects` (invariant PROJECT.md).

Règles de fusion, par projet :
  - tech_stack   = github.tech_stack si la passe GitHub a donné une stack non vide,
                   sinon llm.tech_stack (sinon inchangé)
  - stack_source = 'github' si stack GitHub non vide, sinon 'llm' si la passe LLM a
                   produit une stack, sinon 'none'
  - theme_tags   = llm.theme_tags, uniquement si le projet a une ligne LLM
                   (sinon inchangé : la passe GitHub ne produit pas de thèmes)

Usage:
    python -m pipeline.load.promote_enrichment            # applique
    python -m pipeline.load.promote_enrichment --dry-run  # compte sans écrire
"""

from __future__ import annotations

import argparse

from pipeline.load.db import connect

_MERGE_CTE = """
WITH merged AS (
    SELECT
        COALESCE(g.project_id, l.project_id) AS project_id,
        (g.project_id IS NOT NULL AND cardinality(g.tech_stack) > 0) AS gh_tech,
        (l.project_id IS NOT NULL) AS has_llm,
        CASE
            WHEN g.project_id IS NOT NULL AND cardinality(g.tech_stack) > 0 THEN g.tech_stack
            ELSE COALESCE(l.tech_stack, '{}')
        END AS tech_stack,
        CASE
            WHEN g.project_id IS NOT NULL AND cardinality(g.tech_stack) > 0
                THEN 'github'::stack_source_t
            WHEN l.project_id IS NOT NULL AND cardinality(COALESCE(l.tech_stack, '{}')) > 0
                THEN 'llm'::stack_source_t
            ELSE 'none'::stack_source_t
        END AS stack_source,
        COALESCE(l.theme_tags, '{}') AS theme_tags
    FROM github_tech_staging g
    FULL OUTER JOIN llm_extraction_staging l ON g.project_id = l.project_id
)
"""


def promote(dry_run: bool) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_MERGE_CTE + "SELECT count(*) FROM merged")
        staged = int((cur.fetchone() or [0])[0])

        if dry_run:
            cur.execute(
                _MERGE_CTE + "SELECT stack_source, count(*), "
                "  count(*) FILTER (WHERE has_llm AND cardinality(theme_tags) > 0) "
                "FROM merged GROUP BY stack_source ORDER BY stack_source"
            )
            print(f"[dry-run] {staged} projets en staging d'enrichissement :")
            for src, n, with_theme in cur.fetchall():
                print(f"  stack_source={src}: {n} projets, {with_theme} avec thèmes")
            return

        cur.execute(
            _MERGE_CTE + "UPDATE projects p SET "
            "  tech_stack = m.tech_stack, "
            "  stack_source = m.stack_source, "
            "  theme_tags = CASE WHEN m.has_llm THEN m.theme_tags ELSE p.theme_tags END "
            "FROM merged m WHERE p.id = m.project_id"
        )
        updated = cur.rowcount
        conn.commit()
    print(f"Enrichissement promu : {updated} projets mis à jour dans `projects`.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    promote(args.dry_run)


if __name__ == "__main__":
    main()
