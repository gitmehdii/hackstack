-- Types énumérés partagés.

-- Sources de données. Taxonomie fermée : toute nouvelle source = migration explicite.
CREATE TYPE source_t AS ENUM ('lablab', 'devpost', 'ethglobal');

-- Provenance du tech_stack, pour filtrer sur la fiabilité (cf. PROJECT.md §extraction).
--   github  : lu depuis l'API GitHub / manifestes du repo (fiable)
--   llm     : inféré par LLM sur la description (taxonomie fermée)
--   scraped : tags bruts récupérés au scraping, non normalisés
--   none    : pas de stack renseigné
CREATE TYPE stack_source_t AS ENUM ('github', 'llm', 'scraped', 'none');

-- Statut d'un run de pipeline.
CREATE TYPE run_status_t AS ENUM ('running', 'validated', 'promoted', 'failed');
