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
- [ ] Étape 2 — Site en lecture seule
- [ ] Étape 3 — Recherche hybride
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
ruff check pipeline && ruff format pipeline
mypy pipeline
pytest
```

## Licences

Code sous MIT. Dataset (à publier, Étape 7) sous CC BY-SA avec attribution des sources.
