-- Zone de staging : tout scrape/import atterrit ici d'abord.
-- Un batch = un scrape_run. La promotion vers projects est explicite et conditionnée
-- à la validation (cf. pipeline/load/promote.py et pipeline/contracts/).
-- Pas de FK vers hackathons : un batch peut contenir un hackathon pas encore promu.
-- Pas de colonne fts générée : la recherche ne touche jamais le staging.
CREATE TABLE projects_staging (
    scrape_run_id     bigint      NOT NULL,
    id                text        NOT NULL,
    source            source_t    NOT NULL,
    source_url        text        NOT NULL,

    hackathon_slug    text        NOT NULL,
    hackathon_name    text        NOT NULL,
    hackathon_date    date,

    theme_tags        text[]      NOT NULL DEFAULT '{}',

    title             text        NOT NULL,
    description       text,
    short_description text,

    placement         int,
    raw_placement     text,
    is_winner         boolean     NOT NULL,
    prize_track       text,

    tech_stack        text[]      NOT NULL DEFAULT '{}',
    stack_source      stack_source_t NOT NULL DEFAULT 'none',

    team_size         int,
    team_name         text,

    repo_url          text,
    demo_url          text,

    scraped_at        timestamptz NOT NULL,

    PRIMARY KEY (scrape_run_id, id)
);

-- Hackathons découverts pendant un run, en attente de promotion.
CREATE TABLE hackathons_staging (
    scrape_run_id     bigint      NOT NULL,
    source            source_t    NOT NULL,
    slug              text        NOT NULL,
    name              text        NOT NULL,
    hackathon_date    date,
    url               text,
    scraped_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scrape_run_id, source, slug)
);
