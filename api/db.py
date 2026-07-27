"""Pool de connexions Postgres async. SQL écrit à la main, pas d'ORM (cf. PROJECT.md)."""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.config import database_url, db_pool_max_size, db_prepare_threshold


def make_pool() -> AsyncConnectionPool:
    """Crée le pool sans l'ouvrir (l'ouverture se fait dans le lifespan FastAPI).

    Taille et préparation des requêtes sont configurables : les valeurs qui conviennent à un
    process long-vivant sont fausses en serverless derrière un pooler (cf. `api/config.py`).
    """
    return AsyncConnectionPool(
        conninfo=database_url(),
        min_size=1,
        max_size=db_pool_max_size(),
        open=False,
        kwargs={
            "row_factory": dict_row,
            "prepare_threshold": db_prepare_threshold(),
        },
    )
