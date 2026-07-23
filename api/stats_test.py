"""Tests statistiques légers pour les Trends (Étape 5), en Python pur.

Aucune dépendance lourde (numpy/scipy) côté API : une seule fonction est nécessaire, le
test z de comparaison de deux proportions. La p-value est calculée via la fonction de
répartition de la loi normale (`math.erf`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _normal_sf(z: float) -> float:
    """Fonction de survie de la loi normale centrée réduite : P(Z > z)."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


@dataclass(frozen=True)
class ZTestResult:
    """Résultat d'un test z de comparaison de deux proportions.

    `z` est la statistique (None si le test est dégénéré : effectif nul ou variance nulle).
    `p_value` est bilatérale. `significant` applique le seuil `alpha` (None si non calculable).
    """

    z: float | None
    p_value: float | None
    significant: bool | None


def two_proportion_ztest(k1: int, n1: int, k2: int, n2: int, alpha: float = 0.05) -> ZTestResult:
    """Compare deux proportions k1/n1 et k2/n2 (test z à variance poolée, bilatéral).

    Renvoie un résultat dégénéré (tout à None) si un effectif est nul ou si la proportion
    poolée vaut 0 ou 1 (variance nulle) — cas où aucune conclusion n'est possible. C'est
    exactement la situation d'un corpus quasi entièrement gagnant : le test se déclare
    incalculable plutôt que d'inventer un signal.
    """
    if n1 <= 0 or n2 <= 0:
        return ZTestResult(z=None, p_value=None, significant=None)
    p_pool = (k1 + k2) / (n1 + n2)
    if p_pool <= 0.0 or p_pool >= 1.0:
        return ZTestResult(z=None, p_value=None, significant=None)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0.0:
        return ZTestResult(z=None, p_value=None, significant=None)
    z = (k1 / n1 - k2 / n2) / se
    p_value = 2.0 * _normal_sf(abs(z))
    return ZTestResult(z=z, p_value=p_value, significant=p_value < alpha)
