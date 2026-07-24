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
- [x] **Étape 4 — Thèmes & tech stack** : taxonomies fermées, extraction GitHub + LLM
      (ancrée dans le texte), pages `/theme/[slug]`. Cf. [STATE.md](STATE.md).
- [x] **Étape 5 — Trends** : dashboard `/trends`, les 5 analyses (calculées là où la
      donnée existe, états vides explicites ailleurs), test statistique. Cf. [STATE.md](STATE.md).
- [x] **Étape 6 — Scraping (acquisition)** : classe de base polie, scrapers devpost /
      ethglobal / lablab, tests de contrat sur fixtures figées. Écrit en staging ; la
      promotion reste conditionnée à la validation (Étape 7). Cf. [STATE.md](STATE.md).
- [x] **Étape 7 — Validation & automatisation** : validation avant promotion (double
      baseline mobile/ancre, contrôles unilatéraux, seuils dans `thresholds.yaml`),
      statut `rejected` + rapport de diff, workflows GitHub Actions (CI + hebdo avec
      issue auto). Cf. [STATE.md](STATE.md).
- [ ] Étape 8 — Dataset public
- [ ] Étape 9 — Agent mainteneur

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

## Thèmes et tech stack (Étape 4)

Deux **taxonomies fermées, versionnées** : les thèmes
([`themes.yaml`](pipeline/normalize/themes.yaml), plate, 42 entrées, ≤ 3 par projet) et le
tech stack ([`taxonomy.yaml`](pipeline/normalize/taxonomy.yaml), 112 technos + alias).
L'extraction se fait en **deux passes**, écrites en staging puis promues explicitement
(rien n'écrit direct dans `projects`) :

1. **GitHub** (fiable) — langages + manifestes (`package.json`, `requirements.txt`,
   `pyproject.toml`, `go.mod`, `Cargo.toml`) mappés sur la taxonomie. `stack_source='github'`.
2. **LLM** (OpenRouter, sortie structurée) — `tech_stack` **et** `theme_tags`, restreints aux
   taxonomies, thèmes cappés à 3. `stack_source='llm'`.

```bash
# Passe GitHub (token conseillé ; sans token : 60 req/h, échantillon seulement)
python -m pipeline.normalize.run_extract --pass github --limit 20

# Passe LLM (nécessite OPENROUTER_API_KEY) — tech + thèmes
python -m pipeline.normalize.run_extract --pass llm --source devpost --limit 20

# Fusion des deux passes -> projects (dry-run pour compter d'abord)
python -m pipeline.load.promote_enrichment --dry-run
python -m pipeline.load.promote_enrichment
```

`run_extract` est idempotent (`--only-missing` saute ce qui est déjà en staging). La fusion :
`tech_stack` = GitHub si présent sinon LLM ; `theme_tags` = LLM.

Endpoints : `GET /themes` (index, volumes observés), `GET /themes/{slug}` (volume, taux de
victoire **+ note de biais**, stacks dominantes, projets). Pages : `/themes` et
`/theme/[slug]` (ISR 24 h), chips de thèmes cliquables sur chaque page projet.

> **Taux de victoire biaisé.** Il dépend du nombre de prix et des tracks sponsorisées, pas
> seulement de la qualité (cf. PROJECT.md). Le chiffre est toujours affiché avec sa note
> méthodologique ; la normalisation par prix arrive à l'Étape 5.

## Scraping — acquisition (Étape 6)

Le corpus initial vient d'un import SQLite unique ; l'Étape 6 ajoute la **collecte fraîche**.
Un scrape écrit **uniquement en staging** (`projects_staging`) — la promotion vers `projects`
reste conditionnée à la validation (Étape 7). Un run réussi laisse le run en statut
`scraped` (fini, non validé).

Socle commun ([`pipeline/scrapers/base.py`](pipeline/scrapers/base.py)) : rate limit **1 req/s
par domaine**, respect de `robots.txt`, User-Agent identifiable pointant vers le repo, retry
borné sur transitoire, cache HTTP local optionnel (`--cache`, dossier `.http_cache/`). Sur
**blocage anti-bot** (Cloudflare/captcha/403 systématique), le scraper **s'arrête** — jamais
de contournement — et marque le run `blocked` (distinct de `failed`) avec un rapport dans
`scrape_runs.notes` ; l'ouverture d'issue GitHub est câblée à l'Étape 7 (CI).

Par défaut, un scrape capte **tous** les projets des événements traversés (gagnants **et**
non-gagnants) ; `is_winner` les distingue. `--winners-only` restreint aux gagnants. Garder les
non-gagnants rend le dataset filtrable a posteriori et débiaise `/trends` (cf. PROJECT.md).

```bash
# Scrape poli des trois sources (réseau), borné, avec cache de dev
python -m pipeline.scrapers.run --source ethglobal --live --limit 5 --cache
python -m pipeline.scrapers.run --source devpost   --live --limit 5 --cache
python -m pipeline.scrapers.run --source lablab    --live --limit 5 --cache

# Gagnants uniquement (opt-in)
python -m pipeline.scrapers.run --source devpost --live --winners-only

# lablab peut aussi rejouer un export JSON de l'API hors ligne
python -m pipeline.scrapers.run --source lablab --archive path/to/winners.json
```

> **lablab.** L'API JSON publique `/api/v4/submissions?filter=winners` est accessible
> poliment (200, paginée par cursor) et permise par `robots.txt` — c'est ce que `--live`
> utilise. Seule la surface **HTML** (`/apps/...`) est derrière Cloudflare ; on n'en a pas
> besoin. Si l'API venait à être challengée, la détection anti-bot arrête le run (`blocked`),
> jamais de contournement (pas de cookie `cf_clearance`, pas de fingerprint TLS).

ETHGlobal expose `event.startTime` et l'API Devpost expose les dates de hackathon : les
scrapers **backfillent `hackathon_date`** (la donnée que `/trends` attend depuis l'Étape 5).
Devpost récupère aussi, sur la page `/software/{slug}`, la **description intégrale**, le
**repo GitHub**, l'**URL de démo** et la liste **« Built With »** (→ `raw_project_tech`) —
comblant la dette « devpost = short_description seulement, ni repo ni tech » du corpus importé.

Les **tests de contrat** ([`pipeline/contracts/`](pipeline/contracts/)) tournent sur des
fixtures figées, **sans réseau** (`pytest`), et vérifient les invariants de parsing de chaque
source. Ils démarrent le compteur « un mois » exigé avant l'agent mainteneur (Étape 9). Leurs
fixtures sont **anonymisées** (descriptions intégrales remplacées par du filler, cf.
[`scrub_fixtures.py`](pipeline/contracts/scrub_fixtures.py)) pour ne pas republier de texte.

## Validation & automatisation (Étape 7)

Rien n'entre dans `projects` sans passer la **validation avant promotion**. Un run `scraped`
est comparé, **par source**, à deux baselines (seuils dans
[`pipeline/contracts/thresholds.yaml`](pipeline/contracts/thresholds.yaml), jamais en dur) :

- **moving** — l'état accumulé de `projects` (baseline mobile, seuils resserrés) ;
- **anchor** — le premier run promu de la source (corpus d'origine, figé, seuils larges) —
  capte la **dérive lente** qu'une baseline mobile masquerait.

Les contrôles (taux de non-null par colonne, médiane des descriptions, projets par hackathon
sur le **recouvrement**, taux de placement, URLs bien formées) sont **unilatéraux** : ils ne
flaguent que les *baisses* (une casse de scraper = de la donnée qui disparaît). Un champ qui se
remplit **davantage** (ex. backfill de dates) ne bloque jamais la promotion.

```bash
# Valide tous les runs 'scraped' en attente (promotion si OK), écrit un rapport de diff
python -m pipeline.load.validate --report validation_report.md

# Un run précis, sans promouvoir (inspection)
python -m pipeline.load.validate --run 12 --no-promote
```

Si un seuil est franchi : le run passe **`rejected`**, `projects` reste **inchangée**, et un
rapport de diff est produit (une ligne `contract_checks` par contrôle). `rejected` est distinct
de `failed` (bug) et `blocked` (anti-bot) — la CI traite les trois différemment.

**GitHub Actions** — [`ci.yml`](.github/workflows/ci.yml) : lint + types + tests sur chaque
push/PR (sans DB ni réseau). [`weekly.yml`](.github/workflows/weekly.yml) : hebdomadaire —
(1) rejoue les tests de contrat sur fixtures figées (Niveau-1 détection du mainteneur) et
ouvre une issue en cas de rupture ; (2) si le secret `DATABASE_URL` est configuré, enchaîne
scrape → validation → promotion et ouvre une issue sur rejet ou blocage. Sans le secret, le
volet scrape live se saute proprement.

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
- **`theme_tags` peuplés (86 % des projets), `tech_stack` volontairement épars (11 %)** —
  extraction LLM (Étape 4) faite ; la tech est **ancrée** (seulement ce qui est nommé dans le
  texte), donc rare sur les descriptions courtes de devpost. Les tags bruts lablab restent
  dans `raw_project_tech`, pas exposés.
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
