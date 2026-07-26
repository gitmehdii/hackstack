"""Test d'intégration de l'UPSERT de promotion, contre un vrai Postgres.

Complète tests/test_promote_sql.py, qui n'inspecte que la chaîne SQL produite. Ce que le
test de chaîne ne peut PAS établir, et qui est pourtant l'hypothèse dont dépend tout le
correctif : dans un `ON CONFLICT DO UPDATE`, les expressions du SET sont évaluées sur la
ligne d'AVANT mise à jour. Sans cette garantie, `projects.description IS DISTINCT FROM
EXCLUDED.description` comparerait la nouvelle valeur à elle-même (toujours faux) et
l'embedding ne serait jamais invalidé — un mock de Postgres ne ferait que rejouer notre
supposition, seul un vrai serveur tranche.

Se saute proprement sans `DATABASE_URL` (même convention que .github/workflows/weekly.yml).

Aucune donnée réelle n'est touchée : on crée des tables TEMPORARY homonymes, qui masquent
`public.projects` / `public.projects_staging` le temps de la session (le schéma pg_temp
précède public dans le search_path), et la transaction est annulée à la fin.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from pipeline.load.promote import project_upsert_sql

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL non défini (test d'intégration Postgres)",
)

_RUN_ID = 99
# bge-m3 : 1024 dimensions. La valeur importe peu, seule sa présence/absence est testée.
_VEC = "[" + ",".join(["0.1"] * 1024) + "]"


@pytest.fixture
def cur() -> Iterator[psycopg.Cursor]:
    """Curseur sur des tables TEMP masquant les vraies ; tout est annulé au teardown."""
    from pipeline.load.db import connect

    conn = connect()
    conn.autocommit = False
    try:
        with conn.cursor() as c:
            # `INCLUDING ALL` reprend types, colonnes générées et la PK sur id (nécessaire
            # au ON CONFLICT). Les FK ne sont pas copiées par LIKE : pas besoin d'insérer
            # de ligne scrape_runs.
            c.execute("CREATE TEMP TABLE projects (LIKE public.projects INCLUDING ALL)")
            c.execute(
                "CREATE TEMP TABLE projects_staging (LIKE public.projects_staging INCLUDING ALL)"
            )
            # Garde-fou : si le masquage échouait, l'UPSERT écrirait dans la vraie table.
            c.execute("SELECT 'projects'::regclass::oid, 'public.projects'::regclass::oid")
            temp_oid, real_oid = c.fetchone()  # type: ignore[misc]
            assert temp_oid != real_oid, "les tables TEMP ne masquent pas public.projects"
            yield c
    finally:
        conn.rollback()
        conn.close()


def _insert_projet(cur: psycopg.Cursor, pid: str, title: str, short: str, desc: str | None) -> None:
    """Un projet déjà en base, avec un embedding déjà calculé."""
    cur.execute(
        "INSERT INTO projects (id, source, source_url, hackathon_slug, hackathon_name, "
        "is_winner, stack_source, title, short_description, description, embedding, scraped_at) "
        "VALUES (%s, 'devpost', %s, 'h1', 'Hack 1', false, 'none', %s, %s, %s, %s, now())",
        (pid, f"https://devpost.com/{pid}", title, short, desc, _VEC),
    )


def _stage_projet(cur: psycopg.Cursor, pid: str, title: str, short: str, desc: str | None) -> None:
    """La version rapportée par le nouveau scrape."""
    cur.execute(
        "INSERT INTO projects_staging (id, scrape_run_id, source, source_url, hackathon_slug, "
        "hackathon_name, is_winner, stack_source, title, short_description, description, "
        "scraped_at) "
        "VALUES (%s, %s, 'devpost', %s, 'h1', 'Hack 1', false, 'none', %s, %s, %s, now())",
        (pid, _RUN_ID, f"https://devpost.com/{pid}", title, short, desc),
    )


def _promouvoir(cur: psycopg.Cursor, pid: str) -> tuple[bool, str, str | None]:
    """Exécute l'UPSERT réel ; renvoie (embedding est NULL, titre, description)."""
    cur.execute(project_upsert_sql(), (_RUN_ID,))
    cur.execute("SELECT embedding IS NULL, title, description FROM projects WHERE id = %s", (pid,))
    row = cur.fetchone()
    assert row is not None
    return bool(row[0]), str(row[1]), row[2]


def test_description_enrichie_invalide_lembedding(cur: psycopg.Cursor) -> None:
    # Le cas qui motive le correctif : devpost n'avait que short_description, le scrape
    # réel apporte la description complète.
    _insert_projet(cur, "p1", "Titre", "resume", None)
    _stage_projet(cur, "p1", "Titre", "resume", "description complete arrivee")

    vide, _, desc = _promouvoir(cur, "p1")
    assert vide, "embedding conservé alors que la description a changé"
    assert desc == "description complete arrivee", "le texte doit malgré tout être promu"


def test_titre_modifie_invalide_lembedding(cur: psycopg.Cursor) -> None:
    _insert_projet(cur, "p2", "Ancien titre", "resume", "desc")
    _stage_projet(cur, "p2", "Nouveau titre", "resume", "desc")

    vide, titre, _ = _promouvoir(cur, "p2")
    assert vide, "embedding conservé alors que le titre a changé"
    assert titre == "Nouveau titre"


def test_texte_inchange_conserve_lembedding(cur: psycopg.Cursor) -> None:
    # Le garde-fou coûteux : un re-scrape ne change souvent que scraped_at. Invalider
    # ici, c'est réencoder les 21 k projets à chaque run (des heures de CPU).
    _insert_projet(cur, "p3", "Titre", "resume", "desc")
    _stage_projet(cur, "p3", "Titre", "resume", "desc")

    vide, _, _ = _promouvoir(cur, "p3")
    assert not vide, "embedding invalidé alors que le texte encodé est identique"


def test_insertion_dun_nouveau_projet_laisse_lembedding_null(cur: psycopg.Cursor) -> None:
    # Branche INSERT : pas de ligne existante, l'étape embed s'en chargera.
    _stage_projet(cur, "p4", "Titre", "resume", "desc")

    vide, _, _ = _promouvoir(cur, "p4")
    assert vide
