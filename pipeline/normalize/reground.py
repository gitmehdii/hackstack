"""Re-ancrage de la tech déjà extraite par le LLM (Étape 4), sans re-appeler le modèle.

Applique `Taxonomy.ground_tech` aux lignes existantes de llm_extraction_staging : ne garde
que les technos réellement nommées dans le texte du projet. Corrige a posteriori les runs
faits avant l'ajout de l'ancrage (hallucinations + recrachages de taxonomie). Idempotent.

Usage:
    python -m pipeline.normalize.reground            # applique
    python -m pipeline.normalize.reground --dry-run  # montre l'impact sans écrire
"""

from __future__ import annotations

import argparse

from pipeline.load.db import connect
from pipeline.normalize.taxonomy import load_taxonomy


def reground(dry_run: bool) -> None:
    tax = load_taxonomy()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.project_id, l.tech_stack,
                       coalesce(p.title,'') || ' ' || coalesce(p.short_description,'')
                         || ' ' || coalesce(p.description,'')
                FROM llm_extraction_staging l
                JOIN projects p ON p.id = l.project_id
                WHERE cardinality(l.tech_stack) > 0
                """
            )
            rows = cur.fetchall()

        changed: list[tuple[list[str], str]] = []
        removed_total = 0
        for pid, tech, text in rows:
            grounded = tax.ground_tech(list(tech), str(text))
            if grounded != list(tech):
                removed_total += len(tech) - len(grounded)
                changed.append((grounded, str(pid)))

        print(
            f"{len(rows)} lignes avec tech ; {len(changed)} modifiées ; "
            f"{removed_total} technos non ancrées retirées."
        )
        if dry_run or not changed:
            return

        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE llm_extraction_staging SET tech_stack = %s WHERE project_id = %s",
                changed,
            )
        conn.commit()
        print(f"Re-ancrage appliqué à {len(changed)} lignes.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    reground(args.dry_run)


if __name__ == "__main__":
    main()
