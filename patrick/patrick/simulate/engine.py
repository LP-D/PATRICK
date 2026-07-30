"""Simulateur d'investissement (Phase 4) -- v1 mono-actif.

Contraintes non négociables du plan, appliquées ici :
- ne RÉ-EXÉCUTE JAMAIS un modèle : lit uniquement `prediction` (split test/
  holdout/live) + la donnée brute immuable du snapshot associé au run (pour
  calculer le rendement réalisé de l'actif sous-jacent -- un chargement de
  données, pas une inférence).
- timing d'exécution explicite (rapport de correction, C6 -- remplace la
  convention `open_next` du plan de phase 4, jamais implémentable ici : le
  simulateur ne modélise qu'une série de clôtures close-to-close, pas
  d'open/high/low par actif) : seul `execution_lag_bars` pilote le timing, et
  c'est tout ce qu'il fait. Convention réelle (`_build_exposure`) : le signal
  est connu à la clôture du jour `t` ; l'exposition démarre à la ligne
  `t + execution_lag_bars` de la grille quotidienne ; comme
  `underlying_ret[i] = close[i]/close[i-1] - 1` (le rendement qui SE TERMINE
  au jour i), le PREMIER rendement capté est celui de `t+lag-1` à `t+lag`.
  Avec le minimum imposé `execution_lag_bars=1`, ce premier rendement capté
  est donc exactement celui de `t` à `t+1` -- le mouvement qui suit
  immédiatement la clôture du signal, sans latence réelle supplémentaire.
  `execution_lag_bars=0` est structurellement interdit (`SimParams.
  __post_init__`, anti-pattern #5 du plan) : il ferait capter le rendement de
  `t-1` à `t`, déjà connu au moment où le signal est calculé, donc du
  look-ahead pur. Revisite F.2 (rapport d'audit, "lag=0 donne un Sharpe plus
  bas que lag=1", non résolu) : un signal oracle (prédiction parfaite du
  mouvement `t`->`t+1`) confirme que ce n'est PAS un bug d'alignement --
  lag=1 capte exactement ce que l'oracle prédit (Sharpe ~6, quasi parfait sur
  série synthétique), lag=0/2/3 captent un rendement sans rapport avec la
  prédiction (Sharpe proche de 0, jamais négatif ni anormal). `_build_exposure`
  fonctionne comme attendu ; script de diagnostic non conservé dans le dépôt
  (mesure ponctuelle, comme D2).
- horizons chevauchants explicitement résolus : `overlap_mode` "tranches"
  (moyenne des signaux actifs, par défaut) ou "renewed" (position unique
  renouvelée), jamais un choix implicite.

`y_proba` en base est la confiance du modèle dans SA classe prédite (top-1,
4 classes DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT -- cf. features/target.py),
pas directement P(hausse). Choix documenté (détail mineur laissé à mon
appréciation, cf. rapport de phase) : `_directional_score` la convertit en un
score dans [0,1] façon "P(hausse)" en retournant la confiance quand la classe
prédite est haussière, et son complément sinon.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.simulate import metrics as simmetrics
from patrick.tracking import db as trackdb
from patrick.validation.dsr import deflated_sharpe_ratio

_UP_CLASSES = (2, 3)
_DOWN_CLASSES = (0, 1)

ASSET_CLASS_FRICTION_BPS = {
    "futures_liquid": 1.0,
    "us_large_cap": 3.0,
    "eu_mid_cap": 15.0,
    "crypto_non_major": 30.0,
}


@dataclass
class SimParams:
    position_mode: str = "threshold"  # threshold | proportional | kelly
    threshold: float = 0.55
    kelly_fraction: float = 0.5
    max_leverage: float = 1.0
    max_position: float = 1.0
    short_allowed: bool = True
    execution_lag_bars: int = 1
    overlap_mode: str = "tranches"  # tranches | renewed
    spread_bps: float = 0.0
    commission_bps: float = 0.0
    carry_bps_per_year: float = 0.0
    asset_class: str | None = None  # si fourni, préremplit spread+commission (cf. ASSET_CLASS_FRICTION_BPS)

    def __post_init__(self) -> None:
        if self.execution_lag_bars < 1:
            raise ValueError("execution_lag_bars doit être >= 1 : exécuter sur la bougie du "
                              "signal (anti-pattern #5 du plan) est structurellement interdit.")
        if self.asset_class and self.asset_class in ASSET_CLASS_FRICTION_BPS:
            total = ASSET_CLASS_FRICTION_BPS[self.asset_class]
            if self.spread_bps == 0.0 and self.commission_bps == 0.0:
                self.spread_bps, self.commission_bps = total / 2, total / 2

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _directional_score(y_pred: np.ndarray, y_proba: np.ndarray) -> np.ndarray:
    up = np.isin(y_pred, _UP_CLASSES)
    score = np.where(up, y_proba, 1.0 - y_proba)
    return np.nan_to_num(score, nan=0.5)


def _position_from_score(score: np.ndarray, params: SimParams) -> np.ndarray:
    if params.position_mode == "threshold":
        pos = np.zeros_like(score)
        pos[score >= params.threshold] = 1.0
        pos[score <= 1 - params.threshold] = -1.0
    elif params.position_mode == "proportional":
        pos = np.clip((score - 0.5) * 2, -1.0, 1.0)
    elif params.position_mode == "kelly":
        pos = params.kelly_fraction * (2 * score - 1)
    else:
        raise ValueError(f"position_mode inconnu : {params.position_mode}")

    pos = pos * params.max_leverage
    if not params.short_allowed:
        pos = np.clip(pos, 0.0, params.max_position)
    else:
        pos = np.clip(pos, -params.max_position, params.max_position)
    return pos


def _brier_score(y_true_binary: np.ndarray, score: np.ndarray) -> float:
    return float(np.mean((score - y_true_binary) ** 2))


def check_kelly_available(conn: sqlite3.Connection, trial_id: int, min_obs: int = 30) -> tuple[bool, str]:
    """Le Kelly fractionnaire n'est activable QUE si une courbe de calibration
    (proxy ici : un score de Brier meilleur qu'un tirage au sort sur le
    problème binarisé, 0.25) existe sur le fold de test -- sinon désactivé
    avec un message explicatif (Phase 4.1), jamais silencieusement approximé."""
    rows = conn.execute(
        "SELECT y_pred, y_proba, y_true FROM prediction "
        "WHERE trial_id = ? AND split = 'test' AND y_proba IS NOT NULL AND y_true IS NOT NULL",
        (trial_id,),
    ).fetchall()
    if len(rows) < min_obs:
        return False, f"Kelly désactivé : seulement {len(rows)} observations de test avec proba (min {min_obs})."
    y_pred = np.array([r[0] for r in rows])
    y_proba = np.array([r[1] for r in rows])
    y_true = np.array([r[2] for r in rows])
    score = _directional_score(y_pred, y_proba)
    y_true_binary = np.isin(y_true, _UP_CLASSES).astype(float)
    brier = _brier_score(y_true_binary, score)
    if brier >= 0.25:
        return False, f"Kelly désactivé : score de Brier {brier:.3f} >= 0.25 (pas mieux qu'un tirage au sort)."
    return True, f"Kelly activé (score de Brier {brier:.3f} sur {len(rows)} obs. de test)."


def _load_predictions(conn: sqlite3.Connection, trial_id: int) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT ts, y_pred, y_proba FROM prediction "
        "WHERE trial_id = ? AND split IN ('test', 'holdout', 'live') AND y_proba IS NOT NULL "
        "ORDER BY ts",
        (trial_id,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["ts", "y_pred", "y_proba"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _build_exposure(signal_dates: pd.DatetimeIndex, target_pos: np.ndarray,
                     daily_index: pd.DatetimeIndex, horizon: int, params: SimParams) -> pd.Series:
    """Place chaque signal sur la grille quotidienne à `entry_idx = position du
    signal + execution_lag_bars` (jamais avant, cf. `SimParams.__post_init__`) ;
    le premier rendement capté à cette entrée est `underlying_ret[entry_idx]`,
    c.-à-d. le rendement close-to-close de `entry_idx-1` à `entry_idx` (cf.
    convention détaillée, docstring de module, rapport de correction C6) --
    puis résout les horizons chevauchants (Phase 4, contrainte non
    négociable) : "tranches" moyenne les signaux actifs sur [entry, entry+H),
    "renewed" fait tenir le dernier signal jusqu'au suivant."""
    n = len(daily_index)
    date_to_idx = {d: i for i, d in enumerate(daily_index)}
    entry_idxs = []
    for d in signal_dates:
        pos_in_index = daily_index.searchsorted(d)
        entry_idx = pos_in_index + params.execution_lag_bars
        entry_idxs.append(entry_idx if entry_idx < n else None)

    if params.overlap_mode == "tranches":
        accum = np.zeros(n)
        count = np.zeros(n)
        for entry_idx, pos in zip(entry_idxs, target_pos):
            if entry_idx is None:
                continue
            end_idx = min(entry_idx + horizon, n)
            accum[entry_idx:end_idx] += pos
            count[entry_idx:end_idx] += 1
        exposure = np.divide(accum, count, out=np.zeros(n), where=count > 0)
    elif params.overlap_mode == "renewed":
        sparse = pd.Series(np.nan, index=daily_index)
        for entry_idx, pos in zip(entry_idxs, target_pos):
            if entry_idx is not None:
                sparse.iloc[entry_idx] = pos
        exposure = sparse.ffill().fillna(0.0).values
    else:
        raise ValueError(f"overlap_mode inconnu : {params.overlap_mode}")

    return pd.Series(exposure, index=daily_index)


def solve_break_even_cost_bps(gross_returns: pd.Series, turnover: pd.Series,
                               hard_ceiling_bps: float = 1000.0) -> float:
    """Coût (spread+commission) par unité de turnover, en bps, qui ramène le
    rendement total COMPOSÉ à zéro. `gross_returns` : rendement par période
    net du carry mais avant coût de transaction (`exposure * underlying_ret -
    carry_cost`). `turnover` : |Δexposition| par période, alignée sur
    `gross_returns`.

    Résolution numérique (`brentq`), pas une division linéaire : les coûts de
    transaction s'appliquent période par période sur une équité qui COMPOSE
    (`cumprod`), donc `retour_brut_total / turnover_total` sous-estime
    fortement le coût réel dès que la position est maintenue sur plusieurs
    périodes (cf. rapport d'audit, section F.3 -- réconciliation exacte
    vérifiée par `tests/test_simulate.py::test_break_even_cost_reconciles_...`).
    """
    total_turnover = float(turnover.sum())
    if total_turnover <= 1e-9:
        return float("nan")

    gross_arr = gross_returns.values
    turn_arr = turnover.values

    def net_total_return(c: float) -> float:
        # Clip à 1e-9 (pas 0/négatif) : une fois l'équité "en faillite" sur une
        # période, un coût plus élevé ne peut pas creuser davantage un facteur
        # déjà nul -- sans ce clip, `cumprod` pourrait changer de signe et
        # casser la monotonie décroissante que `brentq` suppose.
        factors = np.clip(1.0 + gross_arr - turn_arr * c, 1e-9, None)
        return float(np.prod(factors) - 1.0)

    gross_total_return = net_total_return(0.0)
    if gross_total_return <= 0.0:
        return 0.0

    hard_ceiling = hard_ceiling_bps / 10000.0
    c_hi = 1e-4  # 1 bp en décimal
    while net_total_return(c_hi) > 0.0 and c_hi < hard_ceiling:
        c_hi *= 2
    c_hi = min(c_hi, hard_ceiling)

    if net_total_return(c_hi) > 0.0:
        warnings.warn(
            f"break_even_cost_bps : rendement encore positif au plafond dur de "
            f"{hard_ceiling_bps:.0f} bps -- pas de changement de signe trouvé, "
            "coût de rentabilité indéterminé.", stacklevel=2)
        return float("nan")

    c_star = brentq(net_total_return, 0.0, c_hi, xtol=1e-14, rtol=1e-12)
    return c_star * 10000.0


def simulate(trial_id: int, params: SimParams, db_path: str | None = None,
             store_root: str | None = None) -> dict:
    conn = trackdb.connect(db_path)
    try:
        trial_row = conn.execute(
            "SELECT run_id FROM trial WHERE trial_id = ?", (trial_id,)).fetchone()
        if trial_row is None:
            raise ValueError(f"Trial introuvable : {trial_id}")
        run = trackdb.get_run(conn, trial_row[0])
        if run is None:
            raise ValueError(f"Run introuvable pour trial {trial_id}")

        kelly_ok, kelly_message = (True, None)
        if params.position_mode == "kelly":
            kelly_ok, kelly_message = check_kelly_available(conn, trial_id)
            if not kelly_ok:
                return {"ok": False, "message": kelly_message, "params": params.to_dict()}

        pred_df = _load_predictions(conn, trial_id)
        if len(pred_df) < 10:
            return {"ok": False, "message": "Pas assez de prédictions (test/holdout/live) pour simuler "
                                             f"(trouvé {len(pred_df)}, minimum 10).", "params": params.to_dict()}

        store = DataStore(root=store_root) if store_root else DataStore()
        raw = store.load(f"raw_{run['target']}", snapshot_id=run["snapshot_id"])
        target_col = clean_symbol(run["target"])
        underlying = raw[target_col].ffill().dropna()

        daily_index = underlying.index[
            (underlying.index >= pred_df["ts"].min()) & (underlying.index <= underlying.index[-1])]
        underlying = underlying.reindex(daily_index)
        underlying_ret = underlying.pct_change().fillna(0.0)

        score = _directional_score(pred_df["y_pred"].values, pred_df["y_proba"].values)
        target_pos = _position_from_score(score, params)
        exposure = _build_exposure(pred_df["ts"], target_pos, daily_index, run["horizon"], params)

        turnover = exposure.diff().abs().fillna(exposure.abs())
        trading_cost = turnover * (params.spread_bps + params.commission_bps) / 10000.0
        carry_cost = exposure.abs() * (params.carry_bps_per_year / 10000.0) / simmetrics.TRADING_DAYS_PER_YEAR
        strategy_returns = exposure * underlying_ret - trading_cost - carry_cost
        gross_returns = exposure * underlying_ret - carry_cost

        equity = (1 + strategy_returns).cumprod()
        gross_equity = (1 + gross_returns).cumprod()
        bh_equity = (1 + underlying_ret).cumprod()

        strat_summary = simmetrics.performance_summary(equity, strategy_returns, exposure)
        bh_exposure = pd.Series(1.0, index=daily_index)
        bh_summary = simmetrics.performance_summary(bh_equity, underlying_ret, bh_exposure)

        annual_turnover = float(turnover.sum() / max(len(daily_index) / simmetrics.TRADING_DAYS_PER_YEAR, 1e-9))

        # Rendements "par trade" : un trade = un segment d'exposition non nulle
        # continue (entrée -> sortie), rendement composé sur ce segment.
        trade_returns = _trade_returns(exposure, strategy_returns)
        strat_summary["turnover_annualized"] = annual_turnover
        strat_summary["hit_rate"] = simmetrics.hit_rate(trade_returns)
        strat_summary["profit_factor"] = simmetrics.profit_factor(trade_returns)

        break_even_bps = solve_break_even_cost_bps(gross_returns, turnover)
        strat_summary["break_even_cost_bps"] = break_even_bps

        n_configs = count_simulations_for_target(conn, run["target"])
        dsr = deflated_sharpe_ratio(strategy_returns.values, n_trials=max(n_configs, 1))
        strat_summary["deflated_sharpe"] = dsr["dsr"]
        strat_summary["sharpe_p_value"] = dsr["p_value"]

        result = {
            "ok": True,
            "message": kelly_message,
            "params": params.to_dict(),
            "n_days": len(daily_index),
            "n_signals": len(pred_df),
            "strategy": strat_summary,
            "buy_and_hold": bh_summary,
            "n_simulation_configs_on_target": n_configs + 1,  # +1 : celle-ci compte aussi
            "equity_curve": _series_to_points(equity),
            "buy_and_hold_curve": _series_to_points(bh_equity),
            "drawdown_curve": _series_to_points(equity / equity.cummax() - 1),
            "trade_returns": [round(float(r), 6) for r in trade_returns],
        }
        return _to_json_safe(result)
    finally:
        conn.close()


def _to_json_safe(obj):
    """NaN/Inf -> None : `json.dumps` les accepte par défaut (`allow_nan=True`,
    extension non standard) mais `JSON.parse` côté navigateur les rejette --
    des métriques indéfinies (ex. Sharpe sur trop peu d'observations) ne
    doivent jamais faire planter le rendu de la page, juste s'afficher "—"."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    if isinstance(obj, np.generic):
        return _to_json_safe(obj.item())
    return obj


def _trade_returns(exposure: pd.Series, strategy_returns: pd.Series) -> pd.Series:
    is_open = exposure.abs() > 1e-9
    segment_id = (is_open != is_open.shift(1)).cumsum()
    out = []
    for seg, group in strategy_returns.groupby(segment_id):
        if not is_open.loc[group.index[0]]:
            continue
        out.append(float((1 + group).prod() - 1))
    return pd.Series(out)


def _series_to_points(s: pd.Series) -> list[dict]:
    return [{"t": ts.strftime("%Y-%m-%d"), "v": None if pd.isna(v) else round(float(v), 6)}
            for ts, v in s.items()]


def save_simulation(conn: sqlite3.Connection, trial_id: int, params: SimParams, result: dict) -> str:
    simulation_id = uuid.uuid4().hex[:12]
    with conn:
        conn.execute(
            "INSERT INTO simulation (simulation_id, trial_id, params_json, metrics_json, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (simulation_id, trial_id, json.dumps(params.to_dict()),
             json.dumps(result) if result.get("ok") else None,
             None if result.get("ok") else result.get("message")),
        )
    return simulation_id


def count_simulations_for_target(conn: sqlite3.Connection, target: str) -> int:
    """Nombre de simulations déjà enregistrées sur cette cible, tout run/trial
    confondu (Phase 4.5, garde-fou anti-surapprentissage) -- symétrique à
    `tracking.stats.count_cumulative_trials`."""
    row = conn.execute(
        "SELECT COUNT(*) FROM simulation "
        "JOIN trial ON simulation.trial_id = trial.trial_id "
        "JOIN run ON trial.run_id = run.run_id "
        "WHERE run.target = ?",
        (target,),
    ).fetchone()
    return int(row[0]) if row else 0
