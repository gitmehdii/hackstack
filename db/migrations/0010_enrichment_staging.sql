-- Enrichissement tech_stack / theme_tags (Étape 4).
--
-- Invariant PROJECT.md : rien n'écrit jamais direct dans `projects`. L'extraction écrit
-- dans ces tables de staging ; la promotion (pipeline/load/promote_enrichment.py) fusionne
-- les deux passes puis met à jour `projects` en une étape explicite.
--
-- Deux passes indépendantes, chacune ré-exécutable sans toucher l'autre :
--   1. github  — langages + manifestes du repo, fiable (couvre surtout ethglobal)
--   2. llm     — inférence sur la description (tech_stack ET theme_tags), taxonomie fermée
--
-- Fusion à la promotion : tech_stack = github si présent, sinon llm ; theme_tags = llm.

-- Passe 1 : résultat brut de la lecture du repo GitHub.
CREATE TABLE github_tech_staging (
    project_id  text     NOT NULL PRIMARY KEY,  -- = projects.id
    source      source_t NOT NULL,
    repo_url    text     NOT NULL,
    tech_stack  text[]   NOT NULL DEFAULT '{}',  -- déjà mappé sur la taxonomie fermée
    languages   jsonb,                           -- réponse brute /languages (octets par langage)
    manifests   text[]   NOT NULL DEFAULT '{}',  -- manifestes lus (package.json, go.mod…)
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

-- Passe 2 : résultat brut de l'extraction LLM (sortie structurée, valeurs de la taxonomie).
CREATE TABLE llm_extraction_staging (
    project_id   text     NOT NULL PRIMARY KEY,  -- = projects.id
    source       source_t NOT NULL,
    tech_stack   text[]   NOT NULL DEFAULT '{}',
    theme_tags   text[]   NOT NULL DEFAULT '{}',  -- <= 3 thèmes (cappé à l'extraction)
    model        text     NOT NULL,               -- modèle OpenRouter utilisé
    extracted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX github_tech_staging_source_idx ON github_tech_staging (source);
CREATE INDEX llm_extraction_staging_source_idx ON llm_extraction_staging (source);
