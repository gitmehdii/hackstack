"""Scraper Devpost : liste de hackathons (API JSON) -> gallery HTML -> page projet.

Trois phases, chacune avec un parseur pur (testable sur fixture figée) :
  1. `parse_hackathon_list` : API `/api/hackathons` -> hackathons terminés avec gagnants
     annoncés, + date d'événement quand elle est exploitable.
  2. `parse_gallery` : `{slug}.devpost.com/project-gallery?sort=prize` -> entrées gagnantes.
  3. `parse_software_page` : `devpost.com/software/{slug}` -> description intégrale
     (comble la dette « devpost = short_description seulement » du corpus importé).
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from selectolax.parser import HTMLParser

from pipeline.normalize.parse_helpers import clean
from pipeline.normalize.schema import Hackathon, Project, RawTech, project_id
from pipeline.scrapers.base import BaseScraper, ScrapeResult

HACKATHONS_API = (
    "https://devpost.com/api/hackathons"
    "?status%5B%5D=ended&order_by=recent-deadline&per_page=50&page={page}"
)
_SUBDOMAIN_RE = re.compile(r"https?://([^.]+)\.devpost\.com")
_MAX_GALLERY_PAGES = 50


# --- Phase 1 : liste des hackathons ------------------------------------------------


_MONTHS_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*")


def _parse_devpost_date(text: str | None) -> date | None:
    """Best-effort : date de FIN de soumission depuis un libellé devpost, ou None.

    Formats vus : 'Apr 05 - 06, 2024' (même mois), 'Jun 16 - Jul 16, 2026' (mois croisé).
    Heuristique : l'année finale + le jour qui la précède + le dernier mois nommé.
    """
    if not text:
        return None
    year_m = re.search(r"(\d{4})", text)
    day_m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?,?\s+\d{4}", text)
    months = _MONTHS_RE.findall(text)
    if not (year_m and day_m and months):
        return None
    try:
        return datetime.strptime(
            f"{months[-1]} {int(day_m.group(1))} {year_m.group(1)}", "%b %d %Y"
        ).date()
    except ValueError:
        return None


@dataclass(slots=True)
class DevpostHackathon:
    title: str
    slug: str
    hackathon_date: date | None


def parse_hackathon_list(payload: dict[str, Any]) -> list[DevpostHackathon]:
    """Hackathons terminés avec gagnants annoncés (pur)."""
    out: list[DevpostHackathon] = []
    for h in payload.get("hackathons") or []:
        if not h.get("winners_announced"):
            continue
        url = h.get("url") or ""
        m = _SUBDOMAIN_RE.match(url)
        if not m:
            continue
        title = clean(h.get("title")) or m.group(1)
        hackathon_date = _parse_devpost_date(h.get("submission_period_dates"))
        out.append(DevpostHackathon(title=title, slug=m.group(1), hackathon_date=hackathon_date))
    return out


def hackathon_list_meta(payload: dict[str, Any]) -> tuple[int, int]:
    """(total_count, per_page) pour piloter la pagination."""
    meta = payload.get("meta") or {}
    return int(meta.get("total_count") or 0), int(meta.get("per_page") or 50)


# --- Phase 2 : gallery d'un hackathon ----------------------------------------------


@dataclass(slots=True)
class GalleryEntry:
    software_slug: str
    url: str
    title: str
    tagline: str | None
    is_winner: bool
    prize_track: str | None
    team_name: str | None


def parse_gallery(html: str) -> list[GalleryEntry]:
    """**Toutes** les entrées d'une page de gallery, gagnants marqués (pur, selectolax).

    On ne filtre plus sur les gagnants : `is_winner` distingue. Un gagnant porte un ruban
    `<img class="winner">` dans un `<aside class="entry-badge">` ; le libellé du prix est le
    texte du badge.
    """
    tree = HTMLParser(html)
    entries: list[GalleryEntry] = []
    for node in tree.css("[data-software-id]"):
        badge = node.css_first("aside.entry-badge")
        is_winner = node.css_first("img.winner") is not None or bool(
            badge and "winner" in badge.text().lower()
        )
        link = node.css_first("a.link-to-software") or node.css_first('a[href*="/software/"]')
        href = link.attributes.get("href") if link else None
        if not href:
            continue
        m = re.search(r"/software/([^/?#]+)", href)
        if not m:
            continue
        title_node = node.css_first("h5")
        title = clean(title_node.text()) if title_node else None
        tag_node = node.css_first("p.tagline")
        tagline = clean(tag_node.text()) if tag_node else None
        seen: set[str] = set()
        members: list[str] = []
        for img in node.css(".members img[alt], .user-profile-link img[alt]"):
            name = clean(img.attributes.get("alt"))
            if name and name not in seen:
                seen.add(name)
                members.append(name)
        team = ", ".join(members) or None
        entries.append(
            GalleryEntry(
                software_slug=m.group(1),
                url=href.split("?")[0],
                title=title or m.group(1),
                tagline=tagline,
                is_winner=is_winner,
                prize_track=clean(badge.text()) if (badge and is_winner) else None,
                team_name=team,
            )
        )
    return entries


# --- Phase 3 : page projet (description + repo + demo + tech) -----------------------


@dataclass(slots=True)
class SoftwareDetail:
    description: str | None
    repo_url: str | None
    demo_url: str | None
    tech: list[str]


def parse_software_page(html: str) -> SoftwareDetail:
    """Détails d'une page /software/{slug} : description, repo, démo, « Built With » (pur)."""
    tree = HTMLParser(html)

    description: str | None = None
    container = tree.css_first("#app-details-left") or tree.css_first("div#software-description")
    if container is not None:
        description = clean(container.text(separator=" ", strip=True))
    if not description:
        meta = tree.css_first('meta[name="description"]')
        if meta is not None:
            description = clean(meta.attributes.get("content"))

    # Liens « Try it out » : premier lien GitHub = repo, premier autre = démo.
    repo_url: str | None = None
    demo_url: str | None = None
    for a in tree.css("nav.app-links a, .app-links a"):
        href = clean(a.attributes.get("href"))
        if not href or not href.startswith("http"):
            continue
        if "github.com" in href and repo_url is None:
            repo_url = href
        elif "github.com" not in href and demo_url is None:
            demo_url = href

    # « Built With » : liste de technos déclarées (signal fiable, -> raw_project_tech).
    tech = [clean(t.text()) or "" for t in tree.css("#built-with .cp-tag")]
    tech = [t for t in tech if t]

    return SoftwareDetail(description=description, repo_url=repo_url, demo_url=demo_url, tech=tech)


# --- Orchestration -----------------------------------------------------------------


class DevpostScraper(BaseScraper):
    source = "devpost"

    def scrape(self, limit: int | None = None, winners_only: bool = False) -> ScrapeResult:
        result = ScrapeResult()
        hackathons = self._list_hackathons(limit)
        for hk in hackathons:
            result.hackathons.append(
                Hackathon(
                    source="devpost",
                    slug=hk.slug,
                    name=hk.title,
                    hackathon_date=hk.hackathon_date,
                    url=f"https://{hk.slug}.devpost.com",
                )
            )
            for entry in self._gallery_entries(hk.slug):
                if winners_only and not entry.is_winner:
                    continue
                project, raw_techs = self._entry_to_project(hk, entry)
                result.projects.append(project)
                result.raw_techs.extend(raw_techs)
                if limit is not None and len(result.projects) >= limit:
                    return result
        return result

    def _list_hackathons(self, limit: int | None) -> list[DevpostHackathon]:
        out: list[DevpostHackathon] = []
        page = 1
        while page <= _MAX_GALLERY_PAGES:
            payload = self.fetch_json(HACKATHONS_API.format(page=page))
            batch = parse_hackathon_list(payload)
            out.extend(batch)
            _, per_page = hackathon_list_meta(payload)
            n_raw = len(payload.get("hackathons") or [])
            if limit is not None and out:
                break  # un hackathon suffit à alimenter un smoke-scrape borné
            if n_raw < per_page or n_raw == 0:
                break
            page += 1
        return out

    def _gallery_entries(self, slug: str) -> list[GalleryEntry]:
        entries: list[GalleryEntry] = []
        page = 1
        empty_streak = 0
        while page <= _MAX_GALLERY_PAGES:
            url = f"https://{slug}.devpost.com/project-gallery?sort=prize&page={page}"
            found = parse_gallery(self.fetch(url).text)
            if not found:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
                entries.extend(found)
            page += 1
        return entries

    def _entry_to_project(
        self, hk: DevpostHackathon, entry: GalleryEntry
    ) -> tuple[Project, list[RawTech]]:
        pid = project_id("devpost", entry.software_slug)
        detail = SoftwareDetail(description=None, repo_url=None, demo_url=None, tech=[])
        # robots interdit la page projet : on garde les infos de la gallery.
        with contextlib.suppress(PermissionError):
            detail = parse_software_page(self.fetch(entry.url).text)
        raw_techs = [
            RawTech(project_id=pid, source="devpost", tech_name=name) for name in detail.tech
        ]
        project = Project(
            id=pid,
            source="devpost",
            source_url=entry.url,
            hackathon_slug=hk.slug,
            hackathon_name=hk.title,
            hackathon_date=hk.hackathon_date,
            title=entry.title,
            description=detail.description,
            short_description=entry.tagline,
            placement=None,
            raw_placement="WINNER" if entry.is_winner else None,
            is_winner=entry.is_winner,
            prize_track=entry.prize_track,
            team_name=entry.team_name,
            repo_url=detail.repo_url,
            demo_url=detail.demo_url,
        )
        return project, raw_techs
