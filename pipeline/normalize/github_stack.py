"""Passe GitHub de l'extraction tech_stack (Étape 4, source fiable).

Deux signaux, mappés sur la taxonomie fermée :
  1. langages détectés par GitHub (`GET /repos/{o}/{r}/languages`),
  2. dépendances déclarées dans les manifestes (package.json, requirements.txt,
     pyproject.toml, go.mod, Cargo.toml).

Le parsing des manifestes est en fonctions pures (testables sur fixtures, sans réseau) ;
la couche HTTP est isolée dans GitHubStackClient et injectable pour les tests.

Politesse (PROJECT.md) : User-Agent identifiable, 1 req/s max, jamais de contournement —
un 403/blocage remonte tel quel et interrompt la passe.
"""

from __future__ import annotations

import base64
import re
import time
import tomllib
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from pipeline.normalize.taxonomy import Taxonomy, load_taxonomy

USER_AGENT = "hackstack-bot/0.1 (+https://github.com/gitmehdii/hackstack)"

MANIFESTS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
)


@dataclass(frozen=True)
class GitHubResult:
    tech_stack: list[str]
    languages: dict[str, int]
    manifests: list[str]  # manifestes effectivement lus


def parse_repo_url(url: str) -> tuple[str, str] | None:
    """Extrait (owner, repo) d'une URL GitHub, ou None si ce n'en est pas une."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if "github.com" not in (parsed.netloc or "").lower():
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


# --- Parsing des manifestes (pur, sans réseau) --------------------------------------


def _deps_package_json(text: str) -> list[str]:
    import json

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    names: list[str] = []
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.extend(str(k) for k in section)
    return names


_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def _deps_requirements_txt(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "http://", "https://", "git+")):
            continue
        m = _REQ_LINE.match(line)
        if m:
            names.append(m.group(1))
    return names


def _deps_pyproject(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    names: list[str] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        for spec in project.get("dependencies", []) or []:
            m = _REQ_LINE.match(str(spec))
            if m:
                names.append(m.group(1))
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        deps = poetry.get("dependencies", {})
        if isinstance(deps, dict):
            names.extend(str(k) for k in deps if str(k).lower() != "python")
    return names


_GOMOD_LINE = re.compile(r"^\s*([\w./-]+)\s+v")


def _deps_go_mod(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        m = _GOMOD_LINE.match(line)
        if m:
            # dernier segment du chemin de module (github.com/x/gin -> gin)
            names.append(m.group(1).rsplit("/", 1)[-1])
    return names


def _deps_cargo(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    deps = data.get("dependencies", {})
    return [str(k) for k in deps] if isinstance(deps, dict) else []


_MANIFEST_PARSERS = {
    "package.json": _deps_package_json,
    "requirements.txt": _deps_requirements_txt,
    "pyproject.toml": _deps_pyproject,
    "go.mod": _deps_go_mod,
    "Cargo.toml": _deps_cargo,
}


def tech_from_signals(
    languages: dict[str, int],
    manifest_texts: dict[str, str],
    tax: Taxonomy,
) -> list[str]:
    """Combine langages + dépendances de manifestes en tech_stack normalisé (pur)."""
    raw: list[str] = list(languages.keys())
    for name, text in manifest_texts.items():
        parser = _MANIFEST_PARSERS.get(name)
        if parser:
            raw.extend(parser(text))
    return tax.clean_tech(raw)


# --- Couche HTTP --------------------------------------------------------------------


class GitHubBlocked(RuntimeError):
    """Blocage GitHub (rate limit épuisé / 403). On s'arrête, on ne contourne pas."""


class GitHubStackClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        client: httpx.Client | None = None,
        min_interval_s: float = 1.0,
    ) -> None:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = client or httpx.Client(
            base_url="https://api.github.com", headers=headers, timeout=15.0
        )
        self._min_interval = min_interval_s
        self._last_call = 0.0
        self._tax = load_taxonomy()

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, path: str) -> httpx.Response:
        self._throttle()
        resp = self._client.get(path)
        if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubBlocked("rate limit GitHub épuisé")
        if resp.status_code == 403:
            raise GitHubBlocked(f"403 GitHub sur {path}")
        return resp

    def _root_manifests(self, owner: str, repo: str) -> list[str]:
        """Manifestes de `MANIFESTS` présents à la racine du dépôt, en un seul appel.

        Renvoie une liste vide si la racine est illisible (dépôt vide, 404) : on préfère
        rater des manifestes que dépenser cinq appels à le vérifier.

        Seule différence avec l'ancien sondage direct : GitHub plafonne ce listing à
        1 000 entrées, donc un dépôt ayant plus de 1 000 fichiers à sa racine pourrait
        voir son manifeste manqué. Cas assez théorique, et la dégradation est douce —
        on retombe sur les seuls langages, comme quand un manifeste est absent.
        """
        resp = self._get(f"/repos/{owner}/{repo}/contents")
        if resp.status_code != 200:
            return []
        try:
            entries = resp.json()
        except ValueError:
            return []
        if not isinstance(entries, list):
            return []
        noms = {e.get("name") for e in entries if isinstance(e, dict) and e.get("type") == "file"}
        return [m for m in MANIFESTS if m in noms]

    def extract(self, repo_url: str) -> GitHubResult | None:
        """tech_stack fiable pour un repo, ou None si l'URL/le repo est inexploitable."""
        parsed = parse_repo_url(repo_url)
        if parsed is None:
            return None
        owner, repo = parsed

        langs_resp = self._get(f"/repos/{owner}/{repo}/languages")
        if langs_resp.status_code == 404:
            return None
        languages: dict[str, int] = {}
        if langs_resp.status_code == 200:
            languages = {str(k): int(v) for k, v in langs_resp.json().items()}

        # Un listing de la racine plutôt qu'un sondage par manifeste : la plupart des
        # dépôts n'en ont qu'un, donc sonder les cinq à l'aveugle coûtait 5 appels dont 4
        # en 404. Avec le throttle d'une seconde par appel, c'était 6 s par projet contre
        # ~3 ici. Sémantique inchangée : on ne regarde que la racine, comme avant.
        present = self._root_manifests(owner, repo)

        manifest_texts: dict[str, str] = {}
        for name in present:
            r = self._get(f"/repos/{owner}/{repo}/contents/{name}")
            if r.status_code != 200:
                continue
            payload = r.json()
            content = payload.get("content")
            if not content or payload.get("encoding") != "base64":
                continue
            try:
                manifest_texts[name] = base64.b64decode(content).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                continue

        tech = tech_from_signals(languages, manifest_texts, self._tax)
        return GitHubResult(
            tech_stack=tech,
            languages=languages,
            manifests=list(manifest_texts.keys()),
        )
