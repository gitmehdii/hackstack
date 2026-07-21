-- Journal des runs de pipeline (scrape ou import).
-- source NULL = run multi-sources (ex. l'import initial du corpus).
CREATE TABLE scrape_runs (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       source_t,
    kind         text        NOT NULL DEFAULT 'scrape',  -- 'import' | 'scrape'
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       run_status_t NOT NULL DEFAULT 'running',
    n_scraped    int,
    n_promoted   int,
    notes        text
);
