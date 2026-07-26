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


def _text_for(title: str, short: str | None, desc: str | None) -> str:
    parts = [title]
    if short:
        parts.append(short)
    if desc:
        parts.append(desc)
    return "\n\n".join(parts)


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
                "SELECT id, title, short_description, description "
                "FROM projects WHERE embedding IS NULL ORDER BY id"
            )
            # `is not None` et pas la simple vérité : `--limit 0` doit encoder zéro ligne,
            # pas lancer le backfill complet par accident.
            if args.limit is not None:
                sql += f" LIMIT {int(args.limit)}"
            cur.execute(sql)
            rows = cur.fetchall()

        total = len(rows)
        print(f"{total} projets à encoder.")
        if total == 0:
            return

        # Trié par longueur : un batch est paddé à la longueur de son plus long texte, et le
        # corpus va de 50 à 3 700 caractères. Grouper les tailles proches supprime ce padding
        # perdu. Les embeddings sont inchangés (chaque texte est encodé indépendamment, le
        # padding est masqué) — seul l'ordre d'écriture change, et il n'a pas d'importance.
        pairs = sorted(((_text_for(r[1], r[2], r[3]), r[0]) for r in rows), key=lambda p: len(p[0]))

        done = 0
        for start in range(0, total, args.batch):
            chunk = pairs[start : start + args.batch]
            texts = [text for text, _ in chunk]
            # bge-m3 : embeddings normalisés -> distance cosine cohérente avec l'index.
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE projects SET embedding = %s WHERE id = %s",
                    [(vec.tolist(), pid) for vec, (_, pid) in zip(vectors, chunk, strict=True)],
                )
            conn.commit()
            done += len(chunk)
            print(f"  {done}/{total}", end="\r", flush=True)

    print(f"\nEmbeddings générés pour {done} projets.")


if __name__ == "__main__":
    main()
