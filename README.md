# hackstack

Searchable database of hackathon projects, with semantic search and trend analysis.

[![ci](https://github.com/gitmehdii/hackstack/actions/workflows/ci.yml/badge.svg)](https://github.com/gitmehdii/hackstack/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Live site: [hackstack-web-kappa.vercel.app](https://hackstack-web-kappa.vercel.app)**

About 21,000 projects from Devpost, ETHGlobal and lablab, deduplicated into one corpus.
You can search it by meaning instead of keywords, and slice it by theme, tech stack and
outcome. Design rationale lives in [PROJECT.md](PROJECT.md).

> The dataset is the asset, not the code. The site reads a versioned snapshot of the
> database, so it keeps serving even when the scrapers break.

## How it works

Nothing ever writes directly to `projects`. Every write lands in a staging table, then a
promotion step copies it across only if validation passes. That single invariant is what
lets a scraper break, or a source silently change its HTML, without corrupting the corpus.

```
scrapers ──> projects_staging ──> validation ──> projects ──> API ──> web
                                      │
                                      └─ thresholds breached: run marked `rejected`,
                                         `projects` untouched, diff report written
```

The API is read only and never returns a full project description, only an excerpt plus
the source URL. The front end talks to the API and never touches the database.

## Quick start

Requirements: Docker and Docker Compose, Python 3.12, [`uv`](https://docs.astral.sh/uv/).

```bash
# Local database (Postgres 16 with pgvector, port 5433)
docker compose up -d

# Python environment
cp .env.example .env
uv venv --python 3.12
uv pip install -e ".[dev]"
source .venv/bin/activate

# Load the corpus
python -m pipeline.load.migrate         # applies db/migrations/*.sql, idempotent
python -m pipeline.load.import_sqlite   # SQLite into projects_staging
python -m pipeline.load.promote         # staging into projects
python -m pipeline.embed.embed          # bge-m3 embeddings, only rows where embedding IS NULL
```

`import` and `promote` are idempotent: ids are deterministic (`sha256(source:slug)`) and
writes are upserts.

Then run the API and the site:

```bash
# API, needs the database up and DATABASE_URL set
uv run uvicorn api.main:app --reload --port 8099   # http://localhost:8099/docs

# Front end
cd web
cp .env.example .env.local        # API_URL=http://localhost:8099
pnpm install
pnpm dev                          # http://localhost:3000
```

## Search

Search is hybrid. A vector arm (pgvector `<=>`, HNSW index) and a full text arm
(`websearch_to_tsquery`, GIN index) are fused by Reciprocal Rank Fusion inside a single SQL
query. The query string is embedded on the fly by bge-m3, the same model as the stored
vectors. That is a hard constraint: changing the model means re-encoding all 21k projects.

When a project has no embedding yet, the vector arm degrades to full text alone, so search
stays usable during a backfill.

Two encoding backends, selected by `EMBED_BACKEND`:

| | `local` (default) | `remote` |
|---|---|---|
| Model | loaded in memory, about 2 GB | HuggingFace inference, no weights |
| API resident memory | about 2 GB | about 80 MB |
| Dependencies | torch, sentence-transformers | one HTTP POST |
| Requires | nothing | `HF_TOKEN` |

Both produce the same vector (verified, cosine similarity 1.0: the HuggingFace endpoint
returns bge-m3 already normalised). `remote` exists so the API fits in a stateless host
where 2 GB of weights do not. `local` stays the development default so tests depend on
neither a token nor the network.

```bash
curl "http://localhost:8099/search?q=ai+agent+for+trading&winners_only=true&limit=5"
curl "http://localhost:8099/projects/{id}/similar"
```

## Themes and tech stack

Two closed, versioned taxonomies: themes
([`themes.yaml`](pipeline/normalize/themes.yaml), flat, 42 entries, at most 3 per project)
and tech stack ([`taxonomy.yaml`](pipeline/normalize/taxonomy.yaml), 112 technologies plus
aliases). Extraction runs in two passes, both writing to staging:

1. **GitHub**, reliable: languages and manifests (`package.json`, `requirements.txt`,
   `pyproject.toml`, `go.mod`, `Cargo.toml`) mapped onto the taxonomy. `stack_source='github'`.
2. **LLM** (OpenRouter, structured output): `tech_stack` and `theme_tags`, both constrained
   to the taxonomies. `stack_source='llm'`.

```bash
python -m pipeline.normalize.run_extract --pass github --limit 20
python -m pipeline.normalize.run_extract --pass llm --source devpost --limit 20
python -m pipeline.load.promote_enrichment --dry-run
python -m pipeline.load.promote_enrichment
```

On merge, `tech_stack` takes GitHub when present and falls back to the LLM; `theme_tags`
always comes from the LLM.

> Win rate is a biased metric. It depends on how many prizes an event awarded and how many
> tracks were sponsored, not only on quality. The number is always rendered with that
> caveat attached.

## Scraping

A scrape only ever writes to `projects_staging`. A successful run ends in state `scraped`,
which means finished but not yet validated.

The shared base ([`pipeline/scrapers/base.py`](pipeline/scrapers/base.py)) rate limits to
1 request per second per domain, respects `robots.txt`, sends an identifiable User-Agent
pointing back at this repository, bounds its retries to transient failures, and can cache
responses locally with `--cache`.

On anti-bot blocking (Cloudflare, captcha, systematic 403) the scraper stops. It does not
attempt to get around the block: no `cf_clearance` cookie, no TLS fingerprinting. The run
is marked `blocked`, which is deliberately distinct from `failed`, with a report in
`scrape_runs.notes`.

By default a scrape captures every project of the events it walks, winners and non-winners
alike, with `is_winner` telling them apart. Keeping the non-winners makes the dataset
filterable after the fact and removes survivor bias from the trend analysis. Pass
`--winners-only` to opt out.

```bash
python -m pipeline.scrapers.run --source ethglobal --live --limit 5 --cache
python -m pipeline.scrapers.run --source devpost   --live --limit 5 --cache
python -m pipeline.scrapers.run --source lablab    --live --limit 5 --cache
```

For lablab, `--live` uses the public JSON API (`/api/v4/submissions`), which is paginated
by cursor and permitted by `robots.txt`. Only its HTML surface sits behind Cloudflare, and
this project does not need it.

Contract tests ([`pipeline/contracts/`](pipeline/contracts/)) pin the parsing invariants of
each source against frozen fixtures, with no network access. The fixtures are scrubbed by
[`scrub_fixtures.py`](pipeline/contracts/scrub_fixtures.py): full descriptions are replaced
with filler, and third party credentials captured in the page (the origin site's Google
Maps key, Mixpanel key and CSRF token) are neutralised.

## Validation

A `scraped` run is compared per source against two baselines, with every threshold declared
in [`thresholds.yaml`](pipeline/contracts/thresholds.yaml) rather than hardcoded:

- **moving**: the accumulated state of `projects`, with tight thresholds.
- **anchor**: the first promoted run of that source, frozen, with wide thresholds. This is
  what catches slow drift, which a moving baseline hides by absorbing it.

The checks (non-null rate per column, median description length, projects per hackathon on
the overlap, placement rate, URL wellformedness) are one sided. They flag decreases only,
because a broken scraper shows up as data going missing. A field that fills in more than
before, such as a date backfill, never blocks a promotion.

```bash
python -m pipeline.load.validate --report validation_report.md
python -m pipeline.load.validate --run 12 --no-promote
```

A run has three failure states, and CI treats them differently: `rejected` (a threshold was
breached), `failed` (a bug), `blocked` (anti-bot).

Two workflows: [`ci.yml`](.github/workflows/ci.yml) runs lint, types and tests on every push
and pull request, without a database or network. [`weekly.yml`](.github/workflows/weekly.yml)
replays the contract tests against the frozen fixtures and opens an issue when a source
breaks, then, if the `DATABASE_URL` secret is set, chains scrape into validation into
promotion and opens an issue on rejection or blocking.

## Public dataset

The export produces a self contained directory ready to push to HuggingFace:
`projects.parquet`, `hackathons.parquet`, `embeddings.parquet` (kept separate so it can be
downloaded on its own) and a dataset card covering licence, attribution and the measured
coverage of that run.

```bash
python -m pipeline.export.dataset --out dist/hackstack-dataset --version 2026q3
python -m pipeline.export.dataset --out dist/d --no-embeddings --limit 500
```

Full description text never leaves the database. The dataset ships `source_url` plus
`has_description` and `description_chars`, which is enough to judge completeness and follow
a row back to its source, but not enough to redistribute the content. Embeddings are
published, which gives semantic search without the text. `check_columns` enforces that
invariant and the tests exercise it column by column. The parquet schema is declared rather
than inferred, so a column that happens to be empty in one export does not change type
between releases.

Publication is pending a review of the terms of service of the three sources.

## Schema

Migrations are versioned SQL in [`db/migrations/`](db/migrations/). The schema is never
edited by hand. Tables: `hackathons`, `projects`, `projects_staging`, `hackathons_staging`,
`scrape_runs`, `contract_checks`, `raw_project_tech`.

## The corpus

21,027 projects after deduplication, from three sources:

| Source | Projects | Descriptions | Placement | prize_track | repo_url |
|---|---:|---|---|---|---|
| devpost | 12,851 | short only | no | no | no |
| ethglobal | 7,647 | 4,693 complete | via `prizes` table | yes | yes |
| lablab | 529 | complete | WINNERS, TOP_2, TOP_3 | no | no |

Known limitations inherited from the initial import, to be closed on rescrape:

- `hackathon_date` is NULL throughout. The dumps carried no dates, which is what the trend
  analysis needs.
- `team_size` is NULL. The corpus has no team composition.
- `theme_tags` covers 86% of projects, `tech_stack` only 11%. The tech extraction is
  deliberately anchored, meaning it records only what the text actually names, so it stays
  sparse on the short descriptions that make up most of Devpost. Raw lablab tags are kept
  in `raw_project_tech` and not exposed.
- Devpost rows only carry a short description, so embeddings and full text search work from
  whatever text is available.

## Development

```bash
ruff check pipeline api && ruff format pipeline api
mypy                     # strict on pipeline/ and api/
pytest
cd web && pnpm typecheck && pnpm build
```

## API and pages

Endpoints: `GET /projects/{id}`, `GET /projects/{id}/similar`, `GET /hackathons/{slug}`,
`GET /search`, `GET /themes`, `GET /themes/{slug}`, `GET /stats`, `GET /health`.

A hackathon slug is not globally unique: two slugs in the corpus exist on two sources. The
richer source wins and the others are exposed under `alternatives`.

Pages: `/` (figures and search), `/search` (client side, filters synced to the URL),
`/project/[id]`, `/hackathon/[slug]`, `/themes`, `/theme/[slug]`, `/trends`. Detail pages
use ISR with a 24 hour revalidation window.

Deployment: front end on Vercel, database on Supabase, API as a Vercel serverless function
with `EMBED_BACKEND=remote`.

## Licence

Code under [MIT](LICENSE). The dataset, once published, under CC BY-SA with attribution to
the sources.
