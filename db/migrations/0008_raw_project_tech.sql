-- Tags technologiques bruts récupérés au scraping (actuellement : lablab uniquement).
-- Conservés tels quels, non normalisés, pour ne rien perdre avant l'extraction propre
-- de l'Étape 4 (taxonomie fermée). Ne PAS utiliser pour l'affichage : c'est du texte libre.
CREATE TABLE raw_project_tech (
    project_id  text NOT NULL,   -- même id que projects.id (pas de FK : peut précéder la promotion)
    source      source_t NOT NULL,
    tech_name   text NOT NULL,
    tech_slug   text,
    PRIMARY KEY (project_id, tech_name)
);

CREATE INDEX raw_project_tech_project_idx ON raw_project_tech (project_id);
