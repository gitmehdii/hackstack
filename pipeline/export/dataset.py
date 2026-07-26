"""Export du dataset public vers un dossier prêt pour HuggingFace (Étape 8).

Produit un dossier autonome (parquet + carte de dataset) à pousser tel quel sur HF :

    projects.parquet     métadonnées, champs dérivés, URLs sources — AUCUN texte libre long
    hackathons.parquet   table de référence des hackathons
    embeddings.parquet   id + vecteur bge-m3 (fichier séparé : ~85 Mo, téléchargeable à part)
    README.md            carte de dataset (licence, attribution, colonnes, couverture)

Invariant légal (PROJECT.md § contraintes) : on ne republie jamais le texte intégral des
descriptions. `description`, `short_description` et `fts` ne sortent pas de la base ; seules
leur présence et leur longueur sont exposées, comme signal de complétude. `check_columns`
verrouille ça et est couvert par les tests — ne pas contourner.

Le script lit uniquement `projects` / `hackathons`, donc uniquement des lignes déjà promues
(la promotion est le seul chemin d'écriture, cf. Étape 7). Rien à valider ici.

Usage :
    python -m pipeline.export.dataset --out dist/hackstack-dataset
    python -m pipeline.export.dataset --out dist/d --no-embeddings   # itération rapide
    python -m pipeline.export.dataset --out dist/d --version 2026q3  # tag de release
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

import polars as pl

from pipeline.load.db import connect

# Colonnes de `projects` publiées telles quelles. Liste explicite, jamais `SELECT *` :
# une colonne ajoutée en base ne doit pas se retrouver publiée par accident.
PROJECT_COLUMNS: tuple[str, ...] = (
    "id",
    "source",
    "source_url",
    "hackathon_slug",
    "hackathon_name",
    "hackathon_date",
    "title",
    "theme_tags",
    "tech_stack",
    "stack_source",
    "is_winner",
    "placement",
    "raw_placement",
    "prize_track",
    "team_size",
    "team_name",
    "repo_url",
    "demo_url",
    "scraped_at",
)

# Texte libre long : reste en base pour la recherche, ne sort jamais dans le dataset.
FORBIDDEN_COLUMNS = frozenset({"description", "short_description", "fts"})

HACKATHON_COLUMNS: tuple[str, ...] = ("source", "slug", "name", "hackathon_date", "url")

# Dérivés du texte : la présence et la taille sont publiables, le contenu non.
DERIVED_COLUMNS: tuple[str, ...] = ("has_description", "description_chars", "has_embedding")

# Types de sortie déclarés, pas inférés : une colonne entièrement NULL sur un export donné
# (`hackathon_date` aujourd'hui) doit garder son type, sinon le parquet change de schéma
# d'une release à l'autre et casse les consommateurs.
PROJECT_SCHEMA: dict[str, Any] = {
    "id": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "hackathon_slug": pl.String,
    "hackathon_name": pl.String,
    "hackathon_date": pl.Date,
    "title": pl.String,
    "theme_tags": pl.List(pl.String),
    "tech_stack": pl.List(pl.String),
    "stack_source": pl.String,
    "is_winner": pl.Boolean,
    "placement": pl.Int32,
    "raw_placement": pl.String,
    "prize_track": pl.String,
    "team_size": pl.Int32,
    "team_name": pl.String,
    "repo_url": pl.String,
    "demo_url": pl.String,
    "scraped_at": pl.Datetime("us", "UTC"),
    "has_description": pl.Boolean,
    "description_chars": pl.Int32,
    "has_embedding": pl.Boolean,
}

HACKATHON_SCHEMA: dict[str, Any] = {
    "source": pl.String,
    "slug": pl.String,
    "name": pl.String,
    "hackathon_date": pl.Date,
    "url": pl.String,
}

# Float32 : bge-m3 est stocké en `real[]` côté Postgres, doubler la taille du fichier
# n'ajouterait aucune précision.
EMBEDDING_SCHEMA: dict[str, Any] = {"id": pl.String, "embedding": pl.List(pl.Float32)}

LICENSE = "cc-by-sa-4.0"


def check_columns(columns: tuple[str, ...]) -> None:
    """Garde-fou : refuse d'exporter si une colonne interdite s'est glissée dans la liste."""
    leaked = sorted(FORBIDDEN_COLUMNS.intersection(columns))
    if leaked:
        raise ValueError(
            f"colonnes interdites dans l'export : {', '.join(leaked)} "
            "(le texte intégral ne se republie pas, cf. PROJECT.md)"
        )


def _projects_sql() -> str:
    check_columns(PROJECT_COLUMNS)
    cols = ", ".join(PROJECT_COLUMNS)
    derived = (
        "(description IS NOT NULL OR short_description IS NOT NULL) AS has_description, "
        "coalesce(length(description), length(short_description), 0) AS description_chars, "
        "(embedding IS NOT NULL) AS has_embedding"
    )
    return f"SELECT {cols}, {derived} FROM projects ORDER BY id"


def _embeddings_query(
    projects: pl.DataFrame, limit: int | None
) -> tuple[str, tuple[Any, ...] | None]:
    """Vecteurs des projets réellement exportés.

    Un `LIMIT` indépendant serait faux : cette requête ne filtre pas comme celle des
    projets (`WHERE embedding IS NOT NULL`), donc les deux `LIMIT` retiendraient des ids
    différents. Mesuré sur la base : parmi les 2 000 premiers ids, 38 n'ont pas de vecteur
    — soit 38 lignes de `embeddings.parquet` absentes de `projects.parquet`. Sans `--limit`
    la question ne se pose pas (tous les projets sortent), et on évite alors de passer un
    tableau de 21 k ids au serveur.
    """
    sql = "SELECT id, embedding::real[] AS embedding FROM projects WHERE embedding IS NOT NULL"
    if limit is None:
        return f"{sql} ORDER BY id", None
    return f"{sql} AND id = ANY(%s) ORDER BY id", (list(projects["id"]),)


def _fetch(
    conn: Any,
    sql: str,
    params: tuple[Any, ...] | None,
    schema: dict[str, Any],
    limit: int | None = None,
) -> pl.DataFrame:
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        names = [d.name for d in cur.description or []]
        rows = cur.fetchall()
    if names != list(schema):
        raise ValueError(f"colonnes SQL {names} != schéma déclaré {list(schema)}")
    return pl.DataFrame(rows, schema=schema, orient="row")


def render_card(stats: dict[str, Any]) -> str:
    """Carte de dataset HuggingFace (front-matter YAML + corps markdown)."""
    return f"""---
license: {LICENSE}
language:
  - en
tags:
  - hackathons
  - projects
  - embeddings
pretty_name: Hackstack — projets de hackathons
size_categories:
  - 10K<n<100K
configs:
  - config_name: projects
    data_files: projects.parquet
  - config_name: hackathons
    data_files: hackathons.parquet
  - config_name: embeddings
    data_files: embeddings.parquet
---

# Hackstack — projets de hackathons

{stats["n_projects"]} projets issus de {stats["n_hackathons"]} hackathons collectés sur
lablab.ai, Devpost et ETHGlobal. Gagnants **et** non-gagnants (`is_winner` distingue les
deux) : le dataset se filtre a posteriori, il ne se recomplète pas.

Version `{stats["version"]}` — export du {stats["exported_at"]}.

## Fichiers

| Fichier | Contenu |
|---|---|
| `projects.parquet` | un projet par ligne : métadonnées, champs dérivés, URLs sources |
| `hackathons.parquet` | table de référence (clé `source` + `slug`) |
| `embeddings.parquet` | `id` + vecteur `bge-m3` de dimension 1024, normalisé (cosine) |

`embeddings.parquet` est séparé pour rester téléchargeable indépendamment.

## Ce qui n'est pas publié, et pourquoi

**Le texte intégral des descriptions n'est pas republié.** Les descriptions appartiennent à
leurs auteurs et aux plateformes d'origine. Le dataset donne à la place `source_url` (le lien
vers la page d'origine), `has_description` et `description_chars` — assez pour juger la
complétude et aller lire la source, pas pour rediffuser le contenu.

Les embeddings, eux, sont publiés : ils permettent la recherche sémantique et la
classification sans rediffuser le texte.

## Colonnes de `projects`

| Colonne | Type | Note |
|---|---|---|
| `id` | string | identifiant stable (hash de l'URL source) |
| `source` | string | `lablab`, `devpost` ou `ethglobal` |
| `source_url` | string | page d'origine du projet |
| `hackathon_slug`, `hackathon_name` | string | rattachement au hackathon |
| `hackathon_date` | date | date du hackathon ({stats["pct_date"]} % renseignées) |
| `title` | string | titre du projet |
| `theme_tags` | list[string] | thèmes extraits par LLM ({stats["pct_theme"]} % renseignés) |
| `tech_stack` | list[string] | technologies, voir `stack_source` pour la provenance |
| `stack_source` | string | `github`, `llm` ou `none` |
| `is_winner` | bool | gagnant d'un prix quelconque |
| `placement`, `raw_placement` | int / string | classement normalisé et libellé d'origine |
| `prize_track` | string | piste de prix, quand la source la donne |
| `team_size`, `team_name` | int / string | équipe, quand la source la donne |
| `repo_url`, `demo_url` | string | liens sortants déclarés par le projet |
| `scraped_at` | timestamp | date de collecte de la ligne |
| `has_description` | bool | une description existe côté source |
| `description_chars` | int | sa longueur (0 si absente) |
| `has_embedding` | bool | un vecteur existe dans `embeddings.parquet` |

Couverture des embeddings : {stats["n_embeddings"]} / {stats["n_projects"]}
({stats["pct_embedding"]} %).

## Licence et attribution

Dataset sous [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Les données
proviennent de [lablab.ai](https://lablab.ai), [Devpost](https://devpost.com) et
[ETHGlobal](https://ethglobal.com) ; citez ces sources en plus de ce dataset. Le code du
pipeline est sous licence MIT.
"""


def export(out_dir: Path, with_embeddings: bool, version: str, limit: int | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        projects = _fetch(conn, _projects_sql(), None, PROJECT_SCHEMA, limit)
        hackathons_sql = (
            f"SELECT {', '.join(HACKATHON_COLUMNS)} FROM hackathons ORDER BY source, slug"
        )
        hackathons = _fetch(conn, hackathons_sql, None, HACKATHON_SCHEMA)
        embeddings = pl.DataFrame(schema=EMBEDDING_SCHEMA)
        if with_embeddings:
            embeddings = _fetch(conn, *_embeddings_query(projects, limit), EMBEDDING_SCHEMA)

    check_columns(tuple(projects.columns))

    projects.write_parquet(out_dir / "projects.parquet")
    hackathons.write_parquet(out_dir / "hackathons.parquet")
    if with_embeddings:
        embeddings.write_parquet(out_dir / "embeddings.parquet")

    n = max(len(projects), 1)
    stats = {
        "version": version,
        "exported_at": dt.date.today().isoformat(),
        "n_projects": len(projects),
        "n_hackathons": len(hackathons),
        "n_embeddings": len(embeddings),
        "pct_date": round(100 * projects["hackathon_date"].is_not_null().sum() / n),
        "pct_theme": round(100 * (projects["theme_tags"].list.len() > 0).sum() / n),
        "pct_embedding": round(100 * len(embeddings) / n),
    }
    (out_dir / "README.md").write_text(render_card(stats), encoding="utf-8")

    print(f"Dataset exporté dans {out_dir} :")
    print(f"  projects.parquet   {len(projects)} lignes")
    print(f"  hackathons.parquet {len(hackathons)} lignes")
    if with_embeddings:
        print(f"  embeddings.parquet {len(embeddings)} lignes ({stats['pct_embedding']} %)")
    else:
        print("  embeddings.parquet non généré (--no-embeddings)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True, help="dossier de sortie")
    ap.add_argument("--no-embeddings", action="store_true")
    ap.add_argument("--version", default=dt.date.today().isoformat(), help="tag de release")
    ap.add_argument("--limit", type=int, default=None, help="test rapide")
    args = ap.parse_args()
    export(args.out, not args.no_embeddings, args.version, args.limit)


if __name__ == "__main__":
    main()
