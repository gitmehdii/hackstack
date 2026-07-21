"""Import du corpus SQLite existant vers projects_staging (Étape 1).

Fusionne les deux dumps (hackathons.db = devpost + lablab, ethglobal.db = ethglobal),
normalise vers le schéma unifié, dédoublonne sur l'id déterministe, et écrit UNIQUEMENT
en staging. La promotion vers `projects` est une étape séparée (promote.py).

Usage:
    python -m pipeline.load.import_sqlite
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pipeline.load.db import connect
from pipeline.normalize.schema import Hackathon, Project, RawTech, Source, project_id

PLACE_RE = re.compile(r"(\d+)\s*(?:st|nd|rd|th)\s+place", re.IGNORECASE)

# lablab : event_position -> (placement, is_winner)
LABLAB_MAP: dict[str, tuple[int | None, bool]] = {
    "WINNERS": (1, True),
    "TOP_2": (2, True),
    "TOP_3": (3, True),
    "FINALISTS": (None, False),
    "OTHER": (None, False),
}


def _file_mtime(path: str) -> datetime:
    ts = Path(path).stat().st_mtime
    return datetime.fromtimestamp(ts, tz=UTC)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_place(text: str | None) -> int | None:
    if not text:
        return None
    m = PLACE_RE.search(text)
    return int(m.group(1)) if m else None


def _load_events(con: sqlite3.Connection) -> dict[int, tuple[str, str, str]]:
    """event_id -> (name, slug, source)."""
    rows = con.execute("SELECT id, name, slug, source FROM events").fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _load_teams(con: sqlite3.Connection) -> dict[int, str]:
    """team_id -> name (peut être vide selon la source)."""
    try:
        rows = con.execute("SELECT id, name FROM teams").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: r[1] for r in rows}


def _import_hackathons_db(
    path: str,
) -> tuple[list[Project], list[Hackathon], list[RawTech]]:
    """devpost + lablab."""
    con = sqlite3.connect(path)
    scraped_at = _file_mtime(path)
    events = _load_events(con)
    teams = _load_teams(con)

    # tech_stack brut (lablab uniquement en pratique)
    tech_by_project: dict[int, list[tuple[str, str | None]]] = {}
    tech_names = {
        r[0]: (r[1], r[2])
        for r in con.execute("SELECT id, name, slug FROM technologies").fetchall()
    }
    for proj_id, tech_id in con.execute(
        "SELECT project_id, tech_id FROM project_tech"
    ).fetchall():
        name_slug = tech_names.get(tech_id)
        if name_slug:
            tech_by_project.setdefault(proj_id, []).append(name_slug)

    projects: list[Project] = []
    hackathons: dict[tuple[str, str], Hackathon] = {}
    raw_techs: list[RawTech] = []

    rows = con.execute(
        "SELECT id, title, slug, url, short_description, description, "
        "event_position, event_id, team_id, source FROM projects"
    ).fetchall()

    for (
        sqlite_id,
        title,
        slug,
        url,
        short_desc,
        desc,
        event_position,
        event_id,
        team_id,
        source,
    ) in rows:
        if not slug:
            continue
        ev = events.get(event_id)
        if ev is None:
            continue
        hk_name, hk_slug, hk_source_raw = ev
        src = cast(Source, source)
        hk_source = cast(Source, hk_source_raw)

        if source == "lablab":
            placement, is_winner = LABLAB_MAP.get(event_position or "", (None, False))
        elif source == "devpost":
            placement, is_winner = None, True  # seuls les gagnants ont été scrapés
        else:
            placement, is_winner = None, False

        pid = project_id(source, slug)
        projects.append(
            Project(
                id=pid,
                source=src,
                source_url=url or "",
                hackathon_slug=hk_slug,
                hackathon_name=hk_name,
                hackathon_date=None,
                title=title,
                description=_clean(desc),
                short_description=_clean(short_desc),
                placement=placement,
                raw_placement=_clean(event_position),
                is_winner=is_winner,
                prize_track=None,
                team_name=teams.get(team_id),
                repo_url=None,
                demo_url=None,
                scraped_at=scraped_at,
            )
        )
        hackathons[(hk_source, hk_slug)] = Hackathon(
            source=hk_source, slug=hk_slug, name=hk_name
        )
        for tname, tslug in tech_by_project.get(sqlite_id, []):
            raw_techs.append(
                RawTech(project_id=pid, source=src, tech_name=tname, tech_slug=tslug)
            )

    con.close()
    return projects, list(hackathons.values()), raw_techs


def _import_ethglobal_db(
    path: str,
) -> tuple[list[Project], list[Hackathon], list[RawTech]]:
    con = sqlite3.connect(path)
    scraped_at = _file_mtime(path)
    events = _load_events(con)

    # Prix par projet : sert à dériver placement / is_winner / prize_track.
    prizes: dict[int, list[tuple[str | None, str | None]]] = {}
    for proj_id, item_name, prize_name in con.execute(
        "SELECT project_id, item_name, prize_name FROM prizes"
    ).fetchall():
        prizes.setdefault(proj_id, []).append((item_name, prize_name))

    projects: list[Project] = []
    hackathons: dict[tuple[str, str], Hackathon] = {}

    rows = con.execute(
        "SELECT id, title, slug, url, short_description, description, "
        "event_position, event_id, source FROM projects"
    ).fetchall()

    for (
        sqlite_id,
        title,
        slug,
        url,
        short_desc,
        desc,
        event_position,
        event_id,
        source,
    ) in rows:
        if not slug:
            continue
        ev = events.get(event_id)
        if ev is None:
            continue
        hk_name, hk_slug, _ = ev
        src = cast(Source, source)

        # placement = meilleur rang trouvé dans les prix ; is_winner = au moins un prix.
        project_prizes = prizes.get(sqlite_id, [])
        is_winner = len(project_prizes) > 0
        best_place: int | None = None
        prize_track: str | None = None
        raw_placement: str | None = _clean(event_position)
        for item_name, prize_name in project_prizes:
            place = _parse_place(item_name)
            if place is not None and (best_place is None or place < best_place):
                best_place = place
                prize_track = _clean(prize_name)
                raw_placement = _clean(item_name)
        if prize_track is None and project_prizes:
            prize_track = _clean(project_prizes[0][1])

        url = _clean(url)
        repo_url = url if (url and "github.com" in url) else None

        pid = project_id(source, slug)
        projects.append(
            Project(
                id=pid,
                source=src,
                source_url=url or "",
                hackathon_slug=hk_slug,
                hackathon_name=hk_name,
                hackathon_date=None,
                title=title,
                description=_clean(desc),
                short_description=_clean(short_desc),
                placement=best_place,
                raw_placement=raw_placement,
                is_winner=is_winner,
                prize_track=prize_track,
                repo_url=repo_url,
                demo_url=None,
                scraped_at=scraped_at,
            )
        )
        hackathons[(src, hk_slug)] = Hackathon(source=src, slug=hk_slug, name=hk_name)

    con.close()
    return projects, list(hackathons.values()), []


def _dedup(projects: list[Project]) -> tuple[list[Project], int]:
    """Premier gagnant sur l'id déterministe. Retourne (uniques, n_collisions)."""
    seen: dict[str, Project] = {}
    collisions = 0
    for p in projects:
        if p.id in seen:
            collisions += 1
            continue
        seen[p.id] = p
    return list(seen.values()), collisions


def main() -> None:
    hk_db = os.environ["SQLITE_HACKATHONS"]
    eg_db = os.environ["SQLITE_ETHGLOBAL"]

    p1, h1, t1 = _import_hackathons_db(hk_db)
    p2, h2, t2 = _import_ethglobal_db(eg_db)

    projects = p1 + p2
    hackathons = h1 + h2
    raw_techs = t1 + t2

    projects, collisions = _dedup(projects)
    # Les raw_techs pointant vers un projet éliminé par dédup restent valides
    # (même id), donc on les dédoublonne juste sur (project_id, tech_name).
    seen_tech: set[tuple[str, str]] = set()
    unique_techs: list[RawTech] = []
    for t in raw_techs:
        key = (t.project_id, t.tech_name)
        if key in seen_tech:
            continue
        seen_tech.add(key)
        unique_techs.append(t)

    print(
        f"Projets: {len(projects)} (dont {collisions} collisions ignorées) | "
        f"hackathons: {len(hackathons)} | raw_techs: {len(unique_techs)}"
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scrape_runs (source, kind, status, n_scraped) "
                "VALUES (NULL, 'import', 'running', %s) RETURNING id",
                (len(projects),),
            )
            row = cur.fetchone()
            assert row is not None
            run_id = row[0]

            cur.executemany(
                "INSERT INTO hackathons_staging "
                "(scrape_run_id, source, slug, name, hackathon_date, url) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [
                    (run_id, h.source, h.slug, h.name, h.hackathon_date, h.url)
                    for h in hackathons
                ],
            )

            cur.executemany(
                "INSERT INTO projects_staging ("
                "scrape_run_id, id, source, source_url, hackathon_slug, hackathon_name, "
                "hackathon_date, theme_tags, title, description, short_description, "
                "placement, raw_placement, is_winner, prize_track, tech_stack, "
                "stack_source, team_size, team_name, repo_url, demo_url, scraped_at"
                ") VALUES ("
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s)",
                [
                    (
                        run_id,
                        p.id,
                        p.source,
                        p.source_url,
                        p.hackathon_slug,
                        p.hackathon_name,
                        p.hackathon_date,
                        p.theme_tags,
                        p.title,
                        p.description,
                        p.short_description,
                        p.placement,
                        p.raw_placement,
                        p.is_winner,
                        p.prize_track,
                        p.tech_stack,
                        p.stack_source,
                        p.team_size,
                        p.team_name,
                        p.repo_url,
                        p.demo_url,
                        p.scraped_at,
                    )
                    for p in projects
                ],
            )

            # raw_project_tech est global (pas de scrape_run) : on remplace le lot.
            cur.execute("DELETE FROM raw_project_tech")
            cur.executemany(
                "INSERT INTO raw_project_tech (project_id, source, tech_name, tech_slug) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [
                    (t.project_id, t.source, t.tech_name, t.tech_slug)
                    for t in unique_techs
                ],
            )

            cur.execute(
                "UPDATE scrape_runs SET status='validated', finished_at=now() WHERE id=%s",
                (run_id,),
            )
        conn.commit()

    print(f"Import en staging terminé (scrape_run #{run_id}).")


if __name__ == "__main__":
    main()
