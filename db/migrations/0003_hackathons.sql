-- Hackathons : un événement par (source, slug).
-- hackathon_date est NULL à l'import initial (aucune date dans le corpus SQLite) ;
-- backfill prévu à l'Étape 6 via re-scrape ciblé.
CREATE TABLE hackathons (
    source          source_t    NOT NULL,
    slug            text        NOT NULL,
    name            text        NOT NULL,
    hackathon_date  date,
    url             text,
    scraped_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, slug)
);
