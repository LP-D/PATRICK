"""Défauts encodant les leçons du projet VIX (README) — activables autrement,
jamais retirés du code : SHAP bat RFE/LASSO en test direct, le stacking perd sur
93% des (horizon, fold) testés en walk-forward, le DL n'a jamais battu le ML
classique, la purge a un effet négligeable, la calibration n'aide que hors STRESS.
"""

DEFAULT_ML_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost"]
DEFAULT_SAMPLERS_ALL = ["SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN"]
DEFAULT_SAMPLER = ["SMOTE"]
DEFAULT_SELECTION_METHOD = "shap"
DEFAULT_N_FEATURES_GRID = list(range(5, 16))
DEFAULT_REGIMES = ["GLOBAL"]
DEFAULT_HORIZONS = [1, 2, 3, 5, 7, 10]
DEFAULT_FEATURE_FAMILIES = ["technical", "interactions", "spike", "vol_models", "macro"]
DEFAULT_POOL_PREFILTER = 450
DEFAULT_SHAP_SAMPLE = 500
DEFAULT_N_WF_FOLDS = 5
DEFAULT_MIN_TRAIN_FRAC = 0.40
DEFAULT_FLAT_THR = 0.003
DEFAULT_SEED = 42

# Optuna fait partie de la boucle par défaut (demande explicite) : sélectionner le
# meilleur modèle sans l'affiner ne répond pas au besoin "ressort le meilleur modèle".
DEFAULT_TUNING_ENABLED = True
DEFAULT_TUNING_TOP_K = 5
DEFAULT_TUNING_N_TRIALS = 100
DEFAULT_TUNING_CV_SPLITS = 3

# Options désactivées par défaut mais câblées dans le pipeline (pas en annexe) :
# purge (VIX_PURGED_CV : delta F1_dir négligeable), calibration (VIX_CALIBRATED_THRESHOLD :
# gain conditionnel au régime, nuit en STRESS), stacking (VIX_STACKING_WF : perd 28/30).
DEFAULT_PURGE_ENABLED = False
DEFAULT_CALIBRATION_ENABLED = False
DEFAULT_STACKING_ENABLED = False
