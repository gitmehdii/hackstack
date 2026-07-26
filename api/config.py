"""Configuration de l'API, lue depuis l'environnement (cf. .env.example)."""

from __future__ import annotations

import os


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL non défini (voir .env.example)")
    return url


def cors_origins() -> list[str]:
    """Origines autorisées pour le front (Vercel + dev local).

    Liste séparée par des virgules dans API_CORS_ORIGINS. Par défaut : dev local.
    """
    raw = os.environ.get("API_CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def embed_model() -> str:
    """Modèle d'embeddings. Doit rester celui du pipeline, sinon les vecteurs stockés
    deviennent incomparables aux vecteurs de requête."""
    return os.environ.get("EMBED_MODEL", "BAAI/bge-m3")


def embed_backend() -> str:
    """`local` (modèle en mémoire, ~2 Go) ou `remote` (inférence HuggingFace).

    Défaut `local` : c'est le comportement de dev, et un défaut `remote` ferait dépendre
    silencieusement les tests d'un token et du réseau. Un déploiement sans état (fonction
    serverless) doit poser `EMBED_BACKEND=remote` explicitement.
    """
    backend = os.environ.get("EMBED_BACKEND", "local").strip().lower()
    if backend not in {"local", "remote"}:
        raise RuntimeError(f"EMBED_BACKEND invalide : {backend!r} (attendu local ou remote)")
    return backend


def hf_token() -> str:
    return os.environ.get("HF_TOKEN", "").strip()


def hf_embed_url() -> str:
    """Endpoint d'inférence, dérivé du modèle pour qu'ils ne puissent pas diverger."""
    base = os.environ.get("HF_INFERENCE_BASE", "https://router.huggingface.co/hf-inference")
    return f"{base}/models/{embed_model()}/pipeline/feature-extraction"


def check_embed_config() -> None:
    """Valide la config d'encodage au démarrage, pas à la première recherche.

    `/search` rattrape toute erreur d'encodage en repli full-text (choix voulu face aux
    pannes réseau). Une *mauvaise configuration* tomberait donc dans le même filet : l'API
    répondrait 200, `/health` resterait vert, et la recherche sémantique ne marcherait
    jamais sans que rien ne le dise. Autant refuser de démarrer.
    """
    if embed_backend() == "remote" and not hf_token():
        raise RuntimeError(
            "EMBED_BACKEND=remote exige HF_TOKEN : sans lui, /search se dégraderait "
            "silencieusement en full-text à chaque requête"
        )


def excerpt_max_chars() -> int:
    """Longueur maximale de l'extrait de description exposé publiquement.

    Contrainte légale : le site n'affiche qu'un extrait, jamais le texte intégral.
    """
    return int(os.environ.get("API_EXCERPT_MAX_CHARS", "600"))
