"""4-class direction/amplitude target (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT)
with causal, regime-conditional thresholds -- logic established throughout
the VIX project (`build_target`), generalized: the series is no longer
hardcoded to the VIX.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TARGET_COL = "target_class"

VOL_WINDOW = 60
VOL_MIN_PERIODS = 20


@dataclass(frozen=True)
class TargetSpec:
    """Définition de la cible. La valeur par défaut est la méthode 1 (historique) ; `METHOD_2` est la méthode 2 (ADR 0008).

    - `flat_vol_mult` : `None` = jour « plat » si |rendement| < `flat_thr` (seuil absolu, tel quel pour tous les actifs et
      horizons) ; sinon si |rendement| < `flat_vol_mult` x volatilité réalisée causale x racine(horizon).
    - `regime_basis` : `"level"` = terciles du NIVEAU du prix (héritage du VIX : pour une action en tendance presque tout le test
      tombe en « STRESS ») ; `"volatility"` = terciles de la volatilité réalisée sur 60 jours (connue à la date, ajustée sur le train).
    - `keep_flat` : les jours plats restent dans les lignes étiquetées (le jeu d'évaluation est celui du live, qui juge tous les
      jours) ; ils sont écartés de l'ENTRAÎNEMENT et de l'ajustement des seuils par `target.attrs["flat"]`."""
    flat_vol_mult: float | None = None
    regime_basis: str = "level"
    keep_flat: bool = False


METHOD_1 = TargetSpec()
METHOD_2 = TargetSpec(flat_vol_mult=0.25, regime_basis="volatility", keep_flat=True)


def spec_for(config) -> TargetSpec:
    """Définition de cible d'un run : la méthode 1 pour tout run enregistré avant `validation.method_version`, la méthode 2 pour un
    run neuf. Une cible dont le NIVEAU est le risque (indices de volatilité) garde des régimes par niveau."""
    if getattr(getattr(config, "validation", None), "method_version", 1) < 2:
        return METHOD_1
    from patrick.data.session_calendar import untradable_kind

    obj = config.objective
    if untradable_kind(obj.target_symbol, obj.target_source) == "volatility":
        return TargetSpec(METHOD_2.flat_vol_mult, "level", True)
    return METHOD_2


def trailing_volatility(s: pd.Series) -> pd.Series:
    """Écart-type des rendements quotidiens sur `VOL_WINDOW` jours, causal ; les premières lignes (moins de `VOL_MIN_PERIODS`
    rendements) prennent l'écart-type cumulé, jamais une valeur future."""
    r1 = s.pct_change()
    vol = r1.rolling(VOL_WINDOW, min_periods=VOL_MIN_PERIODS).std()
    return vol.fillna(r1.expanding(min_periods=5).std())


def non_flat_mask(target: pd.Series) -> np.ndarray:
    """Lignes de `target` utilisables pour l'ENTRAÎNEMENT : toutes, sauf (méthode 2) les jours plats que l'évaluation garde."""
    flat = target.attrs.get("flat")
    if flat is None:
        return np.ones(len(target), dtype=bool)
    return ~flat.reindex(target.index).fillna(False).to_numpy(dtype=bool)


def regime_series(s: pd.Series, split_idx: int, spec: TargetSpec = METHOD_1) -> pd.Series:
    """CALM / NORMAL / STRESS de chaque date ; seuils (terciles) ajustés sur `s[:split_idx]` seulement."""
    basis = trailing_volatility(s) if spec.regime_basis == "volatility" else s
    basis_tr = basis.iloc[:split_idx]
    calm_thr = basis_tr.quantile(0.33)
    stress_thr = basis_tr.quantile(0.67)
    regime = pd.Series("NORMAL", index=s.index)
    regime[basis < calm_thr] = "CALM"
    regime[basis >= stress_thr] = "STRESS"
    return regime


def build_target(series: pd.Series, horizon: int, split_idx: int,
                  flat_thr: float = 0.003, ret: pd.Series | None = None,
                  spec: TargetSpec = METHOD_1) -> tuple[pd.Series, pd.Series, dict]:
    """Returns (target, regime_by_date, thresholds_by_regime). Regime
    thresholds (CALM/NORMAL/STRESS, 33%/67% quantiles of the level) and
    classification thresholds (25%/75% quantiles of the return, per regime)
    are fitted solely on `series[:split_idx]` (the fold's train set) -- no
    future leak.

    `ret` (optional): forward return over `horizon` already computed by the
    caller and indexed like `series` (e.g. the excess return over a benchmark,
    `features/alpha_target.py`); by default the raw return of `series`. The
    regime and the purge of the last `horizon` points are unchanged.

    Phase 0 (correctness): classification thresholds used to be fitted on
    `ret.loc[ret.index < cut_date]`, but `ret[d] = s[d+horizon]/s[d] - 1` --
    for dates `d` within the `horizon` last points before `cut_date`, this
    window overruns into the test set, so `ret[d]` (and by extension the
    quantiles fitted on it) is partly informed by post-cut values, even when
    excluding `d` itself. This is a leak distinct from the one
    `validation/purge.py` fixes (which only acts downstream, on already-
    built train ROWS, not on the threshold computation itself) -- detected
    by the future-corruption test (`tests/test_leakage.py`). `ret_tr`
    therefore also excludes these last `horizon` points: only label windows
    entirely before `cut_date` contribute to the threshold fit."""
    s = series.ffill().bfill()
    regime = regime_series(s, split_idx, spec)

    ret = (s.shift(-horizon) / s) - 1 if ret is None else ret.reindex(s.index)
    if spec.flat_vol_mult is None:
        flat = ret.abs() < flat_thr
    else:
        flat = ret.abs() < spec.flat_vol_mult * trailing_volatility(s) * (horizon ** 0.5)
    ret_all = ret.dropna()
    flat_all = flat.reindex(ret_all.index).fillna(False)
    ret_fit = ret_all.loc[~flat_all]          # les seuils et l'entraînement ne voient jamais les jours plats
    ret = ret_all if spec.keep_flat else ret_fit
    reg_r = regime.reindex(ret.index)

    safe_fit_idx = max(split_idx - horizon, 0)
    safe_fit_cut_date = s.index[safe_fit_idx]
    ret_tr = ret_fit.loc[ret_fit.index < safe_fit_cut_date]
    reg_tr = regime.reindex(ret_tr.index)

    thr = {}
    for reg in ["CALM", "NORMAL", "STRESS"]:
        sub = ret_tr[reg_tr == reg]
        thr[reg] = (
            sub.quantile(0.25) if len(sub) >= 20 else ret_tr.quantile(0.25),
            sub.quantile(0.75) if len(sub) >= 20 else ret_tr.quantile(0.75),
        )
    thr["GLOBAL"] = (ret_tr.quantile(0.25), ret_tr.quantile(0.75))

    def classify(r: float, reg: str) -> int:
        q25, q75 = thr.get(reg, (0, 0))
        if r < q25:
            return 0
        if r < 0:
            return 1
        if r < q75:
            return 2
        return 3

    target = pd.Series(
        [classify(r, reg_r[i]) for i, r in ret.items()], index=ret.index, name=TARGET_COL
    )
    if spec.keep_flat:
        target.attrs["flat"] = flat_all.reindex(target.index).fillna(False)
    return target, reg_r, thr


def live_class_thresholds(series: pd.Series, horizon: int,
                          flat_thr: float = 0.003, ret: pd.Series | None = None,
                          spec: TargetSpec = METHOD_1) -> tuple[float, float]:
    """Seuils (q25, q75) du rendement a `horizon` pour le regime du DERNIER
    point de `series`, ajustes uniquement sur ce qui est deja connu a cette
    date (meme logique causale que `build_target`, appelee avec `split_idx =
    len(series)` : les fenetres de label qui debordent apres le dernier point
    sont exclues). Sert au suivi live : la classe realisee d'un signal est
    jugee avec les seuils d'AUJOURD'HUI, jamais avec ceux du futur."""
    s = series.ffill().bfill()
    _, _, thr = build_target(s, horizon, len(s), flat_thr, ret=ret, spec=spec)
    regime = regime_series(s, len(s), spec).iloc[-1]
    lo, hi = thr.get(regime, thr["GLOBAL"])
    return float(lo), float(hi)


def classify_return(r: float, reg: str, thr: dict) -> int:
    q25, q75 = thr.get(reg, (0, 0))
    if r < q25:
        return 0
    if r < 0:
        return 1
    if r < q75:
        return 2
    return 3
