# STATE

Journal d'avancement du projet. Une section par étape (cf. [PROJECT.md](PROJECT.md)).
Mis à jour à la fin de chaque étape : ce qui a été fait, les décisions prises, ce qui
reste en suspens.

---

## Étape 1 — Fondations ✅

**Statut : terminée.** Repo : [github.com/gitmehdii/hackstack](https://github.com/gitmehdii/hackstack) (privé).

### Fait

- **Schéma Postgres + migrations** — 9 migrations SQL versionnées dans `db/migrations/`
  (`0001`→`0009`), appliquées via un runner idempotent (`pipeline/load/migrate.py`,
  table `schema_migrations`). Tables : `hackathons`, `projects`, `projects_staging`,
  `hackathons_staging`, `scrape_runs`, `contract_checks`, `raw_project_tech`.
  Extensions `vector` + `pg_trgm`. Index HNSW (cosine) + GIN (fts, tableaux) + trigram.
- **Import du corpus SQLite** — `pipeline/load/import_sqlite.py` fusionne les deux dumps
  (`hackathons.db` = devpost + lablab, `ethglobal.db` = ethglobal), normalise par source,
  dédoublonne sur l'id déterministe `sha256(source:slug)`, écrit **uniquement** en
  staging. **21 027 projets** importés (21 190 − 163 collisions), 1 729 hackathons,
  1 482 tags bruts.
- **Promotion** — `pipeline/load/promote.py` : staging → `projects` en bootstrap
  (sans baseline de validation, car premier run). 0 orphelin FK.
- **Embeddings** — `pipeline/embed/embed.py` (bge-m3 → pgvector) écrit et **validé sur un
  échantillon** ; recherche cosine HNSW vérifiée. Génération complète volontairement
  reportée (voir *En suspens*). État actuel : **0 / 21 027 embeddé**.
- **Infra & qualité** — `docker-compose.yml` (Postgres 16 + pgvector, port 5433),
  config `uv` (`pyproject.toml`), `.env.example` à jour, `.gitignore` durci (aucun secret
  versionné). `ruff` clean, `mypy --strict` clean, 6 tests unitaires (`pytest`) verts.

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| `hackathon_date` | NULL à l'import, backfill à l'Étape 6 | Aucune date dans les dumps ; pas de scraping en Étape 1 |
| `tech_stack` | Importé vide ; tags lablab bruts conservés dans `raw_project_tech` | Extraction propre (taxonomie fermée) = Étape 4 |
| Finalistes lablab (`FINALISTS`/`OTHER`) | Gardés, `is_winner=false` ; colonne **`raw_placement`** (généralisée à toutes les sources) conserve la valeur d'origine | Ne pas perdre l'info de classement source |
| Chemin d'import | Via `projects_staging` + promotion explicite | Invariant : rien n'écrit jamais direct dans `projects` |
| Génération des embeddings | Reportée à l'orée de l'Étape 3 | Aucun consommateur avant `/search` ; input texte encore incomplet (devpost) |
| Visibilité du repo | Privé | Passer public à l'Étape 7 (dataset + licences prêts) |

### En suspens / dette connue (héritée du corpus)

- **`hackathon_date` NULL partout** → bloque les Trends (Étape 5) tant que le backfill
  (Étape 6) n'est pas fait.
- **`team_size` NULL partout** → le corpus ne contient pas la composition des équipes.
- **devpost = `short_description` seulement** (61 % du corpus, pas de texte intégral) →
  à compléter au rescrape (Étape 6) ; impacte la qualité future des embeddings.
- **Embeddings à générer** juste avant l'Étape 3, sur le corpus d'alors
  (`python -m pipeline.embed.embed`, idempotent).
- **163 collisions d'id** ignorées à l'import (premier gagnant) — à investiguer si la
  déduplication fine devient un sujet (`pipeline/normalize/dedup.py`, non encore écrit).

---

## Étape 2 — Site en lecture seule ✅

**Statut : terminée.** Branche `etape-2-site-lecture-seule`.

### Fait

- **API FastAPI** (`api/`, lecture seule, SQL à la main, pool psycopg async) — endpoints
  `GET /projects/{id}`, `GET /hackathons/{slug}`, `GET /stats`, `GET /health`. Modèles de
  réponse Pydantic ; `mypy --strict` étendu à `api/` (`pyproject.toml`), `ruff` clean.
  Testé contre la DB live (21 027 projets) : projet OK, palmarès trié, 404, slug ambigu.
- **Invariant légal appliqué à la frontière API** — l'API n'expose **jamais** la
  description intégrale : `api/excerpt.py` fabrique `description_excerpt` (tronqué sur
  frontière de mot, `API_EXCERPT_MAX_CHARS`=600) + flag `is_excerpt_truncated`. Ni
  `embedding` ni `fts` ne sont sélectionnés. 6 tests unitaires sur l'extrait.
- **Front Next.js 15** (`web/`, App Router, TS, Tailwind v4, pnpm) — pages `/`
  (chiffres via `/stats`), `/project/[id]`, `/hackathon/[slug]`. Les deux dernières en
  **ISR** (`revalidate=86400`, `generateStaticParams` vide → génération à la demande puis
  cache HTML), métadonnées Open Graph par page (`generateMetadata`), `robots.ts`.
  Le front consomme l'API (`web/lib/api.ts`), ne touche jamais la base. `pnpm typecheck`
  + `pnpm build` verts, flux vérifié dans le navigateur.
- **Doc** — README : sections API + site, commandes de dev, cible de déploiement
  (front Vercel / API VPS / base Supabase), variables d'env (`web/.env.example`).

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| Slug hackathon non unique (2 collisions inter-sources) | `/hackathons/{slug}` choisit la source la plus fournie, expose les autres en `alternatives` ; le front affiche une note | Garder le contrat `/hackathons/{slug}` + URL ISR à un seul paramètre, sans perdre l'info |
| Extrait de description | Tronqué à 600 car. au niveau **API** (pas seulement front) | L'invariant légal est garanti à la source, quel que soit le consommateur |
| `/stats` | Ajouté hors périmètre strict | La home a besoin de chiffres ; endpoint trivial et déjà au contrat PROJECT.md |
| ISR pages projet/hackathon | `generateStaticParams` retourne `[]` | 21k projets : pas de pré-rendu au build, tout à la demande puis caché (vraie ISR, pages `●` SSG) |
| Front ↔ base | Le front passe **toujours** par l'API | Découplage PROJECT.md ; base non exposée au front |

### En suspens / dette connue

- **Sitemap complet** (par projet / hackathon) reporté à l'Étape 3 : nécessite un endpoint
  de listing (arrive avec `/search`). `robots.ts` en place, autorise le crawl.
- **`pnpm` non installé sur la machine** : deps front installées via
  `corepack pnpm@10` (corepack ne peut pas créer le symlink `/usr/bin/pnpm`).
- **Déploiement réel non effectué** (action externe) : le livrable est *déployable*
  (build vert), pas encore déployé sur Vercel/VPS.
- **Slug ambigu** : la page ne montre que la source principale ; pas de page distincte
  pour l'alternative (URL identique). Acceptable (2 cas), documenté.
