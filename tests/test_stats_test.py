"""Tests du test z de comparaison de deux proportions (api/stats_test.py)."""

from __future__ import annotations

from api.stats_test import two_proportion_ztest


def test_degenerate_when_no_second_group() -> None:
    # Corpus quasi entièrement gagnant : aucun non-gagnant → test incalculable, pas de signal.
    r = two_proportion_ztest(50, 100, 0, 0)
    assert r.z is None and r.p_value is None and r.significant is None


def test_degenerate_when_pooled_proportion_is_zero() -> None:
    # Personne n'a la techno dans aucun groupe → variance nulle → incalculable.
    r = two_proportion_ztest(0, 100, 0, 50)
    assert r.z is None and r.p_value is None and r.significant is None


def test_degenerate_when_pooled_proportion_is_one() -> None:
    r = two_proportion_ztest(100, 100, 50, 50)
    assert r.z is None and r.p_value is None and r.significant is None


def test_no_difference_gives_high_pvalue() -> None:
    # Proportions identiques → z ~ 0, p ~ 1, non significatif.
    r = two_proportion_ztest(20, 100, 20, 100)
    assert r.z is not None and abs(r.z) < 1e-9
    assert r.p_value is not None and r.p_value > 0.99
    assert r.significant is False


def test_clear_difference_is_significant() -> None:
    # 80/100 vs 20/100 : écart massif, largement significatif.
    r = two_proportion_ztest(80, 100, 20, 100)
    assert r.z is not None and r.z > 0
    assert r.p_value is not None and r.p_value < 0.001
    assert r.significant is True


def test_pvalue_is_two_sided_symmetric() -> None:
    # Le test est bilatéral : inverser les groupes ne change que le signe de z, pas p.
    a = two_proportion_ztest(80, 100, 20, 100)
    b = two_proportion_ztest(20, 100, 80, 100)
    assert a.p_value is not None and b.p_value is not None
    assert abs(a.p_value - b.p_value) < 1e-12
    assert a.z is not None and b.z is not None
    assert abs(a.z + b.z) < 1e-12


def test_alpha_threshold_is_applied() -> None:
    # Un écart modéré peut être significatif à 5 % mais pas à 1 %.
    lenient = two_proportion_ztest(30, 100, 18, 100, alpha=0.05)
    strict = two_proportion_ztest(30, 100, 18, 100, alpha=0.01)
    assert lenient.p_value == strict.p_value
    assert lenient.significant is True
    assert strict.significant is False
