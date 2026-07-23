"""Scraper Devpost : liste de hackathons (API JSON) -> gallery HTML -> page projet.

Trois phases, chacune avec un parseur pur (testable sur fixture figée) :
  1. `parse_hackathon_list` : API `/api/hackathons` -> hackathons terminés avec gagnants
     annoncés, + date d'événement quand elle est exploitable.
  2. `parse_gallery` : `{slug}.devpost.com/project-gallery?sort=prize` -> entrées gagnantes.
  3. `parse_software_page` : `devpost.com/software/{slug}` -> description intégrale
     (comble la dette « devpost = short_description seulement » du corpus importé).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from selectolax.parser import HTMLParser

from pipeline.normalize.parse_helpers import clean
from pipeline.normalize.schema import Hackathon, Project, project_id
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
    prize_track: str | None
    team_name: str | None


def parse_gallery(html: str) -> list[GalleryEntry]:
    """Entrées gagnantes d'une page de gallery (pur, selectolax)."""
    tree = HTMLParser(html)
    entries: list[GalleryEntry] = []
    for node in tree.css("[data-software-id]"):
        # Un gagnant porte un ruban <img class="winner"> dans un <aside class="entry-badge">
        # (galleries devpost, tri par prix). Le libellé du prix est le texte du badge.
        badge = node.css_first("aside.entry-badge")
        has_ribbon = node.css_first("img.winner") is not None
        if not has_ribbon and not (badge and "winner" in badge.text().lower()):
            continue
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
                prize_track=clean(badge.text()) if badge else None,
                team_name=team,
            )
        )
    return entries


# --- Phase 3 : page projet (description intégrale) ---------------------------------


def parse_software_page(html: str) -> str | None:
    """Description longue d'une page /software/{slug} (pur)."""
    tree = HTMLParser(html)
    container = tree.css_first("#app-details-left") or tree.css_first("div#software-description")
    if container is not None:
        text = clean(container.text(separator=" ", strip=True))
        if text:
            return text
    meta = tree.css_first('meta[name="description"]')
    if meta is not None:
        return clean(meta.attributes.get("content"))
    return None


# --- Orchestration -----------------------------------------------------------------


class DevpostScraper(BaseScraper):
    source = "devpost"

    def scrape(self, limit: int | None = None) -> ScrapeResult:
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
                result.projects.append(self._entry_to_project(hk, entry))
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

    def _entry_to_project(self, hk: DevpostHackathon, entry: GalleryEntry) -> Project:
        pid = project_id("devpost", entry.software_slug)
        description: str | None = None
        try:
            description = parse_software_page(self.fetch(entry.url).text)
        except PermissionError:
            description = None  # robots interdit la page projet : on garde la tagline
        return Project(
            id=pid,
            source="devpost",
            source_url=entry.url,
            hackathon_slug=hk.slug,
            hackathon_name=hk.title,
            hackathon_date=hk.hackathon_date,
            title=entry.title,
            description=description,
            short_description=entry.tagline,
            placement=None,
            raw_placement="WINNER",
            is_winner=True,
            prize_track=entry.prize_track,
            team_name=entry.team_name,
        )
