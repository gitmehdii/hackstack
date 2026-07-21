"""Connexion Postgres. On écrit le SQL à la main (pas d'ORM), cf. PROJECT.md."""

from __future__ import annotations

import os

import psycopg


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL non défini (voir .env.example)")
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())
