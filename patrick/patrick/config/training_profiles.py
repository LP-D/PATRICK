"""Profils d'entraînement prêts à l'emploi (page Lancer) : un profil = un jeu de réglages « Avancé » cohérent pour un objectif
précis (itérer vite, chercher large, résister au sur-apprentissage, historique court...).

Un profil est un PATCH sur la vue du formulaire (`webapp/forms.py::to_view`, clés plates = champs du formulaire) : appliqué à la
configuration par défaut, il préremplit le formulaire, que l'utilisateur relit avant de lancer. Ne contient que des champs que le
formulaire sait représenter -- sinon le réglage serait perdu à la soumission. Les profils enregistrés par l'utilisateur
(navigateur) restent à part ; ceux-ci sont fournis avec l'application.

`cost` : durée relative d'un run typique de 10 ans+ d'historique (low ≈ 5-10 min, medium ≈ 20-40 min, high ≈ 1-3 h).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from patrick.clock import utc_today
from patrick.config import defaults as D

ALL_ALGOS = list(D.ALL_ML_ALGOS)


@dataclass(frozen=True)
class TrainingProfile:
    key: str
    cost: str                                  # "low" | "medium" | "high"
    patch: dict = field(default_factory=dict)  # clés de `to_view`
    needs: str | None = None                   # contrainte d'usage : "equity" (cible action), "any"
    icon: str = "layers"

    def resolved_patch(self, today: date | None = None) -> dict:
        """Le patch avec ses valeurs calculées (dates relatives à aujourd'hui)."""
        out = dict(self.patch)
        for k, v in list(out.items()):
            if callable(v):
                out[k] = v(today or utc_today())
        return out


def _years_ago(years: int):
    return lambda today: (today - timedelta(days=int(365.25 * years))).isoformat()


PROFILES: tuple[TrainingProfile, ...] = (
    TrainingProfile("quick", "low", {
        "tuning_enabled": False, "staged_screening": True, "n_features_grid": "5,6,7,8,9", "algos": ["XGBoost", "LightGBM"],
        "n_wf_folds": 3, "sampler_candidates": ["SMOTE"], "top_k": 1}, icon="zap"),
    TrainingProfile("standard", "medium", {}, icon="layers"),
    TrainingProfile("deep", "high", {
        "algos": ALL_ALGOS, "n_trials": 200, "top_k": 3, "cv_splits": 4, "stacking": True, "n_wf_folds": 7,
        "n_features_grid": ",".join(str(n) for n in range(5, 21)), "sampler_candidates": ["SMOTE", "BorderlineSMOTE"]}, icon="layers"),
    TrainingProfile("robust", "high", {
        "scheme": "cpcv", "purge": True, "embargo_enabled": True, "holdout_months": 18, "n_features_grid": "5,6,7,8,9,10",
        "n_trials": 60, "top_k": 1, "track_stability": True}, icon="shield"),
    TrainingProfile("recent", "medium", {
        "start_date": _years_ago(10), "holdout_months": 12, "n_wf_folds": 4, "n_features_grid": "5,6,7,8,9,10,11,12"}, icon="clock"),
    TrainingProfile("short_history", "low", {
        "n_wf_folds": 3, "holdout_months": 12, "min_train_frac": 0.5, "n_features_grid": "5,6,7,8", "n_trials": 40,
        "min_history_years": 4}, icon="clock"),
    TrainingProfile("regimes", "high", {"regimes": "GLOBAL,CALM,NORMAL,STRESS"}, icon="activity"),
    TrainingProfile("ensemble", "high", {
        "algos": ALL_ALGOS, "stacking": True, "calibration": True, "n_trials": 120, "top_k": 2}, icon="layers"),
    TrainingProfile("clustered", "medium", {"reduction_corr_threshold": 0.85, "n_features_grid": "5,6,7,8,9,10,11,12"}, icon="layers"),
    TrainingProfile("wide_universe", "high", {"universe_scope": "extended", "reduction_corr_threshold": 0.9}, icon="globe"),
    TrainingProfile("balanced", "medium", {
        "sampler_candidates": ["SMOTE", "BorderlineSMOTE", "SMOTETomek"], "uniqueness_weights": True}, icon="layers"),
    TrainingProfile("alpha", "medium", {"target_kind": "alpha"}, needs="equity", icon="trending-up"),
    TrainingProfile("multi_horizon", "high", {"horizons": [1, 5, 10, 20]}, icon="calendar"),
    TrainingProfile("technical_only", "low", {
        "families": ["technical", "spike"], "tuning_enabled": False, "staged_screening": True}, icon="activity"),
    TrainingProfile("macro_vol", "medium", {"families": ["macro", "vol_models", "technical"]}, icon="globe"),
    TrainingProfile("seed_check", "medium", {"seed": 7}, icon="refresh-cw"),
)

BY_KEY: dict[str, TrainingProfile] = {p.key: p for p in PROFILES}


def get(key: str) -> TrainingProfile | None:
    return BY_KEY.get(key)


def apply_patch(view: dict, patch: dict) -> dict:
    """`view` (vue du formulaire) avec `patch` appliqué, sans modifier l'original. Les clés inconnues du formulaire sont
    refusées : un profil ne doit jamais proposer un réglage que le formulaire perdrait."""
    unknown = [k for k in patch if k not in view]
    if unknown:
        raise KeyError(f"réglage(s) absent(s) du formulaire : {', '.join(sorted(unknown))}")
    return {**view, **patch}
