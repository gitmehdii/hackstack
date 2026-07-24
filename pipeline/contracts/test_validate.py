"""Tests de la logique de validation avant promotion — purs, sans DB ni réseau."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.contracts.validate import (
    CheckResult,
    Metrics,
    bootstrap_result,
    check_url_rate,
    compare,
    is_bootstrap,
    load_thresholds,
    render_report,
    valid_url,
)

TH = load_thresholds()


def _m(
    *,
    n: int = 1000,
    description: float = 0.95,
    hackathon_date: float = 0.90,
    repo_url: float = 0.12,
    demo_url: float = 0.30,
    prize_track: float = 0.50,
    median_desc_len: float = 300.0,
    projects_by_hackathon: dict[str, int] | None = None,
    placement_fill_rate: float = 0.80,
    url_valid_rate: float = 1.0,
) -> Metrics:
    return Metrics(
        n=n,
        fill_rate={
            "description": description,
            "hackathon_date": hackathon_date,
            "repo_url": repo_url,
            "demo_url": demo_url,
            "prize_track": prize_track,
        },
        median_desc_len=median_desc_len,
        projects_by_hackathon={"h1": 5, "h2": 5}
        if projects_by_hackathon is None
        else projects_by_hackathon,
        placement_fill_rate=placement_fill_rate,
        url_valid_rate=url_valid_rate,
    )


def _by(checks: list[CheckResult], name: str) -> CheckResult:
    return next(c for c in checks if c.check_name == name)


# ------------------------------------------------------------------- valid_url


def test_valid_url() -> None:
    assert valid_url("https://github.com/x/y")
    assert valid_url("http://example.com")
    assert not valid_url("ftp://example.com")
    assert not valid_url("/relative/path")
    assert not valid_url("github.com/x")
    assert not valid_url("")
    assert not valid_url(None)


# ------------------------------------------------------------------- seuils


def test_load_thresholds_shape() -> None:
    assert TH.moving.null_rate["description"].mode == "absolute"
    assert TH.moving.null_rate["repo_url"].mode == "relative"
    # ancre plus large que la baseline mobile
    anchor_pts = TH.anchor.null_rate["description"].max_delta_points
    moving_pts = TH.moving.null_rate["description"].max_delta_points
    assert anchor_pts is not None and moving_pts is not None
    assert anchor_pts > moving_pts
    assert 0.0 < TH.url_valid_min_rate <= 1.0


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_thresholds_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="anchor"):
        load_thresholds(_write(tmp_path, "moving: {}\nurl_valid_min_rate: 0.9\n"))


def test_load_thresholds_bad_mode(tmp_path: Path) -> None:
    bad = (
        "moving:\n  null_rate:\n    description: {mode: nope, max_delta_points: 5}\n"
        "  median_desc_len_max_pct: 40\n  projects_per_hackathon_max_pct: 50\n"
        "  placement_fill_max_delta_points: 15\n"
        "anchor:\n  null_rate:\n    description: {mode: absolute, max_delta_points: 5}\n"
        "  median_desc_len_max_pct: 60\n  projects_per_hackathon_max_pct: 75\n"
        "  placement_fill_max_delta_points: 25\n"
        "url_valid_min_rate: 0.9\n"
    )
    with pytest.raises(ValueError, match="mode invalide"):
        load_thresholds(_write(tmp_path, bad))


def test_load_thresholds_rejects_unknown_column(tmp_path: Path) -> None:
    # Une colonne non mesurée passerait toujours en silence : le loader doit la refuser.
    bad = (
        "moving:\n  null_rate:\n    repo_urls: {mode: relative, max_pct: 50}\n"
        "  median_desc_len_max_pct: 40\n  projects_per_hackathon_max_pct: 50\n"
        "  placement_fill_max_delta_points: 15\n"
        "anchor:\n  null_rate:\n    description: {mode: absolute, max_delta_points: 5}\n"
        "  median_desc_len_max_pct: 60\n  projects_per_hackathon_max_pct: 75\n"
        "  placement_fill_max_delta_points: 25\n"
        "url_valid_min_rate: 0.9\n"
    )
    with pytest.raises(ValueError, match="colonnes inconnues"):
        load_thresholds(_write(tmp_path, bad))


def test_load_thresholds_url_rate_out_of_range(tmp_path: Path) -> None:
    ok_profile = (
        "  null_rate:\n    description: {mode: absolute, max_delta_points: 5}\n"
        "  median_desc_len_max_pct: 40\n  projects_per_hackathon_max_pct: 50\n"
        "  placement_fill_max_delta_points: 15\n"
    )
    text = f"moving:\n{ok_profile}anchor:\n{ok_profile}url_valid_min_rate: 1.5\n"
    with pytest.raises(ValueError, match="url_valid_min_rate"):
        load_thresholds(_write(tmp_path, text))


# ------------------------------------------------------------------- compare


def test_compare_all_pass_when_batch_matches_baseline() -> None:
    checks = compare(_m(), _m(), TH.moving)
    assert all(c.passed for c in checks)


def test_compare_absolute_breach_on_high_fill_column() -> None:
    # description chute de 0.95 à 0.40 : 55 points de BAISSE > seuil absolu de 15.
    checks = compare(_m(), _m(description=0.40), TH.moving)
    assert not _by(checks, "moving:null_rate.description").passed


def test_compare_relative_catches_low_fill_erosion() -> None:
    # Le cas de la revue : repo_url 12 % -> 2 % = 83 % de perte. Le mode RELATIF échoue
    # là où un seuil absolu de 15 points (10 points d'écart) laisserait passer.
    checks = compare(_m(), _m(repo_url=0.02), TH.moving)
    repo = _by(checks, "moving:null_rate.repo_url")
    assert not repo.passed
    assert repo.detail["mode"] == "relative"
    # les autres contrôles restent verts : c'est bien l'érosion faible-remplissage qui est captée
    assert _by(checks, "moving:null_rate.description").passed


def test_fill_rate_INCREASE_passes() -> None:
    # Contrôles unilatéraux : un champ qui se remplit DAVANTAGE n'est jamais une casse.
    # hackathon_date 0 -> 100 % (backfill Ét. 6) doit passer, pas être rejeté.
    checks = compare(_m(hackathon_date=0.0), _m(hackathon_date=1.0), TH.moving)
    assert _by(checks, "moving:null_rate.hackathon_date").passed
    # idem pour une médiane de description plus LONGUE
    checks = compare(_m(median_desc_len=300.0), _m(median_desc_len=900.0), TH.moving)
    assert _by(checks, "moving:median_desc_len").passed


def test_compare_median_desc_len_breach() -> None:
    checks = compare(_m(), _m(median_desc_len=100.0), TH.moving)  # -66 % (baisse)
    assert not _by(checks, "moving:median_desc_len").passed


def test_projects_per_hackathon_drop_on_overlap_breaches() -> None:
    # Un hackathon commun perd 90 % de ses projets (pagination cassée) -> échec.
    base = _m(projects_by_hackathon={"h1": 100, "h2": 100})
    cand = _m(projects_by_hackathon={"h1": 10})
    check = _by(compare(base, cand, TH.moving), "moving:projects_per_hackathon")
    assert not check.passed
    assert check.detail["overlap"] == 1


def test_projects_per_hackathon_no_overlap_skipped() -> None:
    # Scrape de NOUVEAUX hackathons : aucun commun -> contrôle sauté (comme bootstrap).
    base = _m(projects_by_hackathon={"h1": 100})
    cand = _m(projects_by_hackathon={"h2": 5, "h3": 5})
    check = _by(compare(base, cand, TH.moving), "moving:projects_per_hackathon")
    assert check.passed
    assert check.detail["note"] == "no_overlap"


def test_projects_per_hackathon_increase_passes() -> None:
    # Un batch qui apporte PLUS de projets sur un hackathon commun : gain, pas casse.
    base = _m(projects_by_hackathon={"h1": 10})
    cand = _m(projects_by_hackathon={"h1": 50})
    assert _by(compare(base, cand, TH.moving), "moving:projects_per_hackathon").passed


def test_compare_placement_fill_breach() -> None:
    checks = compare(_m(), _m(placement_fill_rate=0.50), TH.moving)  # -30 points (baisse)
    assert not _by(checks, "moving:placement_fill").passed


def test_compare_empty_batch_is_rejected() -> None:
    checks = compare(_m(), _m(n=0), TH.moving)
    assert len(checks) == 1
    assert checks[0].check_name == "moving:batch_nonempty"
    assert not checks[0].passed


def test_relative_check_passes_when_baseline_zero() -> None:
    # repo_url absent de la baseline (0), présent dans le batch (0.5) : gain, pas dégradation.
    checks = compare(_m(repo_url=0.0), _m(repo_url=0.50), TH.moving)
    repo = _by(checks, "moving:null_rate.repo_url")
    assert repo.passed
    assert repo.detail["note"] == "baseline_zero_pass"


# ------------------------------------------------------------------- bootstrap & url


def test_is_bootstrap() -> None:
    assert is_bootstrap(_m(n=0))
    assert not is_bootstrap(_m(n=1))


def test_bootstrap_result_passes() -> None:
    r = bootstrap_result("anchor")
    assert r.passed and r.detail["bootstrap"] is True


def test_check_url_rate() -> None:
    assert check_url_rate(_m(url_valid_rate=0.95), TH.url_valid_min_rate).passed
    assert not check_url_rate(_m(url_valid_rate=0.80), TH.url_valid_min_rate).passed


# ------------------------------------------------------------------- rapport


def test_render_report_flags_failures() -> None:
    checks = compare(_m(), _m(description=0.40), TH.moving)
    report = render_report(source="ethglobal", run_id=42, checks=checks, verdict=False)
    assert "REJETÉ" in report
    assert "moving:null_rate.description" in report
    assert "inchangée" in report
