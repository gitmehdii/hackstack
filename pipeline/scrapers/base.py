"""Socle commun des scrapers : politesse, robots.txt, anti-bot, cache, rate limit.

Reprend et généralise le patron déjà éprouvé dans
`pipeline/normalize/github_stack.py` (throttle mono-hôte + arrêt sur blocage). Ici le
rate limit est par domaine, robots.txt est respecté, et un blocage anti-bot lève
`ScraperBlocked` — jamais de contournement (cookie Cloudflare, fingerprint TLS, captcha).

Séparation stricte :
  - la couche HTTP (fetch, cache, throttle, détection anti-bot) vit dans `BaseScraper` ;
  - le parsing de chaque source est en fonctions pures (testables sur fixtures figées,
    sans réseau) dans le module de la source.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from pipeline.normalize.schema import Hackathon, Project, RawTech

# UA identifiable pointant vers le repo (PROJECT.md). Même chaîne que github_stack.
USER_AGENT = "hackstack-bot/0.1 (+https://github.com/gitmehdii/hackstack)"

MIN_INTERVAL_S = 1.0  # 1 req/s max par domaine (PROJECT.md)
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.0
_CACHE_DIR = Path(".http_cache")

# Marqueurs de challenge anti-bot, appliqués quand le STATUT est déjà suspect (403/503).
_BLOCK_MARKERS = (
    "just a moment",
    "cf-chl",
    "cf_chl_opt",
    "attention required! | cloudflare",
    "_cf_chl_",
    "challenge-platform",
    "captcha",
    "verify you are human",
)

# Marqueurs stricts pour un corps en 200 (interstitiel Cloudflare) : tokens spécifiques à
# Cloudflare, quasi impossibles dans du texte utilisateur — sinon on risque un faux positif
# sur une description qui parle de « challenge platform » ou dit « just a moment ».
_STRICT_BLOCK_MARKERS = (
    "cf_chl_opt",
    "cdn-cgi/challenge-platform",
)


class ScraperBlocked(RuntimeError):
    """Blocage anti-bot (Cloudflare/captcha/403 systématique). On s'arrête, pas de contournement."""

    def __init__(self, message: str, *, url: str, status: int | None, marker: str | None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.marker = marker

    def as_notes(self) -> str:
        """Rapport structuré (JSON) pour scrape_runs.notes."""
        return json.dumps(
            {"reason": "blocked", "url": self.url, "status": self.status, "marker": self.marker}
        )


@dataclass(slots=True)
class ScrapeResult:
    projects: list[Project] = field(default_factory=list)
    hackathons: list[Hackathon] = field(default_factory=list)
    raw_techs: list[RawTech] = field(default_factory=list)


@dataclass(slots=True)
class Fetched:
    url: str
    status: int
    text: str


def detect_block(url: str, status: int, text: str) -> ScraperBlocked | None:
    """Renvoie un ScraperBlocked si la réponse ressemble à un challenge anti-bot, sinon None.

    Pur (pas de réseau) pour être testable sur une fixture de challenge figée.
    """
    lowered = text.lower()
    # 403/503 accompagnés d'un marqueur = challenge presque certain.
    if status in (403, 503):
        for marker in _BLOCK_MARKERS:
            if marker in lowered:
                return ScraperBlocked(
                    f"challenge anti-bot ({marker}) sur {url}",
                    url=url,
                    status=status,
                    marker=marker,
                )
        # 403 sans marqueur = blocage sec (systématique) : on s'arrête aussi.
        if status == 403:
            return ScraperBlocked(f"403 sur {url}", url=url, status=403, marker=None)
    # Même en 200, un interstitiel Cloudflare doit être attrapé — mais seulement sur des
    # tokens stricts, pour ne pas confondre avec une description utilisateur.
    for marker in _STRICT_BLOCK_MARKERS:
        if marker in lowered:
            return ScraperBlocked(
                f"page de challenge ({marker}) sur {url}", url=url, status=status, marker=marker
            )
    return None


class _RateLimiter:
    """Intervalle minimum entre deux requêtes, par domaine (netloc)."""

    def __init__(self, min_interval_s: float = MIN_INTERVAL_S) -> None:
        self._min = min_interval_s
        self._last: dict[str, float] = {}

    def wait(self, netloc: str) -> None:
        last = self._last.get(netloc, 0.0)
        gap = self._min - (time.monotonic() - last)
        if gap > 0:
            time.sleep(gap)
        self._last[netloc] = time.monotonic()


class _HttpCache:
    """Cache disque optionnel pour le dev : évite de re-frapper les sites (politesse)."""

    def __init__(self, directory: Path = _CACHE_DIR) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode()).hexdigest()
        return self._dir / f"{key}.json"

    def get(self, url: str) -> Fetched | None:
        path = self._path(url)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Fetched(url=url, status=int(data["status"]), text=data["text"])

    def put(self, fetched: Fetched) -> None:
        self._path(fetched.url).write_text(
            json.dumps({"status": fetched.status, "text": fetched.text}),
            encoding="utf-8",
        )


class BaseScraper(ABC):
    """Base HTTP polie et injectable.

    Le client httpx est injectable pour tester sans réseau (transport mock).
    """

    source: str = ""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        use_cache: bool = False,
        cache_dir: Path | None = None,
        min_interval_s: float = MIN_INTERVAL_S,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
        )
        self._limiter = _RateLimiter(min_interval_s)
        self._cache = _HttpCache(cache_dir or _CACHE_DIR) if use_cache else None
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    # --- robots.txt --------------------------------------------------------------

    def _robots_for(self, netloc: str, scheme: str) -> urllib.robotparser.RobotFileParser:
        rp = self._robots.get(netloc)
        if rp is not None:
            return rp
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{scheme}://{netloc}/robots.txt"
        try:
            self._limiter.wait(netloc)
            resp = self._client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])  # pas de robots.txt lisible -> tout autorisé par défaut
        except httpx.HTTPError:
            rp.parse([])
        self._robots[netloc] = rp
        return rp

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        rp = self._robots_for(parsed.netloc, parsed.scheme or "https")
        return rp.can_fetch(USER_AGENT, url)

    # --- fetch -------------------------------------------------------------------

    def fetch(self, url: str, *, check_robots: bool = True) -> Fetched:
        """GET poli : cache, robots.txt, rate limit, retry transitoire, détection anti-bot.

        Lève ScraperBlocked sur challenge anti-bot (jamais de contournement).
        Lève PermissionError si robots.txt interdit l'URL.
        """
        if self._cache is not None:
            hit = self._cache.get(url)
            if hit is not None:
                blocked = detect_block(hit.url, hit.status, hit.text)
                if blocked is not None:
                    raise blocked
                return hit

        if check_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt interdit {url}")

        parsed = urlparse(url)
        fetched = self._request_with_retry(url, parsed.netloc)

        blocked = detect_block(fetched.url, fetched.status, fetched.text)
        if blocked is not None:
            raise blocked
        if self._cache is not None:
            self._cache.put(fetched)
        return fetched

    def _request_with_retry(self, url: str, netloc: str) -> Fetched:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            self._limiter.wait(netloc)
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:  # timeout / réseau : transitoire
                last_exc = exc
                time.sleep(_BACKOFF_BASE_S * (2**attempt))
                continue
            # 5xx = transitoire (sauf 503, qui peut être un challenge -> détecté en amont).
            if resp.status_code >= 500 and resp.status_code != 503:
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} sur {url}", request=resp.request, response=resp
                )
                time.sleep(_BACKOFF_BASE_S * (2**attempt))
                continue
            return Fetched(url=str(resp.url), status=resp.status_code, text=resp.text)
        assert last_exc is not None
        raise last_exc

    def fetch_json(self, url: str, *, check_robots: bool = True) -> Any:
        return json.loads(self.fetch(url, check_robots=check_robots).text)

    # --- contrat -----------------------------------------------------------------

    @abstractmethod
    def scrape(self, limit: int | None = None, winners_only: bool = False) -> ScrapeResult:
        """Collecte et renvoie un lot normalisé (staging). Ne touche jamais `projects`.

        Par défaut capture **tous** les projets (gagnants et non-gagnants), `is_winner` les
        distingue. `winners_only=True` restreint aux gagnants.
        """
