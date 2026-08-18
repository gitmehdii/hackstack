"""L'API doit rester debout quand la base est injoignable.

Régression d'un incident réel : le projet Supabase du tier gratuit s'est mis en pause, le
lifespan ouvrait le pool avec `wait=True`, l'ouverture a expiré, et FastAPI s'est retrouvé
sans aucune route. Toutes les requêtes renvoyaient 500, `/health` compris, donc rien ne
désignait la base. Ces tests épinglent le comportement dégradé attendu.

Aucun serveur Postgres n'est nécessaire : on pointe `DATABASE_URL` sur un port fermé, ce qui
reproduit exactement le symptôme (connexion impossible, pas identifiants refusés).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


def _closed_port() -> int:
    """Réserve puis libère un port, pour être sûr que personne n'écoute dessus."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def client_without_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    port = _closed_port()
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://user:pass@127.0.0.1:{port}/nope?connect_timeout=1",
    )
    # Délais courts : le test ne doit pas attendre ceux de production.
    monkeypatch.setenv("HEALTH_DB_TIMEOUT", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "2")
    # `remote` évite de charger le modèle local (2 Go) juste pour construire l'app.
    monkeypatch.setenv("EMBED_BACKEND", "remote")
    monkeypatch.setenv("HF_TOKEN", "test-token")

    # Pas de rechargement du module : `api.main` ne lit rien de l'environnement à l'import,
    # tout passe par le lifespan, déclenché à l'entrée du TestClient. Un `importlib.reload`
    # ici laisserait `api.main` reconstruit avec l'environnement de test dans `sys.modules`,
    # donc empoisonnerait tout test ultérieur qui importerait l'app.
    from api.main import app

    with TestClient(app) as client:
        yield client


def test_app_starts_without_database(client_without_db: TestClient) -> None:
    """Le lifespan ne doit plus échouer : c'est ce qui privait l'app de toutes ses routes."""
    # Si le démarrage avait échoué, le TestClient aurait leve avant d'arriver ici.
    assert client_without_db.app is not None


def test_health_answers_and_names_the_culprit(client_without_db: TestClient) -> None:
    """`/health` doit répondre, et dire que c'est la base. Avant, il renvoyait 500."""
    res = client_without_db.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "database": "down"}


def test_db_route_degrades_to_503_not_500(client_without_db: TestClient) -> None:
    """Une route qui lit la base renvoie 503 (dépendance absente), pas 500 (service cassé)."""
    res = client_without_db.get("/stats")
    assert res.status_code == 503
    assert res.json() == {"detail": "Base de données indisponible"}
