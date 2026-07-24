"""Tests de contrat du socle scraper : politesse, robots.txt, anti-bot, cache.

Aucun réseau : le client httpx est piloté par un MockTransport.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from pipeline.scrapers.base import (
    BaseScraper,
    ScraperBlocked,
    ScrapeResult,
    _RateLimiter,
    detect_block,
)

FIXTURES = Path(__file__).parent / "fixtures"


class _Probe(BaseScraper):
    """Scraper minimal pour exercer la couche HTTP de la base."""

    source = "probe"

    def scrape(
        self, limit: int | None = None, winners_only: bool = False
    ) -> ScrapeResult:  # pragma: no cover
        return ScrapeResult()


def _scraper(handler: httpx.MockTransport, **kw: object) -> _Probe:
    client = httpx.Client(transport=handler, base_url="https://example.test")
    return _Probe(client=client, **kw)  # type: ignore[arg-type]


def test_rate_limiter_enforces_interval_per_domain() -> None:
    limiter = _RateLimiter(min_interval_s=0.05)
    limiter.wait("a.test")  # premier appel : immédiat
    start = time.monotonic()
    limiter.wait("a.test")  # deuxième : doit attendre l'intervalle
    assert time.monotonic() - start >= 0.05
    # un autre domaine n'est pas pénalisé par l'attente du premier
    start = time.monotonic()
    limiter.wait("b.test")
    assert time.monotonic() - start < 0.05


def test_detect_block_on_cloudflare_challenge() -> None:
    html = (FIXTURES / "lablab_cloudflare_challenge.html").read_text(encoding="utf-8")
    blocked = detect_block("https://lablab.ai/api/v4/submissions", 403, html)
    assert isinstance(blocked, ScraperBlocked)
    assert blocked.status == 403
    assert blocked.marker is not None


def test_detect_block_bare_403_stops() -> None:
    blocked = detect_block("https://x.test/p", 403, "<html>Forbidden</html>")
    assert isinstance(blocked, ScraperBlocked)
    assert blocked.marker is None


def test_detect_block_passes_normal_pages() -> None:
    assert detect_block("https://x.test/p", 200, "<html>ok</html>") is None
    assert detect_block("https://x.test/p", 404, "<html>not found</html>") is None


def test_fetch_raises_scraper_blocked_on_challenge() -> None:
    html = (FIXTURES / "lablab_cloudflare_challenge.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(403, text=html)

    scraper = _scraper(httpx.MockTransport(handler))
    with pytest.raises(ScraperBlocked):
        scraper.fetch("https://example.test/api")


def test_robots_disallow_blocks_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret\n")
        return httpx.Response(200, text="ok")

    scraper = _scraper(httpx.MockTransport(handler))
    assert scraper.allowed("https://example.test/public") is True
    assert scraper.allowed("https://example.test/secret/x") is False
    with pytest.raises(PermissionError):
        scraper.fetch("https://example.test/secret/x")


def test_cache_hit_avoids_second_request(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        calls["n"] += 1
        return httpx.Response(200, text="payload")

    scraper = _scraper(httpx.MockTransport(handler), use_cache=True, cache_dir=tmp_path)
    first = scraper.fetch("https://example.test/data")
    second = scraper.fetch("https://example.test/data")
    assert first.text == second.text == "payload"
    assert calls["n"] == 1  # deuxième appel servi par le cache
