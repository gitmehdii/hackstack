"""Génération des embeddings bge-m3 pour les projets sans vecteur (Étape 1).

Encode `title + short_description + description`, écrit dans projects.embedding.
Idempotent : ne traite que les lignes où embedding IS NULL. L'index HNSW est maintenu
automatiquement par Postgres.

Usage:
    python -m pipeline.embed.embed
    python -m pipeline.embed.embed --limit 100   # test rapide
"""

from __future__ import annotations

import argparse
import os

from pipeline.load.db import connect

# Colonnes de `projects` qui composent le texte encodé, dans l'ordre de concaténation.
# Source de vérité partagée : la promotion (pipeline/load/promote.py) s'en sert pour
# invalider l'embedding quand l'une d'elles change.
EMBEDDED_TEXT_COLS = ("title", "short_description", "description")


def _text_for(*values: str | None) -> str:
    """Concatène les colonnes de EMBEDDED_TEXT_COLS, dans l'ordre, en sautant les vides.

    Variadique à dessein : appelée en `_text_for(*row)`, elle suit automatiquement toute
    modification de EMBEDDED_TEXT_COLS. Une signature positionnelle fixe se serait
    désynchronisée en silence si la constante était réordonnée — le texte encodé aurait
    changé sans que rien ne le signale.
    """
    return "\n\n".join(v for v in values if v)


# L'écriture est optimiste : entre le SELECT (dont le résultat est gardé en mémoire pendant
# des heures) et l'UPDATE, une promotion a pu changer le texte du projet et remettre son
# embedding à NULL. Sans cette garde, on écrirait un vecteur calculé sur le texte périmé du
# snapshot, et plus rien ne le rattraperait — exactement le défaut que corrige
# pipeline/load/promote.py. Si le texte a bougé, l'UPDATE ne fait rien : la ligne reste NULL
# et la passe suivante la reprend.
_UPDATE_SQL = "UPDATE projects SET embedding = %s WHERE id = %s AND " + " AND ".join(
    f"{c} IS NOT DISTINCT FROM %s" for c in EMBEDDED_TEXT_COLS
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=int(os.environ.get("EMBED_BATCH_SIZE", 32)))
    args = ap.parse_args()

    # Import tardif : lourd, et inutile si on ne fait que --help.
    from sentence_transformers import SentenceTransformer

    model_name = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
    print(f"Chargement du modèle {model_name}…")
    model = SentenceTransformer(model_name)

    with connect() as conn:
        with conn.cursor() as cur:
            sql = (
                f"SELECT id, {', '.join(EMBEDDED_TEXT_COLS)} "
                "FROM projects WHERE embedding IS NULL ORDER BY id"
            )
            if args.limit:
                sql += f" LIMIT {int(args.limit)}"
            cur.execute(sql)
            rows = cur.fetchall()

        total = len(rows)
        print(f"{total} projets à encoder.")
        if total == 0:
            return

        done = 0
        perimes = 0
        for start in range(0, total, args.batch):
            chunk = rows[start : start + args.batch]
            texts = [_text_for(*r[1:]) for r in chunk]
            # bge-m3 : embeddings normalisés -> distance cosine cohérente avec l'index.
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            with conn.cursor() as cur:
                # Le texte du snapshot est repassé en paramètre : c'est la garde optimiste.
                cur.executemany(
                    _UPDATE_SQL,
                    [
                        (vec.tolist(), row[0], *row[1:])
                        for vec, row in zip(vectors, chunk, strict=True)
                    ],
                )
                ecrits = cur.rowcount
            conn.commit()
            done += len(chunk)
            perimes += len(chunk) - ecrits
            print(f"  {done}/{total}", end="\r", flush=True)

    print(f"\nEmbeddings générés pour {done - perimes} projets.")
    if perimes:
        # Non bloquant : ces lignes sont restées NULL, la prochaine passe les reprendra.
        print(
            f"{perimes} projets ignorés : leur texte a changé pendant l'encodage "
            f"(promotion concurrente). Relancer pour les traiter."
        )


if __name__ == "__main__":
    main()
