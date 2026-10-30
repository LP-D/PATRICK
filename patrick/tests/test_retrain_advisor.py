"""Conseiller de réentraînement (`tracking/retrain_advisor.py`) et profils d'entraînement (`config/training_profiles.py`) :
chaque règle se déclenche sur sa condition et sur elle seule, le classement met la correction la plus urgente en tête, les patchs
ne citent que des champs du formulaire, et les pages (`/runs/{id}/detail`, `/launch`) les affichent et les appliquent."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from patrick.clock import utc_today
from patrick.config import training_profiles as profiles
from patrick.tracking import db, retrain_advisor
from patrick.tracking.retrain_advisor import Diagnosis, advise
from patrick.webapp import forms
from patrick.webapp.app import app

VIEW = forms.to_view(forms.default_config_dict())


def diag(**kw) -> Diagnosis:
    base = {"run_id": "r1", "target": "^GSPC", "horizon": 1, "asset_class": "equities_us", "auc_test": 0.57, "f1_test": 0.52,
            "auc_holdout": 0.57, "f1_holdout": 0.52, "fold_auc": [0.57, 0.58, 0.56, 0.57, 0.58], "guard_active": True,
            "history_years": 20.0, "view": dict(VIEW)}
    base.update(kw)
    return Diagnosis(**base)


def keys(d: Diagnosis, limit: int = 20) -> list[str]:
    return [s.key for s in advise(d, limit=limit)]


def test_a_healthy_run_triggers_none_of_the_problem_rules():
    problems = {"fix_leak", "derived_target", "signal_absent", "overfit", "recent_window", "regimes", "unstable_features",
                "short_history", "data_degraded", "class_balance"}
    assert advise(diag()) and not problems & set(keys(diag()))


def test_over_confident_probabilities_of_an_untuned_run_suggest_the_standard_tuning():
    untuned = {**VIEW, "tuning_enabled": False, "n_wf_folds": 3, "algos": ["XGBoost", "LightGBM"]}
    out = advise(diag(brier_holdout=0.285, ece_holdout=0.17, view=untuned))
    s = next(s for s in out if s.key == "overconfident")
    assert s.patch["tuning_enabled"] is True and s.patch["n_wf_folds"] == 5 and len(s.patch["algos"]) == 4
    assert 36 < s.score < 58 and s.facts["brier"] == "0.285" and s.available and not s.manual
    assert {c["field"] for c in s.changes} >= {"tuning_enabled", "n_wf_folds", "algos"}
    assert s.cost_factor > 1.0                                                  # le réglage coûte : le conseiller le dit
    assert "overconfident" not in keys(diag(brier_holdout=0.285, view=VIEW))   # déjà réglé : un autre levier
    assert "overconfident" not in keys(diag(brier_holdout=0.255, view=untuned))
    assert "overconfident" not in keys(diag(brier_holdout=None, view=untuned))
    assert "overconfident" not in keys(diag(brier_holdout=0.30, view=untuned, suspect="F1_dir 0.96"))


def test_a_suspect_run_is_told_to_rerun_with_the_leak_guard_first():
    out = advise(diag(suspect="F1_dir 0.96 ≥ 0.80", guard_active=False, auc_test=0.97))
    assert out[0].key == "fix_leak" and out[0].score == 100 and out[0].available


def test_a_suspect_run_with_the_guard_active_is_a_derived_target():
    out = advise(diag(suspect="F1_dir 0.96 ≥ 0.80", guard_active=True, target="NFCI"))
    assert out[0].key == "derived_target" and out[0].patch == {"reduction_corr_threshold": 0.8}
    assert out[0].facts["target"] == "NFCI"
    assert "overfit" not in [s.key for s in out]                      # un score truqué n'est pas du sur-ajustement ordinaire


def test_chance_level_scores_suggest_longer_horizons():
    out = advise(diag(auc_test=0.505, auc_holdout=0.50, horizon=1, fold_auc=[0.5, 0.51, 0.5, 0.51, 0.5]))
    s = next(s for s in out if s.key == "signal_absent")
    assert s.patch == {"horizons": [5, 10]} and s.score > 60
    assert "signal_absent" not in keys(diag(auc_test=0.60, auc_holdout=0.60))


def test_a_test_to_holdout_gap_means_selection_overfitting():
    out = advise(diag(auc_test=0.62, auc_holdout=0.52, f1_test=0.60, f1_holdout=0.48))
    s = next(s for s in out if s.key == "overfit")
    assert s.patch["holdout_months"] >= 18 and s.patch["purge"] is True and s.patch["n_trials"] <= 50
    assert "n_features_grid" not in s.patch            # moins de variables = moins bon holdout dans la base : on ne réduit plus la grille
    assert {"auc", "f1"} <= set(s.facts["signals"].replace(" ", "").split(","))
    assert advise(diag(auc_test=0.62, auc_holdout=0.52, f1_test=0.60, f1_holdout=0.48))[0].key == "overfit"


def test_a_negative_test_holdout_correlation_or_a_high_pbo_also_flags_overfitting():
    assert "overfit" in keys(diag(rho_test_holdout=-0.4))
    assert "overfit" in keys(diag(pbo=0.8, pbo_reliable=True))
    assert "overfit" not in keys(diag(pbo=0.8, pbo_reliable=False))     # un PBO non fiable ne déclenche rien


def test_unstable_folds_that_improve_over_time_suggest_a_recent_window():
    out = advise(diag(fold_auc=[0.50, 0.51, 0.60, 0.66], history_years=26.0))
    s = next(s for s in out if s.key == "recent_window")
    assert s.patch["n_wf_folds"] == 4 and int(s.patch["start_date"][:4]) >= utc_today().year - 16
    assert "regimes" not in [x.key for x in out]


def test_unstable_folds_without_a_trend_suggest_regimes():
    out = advise(diag(fold_auc=[0.50, 0.64, 0.63, 0.50, 0.64, 0.55], history_years=26.0))
    assert next(s for s in out if s.key == "regimes").patch == {"regimes": "GLOBAL,CALM,NORMAL,STRESS"}


def test_unstable_feature_selection_suggests_clustering_and_the_other_method():
    s = next(s for s in advise(diag(jaccard=0.08)) if s.key == "unstable_features")
    assert s.patch["reduction_corr_threshold"] == 0.85 and s.patch["selection_method"] == "lasso"
    s2 = next(s for s in advise(diag(jaccard=0.08, view={**VIEW, "selection_method": "lasso"})) if s.key == "unstable_features")
    assert s2.patch["selection_method"] == "shap"
    assert "unstable_features" not in keys(diag(jaccard=0.5)) and "unstable_features" not in keys(diag(jaccard=float("nan")))


def test_a_typical_jaccard_is_not_flagged_unstable_and_the_rule_never_tops_a_clean_ranking():
    """La médiane de la base est 0,20 : l'ancien seuil (0,40) écartait 94 % des runs et plaçait cette règle en tête de 73 % des classements."""
    assert "unstable_features" not in keys(diag(jaccard=0.20))
    assert "unstable_features" not in keys(diag(jaccard=0.13))
    worst = next(s for s in advise(diag(jaccard=0.0)) if s.key == "unstable_features")
    assert worst.score <= 62


def test_a_weak_but_stable_model_is_offered_more_capacity_and_deep_learning_as_a_manual_hand_off():
    out = advise(diag(auc_test=0.555, auc_holdout=0.55, fold_auc=[0.55, 0.56, 0.555, 0.553, 0.557]))
    more = next(s for s in out if s.key == "more_capacity")
    assert more.patch["stacking"] is True and more.patch["algos"] == retrain_advisor.CAPACITY_ALGOS and more.cost == "high"
    assert "LightGBM" not in more.patch["algos"] and more.patch["n_features_grid"] == retrain_advisor.CAPACITY_FEATURE_GRID
    dl = next(s for s in out if s.key == "deep_learning")
    assert dl.available is True and dl.manual is True and dl.patch == {}      # pas un patch : ouvre la page /dl
    assert "more_capacity" not in keys(diag(auc_test=0.555, auc_holdout=0.50))   # écart test/holdout : pas plus de capacité


def test_a_short_history_suggests_a_lighter_validation():
    s = next(s for s in advise(diag(history_years=4.0)) if s.key == "short_history")
    assert s.patch["n_wf_folds"] == 3 and s.patch["holdout_months"] == 12 and s.cost == "low"
    assert "short_history" not in keys(diag(history_years=15.0)) and "short_history" not in keys(diag(history_years=None))


def test_many_excluded_series_suggest_a_lower_coverage():
    s = next(s for s in advise(diag(n_excluded=35, n_universe=100)) if s.key == "data_degraded")
    assert s.patch == {"yf_coverage": 0.75} and s.facts["frac"] == "35 %" and s.score <= 50
    assert "data_degraded" not in keys(diag(n_excluded=5, n_universe=100))
    assert "data_degraded" not in keys(diag(n_excluded=25, n_universe=100))      # le seuil est celui de la porte de qualité (30 %)


def test_the_excluded_count_is_series_not_issue_rows(tmp_path):
    """Une série porte plusieurs problèmes (couverture, trou, prix figés) : compter les lignes donnait un rapport au-dessus de 1."""
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    db.add_data_quality_issues(conn, "snap", [
        {"series": "GC=F", "reason": "couverture_insuffisante", "detail": "x"}, {"series": "GC=F", "reason": "trou_de_cotation", "detail": "x"},
        {"series": "GC=F", "reason": "prix_figes", "detail": "x"}, {"series": "SI=F", "reason": "prix_figes", "detail": "x"}])
    db.create_run(conn, "r1", "^VIX", 5, "snap", json.dumps(forms.default_config_dict()), "c", "s", 42)
    tid = db.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, tid)
    db.finish_run(conn, "r1", status="done", n_trials=1)
    assert retrain_advisor.diagnose_run(conn, "r1").n_excluded == 2


def test_a_model_that_does_not_beat_persistence_is_told_so_unless_it_has_no_signal_at_all_or_a_clear_one():
    out = advise(diag(auc_test=0.55, auc_holdout=0.54, f1_test=0.50, persistence_f1=0.53))
    s = next(s for s in out if s.key == "no_edge")
    assert s.patch["horizons"] == [5, 10] and s.facts["edge"] == "-0.030" and 44 < s.score <= 64
    assert "signal_absent" not in [x.key for x in out]                                        # un seul des deux dit « pas de signal »
    assert "no_edge" not in keys(diag(auc_test=0.55, f1_test=0.54, persistence_f1=0.50))      # il y a un gain
    assert "no_edge" not in keys(diag(auc_test=0.55, f1_test=0.50, persistence_f1=None))      # persistance inconnue
    assert "no_edge" not in keys(diag(auc_test=0.505, auc_holdout=0.50, f1_test=0.50, persistence_f1=0.53))   # « signal_absent » le dit déjà
    assert "no_edge" not in keys(diag(auc_test=0.60, auc_holdout=0.60, f1_test=0.50, persistence_f1=0.53))    # signal net
    assert "no_edge" not in keys(diag(suspect="x", auc_test=0.55, f1_test=0.50, persistence_f1=0.53))


def test_imbalanced_classes_suggest_more_samplers():
    s = next(s for s in advise(diag(class_shares={"0": 0.08, "1": 0.2, "2": 0.22, "3": 0.5})) if s.key == "class_balance")
    assert "BorderlineSMOTE" in s.patch["sampler_candidates"]
    assert "class_balance" not in keys(diag(class_shares={"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.25}))


def test_a_good_ranking_without_calibration_suggests_calibrating():
    uncalibrated = {**VIEW, "calibration": False}        # le formulaire part calibré depuis la méthode 3 : le cas visé est un run décoché
    assert "calibrate" in keys(diag(auc_test=0.60, view=uncalibrated))
    assert "calibrate" not in keys(diag(auc_test=0.60, view={**VIEW, "calibration": True}))
    assert "calibrate" not in keys(diag(auc_test=0.60, auc_holdout=0.50, view=uncalibrated))     # le holdout dément le classement


def test_a_solid_holdout_suggests_confirming_with_cpcv_only_for_walk_forward():
    assert "confirm_cpcv" in keys(diag(auc_test=0.61, auc_holdout=0.60))
    assert "confirm_cpcv" not in keys(diag(auc_test=0.61, auc_holdout=0.60, scheme="cpcv"))
    assert "confirm_cpcv" not in keys(diag(auc_test=0.61, auc_holdout=0.60, f1_test=0.5, persistence_f1=0.55))


def test_a_weak_directional_equity_model_suggests_the_alpha_target():
    assert "try_alpha" in keys(diag(auc_test=0.55, auc_holdout=0.55))
    assert next(s for s in advise(diag(auc_test=0.55, auc_holdout=0.55), limit=50) if s.key == "try_alpha").score <= 20   # aucun gain mesuré
    assert "try_alpha" not in keys(diag(auc_test=0.55, asset_class="fx"))
    assert "try_alpha" not in keys(diag(auc_test=0.55, kind="alpha"))


def test_the_best_horizon_of_a_multi_horizon_launch_is_singled_out():
    s = next(s for s in advise(diag(horizon_auc={1: 0.50, 2: 0.52, 3: 0.55, 5: 0.60, 7: 0.57})) if s.key == "best_horizon")
    assert s.patch["horizons"] == [3, 5, 7]
    assert "best_horizon" not in keys(diag(horizon_auc={1: 0.55, 2: 0.56, 3: 0.55}))


def test_every_suggestion_gives_its_texts_all_the_figures_they_name():
    """Un texte « pourquoi / à essayer » qui cite une variable absente des chiffres de sa règle faisait échouer toute la page du run
    (`KeyError: 'best_h'`, règle du meilleur horizon)."""
    from patrick.webapp import i18n

    t = i18n.translator("fr")
    seen = set()
    for kwargs in (
        {"horizon_auc": {1: 0.50, 2: 0.52, 3: 0.55, 5: 0.60, 7: 0.57}},
        {"suspect": "F1 trop beau", "guard_active": True},
        {"suspect": "F1 trop beau", "guard_active": False},
        {"auc_test": 0.51, "f1_test": 0.50, "auc_holdout": 0.50, "f1_holdout": 0.49, "history_years": 3.0, "n_excluded": 12, "n_universe": 30,
         "fold_auc": [0.40, 0.45, 0.55, 0.60], "jaccard": 0.08, "class_shares": {"0": 0.7, "1": 0.1, "2": 0.1, "3": 0.1}},
        {"auc_test": 0.55, "auc_holdout": 0.54, "f1_test": 0.50, "persistence_f1": 0.53},
        {"auc_test": 0.70, "auc_holdout": 0.50, "f1_test": 0.70, "f1_holdout": 0.45, "pbo": 0.8, "pbo_reliable": True, "rho_test_holdout": -0.3},
        {"auc_test": 0.58, "auc_holdout": 0.58, "duration_s": 9000, "asset_class": "equities_us", "scheme": "walkforward"},
    ):
        for s in advise(diag(**kwargs), limit=50):
            seen.add(s.key)
            for part in ("why", "try"):
                t(f"adv_{s.key}_{part}", **s.facts)               # lève KeyError si une variable manque
    assert {"best_horizon", "fix_leak", "short_history", "overfit"} <= seen


def test_a_slow_run_with_a_weak_score_suggests_a_fast_iteration():
    assert next(s for s in advise(diag(duration_s=7200, auc_test=0.52, auc_holdout=0.52)) if s.key == "faster_iteration").patch["tuning_enabled"] is False
    assert "faster_iteration" not in keys(diag(duration_s=600, auc_test=0.52, auc_holdout=0.52))


def test_the_seed_check_is_always_there_for_a_clean_run_and_never_for_a_suspect_one():
    s = next(s for s in advise(diag()) if s.key == "seed_check")
    assert s.patch == {"seed": VIEW["seed"] + 1}
    assert "seed_check" not in keys(diag(suspect="x"))


def test_suggestions_are_ranked_by_score_then_by_cost_and_limited():
    d = diag(auc_test=0.62, auc_holdout=0.50, f1_test=0.6, f1_holdout=0.45, jaccard=0.1, history_years=3.0, class_shares={"0": .05, "1": .3, "2": .3, "3": .35})
    out = advise(d, limit=4)
    assert len(out) == 4 and [s.score for s in out] == sorted((s.score for s in out), reverse=True)


def test_cost_factor_reflects_what_changes():
    cheap = next(s for s in advise(diag(duration_s=7200, auc_test=0.52, auc_holdout=0.52)) if s.key == "faster_iteration")
    big = next(s for s in advise(diag(auc_test=0.555, auc_holdout=0.55, fold_auc=[0.55, 0.56, 0.555, 0.553, 0.557])) if s.key == "more_capacity")
    assert cheap.cost_factor <= 0.5 and cheap.cost == "low" and cheap.est_minutes <= 60
    assert big.cost_factor > 1.6 and big.cost == "high"
    assert retrain_advisor.cost_factor(VIEW, {**VIEW, "scheme": "cpcv"}) > 1.0
    assert retrain_advisor.cost_factor(VIEW, {**VIEW, "stacking": True}) > 1.0


def test_every_suggestion_changes_only_fields_the_form_can_represent():
    many = [diag(suspect="s", guard_active=False), diag(suspect="s", guard_active=True),
            diag(auc_test=0.505, auc_holdout=0.5, fold_auc=[.5, .51, .5, .51]),
            diag(auc_test=0.62, auc_holdout=0.5, f1_test=.6, f1_holdout=.4, rho_test_holdout=-.5, pbo=.9, pbo_reliable=True),
            diag(fold_auc=[0.5, 0.51, 0.6, 0.66]), diag(fold_auc=[0.5, 0.64, 0.51, 0.63, 0.5, 0.65]), diag(jaccard=0.1),
            diag(auc_test=0.555, auc_holdout=0.55, fold_auc=[.55, .56, .555, .553, .557]), diag(history_years=3),
            diag(n_excluded=40, n_universe=100), diag(class_shares={"0": .05, "1": .3, "2": .3, "3": .35}),
            diag(auc_test=0.6, auc_holdout=0.6), diag(horizon_auc={1: .5, 2: .52, 3: .55, 5: .6}),
            diag(duration_s=7200, auc_test=0.52, auc_holdout=0.52), diag(auc_test=0.55, auc_holdout=0.54, f1_test=0.50, persistence_f1=0.53)]
    seen = set()
    for d in many:
        for s in advise(d, limit=50):
            seen.add(s.key)
            assert set(s.patch) <= set(VIEW), (s.key, set(s.patch) - set(VIEW))
    assert len(seen) >= 17


def test_every_profile_patch_uses_form_fields_and_every_text_exists():
    from patrick.webapp.i18n import STRINGS

    assert retrain_advisor.validate_patches() == []
    assert len(profiles.PROFILES) >= 12 and len({p.key for p in profiles.PROFILES}) == len(profiles.PROFILES)
    for p in profiles.PROFILES:
        assert f"prof_{p.key}_name" in STRINGS and f"prof_{p.key}_desc" in STRINGS
        for k in p.resolved_patch():
            assert f"advf_{k}" in STRINGS or p.key == "standard", (p.key, k)
    for key in ("fix_leak", "derived_target", "signal_absent", "overfit", "recent_window", "regimes", "unstable_features", "more_capacity",
                "deep_learning", "short_history", "data_degraded", "class_balance", "overconfident", "calibrate", "confirm_cpcv", "try_alpha",
                "best_horizon", "faster_iteration", "seed_check"):
        for part in ("title", "why", "try"):
            assert f"adv_{key}_{part}" in STRINGS, (key, part)


def test_profile_dates_are_relative_to_today_and_unknown_fields_are_refused():
    p = profiles.get("recent").resolved_patch(date(2026, 10, 10))
    assert p["start_date"] == "2016-10-12" or p["start_date"].startswith("2016-10")
    assert profiles.apply_patch({"a": 1}, {"a": 2}) == {"a": 2}
    with pytest.raises(KeyError):
        profiles.apply_patch({"a": 1}, {"b": 2})


# ---------------------------------------------------------------------------------------------------- pages

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    cfg = forms.default_config_dict()
    cfg["name"] = "r1"
    cfg["objective"].update(target_symbol="^VIX", horizons=[5])
    db.create_run(conn, "r1", "^VIX", 5, "snap", json.dumps(cfg), "c", "s", 42)
    tid = db.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, tid)
    for fold, auc in enumerate((0.97, 0.96, 0.98), 1):
        db.add_fold_metrics(conn, tid, fold, "test", {"F1_dir": 0.95, "AUC_ovr_4cls": auc})
    db.finish_run(conn, "r1", status="done", n_trials=1)
    conn.close()
    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_the_launch_page_shows_the_profile_gallery(client):
    html = client.get("/ml").text
    assert 'id="profile-gallery"' in html and html.count('class="profile-card') == len(profiles.PROFILES)
    assert "Exploration rapide" in html and "Recherche approfondie" in html


def test_a_profile_prefills_the_form_and_says_so(client):
    html = client.get("/ml?profile=quick").text
    assert "Profil « Exploration rapide » appliqué" in html
    assert 'name="tuning_enabled"' in html
    import re
    tuning = re.search(r'<input[^>]*name="tuning_enabled"[^>]*>', html).group(0)
    assert "checked" not in tuning                                       # réglage Optuna désactivé par le profil rapide


def test_the_english_gallery_is_translated(client):
    html = client.get("/ml?lang=en").text
    assert "Ready-made training profiles" in html and "Quick exploration" in html


def test_an_unknown_profile_is_a_404(client):
    assert client.get("/ml?profile=nope").status_code == 404


def test_the_run_page_opens_without_waiting_for_the_advice_which_arrives_as_a_fragment(client):
    page = client.get("/runs/r1/detail").text
    assert 'id="avis"' in page and 'data-lazy-url="/fragments/run-advice/r1"' in page
    assert "Relancer avec la garde anti-fuite" not in page                  # le conseil n'est pas calculé pour afficher la page
    html = client.get("/fragments/run-advice/r1").text
    assert "Relancer avec la garde anti-fuite et les données ALFRED" in html
    assert "/ml?run_id=r1&amp;suggest=fix_leak" in html
    assert "Meilleur prochain essai" in html and "Contrôler la robustesse" not in html   # un score truqué : pas de contrôle de graine


def test_the_advice_fragment_of_an_unknown_run_is_empty_not_an_error(client):
    resp = client.get("/fragments/run-advice/nope")
    assert resp.status_code == 200 and "advisor" not in resp.text


def test_the_class_shares_query_reads_the_primary_key_not_the_split_index(tmp_path):
    """Sans `INDEXED BY`, SQLite parcourt tous les `test` de la base (~180 s sur la vraie base, la page du run n'ouvrait plus)."""
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    cfg = forms.default_config_dict()
    db.create_run(conn, "r1", "^VIX", 5, "snap", json.dumps(cfg), "c", "s", 42)
    tid = db.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, tid)
    n = 80
    db.add_predictions(conn, tid, 1, "test", [f"2024-01-{d:02d}" if d <= 31 else f"2024-02-{d - 31:02d}" for d in range(1, n + 1)],
                       y_true=[float(i % 4) for i in range(n)], y_pred=[float(i % 4) for i in range(n)], y_proba=[0.5] * n, p_up=[0.5] * n)
    db.finish_run(conn, "r1", status="done", n_trials=1)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    retrain_advisor.diagnose_run(conn, "r1")
    conn.set_trace_callback(None)
    sql = next(s for s in statements if "GROUP BY y_true" in s)
    plan = " ".join(str(r[3]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql))
    assert "sqlite_autoindex_prediction_1" in plan and "idx_pred_split" not in plan


def test_a_suggestion_prefills_the_launch_form_from_the_run(client):
    resp = client.get("/ml?run_id=r1&suggest=fix_leak")
    assert resp.status_code == 200 and "Suggestion « Relancer avec la garde anti-fuite" in resp.text
    assert client.get("/ml?run_id=r1&suggest=seed_check").status_code == 404      # run suspect : pas de contrôle de graine


def test_a_missing_suggestion_is_a_404(client):
    assert client.get("/ml?run_id=r1&suggest=calibrate").status_code == 404
