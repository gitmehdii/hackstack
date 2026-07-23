-- Étape 6 : deux états terminaux de run supplémentaires.
--   scraped : le scrape a fini, la donnée est en staging mais PAS encore validée.
--             L'enum n'avait aucun état « fini mais non validé » ; poser 'validated'
--             sur un scrape mentirait. L'Étape 7 fera scraped -> validated | failed.
--   blocked : arrêt sur blocage anti-bot (Cloudflare/captcha/403 systématique).
--             Distinct de 'failed' (échec technique) pour que la CI (Étape 7) traite
--             les deux différemment : un blocage n'est pas un bug du scraper.
-- ADD VALUE hors bloc-usage : le runner de migration commit avant tout usage (OK PG 16).
ALTER TYPE run_status_t ADD VALUE IF NOT EXISTS 'scraped';
ALTER TYPE run_status_t ADD VALUE IF NOT EXISTS 'blocked';
