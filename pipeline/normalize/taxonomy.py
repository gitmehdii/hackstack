"""Chargement et validation des taxonomies fermées (tech_stack et thèmes), Étape 4.

Point d'entrée unique pour :
  - la liste canonique des technos et des thèmes (amorçage du prompt LLM),
  - le mapping des alias (passe GitHub : noms de paquets/langages -> valeur canonique),
  - le filtrage d'une sortie d'extraction sur la taxonomie (rejet du hors-vocabulaire),
  - le cap du nombre de thèmes par projet.

Les taxonomies sont des données versionnées (`*.yaml`), jamais du code en dur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_DIR = Path(__file__).resolve().parent
TAXONOMY_PATH = _DIR / "taxonomy.yaml"
THEMES_PATH = _DIR / "themes.yaml"


@dataclass(frozen=True)
class Theme:
    slug: str
    label: str
    description: str


@dataclass(frozen=True)
class Taxonomy:
    """Vocabulaire tech + thèmes, résolus une fois au chargement."""

    tech_canonical: tuple[str, ...]
    tech_by_category: dict[str, tuple[str, ...]]
    tech_aliases: dict[str, str]  # variante minuscule -> canonique
    themes: tuple[Theme, ...]
    max_themes_per_project: int
    _tech_lower: dict[str, str] = field(default_factory=dict)  # canonique minuscule -> canonique
    _theme_slugs: frozenset[str] = field(default_factory=frozenset)

    def theme_slugs(self) -> frozenset[str]:
        return self._theme_slugs

    def theme(self, slug: str) -> Theme | None:
        for t in self.themes:
            if t.slug == slug:
                return t
        return None

    def normalize_tech(self, raw: str) -> str | None:
        """Résout une techno brute (langage, paquet, sortie LLM) vers la valeur canonique.

        None si hors taxonomie. La résolution est insensible à la casse et passe par les
        alias avant de tenter une correspondance directe sur le vocabulaire canonique.
        """
        key = raw.strip().lower()
        if not key:
            return None
        if key in self.tech_aliases:
            return self.tech_aliases[key]
        return self._tech_lower.get(key)

    def clean_tech(self, values: list[str]) -> list[str]:
        """Filtre + normalise + dédoublonne une liste de technos, ordre stable."""
        out: list[str] = []
        seen: set[str] = set()
        for v in values:
            canon = self.normalize_tech(v)
            if canon is not None and canon not in seen:
                seen.add(canon)
                out.append(canon)
        return out

    def clean_themes(self, slugs: list[str]) -> list[str]:
        """Filtre sur les slugs connus, dédoublonne, cappe à max_themes_per_project."""
        out: list[str] = []
        seen: set[str] = set()
        for s in slugs:
            key = s.strip().lower()
            if key in self._theme_slugs and key not in seen:
                seen.add(key)
                out.append(key)
                if len(out) >= self.max_themes_per_project:
                    break
        return out


def _load_raw() -> Taxonomy:
    tax = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    thm = yaml.safe_load(THEMES_PATH.read_text(encoding="utf-8"))

    by_cat: dict[str, tuple[str, ...]] = {}
    canonical: list[str] = []
    for category, values in tax["canonical"].items():
        vals = tuple(str(v) for v in values)
        by_cat[category] = vals
        canonical.extend(vals)

    # Invariant : pas de doublon dans le vocabulaire canonique.
    dupes = {v for v in canonical if canonical.count(v) > 1}
    if dupes:
        raise ValueError(f"taxonomy.yaml : valeurs canoniques dupliquées : {sorted(dupes)}")

    tech_lower = {v.lower(): v for v in canonical}
    aliases = {str(k).lower(): str(v) for k, v in (tax.get("aliases") or {}).items()}
    # Invariant : tout alias pointe vers une valeur canonique existante.
    bad = {k: v for k, v in aliases.items() if v not in tech_lower.values()}
    if bad:
        raise ValueError(f"taxonomy.yaml : alias vers valeur inconnue : {bad}")

    themes = tuple(
        Theme(slug=str(t["slug"]), label=str(t["label"]), description=str(t["description"]))
        for t in thm["themes"]
    )
    slugs = [t.slug for t in themes]
    theme_dupes = {s for s in slugs if slugs.count(s) > 1}
    if theme_dupes:
        raise ValueError(f"themes.yaml : slugs dupliqués : {sorted(theme_dupes)}")
    if not 30 <= len(themes) <= 50:
        raise ValueError(
            f"themes.yaml : {len(themes)} thèmes hors de la fourchette voulue (30–50) — "
            "une taxonomie qui gonfle dilue les pages /theme."
        )

    return Taxonomy(
        tech_canonical=tuple(canonical),
        tech_by_category=by_cat,
        tech_aliases=aliases,
        themes=themes,
        max_themes_per_project=int(thm["max_per_project"]),
        _tech_lower=tech_lower,
        _theme_slugs=frozenset(slugs),
    )


@lru_cache(maxsize=1)
def load_taxonomy() -> Taxonomy:
    """Taxonomie résolue, mise en cache (les yaml ne changent pas en cours de process)."""
    return _load_raw()
