"""Defaults encoding the lessons learned from the VIX project (README) — can be
switched on differently, never removed from the code: SHAP beats RFE/LASSO in
direct testing, stacking loses on 93% of the (horizon, fold) pairs tested in
walk-forward, DL never beat classical ML, purge has a negligible effect,
calibration only helps outside STRESS regimes.
"""

DEFAULT_ML_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "CatBoost"]
ALL_ML_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost"]
DEFAULT_SAMPLERS_ALL = ["SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN"]
DEFAULT_SAMPLER = ["SMOTE"]
DEFAULT_SELECTION_METHOD = "shap"
DEFAULT_N_FEATURES_GRID = list(range(5, 16))
DEFAULT_REGIMES = ["GLOBAL"]
DEFAULT_HORIZONS = [1, 2, 3, 5, 7, 10]
DEFAULT_FEATURE_FAMILIES = ["technical", "interactions", "spike", "vol_models", "macro"]

# Phase 2 (feature/guida-features-full) -- the 14 lookback windows (trading
# days) used throughout Tony Guida's "Big Data and Machine Learning in
# Quantitative Investment" (CFA Institute Research Foundation) factor
# taxonomy. Reused verbatim (not re-derived) so every Guida-tagged feature in
# this codebase shares the exact same horizon grid, from ~2 weeks (10d) to
# 3 years (756d).
GUIDA_LOOKBACKS: tuple[int, ...] = (10, 22, 44, 66, 88, 130, 200, 252, 300, 382, 400, 504, 600, 756)

# Global opt-in switch (`FeaturesConfig.enable_guida_features`, config/schema.py):
# False by default -- the scan-cost impact of the 14-lookback grid (measured in
# `tests/test_guida_scan_cost.py`) has not been judged against a default-on
# activation; this is a research-platform toggle, not a production default.
DEFAULT_ENABLE_GUIDA_FEATURES = False
DEFAULT_POOL_PREFILTER = 450
DEFAULT_SHAP_SAMPLE = 500
DEFAULT_N_WF_FOLDS = 5
DEFAULT_MIN_TRAIN_FRAC = 0.40
DEFAULT_FLAT_THR = 0.003
DEFAULT_SEED = 42

# Phase 2.1 (statistical validity): last months reserved as terminal holdout,
# never seen by feature selection/tuning/leaderboard ranking. The original plan
# leaves a range (12-24 months); 15 = reasonable midpoint. Configurable via
# validation.holdout_months in the YAML (range: 12-24, default: 15).
DEFAULT_HOLDOUT_MONTHS = 15

# Phase X5 -- mapping from asset class (`data/session_calendar.classify_asset_class`)
# -> "class-specific" baseline candidates for the Diebold-Mariano test (Phase 2.5).
# When several candidates are listed, the best one (highest F1_dir on the
# evaluated fold) is kept -- see `pipeline/engine.py::_evaluate_diebold_mariano`.
# Class-agnostic persistence is ALWAYS computed in addition, as a fixed common
# reference across classes (never part of this mapping). Not exhaustive: any
# class absent here falls back to ["persistence"] (historical, conservative
# behavior).
DEFAULT_BASELINE_BY_ASSET_CLASS: dict[str, list[str]] = {
    "volatility_index": ["har_rv"],
    "equities_us": ["persistence", "majority_by_regime"],
    "equities_americas_other": ["persistence", "majority_by_regime"],
    "equities_europe": ["persistence", "majority_by_regime"],
    "equities_asia_pacific": ["persistence", "majority_by_regime"],
    "fx": ["random_walk_no_drift"],
    "futures": ["momentum_20"],
    "crypto": ["persistence", "momentum_5"],
    "macro": ["random_walk_drift"],
    "other": ["persistence"],
}

# Optuna is part of the loop by default (explicit requirement): selecting the
# best model without tuning it does not fulfill "return the best model".
DEFAULT_TUNING_ENABLED = True
DEFAULT_TUNING_TOP_K = 5
DEFAULT_TUNING_N_TRIALS = 100
DEFAULT_TUNING_CV_SPLITS = 3
# Audit report, C3: `top_k` used to be selected GLOBALLY across all horizons --
# a multi-horizon run could see 100% of the Optuna budget concentrated on a
# single horizon (whichever had the dominant best SCAN trial), the others
# getting none. True = each horizon receives its own top_k/n_trials,
# independently of the others (fixed behavior, default).
DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON = True

# Phase 6.5 (P6.5) -- data quality gates at ingestion: thresholds MEASURED by
# simulation, not chosen by convention -- see detailed justification in
# `data/quality.py` (module docstring).
DEFAULT_QUALITY_MAX_FROZEN_RUN = 4
DEFAULT_QUALITY_MAX_GAP_BDAYS = 10
DEFAULT_QUALITY_MAX_ROBUST_Z = 40.0
DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30

# Phase 6.1 (P6.1) -- CPCV: minimal (N, k=2) pair that makes PBO satisfiable
# (guard C5, MIN_BLOCKS=6) without superfluous combinatorial computation --
# see detailed justification in `validation/cpcv.py`.
DEFAULT_CPCV_N_GROUPS = 7
DEFAULT_CPCV_K_TEST_GROUPS = 2

# Phase 1 (feature/hyperparams-ui) -- the Optuna search space itself (per-algo,
# per-hyperparameter [low, high] bounds, `tuning/optuna_runner.py::
# suggest_params`) used to be fixed in code with NO configuration surface at
# all -- not even a RunConfig field, unlike n_trials/top_k/cv_splits/algos
# which were already exposed on `/launch`. `OPTUNA_PARAM_SPECS` is the
# STRUCTURE of the search (int vs float, log-scale, and the outer sanity
# envelope enforced by `webapp/forms.py::_parse_optuna_bounds`) -- fixed, not
# itself user-configurable: only the [low, high] pair inside that envelope is
# (`RunConfig.tuning.optuna_bounds`, defaulting to `DEFAULT_OPTUNA_BOUNDS`
# below).
OPTUNA_PARAM_SPECS: dict[str, dict[str, dict]] = {
    "XGBoost": {
        "n_estimators": {"type": "int", "min_allowed": 10, "max_allowed": 2000},
        "max_depth": {"type": "int", "min_allowed": 1, "max_allowed": 20},
        "learning_rate": {"type": "float", "log": True, "min_allowed": 0.0001, "max_allowed": 1.0},
        "subsample": {"type": "float", "min_allowed": 0.01, "max_allowed": 1.0},
        "colsample_bytree": {"type": "float", "min_allowed": 0.01, "max_allowed": 1.0},
        "min_child_weight": {"type": "int", "min_allowed": 1, "max_allowed": 50},
    },
    "LightGBM": {
        "n_estimators": {"type": "int", "min_allowed": 10, "max_allowed": 2000},
        "max_depth": {"type": "int", "min_allowed": 1, "max_allowed": 20},
        "learning_rate": {"type": "float", "log": True, "min_allowed": 0.0001, "max_allowed": 1.0},
        "num_leaves": {"type": "int", "min_allowed": 2, "max_allowed": 512},
        "min_child_samples": {"type": "int", "min_allowed": 1, "max_allowed": 500},
        "subsample": {"type": "float", "min_allowed": 0.01, "max_allowed": 1.0},
    },
    "RandomForest": {
        "n_estimators": {"type": "int", "min_allowed": 10, "max_allowed": 2000},
        "max_depth": {"type": "int", "min_allowed": 1, "max_allowed": 50},
        "min_samples_leaf": {"type": "int", "min_allowed": 1, "max_allowed": 200},
    },
    "GradientBoosting": {
        "n_estimators": {"type": "int", "min_allowed": 10, "max_allowed": 2000},
        "learning_rate": {"type": "float", "log": True, "min_allowed": 0.0001, "max_allowed": 1.0},
        "max_depth": {"type": "int", "min_allowed": 1, "max_allowed": 20},
        "min_samples_leaf": {"type": "int", "min_allowed": 1, "max_allowed": 200},
        "subsample": {"type": "float", "min_allowed": 0.01, "max_allowed": 1.0},
    },
    "CatBoost": {
        "iterations": {"type": "int", "min_allowed": 10, "max_allowed": 2000},
        "depth": {"type": "int", "min_allowed": 1, "max_allowed": 16},
        "learning_rate": {"type": "float", "log": True, "min_allowed": 0.0001, "max_allowed": 1.0},
    },
}

# Default [low, high] bounds -- IDENTICAL to the values historically hardcoded
# in `tuning/optuna_runner.py::suggest_params` (VIX_FINAL_OPTUNA methodology):
# a run that does not customize `tuning.optuna_bounds` must search EXACTLY
# the same space as before this config surface existed (see
# `tests/test_optuna_bounds.py::
# test_default_bounds_match_the_ranges_historically_hardcoded_in_suggest_params`).
DEFAULT_OPTUNA_BOUNDS: dict[str, dict[str, list[float]]] = {
    "XGBoost": {
        "n_estimators": [100, 400], "max_depth": [3, 8], "learning_rate": [0.01, 0.2],
        "subsample": [0.6, 1.0], "colsample_bytree": [0.6, 1.0], "min_child_weight": [1, 10],
    },
    "LightGBM": {
        "n_estimators": [100, 400], "max_depth": [3, 8], "learning_rate": [0.01, 0.2],
        "num_leaves": [15, 63], "min_child_samples": [5, 50], "subsample": [0.6, 1.0],
    },
    "RandomForest": {
        "n_estimators": [100, 500], "max_depth": [3, 10], "min_samples_leaf": [1, 20],
    },
    "GradientBoosting": {
        "n_estimators": [100, 400], "learning_rate": [0.01, 0.2], "max_depth": [3, 8],
        "min_samples_leaf": [1, 20], "subsample": [0.6, 1.0],
    },
    "CatBoost": {
        "iterations": [100, 400], "depth": [3, 8], "learning_rate": [0.01, 0.2],
    },
}

# Options disabled by default but wired into the pipeline (not an appendix):
# purge (VIX_PURGED_CV: negligible F1_dir delta), calibration (VIX_CALIBRATED_THRESHOLD:
# regime-conditional gain, hurts in STRESS), stacking (VIX_STACKING_WF: loses 28/30).
DEFAULT_PURGE_ENABLED = False
DEFAULT_CALIBRATION_ENABLED = False
DEFAULT_STACKING_ENABLED = False

# Embargo (Phase 0 correctness, distinct from the purge above): removes from the
# TEST set the first `embargo_bars` bars following the train/test cut, against
# rolling windows (rolling mean/std...) computed right after the cut that are
# still correlated with train. Unlike purge (measured negligible effect in the
# original VIX project), there is not yet an empirical measurement for embargo
# on this generalized framework -- enabled by default out of caution (low cost:
# a few fewer test bars per fold), unlike purge.
DEFAULT_EMBARGO_ENABLED = True
DEFAULT_EMBARGO_BARS = None  # None -> derived from the current horizon (e = horizon)

# Models in the "vol_models" family (patrick/features/vol_models.py), individually
# selectable from the web interface. The first 5 are the ones from the original VIX
# pipeline (always computed together until now) — kept enabled by default so as not
# to change the already-validated F1_dir≈0.610 reference. AR/MA/ARMA/ARIMA are new,
# never tested in walk-forward: disabled by default.
ALL_VOL_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy", "ar", "ma", "arma", "arima"]
DEFAULT_VOL_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy"]

# Open list of targets proposed by the web form ("what to predict?"), grouped
# by category for a browsable dropdown despite their number — no more free-text
# field. Each entry also fixes its source (yfinance except for the
# "Macro (FRED)" group), so there is no separate source choice to make anymore.
# Manually maintained blocklist: tickers already known to be delisted, malformed
# for yfinance, or renamed since — to exclude if ever reinjected into
# YF_TICKERS_RAW/MANUAL_YF_NAMES above during a future extension.
BAD_TICKERS = {
    "XXIV", "TVIX", "ZIV", "^MIB", "CELG", "AET", "HES", "GPS", "JWN", "DFS",
    "SPX", "EON", "EDF", "RWE", "SZR", "ICN", "CEIX", "MXEA", "SQ", "SHELL", "K",
}

FRED_TARGET_GROUP = "Macro (FRED)"

DEFAULT_TARGET_GROUPS = {
    # Univers reduit (feature/universe-reduction) : commodites + macro + 4
    # actifs conserves explicitement (VIX, EUR/USD, S&P500, BTC). Ancien
    # univers (550 cibles, 13 groupes) retire -- aucune dependance technique
    # trouvee (UniverseConfig est un pool dynamique par run, "tout sauf la
    # cible", pas un graphe de dependances entre tickers precis ; verifie par
    # grep sur data/session_calendar.py et patrick/audit.py, cf. rapport de
    # cette phase). Les groupes retires en integralite : Actions France &
    # Europe (80), ETFs larges & style (31), ETFs sectoriels & thematiques
    # (27), Obligataire & taux ETFs (18), Matieres premieres & devises ETFs
    # (24), Volatilite (6), International ETFs pays (29), Actions
    # individuelles (182) -- 397 tickers, aucun n'etait une commodite future,
    # un macro FRED, ni l'un des 4 actifs conserves.
    "Indices": [
        ("^GSPC", "SP500_Price"),
        ("^VIX", "VIX_Price"),
    ],
    "Devises": [
        ("EURUSD=X", "EUR_USD"),
        # DX-Y.NYB (US Dollar Index) : ticker yfinance de l'ancien univers
        # (pre-reduction), reintroduit a la demande -- classe avec les devises
        # plutot qu'un nouveau groupe a une seule entree ; ne doit PAS aller
        # dans "Macro (FRED)" (source y serait a tort "fred").
        ("DX-Y.NYB", "USD_Index"),
    ],
    "Matières premières (futures)": [
        ("GC=F", "Gold_Futures"),
        ("SI=F", "Silver_Futures"),
        ("HG=F", "Copper_Futures"),
        ("CL=F", "WTI_Futures"),
        ("BZ=F", "Brent_Futures"),
        ("NG=F", "NatGas_Futures"),
        ("ZC=F", "Corn_Futures"),
        ("ZO=F", "Oats_Futures"),
        ("KE=F", "Wheat_KC_Futures"),
        ("ZR=F", "Rice_Futures"),
        ("ZS=F", "Soybeans_Futures"),
        ("GF=F", "FeederCattle_Futures"),
        ("HE=F", "LeanHogs_Futures"),
        ("LE=F", "LiveCattle_Futures"),
        ("CC=F", "Cocoa_Futures"),
        ("KC=F", "Coffee_Futures"),
        ("CT=F", "Cotton_Futures"),
        ("LBS=F", "Lumber_Futures"),
        ("OJ=F", "OrangeJuice_Futures"),
        ("SB=F", "Sugar_Futures"),
    ],
    "Crypto": [
        ("BTC-USD", "Bitcoin_Spot"),
    ],
    "Macro (FRED)": [
        ("BAMLC0A0CM", "IG_OAS"),
        ("BAMLC0A4CBBB", "BBB_OAS"),
        ("BAMLH0A0HYM2", "HY_OAS"),
        ("CPIAUCSL", "CPI"),
        ("CPILFESL", "Core_CPI"),
        ("DCOILBRENTEU", "Brent_Oil_FRED"),
        ("DCOILWTICO", "WTI_Oil_FRED"),
        ("DFF", "DFF"),
        ("DGS1", "US1Y_Rate"),
        ("DGS10", "US10Y_Rate"),
        ("DGS2", "US2Y_Rate"),
        ("DGS20", "US20Y_Rate"),
        ("DGS3", "US3Y_Rate"),
        ("DGS30", "US30Y_Rate"),
        ("DGS5", "US5Y_Rate"),
        ("DGS7", "US7Y_Rate"),
        ("DTB1", "US1M_Rate"),
        ("DTB3", "US3M_Rate"),
        ("DTB6", "US6M_Rate"),
        ("EFFR", "EFFR"),
        ("FEDFUNDS", "FedFunds"),
        ("GDP", "GDP"),
        ("INDPRO", "Industrial_Production"),
        ("NFCI", "NFCI"),
        ("OILPRICE", "Oil_Price"),
        ("PAYEMS", "NonfarmPayrolls"),
        ("PCE", "PCE"),
        ("PCEPILFE", "Core_PCE"),
        ("RSAFS", "Retail_Sales"),
        ("SOFR", "SOFR_SecuredOIS"),
        ("SP500", "SP500_Level"),
        ("STLFSI4", "STLFSI4"),
        ("T10Y2Y", "T10Y2Y_Spread"),
        ("T10Y3M", "T10Y3M_Spread"),
        ("T10YIE", "T10Y_Inflation_Expectation"),
        ("T5YIE", "T5Y_Inflation_Expectation"),
        ("T5YIFR", "T5Y5Y_Inflation_Forward"),
        ("TEDRATE", "TED_Spread"),
        ("UMCSENT", "Michigan_Sentiment"),
        ("UNRATE", "Unemployment"),
        ("VIXCLS", "VIX"),
        ("VIXDVOL", "VIX_DrawVol"),
        ("WILL5000IND", "Wilshire5000"),
    ],
}

def _flatten_target_choices():
    out = []
    for group, items in DEFAULT_TARGET_GROUPS.items():
        src = "fred" if group == FRED_TARGET_GROUP else "yfinance"
        for sym, label in items:
            out.append((sym, label, src))
    return out


# (symbol, label, source) — "flattened" view of DEFAULT_TARGET_GROUPS, for any
# code that doesn't need the grouping (resolving a symbol's source, etc.)
DEFAULT_TARGET_CHOICES = _flatten_target_choices()

# "Large" universe automatically used to build features (no more manual ticker
# selection): union of everything available above, both yfinance and FRED side.
# The chosen target is removed from it when building the config (see
# webapp/forms.py) to avoid a ticker predicting itself.
DEFAULT_UNIVERSE_YF_TICKERS = [s for s, _, src in DEFAULT_TARGET_CHOICES if src == "yfinance"]
DEFAULT_UNIVERSE_FRED_SERIES = {label: s for s, label, src in DEFAULT_TARGET_CHOICES if src == "fred"}
