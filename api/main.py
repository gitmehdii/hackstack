"""Point d'entrée de l'API FastAPI (Étape 2).

Lecture seule. Le pool Postgres est ouvert au démarrage (lifespan) et fermé à l'arrêt.
Lancement local : `uvicorn api.main:app --reload`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

from api.config import check_embed_config, cors_origins, health_db_timeout
from api.db import make_pool
from api.routers import hackathons, projects, search, stats, themes, trends
from api.search_encoder import aclose as close_encoder

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_embed_config()
    pool = make_pool()
    # Ouverture **non bloquante**. Avec `wait=True`, une base injoignable faisait échouer le
    # lifespan, et FastAPI n'a alors plus aucune route : *toutes* les requêtes renvoyaient
    # 500, y compris `/health` qui ne touche pourtant jamais la base. Sur Vercel ça se
    # présente en `FUNCTION_INVOCATION_FAILED`, sans rien qui désigne la base.
    #
    # C'est arrivé en production : le projet Supabase du tier gratuit se met en pause après
    # une semaine sans activité, et l'API entière est devenue mutique pendant trois semaines.
    # En ouvrant sans attendre, le process démarre, `/health` répond et nomme le coupable, et
    # seules les routes qui lisent vraiment la base échouent, en 503 (cf. le handler plus
    # bas). Le pool retente ses connexions en arrière-plan, donc l'API se rétablit seule dès
    # que la base revient, sans redéploiement.
    await pool.open(wait=False)
    app.state.pool = pool
    try:
        yield
    finally:
        # Le pool doit être fermé même si la fermeture de l'encodeur échoue : sans ce
        # try/finally imbriqué, une exception de `close_encoder` fuiterait les connexions
        # Postgres à chaque redéploiement (et le tier gratuit Supabase en compte peu).
        try:
            await close_encoder()
        finally:
            await pool.close()


app = FastAPI(
    title="hackstack API",
    version="0.2.0",
    summary="API publique en lecture seule des projets de hackathon.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(hackathons.router)
app.include_router(search.router)
app.include_router(stats.router)
app.include_router(themes.router)
app.include_router(trends.router)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    """Traduit une base injoignable en 503 plutôt qu'en 500.

    `psycopg_pool.PoolTimeout` hérite de `psycopg.OperationalError`, donc ce handler couvre
    aussi bien l'épuisement du pool que l'impossibilité d'établir une connexion. La
    distinction compte pour qui appelle l'API : un 500 dit « ce service est cassé », un 503
    dit « il est vivant mais sa dépendance est absente », ce qui est réessayable.
    """
    log.warning("base indisponible sur %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Base de données indisponible"},
    )


@app.get("/health", tags=["meta"])
async def health(request: Request) -> JSONResponse:
    """Vivacité du process, et état de la base, séparément.

    Les deux sont distingués exprès : le process peut très bien répondre alors que la base
    dort, et c'est précisément le cas qu'on veut pouvoir lire d'un coup d'oeil. La sonde a
    son propre délai, court, pour que l'endpoint réponde vite même base éteinte.
    """
    pool: AsyncConnectionPool = request.app.state.pool
    try:
        async with pool.connection(timeout=health_db_timeout()) as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - toute panne se rapporte pareil ici
        log.warning("sonde base en échec: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "down"},
        )
    return JSONResponse(status_code=200, content={"status": "ok", "database": "up"})
