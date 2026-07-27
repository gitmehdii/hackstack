"""Tests de l'encodeur de requêtes : parsing de la réponse d'inférence et config.

Aucun réseau, aucun modèle chargé. Ce qui est couvert ici, c'est la frontière fragile :
une réponse mal formée doit lever, pas produire un vecteur silencieusement faux — un
vecteur faux ne casse rien visiblement, il dégrade juste la pertinence sans trace.
"""

from __future__ import annotations

from math import sqrt

import pytest

from api.config import (
    check_embed_config,
    db_pool_max_size,
    db_prepare_threshold,
    embed_backend,
    hf_embed_url,
)
from api.search_encoder import EMBED_DIM, parse_embedding


def _vec(value: float = 1.0, dim: int = EMBED_DIM) -> list[float]:
    return [value] * dim


def test_parses_flat_vector_and_normalizes() -> None:
    out = parse_embedding(_vec(2.0))
    assert len(out) == EMBED_DIM
    assert sqrt(sum(v * v for v in out)) == pytest.approx(1.0)


def test_accepts_wrapped_vector() -> None:
    # Certains backends enveloppent la réponse dans une liste supplémentaire.
    assert parse_embedding([_vec()]) == parse_embedding(_vec())


def test_rejects_per_token_response() -> None:
    # Plusieurs vecteurs = réponse par token (pas de pooling). Prendre le premier
    # renverrait le vecteur d'un seul token comme s'il représentait la requête.
    with pytest.raises(ValueError):
        parse_embedding([_vec(), _vec(), _vec()])


def test_already_normalized_vector_is_unchanged() -> None:
    unit = [1.0] + [0.0] * (EMBED_DIM - 1)
    assert parse_embedding(unit) == pytest.approx(unit)


def test_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="dimension 3"):
        parse_embedding([1.0, 2.0, 3.0])


def test_rejects_zero_vector() -> None:
    with pytest.raises(ValueError, match="nul"):
        parse_embedding(_vec(0.0))


@pytest.mark.parametrize("payload", [None, [], {}, "vecteur", [{"a": 1}] * EMBED_DIM])
def test_rejects_malformed_payloads(payload: object) -> None:
    with pytest.raises(ValueError):
        parse_embedding(payload)


def test_rejects_booleans_disguised_as_numbers() -> None:
    # bool est une sous-classe d'int : sans garde explicite, [True]*1024 passerait.
    with pytest.raises(ValueError, match="non numérique"):
        parse_embedding([True] * EMBED_DIM)


def test_backend_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBED_BACKEND", raising=False)
    assert embed_backend() == "local"


def test_backend_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_BACKEND", "huggingface")
    with pytest.raises(RuntimeError, match="EMBED_BACKEND invalide"):
        embed_backend()


def test_remote_backend_without_token_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    # Le repli full-text de /search rattraperait l'erreur à chaque requête : l'API
    # répondrait 200 avec une recherche muette. Mieux vaut ne pas démarrer.
    monkeypatch.setenv("EMBED_BACKEND", "remote")
    monkeypatch.setenv("HF_TOKEN", "")
    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        check_embed_config()


def test_local_backend_needs_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_BACKEND", "local")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    check_embed_config()


def test_inference_url_follows_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # L'URL dérive du modèle : impossible d'encoder les requêtes avec un modèle
    # différent de celui du pipeline sans changer les deux ensemble.
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-m3")
    assert hf_embed_url().endswith("/models/BAAI/bge-m3/pipeline/feature-extraction")


def test_pool_defaut_convient_a_un_process_long_vivant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("DB_PREPARE_THRESHOLD", raising=False)
    assert db_pool_max_size() == 10
    assert db_prepare_threshold() == 5


def test_preparation_desactivable_pour_le_pooler(monkeypatch: pytest.MonkeyPatch) -> None:
    # Derrière le pooler Supabase en mode transaction, les requêtes préparées cassent —
    # et seulement après la 5e exécution, donc pas au premier essai.
    monkeypatch.setenv("DB_PREPARE_THRESHOLD", "none")
    assert db_prepare_threshold() is None
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "2")
    assert db_pool_max_size() == 2
