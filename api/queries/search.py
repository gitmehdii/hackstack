"""Recherche hybride vecteur + full-text sur `projects` (Étape 3).

Deux bras exécutés en parallèle dans une seule requête :

- **vectoriel** : plus proches voisins cosine (`embedding <=> :qvec`, index HNSW) ;
- **lexical** : `websearch_to_tsquery` sur la colonne `fts` (index GIN), classé par
  `ts_rank_cd`, **relâché en OU seulement si la conjonction stricte ne matche rien**. La
  conjonction seule renvoyait 0 résultat sur une requête en langage naturel : le bras
  lexical, qui sert de filet quand l'encodeur de requêtes est indisponible, s'éteignait là
  où il devait rattraper.

Les deux classements sont fusionnés par **Reciprocal Rank Fusion** (RRF) : chaque
document reçoit `1/(k + rang)` dans chaque bras où il apparaît, on somme. RRF ne
dépend que des rangs, donc pas besoin de normaliser des scores hétérogènes (distance
cosine vs `ts_rank_cd`). Cf. PROJECT.md : « Ne pas se contenter du vecteur seul ».

Le SQL est écrit à la main (pas d'ORM masquant le vectoriel, cf. PROJECT.md). Les
fragments de filtre injectés sont des constantes internes ; toutes les *valeurs*
passent par des paramètres liés.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import AsyncConnection

# Colonnes remontées pour un résultat de recherche. `description`/`short_description`
# servent à fabriquer l'extrait côté routeur ; ni `embedding` ni `fts` ne sortent.
_HIT_COLUMNS = """
    p.id, p.source, p.source_url, p.title,
    p.description, p.short_description,
    p.hackathon_slug, p.hackathon_name,
    p.is_winner, p.placement, p.tech_stack, p.theme_tags
"""

# Constante RRF : amortit le poids des tout premiers rangs. 60 est la valeur usuelle
# de la littérature (Cormack et al.).
_RRF_K = 60

# Taille du vivier par bras avant fusion. Large devant `limit` pour que la fusion ait
# de la matière, petit devant le corpus pour rester rapide.
_CANDIDATES_PER_ARM = 200


def _build_filters(
    sources: list[str] | None,
    winners_only: bool,
    since: date | None,
    until: date | None,
) -> tuple[str, dict[str, Any]]:
    """Construit le fragment SQL commun aux deux bras et ses paramètres liés.

    Les conditions portent sur des colonnes de `projects` (accessibles sans alias
    dans les deux CTE). Renvoie ('' , {}) si aucun filtre.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if sources:
        clauses.append("source = ANY(%(sources)s)")
        params["sources"] = sources
    if winners_only:
        clauses.append("is_winner")
    if since is not None:
        # `hackathon_date` est NULL sur tout le corpus actuel (backfill Étape 6) :
        # ce filtre exclut donc naturellement les lignes sans date, ce qui est correct.
        clauses.append("hackathon_date >= %(since)s")
        params["since"] = since
    if until is not None:
        clauses.append("hackathon_date <= %(until)s")
        params["until"] = until
    filter_sql = ("AND " + " AND ".join(clauses)) if clauses else ""
    return filter_sql, params


async def search_projects(
    conn: AsyncConnection,
    query: str,
    query_vector: list[float] | None,
    *,
    sources: list[str] | None = None,
    winners_only: bool = False,
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recherche hybride. `query_vector` peut être None (bras vectoriel désactivé).

    Le bras vectoriel est ignoré si `query_vector` est None (ex. embeddings pas encore
    générés) : la recherche retombe alors sur le seul full-text, sans erreur.
    """
    filter_sql, params = _build_filters(sources, winners_only, since, until)
    params.update(
        {
            "q": query,
            "k": _RRF_K,
            "cand": _CANDIDATES_PER_ARM,
            "limit": limit,
        }
    )

    # Bras vectoriel : monté seulement si on a un vecteur de requête. Sinon on émet une
    # CTE vide typée pour garder la même forme de requête (FULL OUTER JOIN inchangé).
    if query_vector is not None:
        params["qvec"] = "[" + ",".join(f"{x:.7f}" for x in query_vector) + "]"
        vec_cte = f"""
        vec AS (
            SELECT id, row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rank
            FROM projects
            WHERE embedding IS NOT NULL {filter_sql}
            ORDER BY embedding <=> %(qvec)s::vector
            LIMIT %(cand)s
        )"""  # noqa: S608 (filter_sql = constantes internes, valeurs liées)
    else:
        vec_cte = """
        vec AS (
            SELECT NULL::text AS id, NULL::bigint AS rank WHERE false
        )"""

    sql = f"""
    WITH
    {vec_cte},
    tsq AS (
        -- `websearch_to_tsquery` exige TOUS les termes. Sur une requête en langage naturel
        -- (« helping blind people navigate cities ») il ne remonte donc rien : mesuré, 0
        -- résultat contre 2 506 en OU. Le bras lexical est censé être le filet quand le
        -- vecteur est indisponible — il s'éteignait précisément là où il devait servir.
        --
        -- On garde donc la conjonction stricte **quand elle matche**, et on ne relâche en OU
        -- que si elle ne renvoie rien. Deux raisons, toutes deux mesurées :
        --   - un OU systématique fait perdre l'index GIN au planificateur (Seq Scan sur un
        --     large vivier) : 2,5 ms → ~50 ms sur une requête courante ;
        --   - le cas nominal reste ainsi *identique* à l'existant, au lieu d'être « vérifié
        --     sur quelques exemples ».
        -- Quand le OU s'applique, `ts_rank_cd` classe d'abord les documents contenant le plus
        -- de termes : la précision reste en tête et le rappel suit derrière. Sans ce
        -- classement, on remplacerait le vide par du bruit.
        --
        -- Exception : si l'utilisateur a exclu un terme (`-foo` → `!foo`), relâcher
        -- inverserait son intention (`a | !b` matche presque tout). On reste strict.
        SELECT CASE
            WHEN s::text LIKE '%%!%%' THEN s
            WHEN EXISTS (SELECT 1 FROM projects WHERE fts @@ s {filter_sql}) THEN s
            ELSE replace(s::text, ' & ', ' | ')::tsquery
        END AS q
        FROM websearch_to_tsquery('english', %(q)s) AS s
    ),
    fts AS (
        SELECT id, row_number() OVER (ORDER BY ts_rank_cd(fts, tsq.q) DESC) AS rank
        FROM projects, tsq
        WHERE fts @@ tsq.q {filter_sql}
        ORDER BY ts_rank_cd(fts, tsq.q) DESC
        LIMIT %(cand)s
    ),
    fused AS (
        SELECT
            COALESCE(vec.id, fts.id) AS id,
            COALESCE(1.0 / (%(k)s + vec.rank), 0)
                + COALESCE(1.0 / (%(k)s + fts.rank), 0) AS score
        FROM vec
        FULL OUTER JOIN fts ON vec.id = fts.id
    )
    SELECT {_HIT_COLUMNS}, f.score
    FROM fused f
    JOIN projects p ON p.id = f.id
    ORDER BY f.score DESC, p.id
    LIMIT %(limit)s
    """  # noqa: S608 (fragments = constantes internes, valeurs liées)

    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return rows  # type: ignore[return-value]
