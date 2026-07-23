# STATE

Journal d'avancement du projet. Une section par étape (cf. [PROJECT.md](PROJECT.md)).
Mis à jour à la fin de chaque étape : ce qui a été fait, les décisions prises, ce qui
reste en suspens.

> **Révision du plan (2026-07-23, après l'Étape 5).** L'ancienne « Étape 6 — Pipeline de
> rescrape » empilait trop (scrapers + validation + contrats + CI) pour une seule PR. Elle
> est scindée, et l'agent mainteneur décalé d'un cran :
> **6 = Scraping (acquisition)** · **7 = Validation & automatisation** · **8 = Dataset
> public** (ex-7) · **9 = Agent mainteneur** (ex-8). Aucune étape 1→5 n'est affectée. Les
> tests de contrat vivent désormais en Étape 6 (ils démarrent le compteur « un mois » du
> mainteneur). Rappel du contexte : aucune collecte n'existe encore — le corpus vient d'un
> import unique de SQLite, l'Étape 6 est donc à écrire de zéro.

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

## Étape 4 — Thèmes et tech stack ✅

**Statut : terminée. Run LLM complet exécuté sur les 21 027 projets.** Branche
`etape-4-themes-tech-stack` (depuis `etape-3-recherche`).

### Run complet (fait)

- **Passe LLM sur tout le corpus** — modèle **`google/gemini-2.5-flash-lite`** (OpenRouter,
  ~4-5 €, ~40 min à 12 workers). Comparé en réel à qwen3.5-flash et deepseek-v4-flash :
  gemini est le seul à sortir la tech de façon fiable et sans planter. **21 027/21 027**
  traités, **86 % avec ≥ 1 thème**, 42/42 thèmes utilisés (répartition saine, pas
  d'effondrement : generative-ai 5705, defi 4532, productivity 3108…).
- **Fiabilité mesurée, pas supposée** — spot-check de 20 projets : thèmes corrects à ~85 %,
  mais **tech_stack LLM peu fiable** (hallucination quand rien n'est nommé ; ~1,3 % de
  recrachages complets de la taxonomie qui passaient le filtre car toutes valeurs valides).
- **Parade : ancrage** (`Taxonomy.ground_tech` + `reground.py`) — on ne garde qu'une techno
  **réellement écrite** dans le texte (formes de surface = canonique + alias, frontières
  non-alphanumériques). A retiré **42 353** technos hallucinées ; tech tombe à **2 386
  projets (11 %)** mais chacun est justifié. Top ancré : Ethereum, Gemini, IPFS, ENS,
  Polygon, React, Python, Next.js. L'ancrage est aussi appliqué en ligne pour les runs futurs.

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

- **Passe GitHub à l'échelle non exécutée** — faute de `GITHUB_TOKEN` (60 req/h en anonyme,
  insuffisant pour 7,5k repos ethglobal) ; seul un échantillon de 2 projets est en `github`.
  La tech ethglobal vient donc du LLM ancré, pas des repos. À lancer quand un token sera
  dispo : `run_extract --pass github --only-missing` puis `promote_enrichment` (la fusion
  fait déjà primer github sur llm).
- **Couverture tech volontairement basse (11 %)** — conséquence directe de l'ancrage : la
  plupart des descriptions (surtout devpost, court seulement) ne nomment pas leur stack, donc
  on ne la prétend pas. Choix assumé : précision > rappel. Remontera au rescrape (Étape 6,
  descriptions complètes) et avec la passe GitHub.
- **Biais « winners-only »** — devpost et ethglobal sont entièrement des gagnants dans le
  corpus (seul lablab a des non-gagnants). Le `win_rate` par thème sera proche de 100 % tant
  que le corpus reste ainsi : la note de biais est d'autant plus nécessaire. À revoir au
  rescrape (Étape 6).
- **Libellés de thèmes non dupliqués côté front** — les chips sur la page projet affichent le
  slug (le libellé lisible vit dans la taxonomie / l'API). Acceptable ; à améliorer si besoin.

---

## Étape 5 — Trends ✅

**Statut : terminée** (plomberie complète + états vides distincts). Branche
`etape-5-trends` (depuis `main`).

### Contexte de départ (décision utilisateur)

Les 5 analyses de `/trends` sont demandées, mais l'état du corpus en bloque une partie —
donnée vérifiée en base avant de coder :

| # | Analyse | Donnée requise | État | Verdict |
|---|---------|----------------|------|---------|
| 1 | Thème par trimestre × win rate | `hackathon_date` | **0/21027** | en attente backfill (Ét. 6) |
| 2 | Cycle de vie d'une tendance | `hackathon_date` | **0/21027** | en attente backfill (Ét. 6) |
| 3 | Stacks gagnants vs ensemble + test | `tech_stack`, `is_winner` | tech 11 %, winners **99,3 %** | calculée + caveat fort |
| 4 | Corrélation équipe / classement | `team_size` | **0/21027** | indisponible dans le corpus |
| 5 | Thèmes volume / faible win rate | `theme_tags`, `is_winner` | thèmes 86 % | calculée + note de biais |

Choix validé : **construire toute l'infra `/trends`** (endpoints + dashboard + graphes +
notes), calculer les vrais chiffres là où la donnée existe, et afficher des états vides
**explicites** ailleurs. Distinction demandée et implémentée : un statut
`awaiting_date_backfill` (les dates arriveront à l'Étape 6) ≠ un statut
`unavailable_in_corpus` (team_size : aucune source ne la fournit, le rescrape ne la
récupérera peut-être jamais — ne rien promettre). Pas de backfill d'année depuis les noms
de hackathons : seulement 34 % en contiennent, année seule (pas trimestre) — trop partiel
pour ne pas frôler l'interdit « chiffre biaisé présenté comme conclusion » (PROJECT.md).

### Fait

- **Test statistique en Python pur** (`api/stats_test.py`) — test z de comparaison de deux
  proportions (variance poolée, bilatéral, p-value via `math.erf`). Aucune dépendance lourde
  (numpy/scipy exclus de l'API). Se déclare **incalculable** (tout à None) sur les cas
  dégénérés (effectif nul, variance nulle) plutôt que d'inventer un signal. 7 tests unitaires.
- **Requêtes agrégées** (`api/queries/trends.py`, SQL à la main, pool `dict_row`) :
  `date_coverage` (décide l'activation des analyses temporelles), `theme_saturation`
  (volume/gagnants par trimestre, correcte dès que les dates existeront), `theme_win_rates`
  (analyse 5), `stack_winner_vs_rest` (analyse 3 : comptes gagnants/non-gagnants/ensemble +
  totaux pour le test z ; filtre `theme` et `winners_only`).
- **Routeur `/trends`** (`api/routers/trends.py`) — trois endpoints du contrat PROJECT.md :
  - `GET /trends` — tableau de bord : les 5 analyses bundlées, chacune avec `status` + note
    (comme `/themes/{slug}` bundle sa page).
  - `GET /trends/saturation?theme=` — analyse 1 (statut `awaiting_date_backfill`, points `[]`).
  - `GET /trends/stacks?theme=&winners_only=` — analyse 3, lift + test z par techno.
  - Slug de thème validé contre la taxonomie (**404** si inconnu). Statut team_size figé à
    `unavailable_in_corpus`.
- **Note méthodologique honnête** — la « normalisation par nombre de prix » de PROJECT.md
  **n'est pas faisable** (aucune donnée de prix dans le corpus : `prize_track` seulement pour
  ethglobal, pas de table prix). `WIN_RATE_BIAS_NOTE` mise à jour en conséquence. Le caveat
  des stacks (`WINNER_STACKS_CAVEAT`) nomme le **piège de confondant de source** : les rares
  non-gagnants venant tous de lablab, une différence « significative » au test reflète la
  source, pas un effet de victoire.
- **Front** — page **`/trends`** (Server Component, ISR 24 h), graphes en **SVG/CSS pur**
  (aucune lib de charting). Pastilles de statut à 3 états, cartes d'état vide au ton distinct
  (attente ambre vs absence neutre), barres de fréquence (analyse 3) avec lift + marqueur `✻`
  de significativité renvoyant au caveat, barres de volume + « fort volume / faible win rate »
  (analyse 5), note méthodo globale en tête. Lien **« Tendances »** ajouté à la nav.
- **Qualité** — `ruff` + `mypy --strict` clean, `tsc --noEmit` clean, **49 tests** verts.
  Vérifié : logique des builders en direct sur la DB (21 027 projets), endpoints de contrat
  en HTTP (saturation en attente, 404 thème, `winners_only` true/false), et rendu `/trends`
  dans le navigateur (5 cartes, statuts, caveats, `✻`).

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| Analyses 1 & 2 (dates) | Requêtes écrites et correctes, statut `awaiting_date_backfill`, séries vides | S'activeront seules au backfill Ét. 6 ; même patron que `since`/`until` de l'Ét. 3 |
| Analyse 4 (team_size) | Statut distinct `unavailable_in_corpus`, pas de calcul construit | Donnée absente de toutes les sources ; le rescrape ne la garantit pas — ne rien promettre |
| Analyse 3 (stacks) | Calculée + livrée avec caveat de **confondant de source** | Corpus ~99 % gagnants → lift ≈ 1 ; « significativité » = artefact de source (lablab), pas de victoire |
| Normalisation par prix | **Abandonnée**, note méthodo honnête | Aucune donnée de nombre de prix dans le corpus ; la promettre serait mentir |
| Test statistique | z deux proportions en **Python pur** (`math.erf`) | API légère, pas de scipy ; dégénérescence explicite plutôt qu'un faux signal |
| `/trends` bundle | Un endpoint agrège les 5 analyses + statuts | La page fait un seul appel ; patron cohérent avec `/themes/{slug}` |

### En suspens / dette connue

- **3 des 5 analyses en attente de données** — saturation, cycle de vie et corrélation
  équipe restent vides tant que l'Étape 6 n'a pas backfillé `hackathon_date` (et,
  éventuellement, `team_size`). La plomberie et les requêtes sont prêtes : saturation et
  cycle de vie s'allumeront automatiquement dès que des dates seront présentes.
- **Analyse 4 peut-être jamais** — si aucune source ne fournit la taille d'équipe au
  rescrape, la corrélation équipe/classement restera `unavailable_in_corpus`. À rebâtir (test
  de corrélation + graphe) seulement quand la donnée existera.
- **Analyses 3 & 5 biaisées par le corpus winners-only** — chiffres justes mais peu
  informatifs tant que le corpus est ~99 % gagnants. Le vrai contraste (gagnants vs
  non-gagnants variés) arrivera au rescrape. Notes de biais en place partout.
- **Backfill embeddings toujours incomplet** (hérité Ét. 3) — sans impact sur les Trends
  (agrégats SQL, pas de vecteur).

---

## Étape 6 — Scraping (acquisition) ✅

**Statut : terminée.** Branche `etape-6-scraping` (depuis `main`). Cœur data-engineering
écrit de zéro : aucune collecte n'existait (le corpus venait d'un import SQLite unique).

### Fait

- **Socle poli** (`pipeline/scrapers/base.py`) — `BaseScraper` (client httpx injectable),
  rate limit **1 req/s par domaine**, respect de `robots.txt`
  (`urllib.robotparser`, parsé depuis le même client), retry borné sur transitoire (5xx/
  timeout, jamais sur 403), **détection anti-bot** (`detect_block` : 403/503 + marqueurs
  Cloudflare/captcha → `ScraperBlocked`, jamais de contournement), cache HTTP disque
  optionnel (`--cache`). Généralise le patron `_throttle`/`GitHubBlocked` de `github_stack`.
- **Trois scrapers**, parsing **pur** (fonctions testables sans réseau) séparé de la couche
  HTTP :
  - **ethglobal** (`ethglobal.py`) — port Python de l'extraction RSC Next.js
    (`self.__next_f.push`), listing `/showcase` → page projet. Extrait **`event.startTime` →
    `hackathon_date`**, prix → placement/prize_track/is_winner, `sourceCodeUrl` → repo_url,
    description (champ inline **ou** chunk texte `NN:T…` quand la valeur est une référence RSC
    `$28`). Unicode RSC (`\uXXXX`) dé-échappé.
  - **devpost** (`devpost.py`) — 3 phases : API liste (dates de hackathon best-effort) →
    gallery HTML (ruban `img.winner` dans `aside.entry-badge`, selectolax, membres dédupés) →
    page `/software/{slug}` pour la **description intégrale** (comble la dette devpost).
  - **lablab** (`lablab.py`) — **live via l'API JSON publique** `/api/v4/submissions`
    (sondée : 200, paginée par cursor, permise par `robots.txt` ; seule la surface HTML est
    Cloudflare). `parse_submissions` pur + `scrape()` live + `ingest_archive(winners.json)`
    en repli hors ligne. La détection anti-bot reste le garde-fou si l'API se ferme un jour.
- **Runner** (`run.py`) — écrit **uniquement en staging** ; run réussi → statut `scraped`,
  blocage → `blocked` + notes, autre erreur → `failed`. Chemin d'écriture staging factorisé
  dans `pipeline/load/staging.py` (`open_run`/`write_staging_batch`/`finish_run`), **réutilisé
  aussi par `import_sqlite.py`** (fin de la duplication du gros INSERT). Helpers de parsing
  (`LABLAB_MAP`, `parse_place`, `clean`) sortis dans `pipeline/normalize/parse_helpers.py`.
- **Migration `0011`** — deux statuts de run : `scraped` (fini, non validé — l'enum n'avait
  aucun état terminal non-validé) et `blocked` (anti-bot, **distinct de `failed`** pour que la
  CI de l'Étape 7 traite les deux différemment).
- **Tests de contrat** (`pipeline/contracts/`) — fixtures **réelles** figées (devpost/ethglobal
  captées au smoke-scrape ; lablab = sous-ensemble de `winners.json` + challenge Cloudflare
  synthétique). `test_base` (rate limit, robots disallow, détection anti-bot, cache) + un test
  par source (invariants : champs requis, winner/placement, **date parsée** pour ethglobal,
  tech mappée pour lablab, description résolue). **+24 tests (73 au total)**, sans réseau.
- **Qualité & vérif** — `ruff` + `mypy --strict` clean. Migration appliquée. **Smoke-scrape
  live poli** (1 req/s, robots respecté) sur les **trois** sources : ethglobal 5/5 avec
  `hackathon_date` (2026-06-12) + description, devpost 3/3 (gagnants weatherwise), lablab 5/5
  (via API publique) → `projects_staging`, tous en `scraped` et 100 % nouveaux vs `projects`.
  **`projects` inchangée** (21 027). Chemin `blocked` vérifié (challenge Cloudflare mocké →
  statut `blocked`, 0 ligne stagée, 0 `failed`).

### Décisions prises

| Sujet | Décision | Raison |
|---|---|---|
| lablab | **Live via API JSON publique** (sondée), archive en repli | L'hypothèse « Cloudflare bloque » (héritée du JS) était fausse pour l'API : 200 sans challenge, robots OK. Le cookie de l'ancien scraper servait l'API *authentifiée*, plus nécessaire |
| Blocage anti-bot | `status='blocked'` + notes, **stop**, aucun effet externe | L'ouverture d'issue est un effet de bord imprévisible en local ; câblée à la CI (Étape 7). `blocked` ≠ `failed` |
| Statut d'un scrape réussi | Nouveau `scraped` (fini, non validé) | L'enum n'avait pas d'état terminal avant validation ; poser `validated` mentirait |
| Fixtures | **Vraies** captures (devpost/ethglobal) + winners.json (lablab) | Tester le parsing sur du HTML/RSC réel, pas sur des maquettes ; démarre le compteur mainteneur |
| Description devpost | Fetch de la page `/software/{slug}` | Comble la dette « short_description seulement » ; la fraîcheur profite aux embeddings futurs |
| tech lablab scrapée | En `raw_project_tech` (`stack_source` reste `none`) | Cohérent avec l'import Ét. 1 ; la normalisation `tech_stack` est le job de l'Étape 4 |

### En suspens / dette connue

- **`hackathon_date` backfillé au fil du scrape, pas encore promu** — les dates existent en
  staging (ethglobal sûr, devpost best-effort) mais n'atteindront `projects` qu'après la
  validation/promotion (Étape 7). C'est à ce moment que les analyses 1 & 2 de `/trends`
  s'allumeront.
- **Dates devpost best-effort** — parsées d'un libellé humain (`submission_period_dates`,
  ex. « Apr 05 - 06, 2024 ») : date de fin, jour+dernier mois+année. Fiable sur les formats
  vus, `None` sinon. ethglobal reste la source de dates fiable (ISO `startTime`).
- **`team_size` toujours absent** — aucune source scrapée ne fournit la composition d'équipe
  (devpost donne des noms de membres → `team_name`, pas un décompte fiable). L'analyse 4 de
  `/trends` reste `unavailable_in_corpus`.
- **Pas de validation ni de récurrence** — promotion des scrapes, seuils
  `thresholds.yaml`, workflow hebdo GitHub Actions et ouverture d'issue réelle sur blocage :
  tout ça est l'Étape 7. Ici, un scrape s'arrête à `staging`.
- **Robustesse des sélecteurs = surface du mainteneur (Étape 9)** — les tests de contrat sur
  fixtures figées sont le Niveau 1 (détection). Ils doivent tourner ~1 mois avant d'envisager
  les niveaux diagnostic/correction.
