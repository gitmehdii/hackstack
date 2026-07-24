"""Scraper lablab.ai (API JSON `/api/v4/submissions`).

L'**API JSON publique** est accessible poliment (200, pas de challenge) et permise par
`robots.txt` — `scrape()` la pagine par cursor. Seule la surface **HTML** (`/apps/...`)
est derrière Cloudflare ; on n'en a pas besoin, et si l'API venait à être challengée un
jour, `detect_block` s'en charge (arrêt, jamais de contournement — pas de cookie
cf_clearance, pas de fingerprint TLS).

`ingest_archive()` reste disponible pour rejouer un export JSON de l'API hors ligne
(ex. `winners.json`). Le parsing (`parse_submissions`) est pur : testable sur fixture
figée, sans réseau.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.normalize.parse_helpers import LABLAB_MAP, clean
from pipeline.normalize.schema import Hackathon, Project, RawTech, project_id
from pipeline.scrapers.base import BaseScraper, ScrapeResult

_API_BASE = "https://lablab.ai/api/v4/submissions?take=50&order=desc"
# filter=winners = projets placés (WINNERS/TOP_2/TOP_3/FINALISTS) ; sans filtre = toutes
# les soumissions (les non-placés arrivent en position OTHER).
API_URL = f"{_API_BASE}&filter=winners"
API_URL_ALL = _API_BASE


def _submission_to_project(sub: dict[str, Any]) -> tuple[Project, list[RawTech]] | None:
    slug = clean(sub.get("slug"))
    if not slug:
        return None
    event = sub.get("event") or {}
    hk_slug = clean(event.get("slug")) or slug
    hk_name = clean(event.get("name")) or hk_slug

    placement, is_winner = LABLAB_MAP.get(sub.get("eventPosition") or "", (None, False))
    team = sub.get("team") or {}

    pid = project_id("lablab", slug)
    project = Project(
        id=pid,
        source="lablab",
        source_url=f"https://lablab.ai/p/{slug}",
        hackathon_slug=hk_slug,
        hackathon_name=hk_name,
        hackathon_date=None,  # absent du payload API
        title=clean(sub.get("title")) or slug,
        description=clean(sub.get("description")),
        short_description=clean(sub.get("shortDescription")),
        placement=placement,
        raw_placement=clean(sub.get("eventPosition")),
        is_winner=is_winner,
        team_name=clean(team.get("name")),
        demo_url=clean(sub.get("videoLink")),
    )

    raw_techs: list[RawTech] = []
    for entry in sub.get("techIn") or []:
        tech = (entry or {}).get("tech") or {}
        name = clean(tech.get("name"))
        if name:
            raw_techs.append(
                RawTech(
                    project_id=pid,
                    source="lablab",
                    tech_name=name,
                    tech_slug=clean(tech.get("slug")),
                )
            )
    return project, raw_techs


def parse_submissions(payload: dict[str, Any]) -> ScrapeResult:
    """Transforme une réponse `/api/v4/submissions` en lot normalisé (pur, sans réseau)."""
    result = ScrapeResult()
    seen_hackathons: set[str] = set()
    for sub in payload.get("submissions") or []:
        parsed = _submission_to_project(sub)
        if parsed is None:
            continue
        project, raw_techs = parsed
        result.projects.append(project)
        result.raw_techs.extend(raw_techs)
        if project.hackathon_slug not in seen_hackathons:
            seen_hackathons.add(project.hackathon_slug)
            result.hackathons.append(
                Hackathon(
                    source="lablab",
                    slug=project.hackathon_slug,
                    name=project.hackathon_name,
                )
            )
    return result


def ingest_archive(path: str | Path) -> ScrapeResult:
    """Lit un export JSON de l'API lablab (winners.json) et le normalise. Hors ligne."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):  # tolère un dump = liste brute de submissions
        payload = {"submissions": payload}
    return parse_submissions(payload)


class LablabScraper(BaseScraper):
    source = "lablab"

    def scrape(self, limit: int | None = None, winners_only: bool = False) -> ScrapeResult:
        """Live via l'API JSON publique, paginé par cursor.

        `winners_only` → feed `filter=winners` (placés) ; sinon feed complet (tous les
        projets, is_winner posé par eventPosition).
        """
        base = API_URL if winners_only else API_URL_ALL
        merged = ScrapeResult()
        seen_hackathons: set[str] = set()
        url: str | None = base
        while url is not None:
            payload = self.fetch_json(url)
            batch = parse_submissions(payload)
            merged.projects.extend(batch.projects)
            merged.raw_techs.extend(batch.raw_techs)
            for hk in batch.hackathons:
                if hk.slug not in seen_hackathons:
                    seen_hackathons.add(hk.slug)
                    merged.hackathons.append(hk)
            if limit is not None and len(merged.projects) >= limit:
                merged.projects = merged.projects[:limit]
                break
            cursor = payload.get("nextCursor")
            url = f"{base}&cursor={cursor}" if cursor else None
        return merged
