-- Table finale, lecture seule pour le site. Rien n'écrit jamais ici directement :
-- l'écriture passe par projects_staging puis promotion explicite (cf. 0005).
CREATE TABLE projects (
    id                text        PRIMARY KEY,   -- sha256(source||':'||slug), déterministe
    source            source_t    NOT NULL,
    source_url        text        NOT NULL,

    hackathon_slug    text        NOT NULL,
    hackathon_name    text        NOT NULL,
    hackathon_date    date,                       -- dénormalisé depuis hackathons (NULL pour l'instant)

    theme_tags        text[]      NOT NULL DEFAULT '{}',

    title             text        NOT NULL,
    description       text,                       -- texte intégral, NULL possible (devpost n'a que le court)
    short_description text,

    placement         int,                        -- 1, 2, 3 ou NULL (podium normalisé)
    raw_placement     text,                       -- valeur source d'origine (WINNERS, TOP_2, "2nd place"…)
    is_winner         boolean     NOT NULL,
    prize_track       text,

    tech_stack        text[]      NOT NULL DEFAULT '{}',
    stack_source      stack_source_t NOT NULL DEFAULT 'none',

    team_size         int,                        -- indisponible dans le corpus actuel (NULL)
    team_name         text,

    repo_url          text,
    demo_url          text,

    scraped_at        timestamptz NOT NULL,
    embedding         vector(1024),               -- bge-m3, rempli par l'étape embed

    -- Vecteur full-text pour la recherche hybride (Étape 3).
    fts               tsvector GENERATED ALWAYS AS (
                          setweight(to_tsvector('english', coalesce(title, '')), 'A')
                          || setweight(to_tsvector('english', coalesce(short_description, '')), 'B')
                          || setweight(to_tsvector('english', coalesce(description, '')), 'C')
                      ) STORED,

    CONSTRAINT projects_placement_range CHECK (placement IS NULL OR placement >= 1),
    FOREIGN KEY (source, hackathon_slug) REFERENCES hackathons (source, slug)
);
