"""Applique les migrations SQL de db/migrations/ dans l'ordre, une seule fois chacune.

Versionné et idempotent : un fichier déjà appliqué (tracé dans schema_migrations)
est ignoré. Jamais de modification de schéma à la main (cf. PROJECT.md).

Usage:
    python -m pipeline.load.migrate
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from pipeline.load.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"Aucune migration trouvée dans {MIGRATIONS_DIR}")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP)
        conn.commit()

        done = applied_versions(conn)
        for path in files:
            version = path.stem
            if version in done:
                print(f"= {version} (déjà appliqué)")
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            conn.commit()
            print(f"+ {version} appliqué")

    print("Migrations à jour.")


if __name__ == "__main__":
    main()
