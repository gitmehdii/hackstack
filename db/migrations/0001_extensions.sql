-- Extensions requises.
-- pgvector : recherche vectorielle (embeddings bge-m3, 1024 dims).
-- pg_trgm  : recherche fuzzy / accélération LIKE (utile Étape 3).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
