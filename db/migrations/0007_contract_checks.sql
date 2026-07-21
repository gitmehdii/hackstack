-- Résultats des tests de contrat / validation avant promotion (Étape 6).
-- Une ligne par vérification exécutée sur un run.
CREATE TABLE contract_checks (
    id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scrape_run_id  bigint      NOT NULL REFERENCES scrape_runs (id),
    source         source_t    NOT NULL,
    check_name     text        NOT NULL,
    passed         boolean     NOT NULL,
    detail         jsonb,                    -- diff / métriques mesurées vs seuil
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX contract_checks_run_idx ON contract_checks (scrape_run_id);
