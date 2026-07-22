"""Tests de l'extraction d'extrait (invariant légal : jamais le texte intégral)."""

from __future__ import annotations

from api.excerpt import make_excerpt


def test_none_when_empty() -> None:
    assert make_excerpt(None, None, 600) == (None, False)
    assert make_excerpt("   ", "", 600) == (None, False)


def test_short_text_not_truncated() -> None:
    text, truncated = make_excerpt("Un projet simple.", None, 600)
    assert text == "Un projet simple."
    assert truncated is False


def test_prefers_full_description_over_short() -> None:
    text, _ = make_excerpt("description longue", "court", 600)
    assert text == "description longue"


def test_falls_back_to_short_description() -> None:
    text, _ = make_excerpt(None, "juste le court", 600)
    assert text == "juste le court"


def test_truncates_on_word_boundary_with_ellipsis() -> None:
    text, truncated = make_excerpt("alpha beta gamma delta epsilon", None, 12)
    assert truncated is True
    assert text is not None
    assert text.endswith("…")
    assert " " not in text[-2:]  # pas d'espace juste avant l'ellipse
    assert len(text) <= 13


def test_truncation_never_exceeds_original_meaningfully() -> None:
    long = "mot " * 500
    text, truncated = make_excerpt(long, None, 100)
    assert truncated is True
    assert text is not None
    assert len(text) <= 101
