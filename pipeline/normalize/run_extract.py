"""Exécute les passes d'extraction (Étape 4) et écrit dans le staging d'enrichissement.

Ne touche JAMAIS `projects` : écrit dans github_tech_staging / llm_extraction_staging.
La mise à jour de `projects` se fait ensuite via pipeline/load/promote_enrichment.py.

Usage:
    # passe GitHub (fiable, projets avec repo github) — token conseillé, marche sans (60/h)
    python -m pipeline.normalize.run_extract --pass github --limit 20

    # passe LLM (tech + thèmes) — nécessite OPENROUTER_API_KEY
    python -m pipeline.normalize.run_extract --pass llm --source devpost --limit 20

    # les deux, sur tout le corpus (run complet, coûteux)
    python -m pipeline.normalize.run_extract --pass both

Flags:
    --pass {github,llm,both}   passes à exécuter (défaut both)
    --source S                 restreindre à une source (répétable)
    --limit N                  nombre max de projets par passe (échantillon)
    --only-missing             sauter ce qui est déjà en staging (reprise idempotente)
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import httpx
import psycopg

from pipeline.load.db import connect
from pipeline.normalize.github_stack import GitHubBlocked, GitHubStackClient
from pipeline.normalize.llm_extract import LLMExtractor


def _select(
    cur: psycopg.Cursor,
    *,
    columns: str,
    where: str,
    sources: Sequence[str],
    limit: int | None,
) -> list[tuple[object, ...]]:
    params: list[object] = []
    clauses = [where]
    if sources:
        clauses.append("source = ANY(%s)")
        params.append(list(sources))
    sql = f"SELECT {columns} FROM projects WHERE {' AND '.join(clauses)} ORDER BY id"
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    cur.execute(sql, params)
    return cur.fetchall()


def run_github(
    conn: psycopg.Connection, sources: Sequence[str], limit: int | None, only_missing: bool
) -> None:
    where = "repo_url ILIKE '%%github.com%%'"
    if only_missing:
        where += " AND id NOT IN (SELECT project_id FROM github_tech_staging)"
    with conn.cursor() as cur:
        rows = _select(
            cur, columns="id, source, repo_url", where=where, sources=sources, limit=limit
        )
    print(f"[github] {len(rows)} projets à traiter.")
    if not rows:
        return

    client = GitHubStackClient(token=os.environ.get("GITHUB_TOKEN") or None)
    import json as _json

    done = 0
    ignores = 0
    for pid, source, repo_url in rows:
        try:
            result = client.extract(str(repo_url))
        except GitHubBlocked as exc:
            # PROJECT.md : on s'arrête, on ne contourne pas.
            print(f"\n[github] blocage GitHub, arrêt : {exc}")
            break
        except httpx.HTTPError as exc:
            # Aléa réseau (déconnexion, DNS, timeout) : on passe au projet suivant plutôt
            # que de perdre le run. Observé deux fois sur des runs de plusieurs heures —
            # une seule coupure transitoire tuait tout le travail restant. Un blocage
            # GitHub, lui, reste distinct et interrompt bien la passe.
            ignores += 1
            if ignores <= 5 or ignores % 50 == 0:
                print(f"\n[github] aléa réseau ignoré ({ignores}) sur {repo_url} : {exc}")
            continue
        if result is None:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO github_tech_staging "
                "(project_id, source, repo_url, tech_stack, languages, manifests) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (project_id) DO UPDATE SET "
                "  tech_stack = EXCLUDED.tech_stack, languages = EXCLUDED.languages, "
                "  manifests = EXCLUDED.manifests, fetched_at = now()",
                (
                    pid,
                    source,
                    repo_url,
                    result.tech_stack,
                    _json.dumps(result.languages),
                    result.manifests,
                ),
            )
        conn.commit()
        done += 1
        print(f"  [github] {done}/{len(rows)}", end="\r", flush=True)
    suffixe = (
        f" ({ignores} projets sautés sur aléa réseau, repris au prochain run)" if ignores else ""
    )
    print(f"\n[github] {done} projets écrits en staging.{suffixe}")


def run_llm(
    conn: psycopg.Connection,
    sources: Sequence[str],
    limit: int | None,
    only_missing: bool,
    workers: int = 8,
) -> None:
    if not (os.environ.get("OPENROUTER_API_KEY") or "").strip():
        raise SystemExit("OPENROUTER_API_KEY vide — passe LLM impossible (voir .env.example).")
    where = "TRUE"
    if only_missing:
        where = "id NOT IN (SELECT project_id FROM llm_extraction_staging)"
    with conn.cursor() as cur:
        rows = _select(
            cur,
            columns="id, source, title, short_description, description",
            where=where,
            sources=sources,
            limit=limit,
        )
    print(f"[llm] {len(rows)} projets à traiter ({workers} workers).")
    if not rows:
        return

    # Appels réseau en parallèle (httpx.Client est thread-safe), écritures DB sérialisées
    # par lot pour rester dans une seule connexion psycopg. Lot commité => reprise propre
    # via --only-missing si le run est interrompu.
    from concurrent.futures import ThreadPoolExecutor

    extractor = LLMExtractor()

    def _one(row: tuple[object, ...]) -> tuple[object, object, list[str], list[str], str]:
        pid, source, title, short, description = row
        res = extractor.extract(str(title), short, description)  # type: ignore[arg-type]
        return pid, source, res.tech_stack, res.theme_tags, res.model

    done = 0
    chunk = max(workers * 8, 32)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(rows), chunk):
            batch = rows[start : start + chunk]
            results = list(pool.map(_one, batch))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO llm_extraction_staging "
                    "(project_id, source, tech_stack, theme_tags, model) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (project_id) DO UPDATE SET "
                    "  tech_stack = EXCLUDED.tech_stack, theme_tags = EXCLUDED.theme_tags, "
                    "  model = EXCLUDED.model, extracted_at = now()",
                    results,
                )
            conn.commit()
            done += len(batch)
            print(f"  [llm] {done}/{len(rows)}", end="\r", flush=True)
    print(f"\n[llm] {done} projets écrits en staging.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="passes", choices=["github", "llm", "both"], default="both")
    ap.add_argument("--source", action="append", default=[], dest="sources")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--workers", type=int, default=8, help="parallélisme de la passe LLM")
    args = ap.parse_args()

    with connect() as conn:
        if args.passes in ("github", "both"):
            run_github(conn, args.sources, args.limit, args.only_missing)
        if args.passes in ("llm", "both"):
            run_llm(conn, args.sources, args.limit, args.only_missing, args.workers)


if __name__ == "__main__":
    main()
