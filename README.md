# hackstack

Base de données publique des projets de hackathon gagnants, avec recherche sémantique
et analyse de tendances. Voir [PROJECT.md](PROJECT.md) pour la vision complète.

> **Le dataset est l'actif, pas le code.** Le site consomme un snapshot versionné de la
> base ; il continue de fonctionner même si les scrapers cassent.

## État d'avancement

- [x] **Étape 1 — Fondations** : schéma Postgres + migrations, import du corpus SQLite
      existant (~21k projets), index pgvector HNSW en place. La *génération* des
      embeddings est repoussée à l'orée de l'Étape 3 (premier consommateur = `/search`),
      pour l'exécuter sur un corpus dont l'input texte est complet — cf. note ci-dessous.
- [x] **Étape 2 — Site en lecture seule** : API FastAPI (`/projects/{id}`,
      `/hackathons/{slug}`, `/stats`) et front Next.js (pages projet + hackathon en ISR),
      déployable et consultable. Cf. [STATE.md](STATE.md).
- [x] **Étape 3 — Recherche hybride** : `/search` (vecteur pgvector + full-text, fusion
      RRF) avec filtres, page `/search` client-side, « projets similaires » sur la page
      projet. Backfill des embeddings sur les 21k projets en cours. Cf. [STATE.md](STATE.md).
- [ ] Étape 4 — Thèmes & tech stack
- [ ] Étape 5 — Trends
- [ ] Étape 6 — Pipeline de rescrape
- [ ] Étape 7 — Dataset public
- [ ] Étape 8 — Agent mainteneur

## Prérequis

- Docker + Docker Compose (Postgres 16 + pgvector en local)
- Python 3.12, [`uv`](https://docs.astral.sh/uv/)

## Mise en route (Étape 1)

```bash
# 1. Base locale (Postgres 16 + pgvector, port 5433)
docker compose up -d

# 2. Environnement Python
cp .env.example .env          # ajuster les chemins SQLITE_* si besoin
uv venv --python 3.12
uv pip install -e ".[dev]"
source .venv/bin/activate

# 3. Pipeline Étape 1
python -m pipeline.load.migrate         # applique db/migrations/*.sql (idempotent)
python -m pipeline.load.import_sqlite   # SQLite -> projects_staging (+ hackathons_staging)
python -m pipeline.load.promote         # staging -> projects (bootstrap, sans baseline)

# Embeddings : repoussés à l'Étape 3 (aucun consommateur avant, input texte
# encore incomplet côté devpost). Commande prête, idempotente :
# python -m pipeline.embed.embed        # embeddings bge-m3 -> projects.embedding
```

`import` puis `promote` sont idempotents (id déterministe `sha256(source:slug)`,
upsert `ON CONFLICT`). `embed` ne traite que les lignes `embedding IS NULL`.

## API + site (Étape 2)

L'API (FastAPI, lecture seule) et le front (Next.js 15, App Router) sont découplés : le
site consomme l'API, il ne touche jamais la base. L'API n'expose jamais la description
intégrale — seulement un extrait (`description_excerpt`) avec l'URL source (contrainte
légale, cf. PROJECT.md).

```bash
# API — nécessite la base lancée (docker compose up -d) et DATABASE_URL dans .env
uv run uvicorn api.main:app --reload --port 8099   # http://localhost:8099/docs

# Front — dans web/, deps via pnpm
cd web
cp .env.example .env.local        # API_URL=http://localhost:8099, SITE_URL=...
pnpm install
pnpm dev                          # http://localhost:3000
```

Endpoints : `GET /projects/{id}`, `GET /hackathons/{slug}` (palmarès complet ; le slug
n'est pas unique globalement — 2 slugs du corpus existent sur 2 sources, la source la
plus fournie est choisie et les autres exposées en `alternatives`), `GET /stats`,
`GET /health`.

Pages : `/` (chiffres + recherche), `/project/[id]`, `/hackathon/[slug]` — les deux
dernières en ISR (`revalidate` 24 h, génération à la demande), avec métadonnées Open Graph.

## Recherche (Étape 3)

Recherche **hybride** : le bras vectoriel (pgvector `<=>`, index HNSW) et le bras
full-text (`websearch_to_tsquery` sur `fts`, index GIN) sont fusionnés par **Reciprocal
Rank Fusion** dans une seule requête SQL. La requête texte est vectorisée à la volée par
bge-m3 (même modèle que les embeddings), chargé à la demande dans le process API.

```bash
# nécessite l'API lancée + des embeddings générés (python -m pipeline.embed.embed)
curl "http://localhost:8099/search?q=ai+agent+for+trading&winners_only=true&limit=5"
curl "http://localhost:8099/projects/{id}/similar"
```

Endpoints : `GET /search?q=&source=&winners_only=&since=&until=&limit=` (fusion RRF,
filtres), `GET /projects/{id}/similar` (voisins cosine).

Page `/search` : client-side, filtres source/gagnants, état synchronisé à l'URL. Le fetch
passe par un Route Handler proxy (`web/app/api/search/route.ts`) pour garder `API_URL`
privée. Section « projets similaires » sur chaque page projet.

> Le bras vectoriel se dégrade proprement en full-text seul quand un projet n'a pas encore
> d'embedding : la recherche reste utilisable pendant le backfill des 21k embeddings.

**Déploiement** (cible PROJECT.md) : front sur Vercel (`web/`, variables `API_URL` +
`SITE_URL`, `API_URL` pointant vers l'API publique), API sur un VPS (`DATABASE_URL` +
`API_CORS_ORIGINS` = domaine du front), base sur Supabase. Sitemap complet par projet
reporté à l'Étape 3 (nécessite un endpoint de listing).

## Le corpus importé

21 027 projets (après dédup) issus de trois sources :

| Source | Projets | Descriptions | Placement | prize_track | repo_url |
|---|---:|---|---|---|---|
| devpost   | 12 851 | court seulement | ✗ (rang non scrapé) | ✗ | ✗ |
| ethglobal |  7 647 | 4 693 complètes | via table `prizes` | ✓ | ✓ (GitHub) |
| lablab    |    529 | complètes | WINNERS/TOP_2/TOP_3 | ✗ | ✗ |

Limites connues, héritées du corpus (à combler au rescrape, Étape 6) :

- **`hackathon_date` est NULL partout** — aucune date dans les dumps. Bloque les Trends
  (Étape 5) tant que le backfill n'est pas fait.
- **`team_size` NULL** — le corpus ne contient pas la composition des équipes.
- **`tech_stack` vide** — l'extraction propre (taxonomie fermée) est l'Étape 4. Les tags
  bruts lablab existants sont préservés dans `raw_project_tech`, pas exposés.
- **devpost n'a que `short_description`** — les embeddings et le FTS utilisent le texte
  disponible.

## Schéma

Migrations SQL versionnées dans [`db/migrations/`](db/migrations/), jamais de
modification de schéma à la main. Tables : `hackathons`, `projects`,
`projects_staging` / `hackathons_staging`, `scrape_runs`, `contract_checks`,
`raw_project_tech`.

Invariant structurant : **rien n'écrit jamais directement dans `projects`**. Toute
écriture passe par le staging puis une promotion explicite.

## Développement

```bash
ruff check pipeline api && ruff format pipeline api
mypy                     # strict sur pipeline/ et api/ (cf. pyproject.toml)
pytest
cd web && pnpm typecheck && pnpm build
```

## Licences

Code sous MIT. Dataset (à publier, Étape 7) sous CC BY-SA avec attribution des sources.
