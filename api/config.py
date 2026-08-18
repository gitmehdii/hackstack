"""Configuration de l'API, lue depuis l'environnement (cf. .env.example)."""

from __future__ import annotations

import os


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL non défini (voir .env.example)")
    return url


def db_pool_max_size() -> int:
    """Taille max du pool par process.

    10 convient à un process long-vivant. En serverless, **chaque instance** ouvre son
    propre pool : quelques instances concurrentes épuisent le quota de connexions Supabase.
    Poser `DB_POOL_MAX_SIZE=2` sur Vercel, où le pooler côté serveur fait le vrai travail.
    """
    return int(os.environ.get("DB_POOL_MAX_SIZE", "10"))


def db_prepare_threshold() -> int | None:
    """Seuil de préparation des requêtes psycopg, ou None pour désactiver.

    psycopg3 prépare automatiquement une requête après 5 exécutions identiques. Derrière le
    pooler Supabase en **mode transaction** (port 6543), la connexion serveur change entre
    les transactions : la requête préparée n'est plus là où on la cherche, et l'API se met à
    échouer — mais seulement après la 5e exécution, donc pas au premier essai. Poser
    `DB_PREPARE_THRESHOLD=none` quand on passe par le pooler.
    """
    raw = os.environ.get("DB_PREPARE_THRESHOLD", "").strip().lower()
    if raw in {"none", "off", "disabled"}:
        return None
    return int(raw) if raw else 5


def db_pool_timeout() -> float:
    """Attente max d'une connexion du pool, en secondes.

    Le défaut de psycopg_pool est 30 s. C'est trop long ici : quand la base est absente,
    chaque requête immobilise une fonction serverless pendant 30 s avant de renvoyer son
    503, et le front reste bloqué autant. On échoue vite, quitte à réessayer — 10 s laissent
    largement la place à une connexion froide vers Supabase.
    """
    return float(os.environ.get("DB_POOL_TIMEOUT", "10"))


def health_db_timeout() -> float:
    """Délai laissé à la sonde base de `/health`, en secondes.

    Court exprès : `/health` doit répondre, pas attendre. Le délai par défaut du pool est
    de 30 s, ce qui est la bonne valeur pour une requête métier et la mauvaise pour un
    diagnostic — un endpoint de santé qui met 30 s à dire « la base est morte » ne sert à
    personne, et dépasse le budget de la plupart des sondes.
    """
    return float(os.environ.get("HEALTH_DB_TIMEOUT", "3"))


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
