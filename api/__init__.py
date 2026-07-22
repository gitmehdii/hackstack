"""API FastAPI en lecture seule pour hackstack (Étape 2).

Le site consomme cette API ; elle lit `projects` / `hackathons` et n'écrit jamais.
Invariant légal : elle n'expose jamais la description intégrale, seulement un extrait
(`description_excerpt`) accompagné de l'URL source. Cf. PROJECT.md.
"""
