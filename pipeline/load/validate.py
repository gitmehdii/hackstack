"""Validation avant promotion — orchestration DB (Étape 7).

Calcule les `Metrics` d'un run en staging et de ses baselines, applique la logique pure de
`pipeline/contracts/validate.py`, trace chaque contrôle dans `contract_checks`, puis :

  - si tout passe   → statut 'validated', puis promotion (réutilise pipeline.load.promote) ;
  - si un échec     → statut 'rejected', rapport de diff écrit, `projects` INCHANGÉE.

Rien n'écrit dans `projects` hors de la promotion, elle-même conditionnée à la validation
(invariant PROJECT.md). L'ouverture d'issue GitHub sur rejet/blocage est un effet de bord
câblé à la CI (workflow hebdo), pas ici.

Usage :
    python -m pipeline.load.validate --run 12 --report validation_report.md
    python -m pipeline.load.validate                      # tous les runs 'scraped' en attente
    python -m pipeline.load.validate --run 12 --no-promote
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from pipeline.contracts.validate import (
    NULL_RATE_COLUMNS,
    CheckResult,
    Metrics,
    Thresholds,
    bootstrap_result,
    check_url_rate,
    compare,
    is_bootstrap,
    load_thresholds,
    render_report,
)
from pipeline.load.db import connect
from pipeline.load.promote import promote
from pipeline.load.staging import finish_run

_ALLOWED_TABLES = {"projects", "projects_staging"}

_AGG_SQL = """
    WITH base AS (SELECT * FROM {table} WHERE {where})
    SELECT
        count(*) AS n,
        avg((description IS NOT NULL)::int)::float      AS fr_description,
        avg((hackathon_date IS NOT NULL)::int)::float   AS fr_hackathon_date,
        avg((repo_url IS NOT NULL)::int)::float          AS fr_repo_url,
        avg((demo_url IS NOT NULL)::int)::float          AS fr_demo_url,
        avg((prize_track IS NOT NULL)::int)::float       AS fr_prize_track,
        avg((placement IS NOT NULL)::int)::float         AS placement_fill,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY length(description))
            FILTER (WHERE description IS NOT NULL)        AS median_desc_len
    FROM base
"""

# Comptes PAR hackathon : le contrôle projets/hackathon compare sur le recouvrement.
_HACK_SQL = """
    SELECT hackathon_slug AS slug, count(*) AS n
    FROM {table} WHERE {where}
    GROUP BY hackathon_slug
"""

_URL_SQL = """
    SELECT avg((u ~ '^https?://.')::int)::float AS url_valid
    FROM {table}, LATERAL unnest(ARRAY[source_url, repo_url, demo_url]) AS u
    WHERE ({where}) AND u IS NOT NULL
"""


def _f(v: object) -> float:
    """None (avg/percentile sur ensemble vide) -> 0.0."""
    return float(v) if v is not None else 0.0  # type: ignore[arg-type]


def _metrics(
    cur: psycopg.Cursor[Any], table: str, where: str, params: tuple[object, ...]
) -> Metrics:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"table non autorisée : {table}")  # garde contre l'injection de nom
    cur.execute(_AGG_SQL.format(table=table, where=where), params)
    row = cur.fetchone()
    assert row is not None
    cur.execute(_HACK_SQL.format(table=table, where=where), params)
    by_hackathon = {r["slug"]: int(r["n"]) for r in cur.fetchall()}
    cur.execute(_URL_SQL.format(table=table, where=where), params)
    urow = cur.fetchone()
    assert urow is not None
    return Metrics(
        n=int(row["n"]),
        fill_rate={c: _f(row[f"fr_{c}"]) for c in NULL_RATE_COLUMNS},
        median_desc_len=_f(row["median_desc_len"]),
        projects_by_hackathon=by_hackathon,
        placement_fill_rate=_f(row["placement_fill"]),
        url_valid_rate=_f(urow["url_valid"]),
    )


def first_promoted_run(cur: psycopg.Cursor[Any], source: str) -> int | None:
    """Ancre : plus ancien run PROMU contenant des lignes de cette source.

    Pour une source déjà présente, c'est l'import initial (run source-NULL mais dont les
    lignes de staging portent la source) ; pour une source neuve, la 1re promotion. None si
    aucune promotion n'existe encore (l'ancre est alors bootstrap).
    """
    cur.execute(
        "SELECT ps.scrape_run_id AS rid FROM projects_staging ps "
        "JOIN scrape_runs r ON r.id = ps.scrape_run_id "
        "WHERE ps.source = %s AND r.status = 'promoted' "
        "GROUP BY ps.scrape_run_id ORDER BY ps.scrape_run_id ASC LIMIT 1",
        (source,),
    )
    row = cur.fetchone()
    return int(row["rid"]) if row is not None else None


def _run_source(cur: psycopg.Cursor[Any], run_id: int) -> str:
    cur.execute("SELECT source, status FROM scrape_runs WHERE id = %s", (run_id,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"run #{run_id} introuvable")
    if row["source"] is None:
        raise RuntimeError(f"run #{run_id} sans source : non validable (import multi-sources ?)")
    if row["status"] != "scraped":
        raise RuntimeError(
            f"run #{run_id} en statut '{row['status']}' (attendu 'scraped') : "
            "déjà validé/promu, ou non terminé."
        )
    return str(row["source"])


def _evaluate(
    cur: psycopg.Cursor[Any], run_id: int, thresholds: Thresholds
) -> tuple[str, list[CheckResult], bool]:
    """Lit les métriques et produit la liste des contrôles + le verdict. Lecture seule."""
    src = _run_source(cur, run_id)
    where_run = "scrape_run_id = %s AND source = %s"
    candidate = _metrics(cur, "projects_staging", where_run, (run_id, src))
    if candidate.n == 0:
        return src, [CheckResult("batch:nonempty", False, {"candidate_n": 0})], False

    checks: list[CheckResult] = []

    moving_base = _metrics(cur, "projects", "source = %s", (src,))
    if is_bootstrap(moving_base):
        checks.append(bootstrap_result("moving"))
    else:
        checks.extend(compare(moving_base, candidate, thresholds.moving))

    anchor_id = first_promoted_run(cur, src)
    if anchor_id is None:
        checks.append(bootstrap_result("anchor"))
    else:
        anchor_base = _metrics(cur, "projects_staging", where_run, (anchor_id, src))
        if is_bootstrap(anchor_base):
            checks.append(bootstrap_result("anchor"))
        else:
            checks.extend(compare(anchor_base, candidate, thresholds.anchor))

    checks.append(check_url_rate(candidate, thresholds.url_valid_min_rate))
    verdict = all(c.passed for c in checks)
    return src, checks, verdict


def _write_checks(
    cur: psycopg.Cursor[Any], run_id: int, source: str, checks: list[CheckResult]
) -> None:
    cur.executemany(
        "INSERT INTO contract_checks (scrape_run_id, source, check_name, passed, detail) "
        "VALUES (%s, %s, %s, %s, %s)",
        [(run_id, source, c.check_name, c.passed, Json(c.detail)) for c in checks],
    )


def _summary(checks: list[CheckResult]) -> str:
    failed = [c.check_name for c in checks if not c.passed]
    return ("Validation échouée : " + ", ".join(failed))[:2000]


def _process(run_id: int, *, do_promote: bool) -> tuple[bool, str]:
    """Valide un run, écrit les contrôles + le statut, promeut si OK. Renvoie (verdict, rapport)."""
    thresholds = load_thresholds()
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            src, checks, verdict = _evaluate(cur, run_id, thresholds)
        report = render_report(source=src, run_id=run_id, checks=checks, verdict=verdict)
        with conn.cursor() as wcur:
            _write_checks(wcur, run_id, src, checks)
        finish_run(
            conn,
            run_id,
            status="validated" if verdict else "rejected",
            notes=None if verdict else _summary(checks),
        )
        conn.commit()

    # La promotion ouvre sa propre connexion : elle ne s'exécute qu'après le commit du statut
    # 'validated'. C'est le SEUL chemin d'écriture de `projects`.
    if verdict and do_promote:
        promote(run_id)
    return verdict, report


def validate_run(run_id: int, *, report_path: str | None = None, do_promote: bool = True) -> bool:
    verdict, report = _process(run_id, do_promote=do_promote)
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    status = "validé + promu" if verdict else "REJETÉ (projects inchangée)"
    print(f"Run #{run_id} : {status}.")
    return verdict


def _pending_scraped(cur: psycopg.Cursor[Any]) -> list[int]:
    cur.execute("SELECT id FROM scrape_runs WHERE status = 'scraped' ORDER BY id")
    return [int(r[0]) for r in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Valide un run en staging avant promotion.")
    ap.add_argument("--run", type=int, default=None, help="run précis (défaut : tous les scraped)")
    ap.add_argument("--report", metavar="FILE", default=None, help="écrit le rapport de diff")
    ap.add_argument("--no-promote", action="store_true", help="valide sans promouvoir")
    args = ap.parse_args(argv)
    do_promote = not args.no_promote

    if args.run is not None:
        ok = validate_run(args.run, report_path=args.report, do_promote=do_promote)
        return 0 if ok else 1

    with connect() as conn, conn.cursor() as cur:
        ids = _pending_scraped(cur)
    if not ids:
        print("Aucun run 'scraped' en attente.")
        return 0

    all_ok = True
    rejected_reports: list[str] = []
    for rid in ids:
        verdict, report = _process(rid, do_promote=do_promote)
        status = "validé + promu" if verdict else "REJETÉ (projects inchangée)"
        print(f"Run #{rid} : {status}.")
        if not verdict:
            rejected_reports.append(report)
        all_ok = all_ok and verdict

    if args.report and rejected_reports:
        Path(args.report).write_text("\n---\n\n".join(rejected_reports), encoding="utf-8")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
