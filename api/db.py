"""Pool de connexions Postgres async. SQL écrit à la main, pas d'ORM (cf. PROJECT.md)."""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.config import database_url


def make_pool() -> AsyncConnectionPool:
    """Crée le pool sans l'ouvrir (l'ouverture se fait dans le lifespan FastAPI)."""
    return AsyncConnectionPool(
        conninfo=database_url(),
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row},
    )
