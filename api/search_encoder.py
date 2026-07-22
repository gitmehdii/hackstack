"""Encodeur de requêtes pour la recherche vectorielle (Étape 3).

Charge bge-m3 (le même modèle que le pipeline d'embeddings) une seule fois, à la
demande, et vectorise la requête utilisateur au moment de la recherche. Le vecteur
produit est comparable aux embeddings stockés (même modèle, embeddings normalisés →
distance cosine).

Le chargement du modèle (~2 Go) et l'encodage sont bloquants : on les exécute hors de
l'event loop (`asyncio.to_thread`) pour ne pas figer l'API. Un verrou async garantit
qu'une seule instance est chargée même sous requêtes concurrentes.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None
_lock = asyncio.Lock()


def _load() -> SentenceTransformer:
    # Import tardif : torch/sentence-transformers sont lourds à importer.
    from sentence_transformers import SentenceTransformer

    model_name = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
    return SentenceTransformer(model_name)  # type: ignore[no-any-return]


async def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        async with _lock:
            if _model is None:  # re-vérifie sous verrou (double-checked locking)
                _model = await asyncio.to_thread(_load)
    return _model


async def encode_query(text: str) -> list[float]:
    """Vectorise une requête. Renvoie un vecteur de 1024 flottants (normalisé)."""
    model = await _get_model()

    def _encode() -> list[float]:
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return vec[0].tolist()

    return await asyncio.to_thread(_encode)
