"""Profils d'entraînement prêts à l'emploi (page Lancer) : un profil = un jeu de réglages « Avancé » cohérent pour un objectif
précis (itérer vite, chercher large, résister au sur-apprentissage, historique court...).

Un profil est un PATCH sur la vue du formulaire (`webapp/forms.py::to_view`, clés plates = champs du formulaire) : appliqué à la
configuration par défaut, il préremplit le formulaire, que l'utilisateur relit avant de lancer. Ne contient que des champs que le
formulaire sait représenter -- sinon le réglage serait perdu à la soumission. Les profils enregistrés par l'utilisateur
(navigateur) restent à part ; ceux-ci sont fournis avec l'application.

`cost` : durée relative d'un run typique de 10 ans+ d'historique (low ≈ 5-10 min, medium ≈ 20-40 min, high ≈ 1-3 h, max ≈ une nuit ou
plus par cible : la recherche la plus large que le pipeline sait faire, à réserver à une cible et à peu d'horizons).

`task` : l'objectif du modèle (ADR 0029, 0032). `direction` (les classes de mouvement, défaut) ou `value` (le rendement lui-même, régression,
catégorie de champions à part) ; un profil de valeur exacte porte `task: value` dans son patch, un profil de direction ne la touche pas (la page
repart de la configuration par défaut, en direction). Ce que la valeur exacte refuse (empilement, CPCV, sur-échantillonnage) n'apparaît dans
aucun de ses profils.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from patrick.config import defaults as D
from patrick.core.clock import utc_today

ALL_ALGOS = list(D.ALL_ML_ALGOS)


COSTS = ("low", "medium", "high", "max")
TASKS = ("direction", "value")


@dataclass(frozen=True)
class TrainingProfile:
    key: str
    cost: str                                  # "low" | "medium" | "high" | "max"
    patch: dict = field(default_factory=dict)  # clés de `to_view`
    needs: str | None = None                   # contrainte d'usage : "equity" (cible action), "any"
    icon: str = "layers"
    task: str = "direction"                    # objectif du modèle que le profil prépare (voir le module)

    @property
    def warnings(self) -> list[str]:
        """Clés i18n des avertissements à montrer quand le profil est appliqué (bandeau de la page de lancement)."""
        out = []
        if self.needs == "equity":
            out.append("prof_warn_equity")
        if self.task == "value":
            out.append("prof_warn_value")
        if self.cost == "max":
            out.append("prof_warn_max")
        return out

    def resolved_patch(self, today: date | None = None) -> dict:
        """Le patch avec ses valeurs calculées (dates relatives à aujourd'hui)."""
        out = dict(self.patch)
        for k, v in list(out.items()):
            if callable(v):
                out[k] = v(today or utc_today())
        return out


def _years_ago(years: int):
    return lambda today: (today - timedelta(days=int(365.25 * years))).isoformat()


# Profil « max » (2026-11-27) : la configuration la plus large que le formulaire accepte sans changer ce qui juge le modèle (holdout,
# historique minimum, régime GLOBAL) : tous les algorithmes, criblage exhaustif d'une grille de 5 à 30 variables, trois sur-échantillonneurs
# et « aucun », 8 plis walk-forward purgés avec embargo, 300 essais Optuna sur 3 finalistes par horizon (5 plis de validation), interactions
# et pré-filtre élargis, empilement de 40 modèles et probabilités calibrées. Plusieurs heures par horizon : une cible, peu d'horizons.
_MAX_SEARCH = {
    "algos": ALL_ALGOS, "tuning_enabled": True, "n_trials": 300, "top_k": 3, "cv_splits": 5,
    "staged_screening": False, "n_features_grid": "5,6,7,8,9,10,12,14,16,18,20,25,30",
    "n_wf_folds": 8, "purge": True, "embargo_enabled": True, "track_stability": True, "uniqueness_weights": True,
    "interact_top_base": 60, "interact_top_pairs": 30, "interact_final_n": 40, "pool_prefilter": 600,
}
# Valeur exacte : mêmes leviers de recherche, sans ce que l'objectif refuse (empilement, sur-échantillonnage, calibration isotone : la
# distribution des erreurs hors échantillon en tient lieu).
_VALUE = {"task": "value", "value_criterion": "IC", "calibration": False}


PROFILES: tuple[TrainingProfile, ...] = (
    TrainingProfile("quick", "low", {
        "tuning_enabled": False, "staged_screening": True, "n_features_grid": "5,6,7,8,9", "algos": ["XGBoost", "LightGBM"],
        "n_wf_folds": 3, "sampler_candidates": ["SMOTE"], "top_k": 1}, icon="zap"),
    TrainingProfile("standard", "medium", {}, icon="layers"),
    TrainingProfile("deep", "high", {
        "algos": ALL_ALGOS, "n_trials": 200, "top_k": 3, "cv_splits": 4, "stacking": True, "n_wf_folds": 7,
        "n_features_grid": ",".join(str(n) for n in range(5, 21)), "sampler_candidates": ["SMOTE", "BorderlineSMOTE"]}, icon="layers"),
    # La CPCV refuse la présélection progressive, cochée par défaut dans le formulaire : sans `staged_screening: False`, le profil était
    # refusé à la soumission (constat du 2026-11-27).
    TrainingProfile("robust", "high", {
        "scheme": "cpcv", "purge": True, "embargo_enabled": True, "holdout_months": 18, "n_features_grid": "5,6,7,8,9,10",
        "n_trials": 60, "top_k": 1, "track_stability": True, "staged_screening": False}, icon="shield"),
    TrainingProfile("recent", "medium", {
        "start_date": _years_ago(10), "holdout_months": 12, "n_wf_folds": 4, "n_features_grid": "5,6,7,8,9,10,11,12"}, icon="clock"),
    TrainingProfile("short_history", "low", {
        "n_wf_folds": 3, "holdout_months": 12, "min_train_frac": 0.5, "n_features_grid": "5,6,7,8", "n_trials": 40,
        "min_history_years": 4}, icon="clock"),
    TrainingProfile("regimes", "high", {"regimes": "GLOBAL,CALM,NORMAL,STRESS"}, icon="activity"),
    TrainingProfile("ensemble", "high", {
        "algos": ALL_ALGOS, "stacking": True, "calibration": True, "n_trials": 120, "top_k": 2}, icon="layers"),
    TrainingProfile("clustered", "medium", {"reduction_corr_threshold": 0.85, "n_features_grid": "5,6,7,8,9,10,11,12"}, icon="layers"),
    TrainingProfile("stacking", "medium", {
        "stacking": True, "stacking_n_models": 20, "algos": ["XGBoost", "LightGBM", "RandomForest"], "tuning_enabled": False,
        "staged_screening": True, "n_features_grid": "8,12,16"}, icon="layers"),
    TrainingProfile("balanced", "medium", {
        "sampler_candidates": ["SMOTE", "BorderlineSMOTE", "SMOTETomek"], "uniqueness_weights": True}, icon="layers"),
    TrainingProfile("alpha", "medium", {"target_kind": "alpha"}, needs="equity", icon="trending-up"),
    TrainingProfile("multi_horizon", "high", {"horizons": [1, 5, 10, 20]}, icon="calendar"),
    TrainingProfile("technical_only", "low", {
        "families": ["technical", "spike"], "tuning_enabled": False, "staged_screening": True}, icon="activity"),
    TrainingProfile("macro_vol", "medium", {"families": ["macro", "vol_models", "technical"]}, icon="globe"),
    TrainingProfile("seed_check", "medium", {"seed": 7}, icon="refresh-cw"),
    TrainingProfile("max", "max", {
        **_MAX_SEARCH, "sampler_candidates": ["SMOTE", "BorderlineSMOTE", "SMOTETomek", "none"], "calibration": True,
        "stacking": True, "stacking_n_models": 40}, icon="zap"),
    # --- Valeur exacte (régression du rendement, ADR 0029 / 0032). Sur les 84 premiers champions (27/11, tous des MLP sans réglage à 8
    # variables), l'IC médiane du holdout passe de -0,005 à 1 jour à +0,12 à 5 et 7 jours : les profils de valeur visent d'abord ces horizons.
    TrainingProfile("value_quick", "low", {
        **_VALUE, "tuning_enabled": False, "staged_screening": True, "n_features_grid": "5,6,7,8,9", "algos": ["LightGBM", "XGBoost"],
        "n_wf_folds": 3, "top_k": 1}, icon="zap", task="value"),
    TrainingProfile("value_standard", "medium", {**_VALUE}, icon="layers", task="value"),
    TrainingProfile("value_swing", "medium", {**_VALUE, "horizons": [5, 7, 10, 20]}, icon="calendar", task="value"),
    TrainingProfile("value_r2", "medium", {**_VALUE, "value_criterion": "R2_oos"}, icon="target", task="value"),
    TrainingProfile("value_deep", "high", {
        **_VALUE, "algos": ALL_ALGOS, "n_trials": 150, "top_k": 3, "cv_splits": 4, "n_wf_folds": 7,
        "n_features_grid": ",".join(str(n) for n in range(5, 21))}, icon="layers", task="value"),
    TrainingProfile("value_max", "max", {**_MAX_SEARCH, **_VALUE, "sampler_candidates": ["none"], "stacking": False}, icon="zap", task="value"),
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


def _norm(value):
    """Forme comparable d'un réglage : listes et chaînes séparées par des virgules deviennent des tuples de chaînes, les nombres des flottants."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return tuple(str(x).strip() for x in value)
    if isinstance(value, str):
        return tuple(x.strip() for x in value.split(",")) if "," in value else value.strip()
    if isinstance(value, (int, float)):
        return float(value)
    return value


def identify(view: dict, default_view: dict, today: date | None = None) -> str | None:
    """Profil fourni qui décrit une configuration (sa vue de formulaire) : un run n'enregistre pas le profil dont il est parti, il se déduit
    de ses réglages. Le profil reconnu est celui dont le plus de réglages sont tous identiques ; `standard` (patch vide) quand chaque réglage
    que touche un profil est à sa valeur par défaut ; `None` pour une configuration personnalisée. La date de départ, relative au jour du
    lancement, n'est pas comparée."""
    best: tuple[str, int] | None = None
    touched: set[str] = set()
    task = view.get("task") or "direction"
    for p in PROFILES:
        patch = {k: v for k, v in p.resolved_patch(today).items() if k != "start_date"}
        touched.update(patch)
        if p.task != task:                      # un profil de direction ne décrit jamais un run de valeur exacte, et inversement
            continue
        if patch and all(_norm(view.get(k)) == _norm(v) for k, v in patch.items()) and (best is None or len(patch) > best[1]):
            best = (p.key, len(patch))
    if best is not None:
        return best[0]
    return "standard" if all(_norm(view.get(k)) == _norm(default_view.get(k)) for k in touched) else None
