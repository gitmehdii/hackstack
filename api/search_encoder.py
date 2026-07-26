"""Encodeur de requêtes pour la recherche vectorielle (Étape 3).

Vectorise la requête utilisateur avec **bge-m3**, le même modèle que le pipeline
d'embeddings : le vecteur produit doit rester comparable aux embeddings stockés (même
modèle, normalisé → distance cosine). Changer de modèle imposerait de ré-encoder les 21 k
projets — ce n'est donc pas une variable d'ajustement.

Deux backends, choisis par `EMBED_BACKEND` :

  - `local` (défaut) — charge bge-m3 en mémoire (~2 Go). Le chargement et l'encodage sont
    bloquants : exécutés hors de l'event loop (`asyncio.to_thread`), avec un verrou async
    pour ne charger qu'une seule instance sous requêtes concurrentes.
  - `remote` — appelle l'inférence HuggingFace. Aucun poids en mémoire, donc l'API tient
    dans un hébergement sans état (fonction serverless). Vérifié : le vecteur renvoyé est
    identique au modèle local (cosinus = 1.0) et déjà normalisé.

En cas d'échec d'encodage, `/search` retombe sur le full-text seul (cf. `routers/search.py`)
plutôt que de renvoyer une erreur — ça vaut pour les deux backends.
"""

from __future__ import annotations

import asyncio
from math import sqrt
from typing import TYPE_CHECKING, Any

import httpx

from api.config import embed_backend, embed_model, hf_embed_url, hf_token

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# Dimension de `projects.embedding`. Un vecteur d'une autre taille serait rejeté par
# Postgres au moment de la requête : autant échouer ici, avec un message lisible.
EMBED_DIM = 1024

_REMOTE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_model: SentenceTransformer | None = None
_client: httpx.AsyncClient | None = None
# Un verrou par ressource : charger le modèle prend plusieurs secondes, et un seul verrou
# partagé ferait attendre tout ce temps une requête qui n'a besoin que du client HTTP.
_model_lock = asyncio.Lock()
_client_lock = asyncio.Lock()


def _normalize(vec: list[float]) -> list[float]:
    norm = sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        raise ValueError("vecteur nul renvoyé par l'encodeur")
    return [v / norm for v in vec]


def parse_embedding(payload: Any) -> list[float]:
    """Extrait un vecteur normalisé de la réponse d'inférence.

    L'API renvoie une liste plate pour une entrée unique, mais certains backends
    l'enveloppent (`[[...]]`) : on accepte les deux plutôt que de dépendre de la forme.
    Le déballage exige **exactement un** élément : une réponse à plusieurs vecteurs est
    une réponse par token (pas de pooling), et prendre le premier renverrait le vecteur
    d'un seul token sans que rien ne le signale.
    """
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], list):
        payload = payload[0]
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"réponse d'encodage inattendue : {type(payload).__name__}")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in payload):
        raise ValueError("réponse d'encodage non numérique")
    if len(payload) != EMBED_DIM:
        raise ValueError(f"vecteur de dimension {len(payload)}, attendu {EMBED_DIM}")
    return _normalize([float(v) for v in payload])


def _load() -> SentenceTransformer:
    # Import tardif : torch/sentence-transformers sont lourds à importer, et absents
    # d'un déploiement en backend `remote`.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(embed_model())  # type: ignore[no-any-return]


async def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:  # re-vérifie sous verrou (double-checked locking)
                _model = await asyncio.to_thread(_load)
    return _model


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=_REMOTE_TIMEOUT)
    return _client


async def _encode_local(text: str) -> list[float]:
    model = await _get_model()

    def _encode() -> list[float]:
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return [float(v) for v in vec[0]]

    # Même validation que le backend distant : un `EMBED_MODEL` mal configuré (dimension
    # différente) doit échouer ici, avec un message lisible. Sinon l'erreur ne surgit qu'au
    # moment de la requête SQL, hors du try/except de `/search`, donc en 500 au lieu du
    # repli full-text.
    return parse_embedding(await asyncio.to_thread(_encode))


async def _encode_remote(text: str) -> list[float]:
    token = hf_token()
    if not token:
        raise RuntimeError("EMBED_BACKEND=remote mais HF_TOKEN n'est pas défini")
    client = await _get_client()
    resp = await client.post(
        hf_embed_url(),
        json={"inputs": text},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return parse_embedding(resp.json())


async def encode_query(text: str) -> list[float]:
    """Vectorise une requête. Renvoie un vecteur de 1024 flottants (normalisé)."""
    if embed_backend() == "remote":
        return await _encode_remote(text)
    return await _encode_local(text)


async def aclose() -> None:
    """Ferme le client HTTP (appelé à l'arrêt de l'API)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
