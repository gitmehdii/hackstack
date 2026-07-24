"""Petits helpers de parsing partagés entre l'import SQLite et les scrapers.

Extraits de `pipeline/load/import_sqlite.py` pour éviter la duplication : l'import et
les scrapers dérivent placement/is_winner et nettoient les chaînes de la même façon.
"""

from __future__ import annotations

import re

# "1st place" / "2nd Place" / "3rd  place" -> 1 / 2 / 3
PLACE_RE = re.compile(r"(\d+)\s*(?:st|nd|rd|th)\s+place", re.IGNORECASE)

# lablab : eventPosition -> (placement, is_winner).
# WINNERS/TOP_2/TOP_3 sont des gagnants ; FINALISTS/OTHER sont conservés non-gagnants.
LABLAB_MAP: dict[str, tuple[int | None, bool]] = {
    "WINNERS": (1, True),
    "TOP_2": (2, True),
    "TOP_3": (3, True),
    "FINALISTS": (None, False),
    "OTHER": (None, False),
}


def clean(value: str | None) -> str | None:
    """Trim + None si vide."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_place(text: str | None) -> int | None:
    """Rang extrait d'un libellé de prix ('2nd place' -> 2), ou None."""
    if not text:
        return None
    m = PLACE_RE.search(text)
    return int(m.group(1)) if m else None
