"""Tests de la passe GitHub : parsing de manifestes (pur) + client HTTP mocké.

Aucun appel réseau réel (cf. PROJECT.md) : httpx.MockTransport sert les réponses figées.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from pipeline.normalize.github_stack import (
    GitHubBlocked,
    GitHubStackClient,
    _deps_cargo,
    _deps_go_mod,
    _deps_package_json,
    _deps_pyproject,
    _deps_requirements_txt,
    parse_repo_url,
    tech_from_signals,
)
from pipeline.normalize.taxonomy import load_taxonomy


def test_parse_repo_url() -> None:
    assert parse_repo_url("https://github.com/foo/bar") == ("foo", "bar")
    assert parse_repo_url("https://github.com/foo/bar.git") == ("foo", "bar")
    assert parse_repo_url("http://github.com/foo/bar/tree/main") == ("foo", "bar")
    assert parse_repo_url("https://gitlab.com/foo/bar") is None
    assert parse_repo_url("https://github.com/foo") is None
    assert parse_repo_url("not a url at all") is None


def test_deps_package_json() -> None:
    text = json.dumps(
        {"dependencies": {"react": "^18", "ethers": "^6"}, "devDependencies": {"hardhat": "^2"}}
    )
    assert set(_deps_package_json(text)) == {"react", "ethers", "hardhat"}
    assert _deps_package_json("{ not json") == []


def test_deps_requirements_txt() -> None:
    text = "fastapi==0.115\n# comment\npsycopg[binary]>=3.2\n-e .\nhttpx\n"
    assert _deps_requirements_txt(text) == ["fastapi", "psycopg", "httpx"]


def test_deps_pyproject() -> None:
    text = (
        '[project]\ndependencies = ["fastapi>=0.1", "langchain"]\n'
        '[tool.poetry.dependencies]\npython = "^3.12"\ntorch = "*"\n'
    )
    assert set(_deps_pyproject(text)) == {"fastapi", "langchain", "torch"}


def test_deps_go_mod() -> None:
    text = (
        "module x\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/foo/bar v0.1.0\n)\n"
    )
    assert _deps_go_mod(text) == ["gin", "bar"]


def test_deps_cargo() -> None:
    text = '[dependencies]\ntokio = "1"\nserde = { version = "1" }\n'
    assert set(_deps_cargo(text)) == {"tokio", "serde"}


def test_tech_from_signals_maps_to_taxonomy() -> None:
    tax = load_taxonomy()
    languages = {"Python": 12000, "Solidity": 3000, "Brainfuck": 1}
    manifests = {"package.json": json.dumps({"dependencies": {"ethers": "^6", "react": "^18"}})}
    tech = tech_from_signals(languages, manifests, tax)
    assert "Python" in tech and "Solidity" in tech
    assert "ethers.js" in tech and "React" in tech
    assert "Brainfuck" not in tech  # hors taxonomie


def _mock_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(base_url="https://api.github.com", transport=handler)


def test_client_extract_combines_languages_and_manifests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/languages"):
            return httpx.Response(200, json={"Python": 1000, "TypeScript": 500})
        if path.endswith("/contents/requirements.txt"):
            body = base64.b64encode(b"langchain\nfastapi\n").decode()
            return httpx.Response(200, json={"content": body, "encoding": "base64"})
        return httpx.Response(404, json={})

    client = GitHubStackClient(client=_mock_client(httpx.MockTransport(handler)), min_interval_s=0)
    result = client.extract("https://github.com/foo/bar")
    assert result is not None
    assert set(result.tech_stack) >= {"Python", "TypeScript", "LangChain", "FastAPI"}
    assert result.manifests == ["requirements.txt"]


def test_client_extract_returns_none_on_non_github() -> None:
    client = GitHubStackClient(
        client=_mock_client(httpx.MockTransport(lambda r: httpx.Response(200))), min_interval_s=0
    )
    assert client.extract("https://gitlab.com/foo/bar") is None


def test_client_raises_on_ratelimit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={})

    client = GitHubStackClient(client=_mock_client(httpx.MockTransport(handler)), min_interval_s=0)
    with pytest.raises(GitHubBlocked):
        client.extract("https://github.com/foo/bar")
