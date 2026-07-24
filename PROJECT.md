# hackstack

Base de données publique des projets de hackathon, avec recherche sémantique et analyse de tendances.

La base stocke les projets **gagnants et non-gagnants** (`is_winner` les distingue) : les
gagnants restent la vue par défaut du site et du dataset, mais garder les non-gagnants rend
le dataset plus précieux (on peut toujours filtrer, jamais récupérer après coup) et débiaise
l'analyse de tendances (le contraste gagnant/perdant du même événement). Décision prise à
l'Étape 6 ; cf. [STATE.md](STATE.md).

Site web + pipeline de collecte open source + dataset public.

---

## Contexte

J'ai déjà un corpus d'environ 21000 projets scrapés depuis lablab.ai, Devpost et ETHGlobal, actuellement en SQLite + ChromaDB. L'objectif est de transformer ça en un site public utilisable, avec un pipeline propre et un dataset republiable.

Le but est double : un outil que j'utilise réellement avant chaque hackathon, et un projet de portfolio orienté data engineering.

---

## Principe directeur

**Le dataset est l'actif, pas le code.** Le site consomme un snapshot versionné de la base. Si les scrapers cassent, le site continue de fonctionner avec des données moins fraîches. Cette séparation est structurante, ne la casse jamais.

---

## Stack

| Couche | Choix |
|---|---|
| Base | PostgreSQL 16 + pgvector (Supabase free tier au début) |
| Pipeline | Python 3.12, `httpx`, `selectolax`, `playwright` en dernier recours |
| Transformation | `polars` |
| Embeddings | `sentence-transformers`, modèle `BAAI/bge-m3` |
| Extraction stack | OpenRouter, modèle bon marché, sortie structurée |
| API | FastAPI |
| Front | Next.js 15 (App Router), TypeScript, Tailwind |
| Déploiement | Front sur Vercel, API sur VPS, base sur Supabase |
| CI | GitHub Actions |

Gestionnaire de paquets Python : `uv`. Front : `pnpm`.

---

## Structure du repo

```
hackstack/
├── pipeline/
│   ├── scrapers/
│   │   ├── base.py          # classe abstraite, retry, rate limit, cache HTTP
│   │   ├── lablab.py
│   │   ├── devpost.py
│   │   └── ethglobal.py
│   ├── normalize/
│   │   ├── schema.py        # dataclasses du schéma unifié
│   │   ├── dedup.py
│   │   └── stack_extract.py # extraction des technologies
│   ├── embed/
│   ├── load/                # écriture staging + promotion
│   └── contracts/           # tests de contrat sur les scrapers
├── api/
│   ├── main.py
│   ├── routers/
│   └── queries/
├── web/                     # Next.js
├── db/
│   └── migrations/          # SQL, versionné
├── datasets/                # scripts d'export vers HuggingFace
├── .github/workflows/
├── docker-compose.yml
└── README.md
```

---

## Schéma de données

```python
@dataclass
class Project:
    id: str                      # hash stable source+slug
    source: Literal["lablab", "devpost", "ethglobal"]
    source_url: str
    hackathon_slug: str
    hackathon_name: str
    hackathon_date: date | None
    theme_tags: list[str]
    title: str
    description: str
    placement: int | None        # 1, 2, 3, None
    is_winner: bool
    prize_track: str | None
    tech_stack: list[str]        # extrait, taxonomie fermée
    team_size: int | None
    repo_url: str | None
    demo_url: str | None
    scraped_at: datetime
    embedding: list[float]       # 1024 dims, bge-m3
```

Tables : `hackathons`, `projects`, `projects_staging`, `scrape_runs`, `contract_checks`.

`id` doit être déterministe pour que les rescrapes mettent à jour au lieu de dupliquer.

---

## Le pipeline

### Flux

```
scrape → projects_staging → validation → promotion → projects
```

Rien n'écrit jamais directement dans `projects`. La promotion est une étape explicite qui ne s'exécute que si la validation passe.

### Validation avant promotion

Compare le batch en staging au dernier run sain, par source :

- taux de champs non-nuls par colonne (écart max toléré : 15 points)
- longueur médiane des descriptions (écart max : 40%)
- nombre de projets par hackathon (écart max : 50%)
- taux de `placement` renseigné
- taux d'URLs valides

Si un seuil est dépassé, la promotion échoue, une issue GitHub est ouverte avec le rapport de diff, et `projects` reste inchangée.

Les seuils vivent dans `pipeline/contracts/thresholds.yaml`, pas en dur dans le code.

### Extraction de tech_stack

Deux passes :

1. Si `repo_url` existe et pointe vers GitHub, lire les langages via l'API GitHub et les fichiers de manifeste (`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`). Source fiable.
2. Sinon, un appel LLM sur la description avec une taxonomie fermée définie dans `pipeline/normalize/taxonomy.yaml`. Sortie JSON structurée, uniquement des valeurs de la taxonomie, pas de texte libre.

Marquer la provenance dans une colonne `stack_source` pour pouvoir filtrer sur la fiabilité.

---

## L'API

FastAPI, endpoints :

```
GET  /projects/{id}
GET  /hackathons/{slug}
GET  /search?q=&source=&winners_only=&since=&until=&limit=
GET  /themes/{slug}
GET  /trends/saturation?theme=
GET  /trends/stacks?theme=&winners_only=
GET  /stats
```

`/search` fait de la recherche hybride : vecteur pgvector + full-text Postgres, fusion par Reciprocal Rank Fusion. Ne pas se contenter du vecteur seul, les recherches par nom de techno marchent mal en sémantique pure.

---

## Le site

Pages :

- `/` — recherche + quelques chiffres
- `/search` — résultats, filtres source / date / thème / gagnants
- `/project/[id]` — détail, projets similaires en bas
- `/hackathon/[slug]` — palmarès complet
- `/theme/[slug]` — volume, taux de victoire, stacks dominantes
- `/trends` — dashboard

Rendu : ISR pour les pages projet, hackathon et thème (revalidate 24h), client-side pour `/search`.

Métadonnées Open Graph sur chaque page projet et hackathon. Sitemap généré. Ces pages sont censées être trouvables.

---

## Les statistiques

Les analyses à implémenter dans `/trends` :

1. Fréquence d'un thème par trimestre, superposée à son taux de victoire
2. Durée de vie d'une tendance : premier projet, pic, déclin
3. Stacks des gagnants vs stacks de l'ensemble, avec test statistique
4. Corrélation taille d'équipe / classement
5. Thèmes à fort volume et faible taux de victoire

**Important sur l'interprétation.** Le taux de victoire par thème est biaisé par le nombre de prix disponibles et par les tracks sponsorisées. Un projet blockchain sur ETHGlobal gagne plus souvent parce qu'il y a plus de prix, pas parce que l'idée est meilleure.

Donc : normaliser par le nombre de prix de l'événement quand l'information est disponible, et afficher une note méthodologique explicite sur `/trends` quand elle ne l'est pas. Ne pas présenter un chiffre biaisé comme une conclusion.

---

## Aspects légaux, à traiter dès le début

- Vérifier les CGU de lablab.ai, Devpost et ETHGlobal avant de publier quoi que ce soit
- Respecter `robots.txt`, avec un User-Agent identifiable qui pointe vers le repo
- Rate limit conservateur : 1 requête/seconde par domaine maximum
- **Ne pas republier les descriptions intégrales dans le dataset public.** Publier les métadonnées, les URLs sources, les champs dérivés (tech_stack, tags) et les embeddings. Le texte intégral reste en base pour la recherche, le site affiche un extrait avec un lien vers la source.
- Licence : code en MIT, dataset en CC BY-SA avec attribution des sources

Si un scraper rencontre un blocage anti-bot (Cloudflare challenge, captcha, 403 systématique), il s'arrête et ouvre une issue. Il ne contourne pas.

---

## Ordre de construction

### Étape 1 — Fondations

- Schéma Postgres + migrations
- Import du corpus SQLite existant vers Postgres
- Génération des embeddings, index pgvector (HNSW)
- Aucun scraping à ce stade

### Étape 2 — Site en lecture seule

- API : `/projects/{id}`, `/hackathons/{slug}`
- Pages projet et hackathon en ISR
- Pas encore de recherche

À la fin de cette étape le site doit être déployable et consultable.

### Étape 3 — Recherche

- `/search` hybride vecteur + full-text
- Page de résultats avec filtres
- Projets similaires sur la page projet

### Étape 4 — Thèmes et tech stack

- Taxonomie, extraction sur l'ensemble du corpus
- Pages `/theme/[slug]`

### Étape 5 — Trends

- Les cinq analyses, avec les graphes
- Note méthodologique

### Étape 6 — Scraping (acquisition)

Le cœur data engineering, entièrement à écrire (aucune collecte n'existe : le corpus vient
d'un import unique de SQLite). Alimente `projects_staging` en manuel.

- Classe de base `pipeline/scrapers/base.py` : retry, rate limit (1 req/s max par domaine),
  cache HTTP local pour le développement
- Les trois scrapers : `lablab.py`, `devpost.py`, `ethglobal.py`
- Politesse : respect de `robots.txt`, User-Agent identifiable pointant vers le repo, arrêt
  et ouverture d'issue sur blocage anti-bot (Cloudflare/captcha/403) — jamais de contournement
- Tests de contrat sur fixtures HTML figées (`pipeline/contracts/`) — démarre aussi le
  compteur « un mois » exigé avant l'agent mainteneur

À la fin de cette étape, un scrape produit de la donnée fraîche dans `staging` ; elle n'y
monte dans `projects` qu'une fois la barrière de validation posée (Étape 7).

### Étape 7 — Validation & automatisation

Rend le scrape récurrent et sûr.

- Validation avant promotion : comparaison du batch au dernier run sain par source, seuils
  dans `pipeline/contracts/thresholds.yaml`, rapport de diff, issue GitHub auto en cas
  d'échec ; `projects` reste inchangée si un seuil est dépassé
- Workflow GitHub Actions hebdomadaire

### Étape 8 — Dataset public

- Export vers HuggingFace Datasets
- Releases trimestrielles versionnées

### Étape 9 — Agent mainteneur

Voir la section dédiée plus bas. **Ne pas commencer cette étape avant que les étapes 1 à 8 soient stables et que les tests de contrat aient tourné pendant au moins un mois.**

---

## Agent mainteneur (étape 9, plus tard)

L'idée : un agent qui diagnostique et propose des corrections quand un scraper casse.

Trois niveaux, à implémenter dans l'ordre, jamais en sautant une marche :

**Niveau 1 — détection.** Aucun LLM. Les tests de contrat (écrits à l'étape 6, planifiés en hebdomadaire à l'étape 7) tournent chaque semaine sur un échantillon de 20 pages figées par source, et vérifient les invariants. Issue automatique en cas d'échec. Ce niveau attrape la grande majorité des casses et doit être fiable avant d'aller plus loin.

**Niveau 2 — diagnostic.** Quand le niveau 1 échoue, un agent reçoit : le HTML de référence, le HTML actuel, le code du scraper, le rapport d'échec. Il écrit une analyse dans l'issue. Il ne modifie aucun fichier. Périmètre en lecture seule, strictement.

**Niveau 3 — correction.** L'agent ouvre une PR modifiant uniquement les sélecteurs dans `pipeline/scrapers/`. Conditions non négociables :

- la PR ne peut toucher aucun autre répertoire
- elle ne merge que si les tests de contrat passent sur l'échantillon figé
- auto-merge désactivé, revue humaine obligatoire
- l'agent n'a jamais accès à la table `projects`, uniquement à `projects_staging`
- si l'échec vient d'un blocage anti-bot, l'agent s'arrête et le signale, il ne cherche pas de contournement

Fichier `MAINTAINER.md` à la racine décrivant ce périmètre, lu par l'agent à chaque exécution.

Instrumenter : nombre de casses détectées, diagnostics corrects, PR mergées sans modification. Ces chiffres servent à décider si le niveau 3 mérite d'exister.

---

## Conventions de développement

- Tout le code Python typé, `mypy --strict` sur `pipeline/` et `api/`
- `ruff` pour le lint et le format
- Tests avec `pytest`, fixtures HTML figées pour les scrapers, jamais d'appel réseau en test
- Migrations SQL versionnées, jamais de modification de schéma à la main
- Secrets par variables d'environnement, `.env.example` à jour
- Commits conventionnels
- Une PR par étape, pas de commit géant

---

## Ce qu'il ne faut pas faire

- Écrire dans `projects` sans passer par staging
- Utiliser un ORM qui masque les requêtes vectorielles, écrire le SQL
- Ajouter Playwright par défaut, seulement là où le HTTP simple échoue
- Republier le texte intégral des descriptions
- Présenter des taux de victoire sans mention du biais de tracks
- Commencer l'étape 9 (agent mainteneur) avant que le reste soit stable

---

## Première tâche

Étape 1 uniquement. Commence par proposer le schéma SQL et le plan de migration depuis le SQLite existant, avant d'écrire du code. Je validerai avant de continuer.
