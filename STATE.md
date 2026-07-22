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

---

## Étape 3 — Recherche ✅

**Statut : terminée** (code). Branche `etape-3-recherche`. Backfill embeddings en cours
(voir *En suspens*).

### Fait

- **Recherche hybride `/search`** (`api/queries/search.py`) — bras **vectoriel** (pgvector
  `<=>`, index HNSW) + bras **full-text** (`websearch_to_tsquery` sur `fts`, index GIN),
  fusionnés par **Reciprocal Rank Fusion** (`k=60`) dans **une seule requête SQL** (deux
  CTE + `FULL OUTER JOIN`, `1/(k+rang)`). RRF ne dépend que des rangs → pas de
  normalisation de scores hétérogènes. Filtres `source` (répétable), `winners_only`,
  `since`/`until`, `limit`. SQL écrit à la main (pas d'ORM masquant le vectoriel).
- **Encodeur de requête** (`api/search_encoder.py`) — bge-m3 chargé une fois, à la
  demande (singleton + verrou async, double-checked locking), encodage hors event loop
  (`asyncio.to_thread`). Même modèle que le pipeline → vecteurs comparables. Le bras
  vectoriel se **désactive proprement** si `query_vector` est None (CTE vide typée) : la
  recherche retombe sur le full-text seul, sans erreur.
- **Projets similaires** (`GET /projects/{id}/similar`, `api/queries/projects.py`) — plus
  proches voisins cosine hors soi-même ; liste vide (pas de 404) si le projet n'a pas
  encore d'embedding.
- **Front** — page **`/search`** client-side (`web/components/search-client.tsx` +
  wrapper `Suspense`) : champ + filtres source/gagnants, **état synchronisé à l'URL**
  (résultats partageables/navigables, back-button). Le fetch passe par un **Route Handler
  proxy** `web/app/api/search/route.ts` (`API_URL` reste **privée**, pas de CORS navigateur,
  whitelist des paramètres). Section **« Projets similaires »** sur la page projet (rendu
  serveur, mis en cache avec l'ISR). Champ de recherche sur `/` (formulaire natif) + lien
  nav. `line-clamp` (Tailwind v4).
- **Qualité** — `ruff` + `mypy --strict` clean, **17 tests** verts (dont
  `tests/test_search_filters.py` sur le constructeur de filtres). Vérifié end-to-end dans
  le navigateur : `/search` (requête + filtres, URL sync), page projet + similaires.
  Latence à chaud ~0,4 s (premier appel ~15 s = chargement du modèle).

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| Fusion vecteur/lexical | **RRF** (`k=60`), pas de combinaison de scores bruts | Distance cosine et `ts_rank_cd` non comparables ; RRF ne dépend que des rangs |
| Vivier par bras | 200 candidats/bras avant fusion (`_CANDIDATES_PER_ARM`) | Assez large devant `limit` pour une vraie fusion, petit devant le corpus |
| Encodage de la requête | bge-m3 **dans le process API**, lazy + hors event loop | Un seul modèle, cohérent avec les embeddings ; pas de service séparé (overkill) |
| `/search` client-side | Fetch via **Route Handler proxy** Next, pas d'appel navigateur direct | Garde `API_URL` privée (invariant Étape 2), évite d'exposer l'API + config CORS |
| Filtres `theme`/`date` dans l'UI | **Non exposés** (seulement source/gagnants) | `theme_tags` vide (Étape 4) et `hackathon_date` NULL (Étape 6) : filtrer sur du vide tromperait |
| API `since`/`until` | **Implémentés** au contrat même sans données | Corrects dès que les dates seront backfillées (Étape 6) ; excluent naturellement les NULL |
| Bras vectoriel si embeddings absents | Dégradation en full-text seul (CTE vide) | La recherche marche pendant le backfill des 21k embeddings |

### En suspens / dette connue

- **Backfill embeddings en cours** — lancé sur les 21 027 projets (`python -m
  pipeline.embed.embed`, idempotent, `embedding IS NULL`). Sur CPU 8 cœurs : ~0,5 doc/s,
  **ETA ~11 h**. Tant qu'il n'est pas fini, la recherche est **full-text + vectoriel
  partiel** (qualité sémantique croissante à mesure du remplissage). Aucun GPU dispo ;
  les descriptions sont courtes (max ~980 tokens), donc rien à tronquer — la lenteur est
  inhérente au modèle.
- **Descriptions polluées** (résidus de payload RSC `_next/static/chunks/...` dans
  quelques descriptions scrapées, ex. « ML memecoin AI Agent ») remontent dans l'extrait.
  Dette de **corpus** (pas de la recherche) — à nettoyer au rescrape (Étape 6) ou par une
  passe de nettoyage `pipeline/normalize/`.
- **Chargement du modèle au 1ᵉʳ `/search`** (~15 s, ~2 Go RAM) : lazy pour ne pas peser
  sur `/health` et le démarrage. Sur VPS contraint, envisager un warm-up au *lifespan* ou
  un modèle plus léger si la latence du premier appel gêne.
- **Sitemap complet** (hérité de l'Étape 2) : toujours pas d'endpoint de listing ;
  `/search` n'en fournit pas. À traiter quand le SEO deviendra prioritaire.
- **`total` de `/search`** = nombre de hits renvoyés (borné par `limit`), pas un vrai
  total corpus. Pas de pagination (hors périmètre PROJECT.md).

---

## Étape 4 — Thèmes et tech stack ✅ (machinerie)

**Statut : machinerie terminée + validée sur échantillon. Le run complet attend les clés
API.** Branche `etape-4-themes-tech-stack` (depuis `etape-3-recherche`).

### Fait

- **Taxonomies fermées, versionnées** — `pipeline/normalize/themes.yaml` (**plate, 42
  thèmes**, ≤ 3 par projet, bornée 30–50 par un invariant du loader) et
  `pipeline/normalize/taxonomy.yaml` (**112 technos** groupées par catégorie + table
  d'alias pour la passe GitHub). Loader/validateur `taxonomy.py` : résolution par alias
  insensible à la casse, filtrage sur vocabulaire, cap des thèmes, invariants au chargement
  (pas de doublon, alias → valeur existante, fourchette des thèmes).
- **Extraction en deux passes**, SQL écrit à la main, couche HTTP isolée (injectable → tests
  sans réseau) :
  - **GitHub** (`github_stack.py`) — langages API + manifestes (`package.json`,
    `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`), parseurs purs, mappés sur
    la taxonomie. Politesse PROJECT.md : UA identifiable, 1 req/s, un 403/rate-limit lève
    `GitHubBlocked` et **arrête** la passe (pas de contournement). **Validé en réel** sur un
    échantillon ethglobal (non authentifié).
  - **LLM** (`llm_extract.py`) — OpenRouter, sortie structurée (JSON schema), taxonomies
    injectées, sortie **re-filtrée côté client** (jamais confiance au modèle : hors-vocab
    retiré, thèmes re-cappés à 3). Testée bout-en-bout avec client mocké.
- **Staging + promotion explicite** — migration `0010` (`github_tech_staging`,
  `llm_extraction_staging`). `run_extract.py` (flags `--pass`, `--source`, `--limit`,
  `--only-missing`) écrit **uniquement** en staging ; `promote_enrichment.py` fusionne
  (tech = GitHub sinon LLM ; thèmes = LLM ; `stack_source` posé en conséquence) et met à
  jour `projects` — **seul chemin d'écriture** de `tech_stack`/`theme_tags`. `--dry-run`
  pour compter d'abord. **Validé** : staging → promotion → `projects`.
- **API** — `GET /themes` (index : les 42 thèmes + volumes/gagnants observés) et
  `GET /themes/{slug}` (volume, gagnants, `win_rate`, **`methodology_note` de biais**,
  stacks dominantes, projets). Slug validé contre la taxonomie (404 si inconnu ; un thème
  valide sans projet renvoie une réponse vide propre). Taxonomie = source de vérité des
  libellés, réutilisée côté API.
- **Web** — pages `/themes` (index) et `/theme/[slug]` (ISR 24 h, stats + **note de biais
  affichée** + stacks dominantes + liste projets), chips de thèmes cliquables sur la page
  projet, lien « Thèmes » dans la nav. `pnpm typecheck` + `pnpm build` verts, rendu vérifié
  au navigateur (avec un échantillon seedé puis retiré).
- **Qualité** — `ruff` + `mypy --strict` clean, **+22 tests** (61 au total) : taxonomies,
  parseurs de manifestes, client GitHub mocké (dont rate-limit), passe LLM mockée.

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| Source des thèmes | LLM sur taxonomie fermée **plate** (42, ≤ 3/projet) | Aucun signal de thème propre dans le corpus (`theme_tags` vide, `prize_track` = sponsors). Une taxo qui gonfle dilue les pages |
| Périmètre du run | Machinerie + validation échantillon, **run complet reporté** | Clés API vides ; la passe LLM sur 21k projets coûte de l'argent — décision de dépense laissée à l'utilisateur |
| Staging d'enrichissement | 2 tables (github/llm) + promotion fusionnante, pas d'écriture directe | Invariant PROJECT.md ; passes ré-exécutables indépendamment ; provenance claire |
| `win_rate` par thème | Exposé **toujours** avec `methodology_note`, jamais seul | Contrainte PROJECT.md : ne pas présenter un chiffre biaisé comme conclusion |
| Base de branche | `etape-3-recherche` (PR 3 non encore mergée) | `/theme` s'appuie sur l'infra existante ; PR 3 à merger avant/avec PR 4 |

### En suspens / dette connue

- **Run complet non exécuté** — nécessite `OPENROUTER_API_KEY` (+ `GITHUB_TOKEN` pour tenir
  le débit sur 7,5k repos ethglobal). Après remplissage :
  `run_extract --pass github` puis `--pass llm`, puis `promote_enrichment`. **`projects`
  reste donc à `tech_stack`/`theme_tags` vides** (hors 2 projets de l'échantillon GitHub réel
  laissés en base) ; les pages `/themes` sont prêtes mais affichent surtout des thèmes vides
  tant que le run n'a pas tourné.
- **Couverture GitHub asymétrique** — seul ethglobal a des repos (~7,5k) ; devpost/lablab
  passent entièrement par le LLM. La passe GitHub sur ethglobal a ramené peu de manifestes
  (repos souvent monorepos / manifeste hors racine) : le signal principal y est les langages.
- **Biais « winners-only »** — devpost et ethglobal sont entièrement des gagnants dans le
  corpus (seul lablab a des non-gagnants). Le `win_rate` par thème sera proche de 100 % tant
  que le corpus reste ainsi : la note de biais est d'autant plus nécessaire. À revoir au
  rescrape (Étape 6).
- **Libellés de thèmes non dupliqués côté front** — les chips sur la page projet affichent le
  slug (le libellé lisible vit dans la taxonomie / l'API). Acceptable ; à améliorer si besoin.
