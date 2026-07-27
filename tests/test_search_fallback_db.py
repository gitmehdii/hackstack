"""Le bras lexical doit rattraper quand l'encodeur de requêtes est indisponible.

Régression observée en vrai : l'inférence HuggingFace est tombée (`status: error` côté
provider), `/search` est passé en repli full-text comme prévu — et a renvoyé **zéro**
résultat sur des requêtes en langage naturel, parce que `websearch_to_tsquery` exige tous
les termes. Mesuré alors : 0 résultat contre 2 506 en OU. Le filet existait sans rattraper
quoi que ce soit.

Lecture seule sur le corpus réel : aucune écriture, aucune table temporaire. Les tests sont
synchrones et pilotent l'asynchrone par `asyncio.run`, pour ne pas ajouter `pytest-asyncio`
aux dépendances du projet. Se saute proprement sans `DATABASE_URL`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from api.queries.search import search_projects

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL non défini (test d'intégration Postgres)",
)


def _chercher(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Recherche avec `query_vector=None` : exactement une panne d'encodeur."""

    async def run() -> list[dict[str, Any]]:
        from api.config import database_url

        async with await AsyncConnection.connect(database_url(), row_factory=dict_row) as conn:
            return await search_projects(conn, query, None, limit=limit)

    return asyncio.run(run())


def test_requete_langage_naturel_sans_vecteur_remonte_des_resultats() -> None:
    # Avec la conjonction stricte, cette requête renvoyait 0.
    rows = _chercher("helping blind people navigate cities")
    assert rows, "le repli lexical ne rattrape rien : la recherche est éteinte, pas dégradée"


def test_le_classement_place_les_plus_pertinents_en_tete() -> None:
    # Relâcher en OU élargit beaucoup le vivier : c'est `ts_rank_cd` qui rend le résultat
    # utilisable. Sans classement on renverrait du bruit plutôt que rien — pas un progrès.
    rows = _chercher("carbon footprint tracking")
    assert rows
    titres = " ".join(r["title"].lower() for r in rows)
    assert "carbon" in titres, f"aucun résultat de tête ne parle du sujet : {titres}"


def test_un_terme_exclu_reste_exclu() -> None:
    # `-terme` produit `!terme` : relâcher en OU inverserait l'intention (`a | !b` matche
    # presque tout). La sémantique stricte doit être conservée dans ce cas.
    assert _chercher("blockchain -blockchain") == [], (
        "un terme à la fois exigé et exclu doit ne rien renvoyer : la relaxation en OU "
        "s'est appliquée à une requête avec négation"
    )
