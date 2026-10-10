"""Conseiller de réentraînement : après un entraînement, détermine par des RÈGLES (conditions sur les résultats et sur la façon
dont le modèle a été entraîné, pas un modèle de langage) quel réentraînement tester ensuite, avec le réglage « Avancé » à changer.

Chaque règle lit un diagnostic chiffré du run (AUC et F1 sur les folds de test et sur le holdout, écart entre les deux, variance
entre folds, tendance dans le temps, stabilité de la sélection de features, PBO, rho test/holdout, historique disponible, qualité
des données, équilibre des classes, durée) et, si sa condition est vraie, propose :

- un PATCH sur les champs du formulaire de lancement (`webapp/forms.py::to_view`), applicable en un clic ;
- un score de pertinence 0-100 (sévérité du symptôme, pas une probabilité de succès) ;
- les faits chiffrés qui l'ont déclenchée (affichés tels quels : on voit pourquoi) ;
- une estimation du coût (durée relative au run précédent).

Les propositions sont classées ; la première est « le meilleur prochain essai ». Limites assumées : aucune règle ne promet une
amélioration, elles désignent l'hypothèse la plus plausible à tester. Le deep learning n'existe pas dans PATRICK (boosting
d'arbres, forêts et empilement) : il n'est cité que comme alternative indisponible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from math import comb

from patrick.clock import utc_today
from patrick.config import defaults as D
from patrick.config import training_profiles as profiles

# Seuils (AUC multiclasse un-contre-tous sur 4 classes : le hasard vaut 0,50).
CHANCE_AUC = 0.53          # en dessous : pas de signal
GOOD_AUC = 0.58            # au-dessus : signal net
GAP_AUC = 0.05             # écart test -> holdout au-delà duquel on soupçonne la sur-sélection
GAP_F1 = 0.08
FOLD_STD_AUC = 0.05        # dispersion des folds jugée instable
TREND_AUC = 0.04           # différence première/seconde moitié des folds
JACCARD_MIN = 0.40         # `selection.stability.MIN_MEAN_JACCARD_WARNING`
SHORT_HISTORY_YEARS = 8.0
EXCLUSION_FRAC = 0.20
IMBALANCE_RATIO = 2.2      # plus grosse classe / plus petite classe
SLOW_RUN_S = 3600.0

COST_LABEL = {0: "low", 1: "medium", 2: "high"}


@dataclass
class Diagnosis:
    run_id: str
    target: str
    horizon: int
    asset_class: str = "other"
    kind: str = "raw"                       # "raw" | "alpha"
    scheme: str = "walkforward"
    suspect: str | None = None
    guard_active: bool = False              # garde anti-fuite (`data/alignment.py`) appliquée à ce run
    auc_test: float | None = None
    f1_test: float | None = None
    auc_holdout: float | None = None
    f1_holdout: float | None = None
    fold_auc: list[float] = field(default_factory=list)
    persistence_f1: float | None = None
    dm_p: float | None = None
    pbo: float | None = None
    pbo_reliable: bool = False
    jaccard: float | None = None
    rho_test_holdout: float | None = None
    cumulative_trials: int | None = None
    history_years: float | None = None
    n_excluded: int = 0
    n_universe: int = 0
    class_shares: dict[str, float] | None = None
    horizon_auc: dict[int, float] = field(default_factory=dict)   # AUC de test par horizon d'un même lancement
    duration_s: float | None = None
    view: dict = field(default_factory=dict)  # valeurs actuelles des champs du formulaire

    # ---- dérivés
    @property
    def gap_auc(self) -> float | None:
        return None if self.auc_test is None or self.auc_holdout is None else self.auc_test - self.auc_holdout

    @property
    def gap_f1(self) -> float | None:
        return None if self.f1_test is None or self.f1_holdout is None else self.f1_test - self.f1_holdout

    @property
    def fold_std(self) -> float | None:
        return _std(self.fold_auc) if len(self.fold_auc) >= 3 else None

    @property
    def fold_trend(self) -> float | None:
        """AUC moyenne de la seconde moitié des folds moins celle de la première (positif : le modèle s'améliore avec le temps)."""
        n = len(self.fold_auc)
        if n < 4:
            return None
        half = n // 2
        return sum(self.fold_auc[n - half:]) / half - sum(self.fold_auc[:half]) / half

    @property
    def edge_vs_persistence(self) -> float | None:
        return None if self.f1_test is None or self.persistence_f1 is None else self.f1_test - self.persistence_f1

    @property
    def is_equity_like(self) -> bool:
        return self.asset_class.startswith("equities")


@dataclass
class Suggestion:
    key: str
    score: float
    patch: dict = field(default_factory=dict)       # champs du formulaire -> nouvelle valeur
    facts: dict = field(default_factory=dict)       # chiffres qui ont déclenché la règle (pour le texte)
    cost: str = "medium"
    cost_factor: float | None = None                # durée relative au run précédent
    est_minutes: float | None = None
    available: bool = True                          # False : levier absent de PATRICK (deep learning)
    manual: bool = False                            # True : action hors formulaire (rien à pré-remplir)
    changes: list[dict] = field(default_factory=list)   # [{field, before, after}]


def _fmt(v) -> str:
    """Valeur de fait affichée : 3 décimales par défaut, « — » si absente, liste jointe."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def _signed(v: float | None) -> str:
    return "—" if v is None or math.isnan(v) else f"{v:+.3f}"


def _pct(v: float) -> str:
    return f"{v * 100:.0f} %"


def _std(xs: list[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------------------------------------------- coût

def _units(view: dict) -> float:
    """Charge de calcul relative d'une configuration (nombre d'ajustements de modèles, grosso modo). Sert uniquement à comparer
    deux configurations entre elles : le rapport donne le facteur de durée, pas une durée absolue."""
    algos = max(1, len(view.get("algos") or [1]))
    samplers = max(1, len(view.get("sampler_candidates") or [1]))
    grid = max(1, len([x for x in str(view.get("n_features_grid", "")).split(",") if x.strip()]))
    horizons = max(1, len(view.get("horizons") or [1]))
    regimes = max(1, len([x for x in str(view.get("regimes", "GLOBAL")).split(",") if x.strip()]))
    if view.get("scheme") == "cpcv":
        splits = comb(int(view.get("n_groups") or 7), int(view.get("k_test_groups") or 2))
    else:
        splits = max(1, int(view.get("n_wf_folds") or 5))
    scan = algos * samplers * grid * horizons * regimes * (1 if view.get("staged_screening") else splits)
    scan += algos * samplers * horizons * regimes * splits * (3 if view.get("staged_screening") else 0)   # finalistes sur les folds
    tuning = 0.0
    if view.get("tuning_enabled", True):
        tuning = (int(view.get("top_k") or 1) * int(view.get("n_trials") or 100) * int(view.get("cv_splits") or 3)
                  * horizons * regimes * 0.35)
    extra = 1.0 + (0.35 if view.get("stacking") else 0.0) + (0.1 if view.get("calibration") else 0.0)
    if view.get("universe_scope") == "extended":
        extra += 0.4
    return (scan + tuning) * extra


def cost_factor(before: dict, after: dict) -> float:
    b = _units(before)
    return _units(after) / b if b else 1.0


def _cost_class(factor: float) -> str:
    return COST_LABEL[0 if factor <= 0.7 else (1 if factor <= 1.6 else 2)]


# ---------------------------------------------------------------------------------------------------------------- règles

def _next_horizons(horizon: int) -> list[int]:
    """Deux horizons nettement plus longs (le bruit pèse moins sur un mouvement de plusieurs jours)."""
    if horizon < 5:
        return [5, 10]
    if horizon < 10:
        return [10, 20]
    return [20, 30] if horizon < 20 else [horizon]


def _rule_fix_leak(d: Diagnosis) -> Suggestion | None:
    if not d.suspect:
        return None
    if not d.guard_active:
        return Suggestion("fix_leak", 100, {}, {"reason": d.suspect}, manual=False)
    return Suggestion("derived_target", 100, {"reduction_corr_threshold": 0.8},
                      {"reason": d.suspect, "target": d.target})


def _rule_signal_absent(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.auc_test is None or d.auc_test >= CHANCE_AUC:
        return None
    if d.auc_holdout is not None and d.auc_holdout >= CHANCE_AUC + 0.02:
        return None
    score = _clip(60 + (CHANCE_AUC - d.auc_test) * 500, 0, 85)
    return Suggestion("signal_absent", score, {"horizons": _next_horizons(d.horizon)},
                      {"auc": d.auc_test, "auc_ho": d.auc_holdout, "horizon": d.horizon,
                       "horizons": ", ".join(str(h) for h in _next_horizons(d.horizon))})


def _rule_overfit(d: Diagnosis) -> Suggestion | None:
    if d.suspect:
        return None
    reasons, severity = [], 0.0
    if d.gap_auc is not None and d.gap_auc >= GAP_AUC:
        reasons.append("auc")
        severity = max(severity, (d.gap_auc - GAP_AUC) * 600)
    if d.gap_f1 is not None and d.gap_f1 >= GAP_F1:
        reasons.append("f1")
        severity = max(severity, (d.gap_f1 - GAP_F1) * 400)
    if d.rho_test_holdout is not None and d.rho_test_holdout < 0:
        reasons.append("rho")
        severity = max(severity, 25 - d.rho_test_holdout * 30)
    if d.pbo_reliable and d.pbo is not None and d.pbo > 0.5:
        reasons.append("pbo")
        severity = max(severity, (d.pbo - 0.5) * 120)
    if not reasons:
        return None
    cur = d.view
    return Suggestion("overfit", _clip(50 + severity, 0, 92), {
        "n_features_grid": "5,6,7,8,9,10", "n_trials": min(int(cur.get("n_trials") or 100), 50), "top_k": 1,
        "holdout_months": max(int(cur.get("holdout_months") or 15), 18), "embargo_enabled": True, "purge": True},
        {"gap_auc": _signed(d.gap_auc), "gap_f1": _signed(d.gap_f1), "rho": _signed(d.rho_test_holdout), "pbo": d.pbo,
         "signals": ", ".join(reasons)})


def _rule_unstable_folds(d: Diagnosis) -> Suggestion | None:
    std, trend = d.fold_std, d.fold_trend
    if d.suspect or std is None or std < FOLD_STD_AUC:
        return None
    facts = {"std": std, "min": min(d.fold_auc), "max": max(d.fold_auc), "n": len(d.fold_auc)}
    score = _clip(42 + (std - FOLD_STD_AUC) * 700, 0, 82)
    if trend is not None and trend >= TREND_AUC:
        # les folds récents sont meilleurs : les données anciennes brouillent le signal -> fenêtre plus récente
        years = d.history_years or 20.0
        start = f"{max(1990, int(utc_today().year - max(8, years * 0.6)))}-01-01"
        return Suggestion("recent_window", score, {"start_date": start, "n_wf_folds": 4},
                          {**facts, "trend": _signed(trend), "start": start})
    return Suggestion("regimes", score, {"regimes": "GLOBAL,CALM,NORMAL,STRESS"}, {**facts, "trend": _signed(trend)})


def _rule_unstable_features(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.jaccard is None or d.jaccard != d.jaccard or d.jaccard >= JACCARD_MIN:
        return None
    method = d.view.get("selection_method", "shap")
    return Suggestion("unstable_features", _clip(45 + (JACCARD_MIN - d.jaccard) * 200, 0, 78), {
        "reduction_corr_threshold": 0.85, "selection_method": "lasso" if method == "shap" else "shap", "shap_sample": 1000},
        {"jaccard": d.jaccard, "threshold": f"{JACCARD_MIN:.2f}", "method": method})


def _rule_more_capacity(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.auc_test is None or not (CHANCE_AUC <= d.auc_test < GOOD_AUC):
        return None
    if d.gap_auc is not None and d.gap_auc >= GAP_AUC / 2:        # écart test/holdout : plus de capacité aggraverait la sur-sélection
        return None
    if d.fold_std is not None and d.fold_std >= FOLD_STD_AUC:
        return None
    cur = d.view
    small = (not cur.get("tuning_enabled", True) or int(cur.get("n_trials") or 100) < 150 or int(cur.get("top_k") or 1) < 2
             or len(cur.get("algos") or []) < 4 or not cur.get("stacking"))
    if not small:
        return None
    return Suggestion("more_capacity", 52, {
        "algos": list(D.ALL_ML_ALGOS), "stacking": True, "tuning_enabled": True, "n_trials": max(150, int(cur.get("n_trials") or 100)),
        "top_k": 3}, {"auc": d.auc_test, "gap": _signed(d.gap_auc), "std": d.fold_std})


def _rule_deep_learning(d: Diagnosis) -> Suggestion | None:
    cap = _rule_more_capacity(d)
    if cap is None:
        return None
    return Suggestion("deep_learning", 20, {}, {"auc": d.auc_test}, available=False, manual=True)


def _rule_short_history(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.history_years is None or d.history_years >= SHORT_HISTORY_YEARS:
        return None
    cur = d.view
    return Suggestion("short_history", _clip(55 + (SHORT_HISTORY_YEARS - d.history_years) * 4, 0, 85), {
        "n_wf_folds": min(3, int(cur.get("n_wf_folds") or 5)), "holdout_months": 12, "n_features_grid": "5,6,7,8", "n_trials": 40,
        "min_train_frac": 0.5}, {"years": f"{d.history_years:.1f}", "threshold": f"{SHORT_HISTORY_YEARS:.0f}"})


def _rule_data_degraded(d: Diagnosis) -> Suggestion | None:
    if d.n_universe <= 0 or d.n_excluded / d.n_universe < EXCLUSION_FRAC:
        return None
    frac = d.n_excluded / d.n_universe
    return Suggestion("data_degraded", _clip(48 + (frac - EXCLUSION_FRAC) * 120, 0, 75), {"yf_coverage": 0.75},
                      {"excluded": d.n_excluded, "universe": d.n_universe, "frac": _pct(frac)})


def _rule_class_balance(d: Diagnosis) -> Suggestion | None:
    shares = d.class_shares
    if not shares or len(shares) < 2:
        return None
    hi, lo = max(shares.values()), min(shares.values())
    if lo <= 0 or hi / lo < IMBALANCE_RATIO:
        return None
    return Suggestion("class_balance", _clip(40 + (hi / lo - IMBALANCE_RATIO) * 12, 0, 70), {
        "sampler_candidates": ["SMOTE", "BorderlineSMOTE", "SMOTETomek"], "uniqueness_weights": True},
        {"ratio": f"{hi / lo:.1f}", "hi": _pct(hi), "lo": _pct(lo)})


def _rule_calibrate(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.auc_test is None or d.auc_test < 0.56 or d.view.get("calibration"):
        return None
    if d.auc_holdout is not None and d.auc_holdout < CHANCE_AUC:       # le classement ne tient pas sur le holdout : rien à calibrer
        return None
    return Suggestion("calibrate", 34, {"calibration": True}, {"auc": d.auc_test})


def _rule_confirm_cpcv(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.scheme == "cpcv" or d.auc_holdout is None or d.auc_holdout < 0.57:
        return None
    if (d.gap_auc is not None and d.gap_auc >= GAP_AUC) or (d.edge_vs_persistence is not None and d.edge_vs_persistence <= 0):
        return None
    return Suggestion("confirm_cpcv", 56, {"scheme": "cpcv", "purge": True, "embargo_enabled": True},
                      {"auc_ho": d.auc_holdout, "gap": _signed(d.gap_auc)})


def _rule_try_alpha(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.kind != "raw" or not d.is_equity_like or d.auc_test is None or d.auc_test >= 0.57:
        return None
    return Suggestion("try_alpha", 41, {"target_kind": "alpha"}, {"auc": d.auc_test, "asset_class": d.asset_class})


def _rule_best_horizon(d: Diagnosis) -> Suggestion | None:
    if d.suspect or len(d.horizon_auc) < 3:
        return None
    best_h, best = max(d.horizon_auc.items(), key=lambda kv: kv[1])
    worst = min(d.horizon_auc.values())
    if best - worst < 0.03 or best < CHANCE_AUC:
        return None
    ladder = sorted(d.horizon_auc)
    i = ladder.index(best_h)
    around = ladder[max(0, i - 1): i + 2]
    return Suggestion("best_horizon", _clip(40 + (best - worst) * 400, 0, 70), {"horizons": around},
                      {"best": best_h, "auc": best, "worst": worst, "horizons": ", ".join(str(h) for h in around),
                       "spread": best - worst})


def _rule_faster_iteration(d: Diagnosis) -> Suggestion | None:
    if d.suspect or d.duration_s is None or d.duration_s < SLOW_RUN_S or d.auc_test is None or d.auc_test >= GOOD_AUC:
        return None
    return Suggestion("faster_iteration", 32, {"tuning_enabled": False, "staged_screening": True, "n_trials": 30},
                      {"minutes": f"{d.duration_s / 60:.0f}", "auc": d.auc_test})


def _rule_robustness_seed(d: Diagnosis) -> Suggestion | None:
    if d.suspect:
        return None
    seed = int(d.view.get("seed") or D.DEFAULT_SEED)
    return Suggestion("seed_check", 25, {"seed": seed + 1}, {"seed": seed})


RULES = (_rule_fix_leak, _rule_signal_absent, _rule_overfit, _rule_unstable_folds, _rule_unstable_features, _rule_more_capacity,
         _rule_deep_learning, _rule_short_history, _rule_data_degraded, _rule_class_balance, _rule_calibrate, _rule_confirm_cpcv,
         _rule_try_alpha, _rule_best_horizon, _rule_faster_iteration, _rule_robustness_seed)


def advise(diag: Diagnosis, *, limit: int = 6) -> list[Suggestion]:
    """Les propositions de réentraînement, de la plus pertinente à la moins pertinente (à score égal : la moins chère d'abord)."""
    out: list[Suggestion] = []
    seen: set[str] = set()
    for rule in RULES:
        s = rule(diag)
        if s is None or s.key in seen:
            continue
        seen.add(s.key)
        if s.patch:
            after = {**diag.view, **{k: v for k, v in s.patch.items() if k in diag.view}}
            s.changes = [{"field": k, "before": diag.view.get(k), "after": v} for k, v in s.patch.items()
                         if diag.view.get(k) != v]
            s.cost_factor = round(cost_factor(diag.view, after), 2)
            s.cost = _cost_class(s.cost_factor)
            if diag.duration_s:
                s.est_minutes = round(diag.duration_s / 60 * s.cost_factor, 1)
        s.facts = {k: _fmt(v) for k, v in s.facts.items()}
        out.append(s)
    out.sort(key=lambda s: (-s.score, s.cost_factor or 1.0))
    return out[:limit]


def validate_patches() -> list[str]:
    """Contrôle interne (utilisé par les tests) : chaque patch de profil ou de règle ne cite que des champs du formulaire."""
    from patrick.webapp import forms

    view = forms.to_view(forms.default_config_dict())
    problems = [f"profil {p.key}: {k}" for p in profiles.PROFILES for k in p.resolved_patch() if k not in view]
    return problems


# ---------------------------------------------------------------------------------------------------------------- diagnostic d'un run

def _blocks(detail: dict, *splits: str) -> list[dict]:
    return [b for b in detail.get("fold_metrics") or [] if b["split"] in splits]


def diagnose_run(conn, run_id: str, *, detail: dict | None = None, history: dict | None = None) -> Diagnosis | None:
    """Rassemble le diagnostic chiffré d'un run (`tracking.history.run_detail` + quelques lectures ciblées). `history` :
    `data_health.history_depths()` déjà lu (évite de relire l'index du magasin pour chaque run)."""
    from patrick.config.target_label import split_run_label
    from patrick.data.session_calendar import classify_asset_class
    from patrick.tracking import db as trackdb
    from patrick.tracking import history as trackhistory
    from patrick.webapp import forms

    detail = detail or trackhistory.run_detail(conn, run_id)
    if detail is None:
        return None
    run, cfg = detail["run"], detail.get("config") or {}
    obj = cfg.get("objective", {})
    symbol = split_run_label(run["target"])[0]
    guard = (obj.get("alignment") or {}).get("version", 0) >= 1
    view = forms.to_view(cfg) if cfg.get("objective") else {}

    headline = detail.get("headline") or {}
    test, holdout = headline.get("test") or {}, headline.get("holdout") or {}
    fold_auc: list[float] = []
    for block in _blocks(detail, "test", "test_path"):
        fold_auc += [f["vals"]["AUC_ovr_4cls"] for f in block["folds"] if "AUC_ovr_4cls" in f["vals"]]
    persistence = next((b["metrics"].get("F1_dir") for b in detail.get("baselines") or [] if b["baseline"] == "BASELINE_persistence"), None)
    pbo = detail.get("pbo") or {}
    stab = detail.get("feature_stability") or {}
    diag_ho = detail.get("holdout_diag") or {}
    issues = [i for i in detail.get("quality_issues") or [] if i.get("reason") != trackdb.ALIGNMENT_REASON]
    uni = cfg.get("universe", {})

    first = (history or {}).get(symbol, {}).get("first")
    years = None
    if first:
        years = max(0.0, (utc_today() - date.fromisoformat(first)).days / 365.25)

    shares = None
    best = detail.get("best_trial")
    if best:
        rows = conn.execute("SELECT y_true, COUNT(*) FROM prediction WHERE trial_id = ? AND split = 'test' AND y_true IS NOT NULL "
                            "GROUP BY y_true", (best["trial_id"],)).fetchall()
        total = sum(n for _, n in rows)
        if total >= 40:
            shares = {str(int(k)): n / total for k, n in rows}

    horizon_auc: dict[int, float] = {}
    sibling = conn.execute("SELECT run_id, horizon FROM run WHERE config_hash = ? AND status = 'done'", (run.get("config_hash"),)).fetchall()
    if len(sibling) >= 3:
        metrics = trackdb.batch_best_metrics(conn, [r[0] for r in sibling])
        for rid, h in sibling:
            auc = (metrics.get(rid, {}).get("test") or {}).get("AUC_ovr_4cls")
            if auc is not None:
                horizon_auc[int(h)] = auc

    dm = detail.get("dm_result") or {}
    return Diagnosis(
        run_id=run_id, target=run["target"], horizon=int(run["horizon"]),
        asset_class=classify_asset_class(symbol, obj.get("target_source", "yfinance")), kind=obj.get("target_kind", "raw"),
        scheme=detail.get("scheme", "walkforward"), suspect=detail.get("suspect"), guard_active=guard,
        auc_test=test.get("AUC_ovr_4cls"), f1_test=test.get("F1_dir"), auc_holdout=holdout.get("AUC_ovr_4cls"),
        f1_holdout=holdout.get("F1_dir"), fold_auc=fold_auc, persistence_f1=persistence, dm_p=dm.get("p_value"),
        pbo=None if pbo.get("pbo") is None or pbo.get("pbo") != pbo.get("pbo") else pbo["pbo"],
        pbo_reliable=bool((pbo.get("reliability") or {}).get("ok")),
        jaccard=stab.get("mean_jaccard"), rho_test_holdout=diag_ho.get("rho") if (diag_ho.get("n_trials") or 0) >= 3 else None,
        cumulative_trials=detail.get("cumulative_trials"), history_years=years, n_excluded=len(issues),
        n_universe=len(uni.get("yf_tickers") or []) + len(uni.get("fred_series") or {}), class_shares=shares,
        horizon_auc=horizon_auc, duration_s=(detail.get("phase_breakdown") or {}).get("run_total_s"), view=view)


def advise_run(conn, run_id: str, *, detail: dict | None = None, history: dict | None = None, limit: int = 6) -> dict | None:
    """`{"diagnosis": Diagnosis, "suggestions": [Suggestion, ...]}` d'un run terminé, ou `None` s'il n'existe pas ou n'a pas de résultat."""
    diag = diagnose_run(conn, run_id, detail=detail, history=history)
    if diag is None or diag.auc_test is None and diag.f1_test is None:
        return None
    return {"diagnosis": diag, "suggestions": advise(diag, limit=limit)}
