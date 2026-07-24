"""Import du corpus SQLite existant vers projects_staging (Étape 1).

Fusionne les deux dumps (hackathons.db = devpost + lablab, ethglobal.db = ethglobal),
normalise vers le schéma unifié, dédoublonne sur l'id déterministe, et écrit UNIQUEMENT
en staging. La promotion vers `projects` est une étape séparée (promote.py).

Usage:
    python -m pipeline.load.import_sqlite
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pipeline.load.db import connect
from pipeline.load.staging import finish_run, open_run, write_staging_batch
from pipeline.normalize.parse_helpers import (
    LABLAB_MAP,
)
from pipeline.normalize.parse_helpers import (
    clean as _clean,
)
from pipeline.normalize.parse_helpers import (
    parse_place as _parse_place,
)
from pipeline.normalize.schema import Hackathon, Project, RawTech, Source, project_id


def _file_mtime(path: str) -> datetime:
    ts = Path(path).stat().st_mtime
    return datetime.fromtimestamp(ts, tz=UTC)


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
    for proj_id, tech_id in con.execute("SELECT project_id, tech_id FROM project_tech").fetchall():
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
        hackathons[(hk_source, hk_slug)] = Hackathon(source=hk_source, slug=hk_slug, name=hk_name)
        for tname, tslug in tech_by_project.get(sqlite_id, []):
            raw_techs.append(RawTech(project_id=pid, source=src, tech_name=tname, tech_slug=tslug))

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
        run_id = open_run(conn, source=None, kind="import", n_scraped=len(projects))
        # raw_project_tech est global (pas de scrape_run) : l'import remplace le lot
        # avant l'écriture (les scrapers, eux, insèrent en ON CONFLICT DO NOTHING).
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw_project_tech")
        write_staging_batch(conn, run_id, projects, hackathons, unique_techs)
        # Import initial = bootstrap sans baseline de validation (cf. STATE.md Étape 1).
        finish_run(conn, run_id, status="validated")
        conn.commit()

    print(f"Import en staging terminé (scrape_run #{run_id}).")


if __name__ == "__main__":
    main()
