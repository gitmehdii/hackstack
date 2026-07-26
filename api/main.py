"""Point d'entrée de l'API FastAPI (Étape 2).

Lecture seule. Le pool Postgres est ouvert au démarrage (lifespan) et fermé à l'arrêt.
Lancement local : `uvicorn api.main:app --reload`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import check_embed_config, cors_origins
from api.db import make_pool
from api.routers import hackathons, projects, search, stats, themes, trends
from api.search_encoder import aclose as close_encoder


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_embed_config()
    pool = make_pool()
    await pool.open(wait=True)
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


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
