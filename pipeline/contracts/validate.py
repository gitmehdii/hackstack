"""Logique de validation avant promotion — pure, sans DB ni réseau (Étape 7).

Ce module ne connaît que des `Metrics` (déjà agrégées) et des seuils (`thresholds.yaml`).
Il décide si un batch en staging peut être promu, en le comparant à deux baselines par
source (cf. `thresholds.yaml`) :

  - moving : état accumulé de `projects` (baseline mobile, seuils resserrés) ;
  - anchor : premier run promu de la source (baseline figée, seuils larges) — capte la
             dérive lente qu'une baseline mobile masquerait.

Tous les contrôles doivent passer pour promouvoir. Le calcul des `Metrics` depuis la base
vit dans `pipeline/load/validate.py` : ici, aucune requête, donc tout est testable sans
réseau (c'est le cœur de la suite de tests de contrat).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

_DIR = Path(__file__).resolve().parent
THRESHOLDS_PATH = _DIR / "thresholds.yaml"

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# Colonnes dont on suit le taux de non-null (fill rate). L'ordre est stable pour le rapport.
NULL_RATE_COLUMNS = ("description", "hackathon_date", "repo_url", "demo_url", "prize_track")


def valid_url(u: str | None) -> bool:
    """URL bien formée : schéma http(s) explicite + hôte non vide. Pur, sans réseau."""
    if not u or not _URL_SCHEME_RE.match(u):
        return False
    return bool(urlparse(u).netloc)


# --------------------------------------------------------------------------- métriques


@dataclass(frozen=True)
class Metrics:
    """Métriques agrégées d'un batch (ou d'une baseline), pour une source.

    fill_rate : taux de non-null par colonne (fraction 0..1).
    projects_by_hackathon : nombre de projets PAR hackathon_slug (le contrôle compare sur
      les hackathons communs au batch et à la baseline — cf. `compare`).
    Une baseline vide a n == 0 (déclenche le bootstrap : comparaison sautée).
    """

    n: int
    fill_rate: dict[str, float]
    median_desc_len: float
    projects_by_hackathon: dict[str, int]
    placement_fill_rate: float
    url_valid_rate: float


def is_bootstrap(baseline: Metrics) -> bool:
    """True si la baseline est vide : on n'a rien à quoi comparer (première fois)."""
    return baseline.n == 0


# --------------------------------------------------------------------------- seuils


@dataclass(frozen=True)
class ColumnRule:
    mode: str  # "absolute" (points) | "relative" (% de la baseline)
    max_delta_points: float | None = None
    max_pct: float | None = None


@dataclass(frozen=True)
class Profile:
    label: str
    null_rate: dict[str, ColumnRule]
    median_desc_len_max_pct: float
    projects_per_hackathon_max_pct: float
    placement_fill_max_delta_points: float


@dataclass(frozen=True)
class Thresholds:
    moving: Profile
    anchor: Profile
    url_valid_min_rate: float


def _column_rule(profile: str, col: str, raw: object) -> ColumnRule:
    if not isinstance(raw, dict):
        raise ValueError(f"thresholds[{profile}].null_rate.{col} doit être un mapping")
    mode = raw.get("mode")
    if mode not in ("absolute", "relative"):
        raise ValueError(
            f"thresholds[{profile}].null_rate.{col}.mode invalide : {mode!r} "
            "(attendu 'absolute' ou 'relative')"
        )
    if mode == "absolute":
        v = raw.get("max_delta_points")
        if not isinstance(v, int | float) or v <= 0:
            raise ValueError(f"thresholds[{profile}].null_rate.{col}.max_delta_points > 0 requis")
        return ColumnRule(mode="absolute", max_delta_points=float(v))
    v = raw.get("max_pct")
    if not isinstance(v, int | float) or v <= 0:
        raise ValueError(f"thresholds[{profile}].null_rate.{col}.max_pct > 0 requis")
    return ColumnRule(mode="relative", max_pct=float(v))


def _positive(profile: str, block: dict[str, object], key: str) -> float:
    v = block.get(key)
    if not isinstance(v, int | float) or v <= 0:
        raise ValueError(f"thresholds[{profile}].{key} > 0 requis (reçu {v!r})")
    return float(v)


def _profile(label: str, raw: object) -> Profile:
    if not isinstance(raw, dict):
        raise ValueError(f"thresholds[{label}] doit être un mapping")
    nr = raw.get("null_rate")
    if not isinstance(nr, dict) or not nr:
        raise ValueError(f"thresholds[{label}].null_rate manquant ou vide")
    rules = {col: _column_rule(label, col, spec) for col, spec in nr.items()}
    # Une colonne non mesurée passerait toujours en silence (fill_rate.get -> 0.0 des deux
    # côtés) : on refuse toute colonne hors du vocabulaire mesuré plutôt que de désactiver
    # un contrôle sur une faute de frappe.
    unknown = set(rules) - set(NULL_RATE_COLUMNS)
    if unknown:
        raise ValueError(
            f"thresholds[{label}].null_rate : colonnes inconnues {sorted(unknown)} "
            f"(mesurées : {list(NULL_RATE_COLUMNS)})"
        )
    return Profile(
        label=label,
        null_rate=rules,
        median_desc_len_max_pct=_positive(label, raw, "median_desc_len_max_pct"),
        projects_per_hackathon_max_pct=_positive(label, raw, "projects_per_hackathon_max_pct"),
        placement_fill_max_delta_points=_positive(label, raw, "placement_fill_max_delta_points"),
    )


def load_thresholds(path: Path = THRESHOLDS_PATH) -> Thresholds:
    """Charge et valide les seuils. Lève ValueError sur toute incohérence (au chargement)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} : racine YAML doit être un mapping")
    for key in ("moving", "anchor", "url_valid_min_rate"):
        if key not in data:
            raise ValueError(f"{path} : clé '{key}' manquante")
    min_rate = data["url_valid_min_rate"]
    if not isinstance(min_rate, int | float) or not (0.0 < min_rate <= 1.0):
        raise ValueError(f"url_valid_min_rate doit être dans ]0, 1] (reçu {min_rate!r})")
    return Thresholds(
        moving=_profile("moving", data["moving"]),
        anchor=_profile("anchor", data["anchor"]),
        url_valid_min_rate=float(min_rate),
    )


# --------------------------------------------------------------------------- contrôles


@dataclass(frozen=True)
class CheckResult:
    check_name: str  # préfixé par profil : "moving:null_rate.repo_url", "batch:url_valid"…
    passed: bool
    detail: dict[str, object]


# Les contrôles sont UNILATÉRAUX : ils ne flaguent que les *baisses* (dégradation). Une casse
# de scraper = un champ qui cesse de se remplir, des descriptions qui raccourcissent, un
# hackathon qui perd des projets. Un champ qui se remplit DAVANTAGE (ex. backfill de dates
# 0→100 %) ou des descriptions plus longues ne sont jamais un signal de casse → jamais rejetés.


def _drop_absolute(name: str, base: float, cand: float, max_points: float) -> CheckResult:
    drop_points = (base - cand) * 100.0  # signé : > 0 = baisse ; < 0 = gain (passe)
    return CheckResult(
        name,
        drop_points <= max_points,
        {
            "mode": "absolute",
            "baseline": round(base, 4),
            "candidate": round(cand, 4),
            "drop_points": round(drop_points, 2),
            "max_delta_points": max_points,
        },
    )


def _drop_relative(name: str, base: float, cand: float, max_pct: float) -> CheckResult:
    # Garde : baseline nulle => on ne peut pas baisser sous zéro ; de la donnée qui apparaît
    # est un gain. Passe.
    if base == 0.0:
        return CheckResult(
            name,
            True,
            {
                "mode": "relative",
                "baseline": 0.0,
                "candidate": round(cand, 4),
                "note": "baseline_zero_pass",
            },
        )
    drop_pct = (base - cand) / base * 100.0  # signé : > 0 = baisse ; < 0 = gain (passe)
    return CheckResult(
        name,
        drop_pct <= max_pct,
        {
            "mode": "relative",
            "baseline": round(base, 4),
            "candidate": round(cand, 4),
            "drop_pct": round(drop_pct, 2),
            "max_pct": max_pct,
        },
    )


def _projects_per_hackathon(
    name: str, base: dict[str, int], cand: dict[str, int], max_pct: float
) -> CheckResult:
    """Compare les projets/hackathon SUR LE RECOUVREMENT (hackathons présents des deux côtés).

    Un batch incrémental couvre peu de hackathons du corpus entier : comparer son ratio global
    au corpus le rejetterait toujours. On restreint donc aux hackathons communs et on ne flague
    qu'une *baisse* du total de projets sur ces hackathons (pagination cassée). Aucun hackathon
    commun (scrape de nouveaux événements) => contrôle sauté.
    """
    overlap = set(base) & set(cand)
    if not overlap:
        return CheckResult(name, True, {"note": "no_overlap", "overlap": 0})
    base_total = sum(base[h] for h in overlap)
    cand_total = sum(cand[h] for h in overlap)
    if base_total == 0:
        return CheckResult(name, True, {"note": "baseline_zero_pass", "overlap": len(overlap)})
    drop_pct = (base_total - cand_total) / base_total * 100.0
    return CheckResult(
        name,
        drop_pct <= max_pct,
        {
            "overlap": len(overlap),
            "baseline": base_total,
            "candidate": cand_total,
            "drop_pct": round(drop_pct, 2),
            "max_pct": max_pct,
        },
    )


def compare(baseline: Metrics, candidate: Metrics, profile: Profile) -> list[CheckResult]:
    """Compare un batch (candidate) à une baseline selon un profil. Fonction pure.

    Un batch vide échoue d'emblée (on ne promeut jamais du vide). Sinon, un contrôle par
    colonne de null_rate (absolu/relatif selon la règle), + médiane des descriptions, + projets
    par hackathon (sur recouvrement), + taux de placement. Tous UNILATÉRAUX (baisses seules).
    """
    label = profile.label
    if candidate.n == 0:
        return [CheckResult(f"{label}:batch_nonempty", False, {"candidate_n": 0})]

    checks: list[CheckResult] = []
    for col, rule in profile.null_rate.items():
        base = baseline.fill_rate.get(col, 0.0)
        cand = candidate.fill_rate.get(col, 0.0)
        name = f"{label}:null_rate.{col}"
        if rule.mode == "absolute":
            assert rule.max_delta_points is not None
            checks.append(_drop_absolute(name, base, cand, rule.max_delta_points))
        else:
            assert rule.max_pct is not None
            r = _drop_relative(name, base, cand, rule.max_pct)
            checks.append(CheckResult(name, r.passed, {**r.detail, "column": col}))
    checks.append(
        _drop_relative(
            f"{label}:median_desc_len",
            baseline.median_desc_len,
            candidate.median_desc_len,
            profile.median_desc_len_max_pct,
        )
    )
    checks.append(
        _projects_per_hackathon(
            f"{label}:projects_per_hackathon",
            baseline.projects_by_hackathon,
            candidate.projects_by_hackathon,
            profile.projects_per_hackathon_max_pct,
        )
    )
    checks.append(
        _drop_absolute(
            f"{label}:placement_fill",
            baseline.placement_fill_rate,
            candidate.placement_fill_rate,
            profile.placement_fill_max_delta_points,
        )
    )
    return checks


def check_url_rate(candidate: Metrics, min_rate: float) -> CheckResult:
    """Contrôle absolu sur le batch : taux d'URLs bien formées ≥ min_rate."""
    return CheckResult(
        "batch:url_valid",
        candidate.url_valid_rate >= min_rate,
        {"url_valid_rate": round(candidate.url_valid_rate, 4), "min_rate": min_rate},
    )


def bootstrap_result(label: str) -> CheckResult:
    """Profil sauté faute de baseline (première fois qu'on voit la source)."""
    return CheckResult(
        f"{label}:bootstrap",
        True,
        {"bootstrap": True, "note": "baseline vide, comparaison sautée"},
    )


# --------------------------------------------------------------------------- rapport


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _report_row(c: CheckResult) -> str:
    d = c.detail
    mark = "✅" if c.passed else "❌"
    if d.get("bootstrap"):
        return f"| `{c.check_name}` | — | — | bootstrap | — | {mark} |"
    if "candidate_n" in d:
        return f"| `{c.check_name}` | — | {_fmt(d['candidate_n'])} | batch vide | > 0 | {mark} |"
    if "url_valid_rate" in d:
        return (
            f"| `{c.check_name}` | — | {_fmt(d['url_valid_rate'])} | — "
            f"| ≥ {_fmt(d['min_rate'])} | {mark} |"
        )
    if d.get("note") == "no_overlap":
        return f"| `{c.check_name}` | — | — | aucun hackathon commun | — | {mark} |"
    base = _fmt(d.get("baseline", "—"))
    cand = _fmt(d.get("candidate", "—"))
    if d.get("note") == "baseline_zero_pass":
        return f"| `{c.check_name}` | 0 | {cand} | baseline 0 → pass | — | {mark} |"
    if "drop_points" in d:
        ecart = f"{_fmt(d['drop_points'])} pts (baisse)"
        seuil = f"≤ {_fmt(d['max_delta_points'])} pts"
    else:
        ecart = f"{_fmt(d.get('drop_pct', '—'))} % (baisse)"
        seuil = f"≤ {_fmt(d.get('max_pct', '—'))} %"
    return f"| `{c.check_name}` | {base} | {cand} | {ecart} | {seuil} | {mark} |"


def render_report(*, source: str, run_id: int, checks: list[CheckResult], verdict: bool) -> str:
    """Rapport markdown (corps d'issue GitHub) : verdict + tableau de tous les contrôles."""
    head = "✅ VALIDÉ" if verdict else "❌ REJETÉ"
    failed = [c.check_name for c in checks if not c.passed]
    lines = [
        f"## Validation du run #{run_id} — source `{source}` — {head}",
        "",
        "| Contrôle | Baseline | Batch | Écart | Seuil | |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(_report_row(c) for c in checks)
    if failed:
        lines += ["", "**Contrôles en échec :** " + ", ".join(f"`{n}`" for n in failed)]
        lines += ["", "`projects` est resté **inchangée** ; le run est en statut `rejected`."]
    return "\n".join(lines) + "\n"
