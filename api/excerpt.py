"""Extraction d'un extrait de description.

Invariant légal (PROJECT.md) : le site n'affiche qu'un extrait, jamais le texte
intégral. On tronque proprement sur une frontière de mot.
"""

from __future__ import annotations


def make_excerpt(
    description: str | None,
    short_description: str | None,
    max_chars: int,
) -> tuple[str | None, bool]:
    """Retourne (extrait, tronqué?).

    Préfère la description intégrale (tronquée) au short_description ; retombe sur
    le short_description s'il n'y a pas de description. Renvoie (None, False) si les
    deux sont vides.
    """
    text = (description or "").strip() or (short_description or "").strip()
    if not text:
        return None, False

    if len(text) <= max_chars:
        return text, False

    cut = text[:max_chars]
    # Recule jusqu'à la dernière espace pour ne pas couper un mot en deux.
    space = cut.rfind(" ")
    if space > max_chars // 2:
        cut = cut[:space]
    return cut.rstrip() + "…", True
