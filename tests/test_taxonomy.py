"""Tests des taxonomies fermées (chargement, invariants, filtrage), sans DB ni réseau."""

from __future__ import annotations

from pipeline.normalize.taxonomy import load_taxonomy


def test_loads_within_bounds() -> None:
    tax = load_taxonomy()
    assert 30 <= len(tax.themes) <= 50  # taxonomie plate et courte (contrainte Étape 4)
    assert tax.max_themes_per_project == 3
    assert len(tax.tech_canonical) > 0


def test_no_duplicate_canonical_tech() -> None:
    tax = load_taxonomy()
    assert len(set(tax.tech_canonical)) == len(tax.tech_canonical)


def test_every_alias_points_to_canonical() -> None:
    tax = load_taxonomy()
    canon = set(tax.tech_canonical)
    assert all(v in canon for v in tax.tech_aliases.values())


def test_normalize_tech_via_alias_and_case() -> None:
    tax = load_taxonomy()
    assert tax.normalize_tech("py") == "Python"
    assert tax.normalize_tech("PYTHON") == "Python"
    assert tax.normalize_tech("openai") == "GPT-4"
    assert tax.normalize_tech("ethers") == "ethers.js"
    assert tax.normalize_tech("totally-unknown-lib") is None


def test_clean_tech_dedups_and_drops_unknown() -> None:
    tax = load_taxonomy()
    out = tax.clean_tech(["python", "Python", "py", "nope", "TypeScript"])
    assert out == ["Python", "TypeScript"]  # dédoublonné, ordre stable, hors-vocab retiré


def test_clean_themes_caps_at_three() -> None:
    tax = load_taxonomy()
    out = tax.clean_themes(["defi", "ai-agents", "healthcare", "education", "unknown-theme"])
    assert out == ["defi", "ai-agents", "healthcare"]  # cappé, inconnu retiré


def test_clean_themes_dedups() -> None:
    tax = load_taxonomy()
    assert tax.clean_themes(["defi", "DeFi", "defi"]) == ["defi"]
