"""Tests de l'UPSERT de promotion (construction du SQL, sans DB).

Enjeu : un re-scrape qui enrichit le texte d'un projet déjà en base doit invalider son
embedding, sinon `/search` compare des vecteurs calculés sur l'ancien texte sans qu'aucun
signal ne le révèle. Mais l'invalidation doit rester conditionnelle : réencoder tout le
corpus coûte des heures de CPU.
"""

from __future__ import annotations

import re

from pipeline.embed.embed import EMBEDDED_TEXT_COLS
from pipeline.load.promote import _PROJECT_COLS, project_upsert_sql

_COLS = [c.strip() for c in _PROJECT_COLS.split(",")]


def _set_clause(sql: str) -> str:
    _, _, clause = sql.partition("ON CONFLICT (id) DO UPDATE SET ")
    assert clause, "l'UPSERT doit comporter un DO UPDATE SET"
    return clause


def _embedding_condition(sql: str) -> str:
    m = re.search(r"embedding = CASE WHEN (.+?) THEN NULL ELSE projects\.embedding END", sql)
    assert m is not None, f"pas d'invalidation conditionnelle de l'embedding dans : {sql}"
    return m.group(1)


def test_toutes_les_colonnes_sont_ecrasees_sauf_id() -> None:
    clause = _set_clause(project_upsert_sql())
    for col in _COLS:
        if col == "id":
            continue
        assert f"{col} = EXCLUDED.{col}" in clause
    # `id` est la clé du conflit : le réassigner n'aurait pas de sens.
    assert "id = EXCLUDED.id" not in clause


def test_embedding_nest_jamais_repris_du_staging() -> None:
    # projects_staging n'a pas de vecteur : l'embedding ne peut venir que de l'étape embed.
    sql = project_upsert_sql()
    assert "embedding" not in _PROJECT_COLS
    assert "embedding = EXCLUDED.embedding" not in sql


def test_invalidation_couvre_exactement_le_texte_encode() -> None:
    # Garde-fou anti-dérive : si embed.py encode un jour une colonne de plus, la
    # condition doit la couvrir, sans quoi ce test casse.
    cond = _embedding_condition(project_upsert_sql())
    for col in EMBEDDED_TEXT_COLS:
        assert f"projects.{col} IS DISTINCT FROM EXCLUDED.{col}" in cond
    compared = set(re.findall(r"projects\.(\w+) IS DISTINCT FROM", cond))
    assert compared == set(EMBEDDED_TEXT_COLS)


def test_invalidation_ignore_les_colonnes_hors_texte() -> None:
    # scraped_at change à chaque run : le déclencher invaliderait tout le corpus à
    # chaque scrape (des heures de réencodage pour rien).
    cond = _embedding_condition(project_upsert_sql())
    for col in ("scraped_at", "tech_stack", "theme_tags", "is_winner"):
        assert col not in cond


def test_conditions_reliees_par_ou() -> None:
    # Un OU : n'importe quel champ de texte modifié suffit à invalider.
    cond = _embedding_condition(project_upsert_sql())
    assert cond.count(" OR ") == len(EMBEDDED_TEXT_COLS) - 1
    assert " AND " not in cond


def test_is_distinct_from_gere_les_null() -> None:
    # `<>` renverrait NULL (donc pas d'invalidation) quand devpost passe d'une
    # description NULL à un texte complet : c'est précisément le cas à couvrir.
    cond = _embedding_condition(project_upsert_sql())
    assert "IS DISTINCT FROM" in cond
    assert re.search(r"projects\.\w+ (?:<>|!=) EXCLUDED", cond) is None
