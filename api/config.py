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


def excerpt_max_chars() -> int:
    """Longueur maximale de l'extrait de description exposé publiquement.

    Contrainte légale : le site n'affiche qu'un extrait, jamais le texte intégral.
    """
    return int(os.environ.get("API_EXCERPT_MAX_CHARS", "600"))
