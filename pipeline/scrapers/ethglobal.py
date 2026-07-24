"""Scraper ETHGlobal (Next.js — données dans les payloads RSC `self.__next_f.push`).

Deux phases, parseurs purs :
  1. `parse_listing` : `/showcase?page=N` -> projets primés (uuid, slug, name, tagline).
  2. `parse_project` : `/showcase/{slug}-{uuid}` -> projet complet, dont **`event.startTime`**
     (la date d'événement que `/trends` attend depuis l'Étape 5), les prix (placement /
     prize_track / is_winner) et `sourceCodeUrl` (repo_url).

Le parsing RSC est un port du scraper JS d'origine : on isole les payloads, on les
dé-échappe, puis on extrait par regex ciblées (la structure est connue et stable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from pipeline.normalize.parse_helpers import clean, parse_place
from pipeline.normalize.schema import Hackathon, Project, project_id
from pipeline.scrapers.base import BaseScraper, ScrapeResult

BASE = "https://ethglobal.com"
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_PROJECT_LISTING_RE = re.compile(r'"uuid":"([^"]{4,12})","slug":"([^"]*)","name":"([^"]*)')


_UNICODE_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape(text: str) -> str:
    text = (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace('\\"', '"')
    )
    text = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    return text.replace("\\\\", "\\")


def extract_rsc_payloads(html: str) -> list[str]:
    """Tous les payloads `self.__next_f.push([1,"…"])`, dé-échappés (pur)."""
    return [_unescape(m.group(1)) for m in _PUSH_RE.finditer(html)]


def _find_string_end(s: str, start: int) -> int:
    i = start
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            return i
        i += 1
    return -1


def _str_field(chunk: str, key: str) -> str | None:
    """Valeur d'un champ chaîne `"key":"…"` (gère les échappements). None sinon/null."""
    kpos = chunk.find(f'"{key}":')
    if kpos == -1:
        return None
    vpos = kpos + len(key) + 3
    if vpos >= len(chunk):
        return None
    if chunk[vpos] != '"':
        return None  # null / number / objet -> non traité ici
    end = _find_string_end(chunk, vpos + 1)
    if end == -1:
        return None
    return clean(chunk[vpos + 1 : end])


@dataclass(slots=True)
class EthListing:
    uuid: str
    slug: str
    name: str
    tagline: str | None
    has_prizes: bool


def parse_listing(html: str) -> list[EthListing]:
    """**Tous** les projets d'une page showcase, `has_prizes` marqué (pur).

    On ne filtre plus sur les projets primés : `has_prizes` (dérivé en `is_winner` après
    la page projet) distingue. Le filtrage gagnants-only est une décision du scraper.
    """
    for payload in extract_rsc_payloads(html):
        pos = payload.find('"projects":[{')
        if pos == -1:
            continue
        chunk = payload[pos:]
        out: list[EthListing] = []
        for m in _PROJECT_LISTING_RE.finditer(chunk):
            local = chunk[m.start() : m.start() + 3000]
            prizes_pos = local.find('"prizes":[')
            has_prizes = prizes_pos != -1 and local[prizes_pos + 10 :].lstrip()[:1] != "]"
            out.append(
                EthListing(
                    uuid=m.group(1),
                    slug=m.group(2),
                    name=clean(m.group(3)) or m.group(2),
                    tagline=_str_field(local, "tagline"),
                    has_prizes=has_prizes,
                )
            )
        return out
    return []


def _parse_start_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


@dataclass(slots=True)
class EthProject:
    uuid: str
    slug: str
    name: str
    tagline: str | None
    repo_url: str | None
    description: str | None
    event_slug: str | None
    event_name: str | None
    event_date: date | None
    placement: int | None
    is_winner: bool
    prize_track: str | None
    raw_placement: str | None


def _extract_prizes(chunk: str) -> list[tuple[str | None, str | None]]:
    """Liste (item_name, prize_name) du premier tableau "prizes":[…] du chunk."""
    pp = chunk.find('"prizes":[')
    if pp == -1:
        return []
    i = pp + 10
    if i < len(chunk) and chunk[i] == "]":
        return []
    prizes: list[tuple[str | None, str | None]] = []
    end = min(len(chunk), i + 6000)
    while i < end:
        if chunk[i] == "]":
            break
        if chunk[i] != "{":
            i += 1
            continue
        item = chunk[i : i + 1200]
        item_name = _str_field(item, "name")
        prize_name = None
        prize_obj = item.find('"prize":{')
        if prize_obj != -1:
            prize_name = _str_field(item[prize_obj:], "name")
        prizes.append((item_name, prize_name))
        depth, j = 1, i + 1
        while j < end and depth > 0:
            if chunk[j] == "{":
                depth += 1
            elif chunk[j] == "}":
                depth -= 1
            j += 1
        i = j
    return prizes


def _extract_description(payloads: list[str]) -> str | None:
    """Repli : la description vit dans un chunk RSC texte séparé `NN:T…`."""
    for payload in payloads:
        text = re.match(r"\w+:T[0-9a-fA-F]+,([\s\S]+)", payload)
        if text and len(text.group(1)) > 80:
            return clean(text.group(1))
    return None


def _pick_description(field_value: str | None, payloads: list[str]) -> str | None:
    """Description finale : le champ inline s'il est du texte, sinon le chunk texte.

    Une valeur `$28` est une *référence* RSC (chunk chargé à part), pas la description :
    on retombe alors sur le chunk texte `NN:T…` (un seul par page projet en pratique).
    """
    if field_value and not field_value.startswith("$"):
        return field_value
    return _extract_description(payloads)


def parse_project(html: str) -> EthProject | None:
    """Projet complet depuis sa page showcase (pur)."""
    payloads = extract_rsc_payloads(html)
    for payload in payloads:
        pstart = payload.find('"project":{')
        if pstart == -1:
            continue
        chunk = payload[pstart + 10 : pstart + 20000]
        uuid = _str_field(chunk, "uuid")
        name = _str_field(chunk, "name")
        if not uuid and not name:
            continue

        ev_pos = chunk.find('"event":{')
        event_slug = event_name = None
        event_date: date | None = None
        if ev_pos != -1:
            ev = chunk[ev_pos + 9 : ev_pos + 500]
            event_slug = _str_field(ev, "slug")
            event_name = _str_field(ev, "name")
            event_date = _parse_start_date(_str_field(ev, "startTime"))

        prizes = _extract_prizes(chunk)
        is_winner = len(prizes) > 0
        best_place: int | None = None
        prize_track: str | None = None
        raw_placement: str | None = None
        for item_name, prize_name in prizes:
            place = parse_place(item_name)
            if place is not None and (best_place is None or place < best_place):
                best_place = place
                prize_track = prize_name
                raw_placement = item_name
        if prize_track is None and prizes:
            prize_track = prizes[0][1] or prizes[0][0]
            raw_placement = raw_placement or prizes[0][0]

        repo = _str_field(chunk, "sourceCodeUrl") or _str_field(chunk, "url")
        return EthProject(
            uuid=uuid or "",
            slug=_str_field(chunk, "slug") or (uuid or ""),
            name=name or (uuid or ""),
            tagline=_str_field(chunk, "tagline"),
            repo_url=repo,
            description=_pick_description(_str_field(chunk, "description"), payloads),
            event_slug=event_slug,
            event_name=event_name,
            event_date=event_date,
            placement=best_place,
            is_winner=is_winner,
            prize_track=prize_track,
            raw_placement=raw_placement,
        )
    return None


class EthglobalScraper(BaseScraper):
    source = "ethglobal"

    def scrape(self, limit: int | None = None, winners_only: bool = False) -> ScrapeResult:
        result = ScrapeResult()
        seen_hackathons: set[str] = set()
        queue = self._scan_listing(limit, winners_only)
        for listing in queue:
            url = f"{BASE}/showcase/{listing.slug}-{listing.uuid}"
            project = parse_project(self.fetch(url).text)
            if project is None:
                continue
            proj, hackathon = self._to_schema(project, url)
            result.projects.append(proj)
            if hackathon.slug not in seen_hackathons:
                seen_hackathons.add(hackathon.slug)
                result.hackathons.append(hackathon)
            if limit is not None and len(result.projects) >= limit:
                break
        return result

    def _scan_listing(self, limit: int | None, winners_only: bool) -> list[EthListing]:
        found: list[EthListing] = []
        seen: set[str] = set()
        page = 1
        while page <= 600:
            url = f"{BASE}/showcase?page={page}"
            fetched = self.fetch(url)
            batch = parse_listing(fetched.text)
            if not batch and 'href="/showcase/' not in fetched.text:
                break
            for item in batch:
                if winners_only and not item.has_prizes:
                    continue
                if item.uuid not in seen:
                    seen.add(item.uuid)
                    found.append(item)
            if limit is not None and len(found) >= limit:
                return found[:limit]
            page += 1
        return found

    def _to_schema(self, p: EthProject, url: str) -> tuple[Project, Hackathon]:
        hk_slug = p.event_slug or p.uuid
        hk_name = p.event_name or hk_slug
        project = Project(
            id=project_id("ethglobal", p.slug),
            source="ethglobal",
            source_url=p.repo_url or url,
            hackathon_slug=hk_slug,
            hackathon_name=hk_name,
            hackathon_date=p.event_date,
            title=p.name,
            description=p.description,
            short_description=p.tagline,
            placement=p.placement,
            raw_placement=p.raw_placement,
            is_winner=p.is_winner,
            prize_track=p.prize_track,
            repo_url=p.repo_url if p.repo_url and "github.com" in p.repo_url else None,
        )
        hackathon = Hackathon(
            source="ethglobal", slug=hk_slug, name=hk_name, hackathon_date=p.event_date
        )
        return project, hackathon
