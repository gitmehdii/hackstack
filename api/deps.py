"""Dépendances FastAPI : fournit une connexion issue du pool à chaque requête."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


def get_pool(request: Request) -> AsyncConnectionPool:
    pool: AsyncConnectionPool = request.app.state.pool
    return pool


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    pool = get_pool(request)
    async with pool.connection() as conn:
        yield conn
