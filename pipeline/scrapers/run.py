"""Runner de scraping : collecte une source et écrit UNIQUEMENT en staging.

Rien ne monte dans `projects` ici : la promotion est conditionnée à la validation
(Étape 7). Un scrape réussi laisse le run en statut 'scraped' (fini, non validé).

Sur blocage anti-bot (Cloudflare/captcha/403 systématique) : le run passe 'blocked'
(distinct de 'failed'), les notes portent le rapport structuré, et on s'arrête —
aucun effet externe (l'ouverture d'issue GitHub est câblée à l'Étape 7, côté CI).

Usage :
    python -m pipeline.scrapers.run --source ethglobal --live --limit 5 --cache
    python -m pipeline.scrapers.run --source devpost   --live --limit 5 --cache
    python -m pipeline.scrapers.run --source lablab     --archive path/to/winners.json
"""

from __future__ import annotations

import argparse
import sys
import traceback

from pipeline.load.db import connect
from pipeline.load.staging import finish_run, open_run, write_staging_batch
from pipeline.scrapers.base import BaseScraper, ScraperBlocked, ScrapeResult
from pipeline.scrapers.devpost import DevpostScraper
from pipeline.scrapers.ethglobal import EthglobalScraper
from pipeline.scrapers.lablab import LablabScraper, ingest_archive

_SCRAPERS: dict[str, type[BaseScraper]] = {
    "devpost": DevpostScraper,
    "ethglobal": EthglobalScraper,
    "lablab": LablabScraper,
}


def _persist(source: str, result: ScrapeResult) -> int:
    with connect() as conn:
        run_id = open_run(conn, source=source, kind="scrape", n_scraped=len(result.projects))
        write_staging_batch(conn, run_id, result.projects, result.hackathons, result.raw_techs)
        finish_run(conn, run_id, status="scraped")
        conn.commit()
    return run_id


def _persist_block(source: str, exc: ScraperBlocked) -> int:
    with connect() as conn:
        run_id = open_run(conn, source=source, kind="scrape", n_scraped=0)
        finish_run(conn, run_id, status="blocked", notes=exc.as_notes())
        conn.commit()
    return run_id


def _persist_failure(source: str, message: str) -> int:
    with connect() as conn:
        run_id = open_run(conn, source=source, kind="scrape", n_scraped=0)
        finish_run(conn, run_id, status="failed", notes=message[:2000])
        conn.commit()
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape une source vers projects_staging.")
    parser.add_argument("--source", required=True, choices=sorted(_SCRAPERS))
    parser.add_argument("--limit", type=int, default=None, help="borne le nombre de projets")
    parser.add_argument("--live", action="store_true", help="scrape réseau (devpost/ethglobal)")
    parser.add_argument("--archive", metavar="PATH", help="ingestion hors ligne (lablab)")
    parser.add_argument("--cache", action="store_true", help="cache HTTP local (dev)")
    parser.add_argument(
        "--winners-only",
        action="store_true",
        help="ne capter que les gagnants (défaut : gagnants ET non-gagnants)",
    )
    args = parser.parse_args(argv)

    # --archive (lablab uniquement) : ingestion hors ligne d'un export JSON de l'API.
    if args.archive:
        if args.source != "lablab":
            print("--archive n'est prévu que pour lablab.", file=sys.stderr)
            return 2
        result = ingest_archive(args.archive)
        run_id = _persist(args.source, result)
        print(f"lablab (archive) : {len(result.projects)} projets -> staging (run #{run_id}).")
        return 0

    if not args.live:
        print(
            f"{args.source} requiert --live (scrape réseau poli) ou --archive (lablab).",
            file=sys.stderr,
        )
        return 2

    scraper = _SCRAPERS[args.source](use_cache=args.cache)
    try:
        result = scraper.scrape(limit=args.limit, winners_only=args.winners_only)
    except ScraperBlocked as exc:
        run_id = _persist_block(args.source, exc)
        print(
            f"[BLOCKED] {args.source} : {exc} — run #{run_id} en statut 'blocked', staging "
            "inchangé. (L'issue GitHub sera ouverte par la CI à l'Étape 7.)",
            file=sys.stderr,
        )
        return 3
    except Exception:  # noqa: BLE001 — on trace et on marque 'failed', distinct de 'blocked'
        tb = traceback.format_exc()
        run_id = _persist_failure(args.source, tb)
        print(f"[FAILED] {args.source} : run #{run_id} en statut 'failed'.\n{tb}", file=sys.stderr)
        return 1

    run_id = _persist(args.source, result)
    print(
        f"{args.source} : {len(result.projects)} projets, {len(result.hackathons)} hackathons "
        f"-> staging (run #{run_id}, statut 'scraped')."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
