"""Point d'entrée du runtime Python de Vercel : expose l'application ASGI.

Vercel cherche une variable `app` dans le fichier désigné par `vercel.json`. Le module ne
fait que ça — toute la logique reste dans `api/main.py`, qui sert aussi au dev local via
`uvicorn api.main:app`.

La racine du dépôt est ajoutée à `sys.path` : la fonction est exécutée depuis un répertoire
qui n'est pas forcément la racine, alors que `api` et `pipeline` s'importent en absolu.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import app  # noqa: E402

__all__ = ["app"]
