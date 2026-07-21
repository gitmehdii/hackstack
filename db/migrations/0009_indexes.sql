-- Index sur projects. Le corpus (~21k lignes) est petit : maintenir le HNSW au fil
-- des UPDATE d'embeddings est négligeable, donc ces index font partie des migrations
-- normales. Pour un rechargement massif futur, envisager de DROP puis recréer.

-- Recherche vectorielle (cosine, cohérent avec bge-m3 normalisé).
CREATE INDEX projects_embedding_hnsw
    ON projects USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Recherche full-text (composante lexicale de la recherche hybride, Étape 3).
CREATE INDEX projects_fts_idx ON projects USING gin (fts);

-- Filtres sur tableaux.
CREATE INDEX projects_tech_stack_idx ON projects USING gin (tech_stack);
CREATE INDEX projects_theme_tags_idx ON projects USING gin (theme_tags);

-- Filtres et jointures fréquents.
CREATE INDEX projects_hackathon_idx ON projects (source, hackathon_slug);
CREATE INDEX projects_winners_idx   ON projects (source) WHERE is_winner;
CREATE INDEX projects_title_trgm_idx ON projects USING gin (title gin_trgm_ops);
