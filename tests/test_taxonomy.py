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


def test_ground_tech_keeps_only_mentioned() -> None:
    tax = load_taxonomy()
    # Rien nommé -> tout retiré (anti-hallucination).
    assert tax.ground_tech(["GPT-4", "Python", "Docker"], "Report a bug, get fixes.") == []
    # Nommé (dont via alias) -> gardé.
    assert tax.ground_tech(["Gemini", "GPT-4"], "built with Gemini 2.5 Flash") == ["Gemini"]
    assert tax.ground_tech(["GPT-4", "React"], "uses the openai api and react") == [
        "GPT-4",
        "React",
    ]


def test_ground_tech_kills_full_dump() -> None:
    tax = load_taxonomy()
    # Le modèle recrache toute la taxonomie : seul ce qui est dans le texte survit.
    grounded = tax.ground_tech(list(tax.tech_canonical), "coordinates agents on live Kubernetes")
    assert grounded == ["Kubernetes"]


def test_ground_tech_no_false_positive_on_substrings() -> None:
    tax = load_taxonomy()
    # « google » ne doit pas ancrer « Go » ; « database » ne doit pas ancrer « Base ».
    assert tax.ground_tech(["Go", "Base"], "we use google cloud and a database") == []
