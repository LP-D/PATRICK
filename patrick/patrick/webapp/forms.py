"""Traduction formulaire HTML <-> config `RunConfig` — remplace l'édition
manuelle du YAML. Pas de contrainte imposée par `RunConfig` lui-même (schéma
pydantic sans bornes ni validateurs, cf. exploration), donc les vérifications
de base (listes non vides...) sont faites ici, avant `model_validate`, pour
éviter un run qui parte avec une grille vide.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import yaml

from patrick.config import defaults as D

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "configs" / "examples"


def list_example_configs() -> list[str]:
    if not EXAMPLES_DIR.is_dir():
        return []
    return sorted(p.name for p in EXAMPLES_DIR.glob("*.yaml"))


def load_example_config(filename: str) -> dict:
    path = EXAMPLES_DIR / filename
    if not path.is_file() or path.parent != EXAMPLES_DIR:
        raise FileNotFoundError(filename)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


TARGET_SOURCE_BY_SYMBOL = {sym: src for sym, _, src in D.DEFAULT_TARGET_CHOICES}


def universe_excluding(target_symbol: str) -> tuple[list[str], dict[str, str]]:
    """L'univers de features est toujours "tout ce qu'on a" (plus de sélection
    manuelle de tickers/source) — sauf la cible elle-même, pour ne pas la donner
    en feature d'entrée (fuite triviale)."""
    yf_tickers = [t for t in D.DEFAULT_UNIVERSE_YF_TICKERS if t != target_symbol]
    fred_series = {k: v for k, v in D.DEFAULT_UNIVERSE_FRED_SERIES.items() if k != target_symbol}
    return yf_tickers, fred_series


def default_config_dict() -> dict:
    target_symbol = "^VIX"
    yf_tickers, fred_series = universe_excluding(target_symbol)
    return {
        "name": "mon_run",
        "objective": {
            "target_symbol": target_symbol,
            "target_source": TARGET_SOURCE_BY_SYMBOL.get(target_symbol, "yfinance"),
            "horizons": list(D.DEFAULT_HORIZONS),
            "flat_thr": D.DEFAULT_FLAT_THR,
            "regimes": list(D.DEFAULT_REGIMES),
        },
        "universe": {
            "yf_tickers": yf_tickers,
            "fred_series": fred_series,
            "start_date": "2000-01-01",
            "yf_coverage": 0.85,
        },
        "data_quality": {
            "enabled": True,
            "max_frozen_run": D.DEFAULT_QUALITY_MAX_FROZEN_RUN,
            "max_gap_bdays": D.DEFAULT_QUALITY_MAX_GAP_BDAYS,
            "max_robust_z": D.DEFAULT_QUALITY_MAX_ROBUST_Z,
            "max_universe_exclusion_frac": D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC,
        },
        "features": {
            "families": list(D.DEFAULT_FEATURE_FAMILIES),
            "vol_models": list(D.DEFAULT_VOL_MODELS),
            "interact_top_base": 40,
            "interact_top_pairs": 20,
            "interact_final_n": 30,
            "pool_prefilter": D.DEFAULT_POOL_PREFILTER,
        },
        "validation": {
            "scheme": "walkforward",
            "n_groups": D.DEFAULT_CPCV_N_GROUPS,
            "k_test_groups": D.DEFAULT_CPCV_K_TEST_GROUPS,
            "n_wf_folds": D.DEFAULT_N_WF_FOLDS,
            "min_train_frac": D.DEFAULT_MIN_TRAIN_FRAC,
            "purge": D.DEFAULT_PURGE_ENABLED,
            "embargo_enabled": D.DEFAULT_EMBARGO_ENABLED,
            "embargo_bars": D.DEFAULT_EMBARGO_BARS,
            "min_train_rows": 100,
            "min_test_rows": 20,
        },
        "selection": {
            "method": D.DEFAULT_SELECTION_METHOD,
            "n_features_grid": list(D.DEFAULT_N_FEATURES_GRID),
            "shap_sample": D.DEFAULT_SHAP_SAMPLE,
            "track_stability": True,
        },
        "sampler": {"candidates": list(D.DEFAULT_SAMPLER)},
        "sampling": {"uniqueness_weights": True},
        "models": {
            "algos": list(D.DEFAULT_ML_ALGOS),
            "calibration": D.DEFAULT_CALIBRATION_ENABLED,
            "stacking": D.DEFAULT_STACKING_ENABLED,
        },
        "tuning": {
            "enabled": D.DEFAULT_TUNING_ENABLED,
            "top_k": D.DEFAULT_TUNING_TOP_K,
            "n_trials": D.DEFAULT_TUNING_N_TRIALS,
            "cv_splits": D.DEFAULT_TUNING_CV_SPLITS,
            "optuna_select_top_k_per_horizon": D.DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON,
        },
        "output": {"dir": "runs/mon_run", "seed": D.DEFAULT_SEED},
    }


ALL_FEATURE_FAMILIES = ["technical", "interactions", "spike", "vol_models", "macro"]
ALL_SAMPLERS = ["SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN", "none"]
ALL_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost"]
ALL_VOL_MODELS = list(D.ALL_VOL_MODELS)
TARGET_CHOICES = list(D.DEFAULT_TARGET_CHOICES)
TARGET_GROUPS = D.DEFAULT_TARGET_GROUPS
VOL_MODEL_LABELS = {
    "egarch": "EGARCH (vol. conditionnelle)",
    "kalman": "Filtre de Kalman (niveau filtré)",
    "hmm": "HMM (proba. de régime stress)",
    "heston_proxy": "Proxy Heston (mean-reversion vol.)",
    "vrp_proxy": "Proxy VRP (prime de risque de variance)",
    "ar": "AR (autorégressif)",
    "ma": "MA (moyenne mobile)",
    "arma": "ARMA",
    "arima": "ARIMA",
}


def _split_list(raw: str) -> list[str]:
    if not raw:
        return []
    parts = raw.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _int_list(raw: str) -> list[int]:
    out = []
    for tok in _split_list(raw):
        if "-" in tok and tok.count("-") == 1:
            lo, hi = tok.split("-")
            out.extend(range(int(lo.strip()), int(hi.strip()) + 1))
        else:
            out.append(int(tok))
    return out


def _kv_lines(raw: str) -> dict[str, str]:
    out = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip():
            out[k.strip()] = v.strip()
    return out


def _checked(form, name: str) -> bool:
    return form.get(name) in ("on", "true", "1")


def build_config_dict(form) -> tuple[dict, list[str]]:
    """`form` est une `starlette.datastructures.FormData`. Renvoie
    (config_dict, erreurs) — `config_dict` reste utilisable même avec des
    erreurs (pour repeupler le formulaire), mais ne doit pas être passé à
    `RunConfig.model_validate` si `erreurs` est non vide."""
    errors: list[str] = []

    def _require_non_empty(lst: list, label: str) -> list:
        if not lst:
            errors.append(f"« {label} » ne peut pas être vide.")
        return lst

    name = (form.get("name") or "").strip() or "mon_run"
    horizons = _require_non_empty(_int_list(form.get("horizons", "")), "Horizons")
    regimes = _require_non_empty(_split_list(form.get("regimes", "GLOBAL")), "Régimes")
    families = _require_non_empty(form.getlist("families"), "Familles de features")
    vol_models = form.getlist("vol_models")
    if "vol_models" in families:
        vol_models = _require_non_empty(vol_models, "Modèles de volatilité")
    n_features_grid = _require_non_empty(
        _int_list(form.get("n_features_grid", "")), "Grille N (sélection)")
    sampler_candidates = _require_non_empty(form.getlist("sampler_candidates"), "Samplers")
    algos = _require_non_empty(form.getlist("algos"), "Algorithmes")

    target_symbol = (form.get("target_symbol") or "").strip()
    if target_symbol not in TARGET_SOURCE_BY_SYMBOL:
        errors.append("« Que prédire » : choix invalide.")
    target_source = TARGET_SOURCE_BY_SYMBOL.get(target_symbol, "yfinance")
    yf_tickers, fred_series = universe_excluding(target_symbol)

    out_dir = (form.get("output_dir") or "").strip() or f"runs/{name}"

    try:
        flat_thr = float(form.get("flat_thr", D.DEFAULT_FLAT_THR))
        yf_coverage = float(form.get("yf_coverage", 0.85))
        min_train_frac = float(form.get("min_train_frac", D.DEFAULT_MIN_TRAIN_FRAC))
        max_robust_z = float(form.get("max_robust_z", D.DEFAULT_QUALITY_MAX_ROBUST_Z))
        max_universe_exclusion_frac = float(
            form.get("max_universe_exclusion_frac", D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC))
    except ValueError:
        errors.append("Un champ numérique décimal est invalide.")
        flat_thr, yf_coverage, min_train_frac = D.DEFAULT_FLAT_THR, 0.85, D.DEFAULT_MIN_TRAIN_FRAC
        max_robust_z = D.DEFAULT_QUALITY_MAX_ROBUST_Z
        max_universe_exclusion_frac = D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC

    try:
        n_groups = int(form.get("n_groups", D.DEFAULT_CPCV_N_GROUPS))
        k_test_groups = int(form.get("k_test_groups", D.DEFAULT_CPCV_K_TEST_GROUPS))
        n_wf_folds = int(form.get("n_wf_folds", D.DEFAULT_N_WF_FOLDS))
        min_train_rows = int(form.get("min_train_rows", 100))
        min_test_rows = int(form.get("min_test_rows", 20))
        interact_top_base = int(form.get("interact_top_base", 40))
        interact_top_pairs = int(form.get("interact_top_pairs", 20))
        interact_final_n = int(form.get("interact_final_n", 30))
        pool_prefilter = int(form.get("pool_prefilter", D.DEFAULT_POOL_PREFILTER))
        shap_sample = int(form.get("shap_sample", D.DEFAULT_SHAP_SAMPLE))
        top_k = int(form.get("top_k", D.DEFAULT_TUNING_TOP_K))
        n_trials = int(form.get("n_trials", D.DEFAULT_TUNING_N_TRIALS))
        cv_splits = int(form.get("cv_splits", D.DEFAULT_TUNING_CV_SPLITS))
        seed = int(form.get("seed", D.DEFAULT_SEED))
        embargo_bars_raw = (form.get("embargo_bars") or "").strip()
        embargo_bars = int(embargo_bars_raw) if embargo_bars_raw else None
        max_frozen_run = int(form.get("max_frozen_run", D.DEFAULT_QUALITY_MAX_FROZEN_RUN))
        max_gap_bdays = int(form.get("max_gap_bdays", D.DEFAULT_QUALITY_MAX_GAP_BDAYS))
    except ValueError:
        errors.append("Un champ numérique entier est invalide.")
        n_groups = D.DEFAULT_CPCV_N_GROUPS
        k_test_groups = D.DEFAULT_CPCV_K_TEST_GROUPS
        n_wf_folds = D.DEFAULT_N_WF_FOLDS
        min_train_rows, min_test_rows = 100, 20
        interact_top_base, interact_top_pairs, interact_final_n = 40, 20, 30
        pool_prefilter, shap_sample = D.DEFAULT_POOL_PREFILTER, D.DEFAULT_SHAP_SAMPLE
        top_k, n_trials, cv_splits = D.DEFAULT_TUNING_TOP_K, D.DEFAULT_TUNING_N_TRIALS, D.DEFAULT_TUNING_CV_SPLITS
        embargo_bars = D.DEFAULT_EMBARGO_BARS
        seed = D.DEFAULT_SEED
        max_frozen_run = D.DEFAULT_QUALITY_MAX_FROZEN_RUN
        max_gap_bdays = D.DEFAULT_QUALITY_MAX_GAP_BDAYS

    config_dict = {
        "name": name,
        "objective": {
            "target_symbol": target_symbol,
            "target_source": target_source,
            "horizons": horizons,
            "flat_thr": flat_thr,
            "regimes": regimes,
        },
        "universe": {
            "yf_tickers": yf_tickers,
            "fred_series": fred_series,
            "start_date": (form.get("start_date") or "2000-01-01").strip(),
            "yf_coverage": yf_coverage,
        },
        "data_quality": {
            "enabled": _checked(form, "data_quality_enabled"),
            "max_frozen_run": max_frozen_run,
            "max_gap_bdays": max_gap_bdays,
            "max_robust_z": max_robust_z,
            "max_universe_exclusion_frac": max_universe_exclusion_frac,
        },
        "features": {
            "families": families,
            "vol_models": vol_models,
            "interact_top_base": interact_top_base,
            "interact_top_pairs": interact_top_pairs,
            "interact_final_n": interact_final_n,
            "pool_prefilter": pool_prefilter,
        },
        "validation": {
            "scheme": form.get("scheme", "walkforward"),
            "n_groups": n_groups,
            "k_test_groups": k_test_groups,
            "n_wf_folds": n_wf_folds,
            "min_train_frac": min_train_frac,
            "purge": _checked(form, "purge"),
            "embargo_enabled": _checked(form, "embargo_enabled"),
            "embargo_bars": embargo_bars,
            "min_train_rows": min_train_rows,
            "min_test_rows": min_test_rows,
        },
        "selection": {
            "method": form.get("selection_method", D.DEFAULT_SELECTION_METHOD),
            "n_features_grid": n_features_grid,
            "shap_sample": shap_sample,
            "track_stability": _checked(form, "track_stability"),
        },
        "sampler": {"candidates": sampler_candidates},
        "sampling": {"uniqueness_weights": _checked(form, "uniqueness_weights")},
        "models": {
            "algos": algos,
            "calibration": _checked(form, "calibration"),
            "stacking": _checked(form, "stacking"),
        },
        "tuning": {
            "enabled": _checked(form, "tuning_enabled"),
            "top_k": top_k,
            "n_trials": n_trials,
            "cv_splits": cv_splits,
            "optuna_select_top_k_per_horizon": _checked(form, "optuna_select_top_k_per_horizon"),
        },
        "output": {"dir": out_dir, "seed": seed},
    }
    return config_dict, errors


def to_view(cfg: dict) -> dict:
    """Convertit un dict de config (types réels, listes/dicts) en valeurs
    plates pour préremplir les champs du formulaire `index.html`."""
    obj, uni = cfg.get("objective", {}), cfg.get("universe", {})
    dq = cfg.get("data_quality", {})
    feat, val = cfg.get("features", {}), cfg.get("validation", {})
    sel, sam = cfg.get("selection", {}), cfg.get("sampler", {})
    mod, tun = cfg.get("models", {}), cfg.get("tuning", {})
    out = cfg.get("output", {})
    return {
        "name": cfg.get("name", ""),
        "target_symbol": obj.get("target_symbol", ""),
        "horizons": ",".join(str(h) for h in obj.get("horizons", [])),
        "flat_thr": obj.get("flat_thr", D.DEFAULT_FLAT_THR),
        "regimes": ",".join(obj.get("regimes", [])),
        "start_date": uni.get("start_date", "2000-01-01"),
        "yf_coverage": uni.get("yf_coverage", 0.85),
        "data_quality_enabled": bool(dq.get("enabled", True)),
        "max_frozen_run": dq.get("max_frozen_run", D.DEFAULT_QUALITY_MAX_FROZEN_RUN),
        "max_gap_bdays": dq.get("max_gap_bdays", D.DEFAULT_QUALITY_MAX_GAP_BDAYS),
        "max_robust_z": dq.get("max_robust_z", D.DEFAULT_QUALITY_MAX_ROBUST_Z),
        "max_universe_exclusion_frac": dq.get(
            "max_universe_exclusion_frac", D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC),
        "families": feat.get("families", []),
        "vol_models": feat.get("vol_models") or list(D.DEFAULT_VOL_MODELS),
        "interact_top_base": feat.get("interact_top_base", 40),
        "interact_top_pairs": feat.get("interact_top_pairs", 20),
        "interact_final_n": feat.get("interact_final_n", 30),
        "pool_prefilter": feat.get("pool_prefilter", D.DEFAULT_POOL_PREFILTER),
        "scheme": val.get("scheme", "walkforward"),
        "n_groups": val.get("n_groups", D.DEFAULT_CPCV_N_GROUPS),
        "k_test_groups": val.get("k_test_groups", D.DEFAULT_CPCV_K_TEST_GROUPS),
        "n_wf_folds": val.get("n_wf_folds", D.DEFAULT_N_WF_FOLDS),
        "min_train_frac": val.get("min_train_frac", D.DEFAULT_MIN_TRAIN_FRAC),
        "purge": bool(val.get("purge", False)),
        "embargo_enabled": bool(val.get("embargo_enabled", D.DEFAULT_EMBARGO_ENABLED)),
        "embargo_bars": val.get("embargo_bars", D.DEFAULT_EMBARGO_BARS),
        "min_train_rows": val.get("min_train_rows", 100),
        "min_test_rows": val.get("min_test_rows", 20),
        "selection_method": sel.get("method", D.DEFAULT_SELECTION_METHOD),
        "n_features_grid": ",".join(str(n) for n in sel.get("n_features_grid", [])),
        "shap_sample": sel.get("shap_sample", D.DEFAULT_SHAP_SAMPLE),
        "track_stability": bool(sel.get("track_stability", True)),
        "sampler_candidates": sam.get("candidates", []),
        "uniqueness_weights": bool(cfg.get("sampling", {}).get("uniqueness_weights", True)),
        "algos": mod.get("algos", []),
        "calibration": bool(mod.get("calibration", False)),
        "stacking": bool(mod.get("stacking", False)),
        "tuning_enabled": bool(tun.get("enabled", True)),
        "top_k": tun.get("top_k", D.DEFAULT_TUNING_TOP_K),
        "n_trials": tun.get("n_trials", D.DEFAULT_TUNING_N_TRIALS),
        "cv_splits": tun.get("cv_splits", D.DEFAULT_TUNING_CV_SPLITS),
        "optuna_select_top_k_per_horizon": bool(
            tun.get("optuna_select_top_k_per_horizon", D.DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON)),
        "output_dir": out.get("dir", "runs"),
        "seed": out.get("seed", D.DEFAULT_SEED),
    }
