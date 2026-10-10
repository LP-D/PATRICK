"""Validation walk-forward du RL : entraîner sur le passé, évaluer sur la période suivante, avancer.

Plis en fenêtre élargie (tout le passé) ou glissante (`rolling_bars` dernières dates). Le premier pli teste après `min_train_frac` de
l'historique ; les `n_folds` blocs de test suivants se suivent sans trou ni recouvrement et leurs résultats sont recollés en UNE
courbe hors échantillon. Un pli n'entraîne que sur des dates dont le rendement suivant est connu AVANT son premier jour de test (un
jour d'écart) ; la sélection des variables et leur mise à l'échelle sont faites sur l'entraînement seul. La position tenue en fin de
pli est reportée au pli suivant (le passage coûte ce qu'il coûte).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.rl import data as rl_data
from patrick.rl import metrics as rl_metrics
from patrick.rl.config import RLRunConfig, RLSettings
from patrick.rl.core import TradingCore, rollout
from patrick.simulate import metrics as sim_metrics

MIN_TRAIN_ROWS = 250
MIN_TEST_ROWS = 20
MOMENTUM_WINDOW = 20
MAX_CURVE_POINTS = 1500


@dataclass(frozen=True)
class Fold:
    index: int
    train_lo: int            # première ligne d'entraînement
    train_hi: int            # fin (exclue) des lignes d'entraînement : dernière décision d'entraînement = train_hi − 1
    test_lo: int
    test_hi: int             # exclue


def make_folds(n_rows: int, s: RLSettings) -> list[Fold]:
    first_test = int(n_rows * s.min_train_frac)
    if first_test < MIN_TRAIN_ROWS + 1:
        raise rl_data.RLDataError(f"Historique trop court pour entraîner : {first_test} lignes avant le premier test (minimum {MIN_TRAIN_ROWS}).")
    remaining = n_rows - first_test
    k = max(1, min(int(s.n_folds), remaining // MIN_TEST_ROWS))
    block = remaining // k
    folds = []
    for i in range(k):
        test_lo = first_test + i * block
        test_hi = n_rows if i == k - 1 else test_lo + block
        train_lo = 0 if s.retrain == "expanding" else max(0, test_lo - int(s.rolling_bars))
        folds.append(Fold(i, train_lo, test_lo - 1, test_lo, test_hi))
    return folds


def momentum_positions(price: pd.Series, rows: np.ndarray, settings: RLSettings) -> np.ndarray:
    """Position du momentum simple : signe du rendement des 20 dernières périodes (causal), au levier maximal."""
    back = price.shift(MOMENTUM_WINDOW)
    sig = np.sign((price / back - 1.0).to_numpy())
    sig = np.nan_to_num(sig[rows], nan=0.0)
    if not settings.allow_short:
        sig = np.maximum(sig, 0.0)
    return sig * settings.max_leverage


def _net_from_positions(pos: np.ndarray, fwd: np.ndarray, fee: float, prev: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    costs = np.abs(np.diff(np.concatenate([[prev], pos]))) * fee
    return pos * fwd - costs, costs


def downsample(values: np.ndarray, limit: int = MAX_CURVE_POINTS) -> np.ndarray:
    if len(values) <= limit:
        return values
    idx = np.unique(np.linspace(0, len(values) - 1, limit).astype(int))
    return values[idx]


def run_walkforward(data: rl_data.RLData, config: RLRunConfig, train_agent: Callable, policy_from_model: Callable,
                    ensemble_policy: Callable, progress: Callable[[str], None] = print, n_trials: int = 1,
                    on_model: Callable[[int, int, object], None] | None = None) -> dict:
    """Entraîne et évalue tous les plis. `train_agent(core, settings, seed, start, end, on_progress)`, `policy_from_model` et
    `ensemble_policy` sont injectés (`rl/agents.py`) : les tests de la logique de plis n'ont besoin ni de PyTorch ni de SB3."""
    s = config.rl
    folds = make_folds(data.n, s)
    fee = (s.cost_bps + s.slippage_bps) / 1e4
    base_seed = int(config.output.seed)
    total_fits = len(folds) * int(s.n_seeds)
    done_fits = 0
    t0 = time.time()
    carry = [0.0] * (int(s.n_seeds) + 1)      # position reportée : [ensemble, graine 1, graine 2, ...]
    out_dates: list[pd.Timestamp] = []
    pos_all: list[np.ndarray] = []
    net_all: list[np.ndarray] = []
    cost_all: list[np.ndarray] = []
    bh_net: list[np.ndarray] = []
    mom_net: list[np.ndarray] = []
    mom_pos: list[np.ndarray] = []
    seed_net: dict[int, list[np.ndarray]] = {i: [] for i in range(int(s.n_seeds))}
    fold_rows: list[dict] = []
    mom_prev = 0.0
    feature_usage: dict[str, int] = {}
    progress(f"[RL-DATA] {data.n} dates ({data.dates[0]:%Y-%m-%d} -> {data.dates[-1]:%Y-%m-%d}), {data.features.shape[1]} variables causales, {len(folds)} plis")
    progress(f"[RL-PROGRESS] 0/{total_fits}")

    for fold in folds:
        rows_train = np.arange(fold.train_lo, fold.train_hi)
        rows_all = np.arange(fold.train_lo, fold.test_hi)
        train_frame = data.features.iloc[rows_train]
        fwd_train = data.fwd_ret[rows_train]
        cols = rl_data.select_columns(train_frame, fwd_train, int(s.max_features), s.feature_selection)
        for c in cols:
            feature_usage[c] = feature_usage.get(c, 0) + 1
        x_train, x_all = rl_data.scale_fold(train_frame, data.features.iloc[rows_all], cols)
        sd = float(np.std(fwd_train))
        reward_scale = 1.0 / sd if sd > 0 else 1.0
        core_train = TradingCore(x_train, fwd_train, s, reward_scale)
        core_eval = TradingCore(x_all, data.fwd_ret[rows_all], s, reward_scale)
        lo, hi = fold.test_lo - fold.train_lo, fold.test_hi - fold.train_lo
        progress(f"[RL-TRAIN] pli {fold.index + 1}/{len(folds)} : entraînement {data.dates[fold.train_lo]:%Y-%m-%d} -> "
                 f"{data.dates[fold.train_hi - 1]:%Y-%m-%d} ({len(rows_train)} dates, {len(cols)} variables), "
                 f"test {data.dates[fold.test_lo]:%Y-%m-%d} -> {data.dates[fold.test_hi - 1]:%Y-%m-%d} ({fold.test_hi - fold.test_lo} dates)")

        policies = []
        for si in range(int(s.n_seeds)):
            seed = base_seed + 100 * fold.index + si
            t_fit = time.time()
            model = train_agent(core_train, s, seed, 0, len(rows_train), None)
            policies.append(policy_from_model(model, s))
            if on_model is not None:
                on_model(fold.index, si, model)
            done_fits += 1
            progress(f"[RL-TRAIN] pli {fold.index + 1}/{len(folds)} graine {si + 1}/{s.n_seeds} : {time.time() - t_fit:.0f} s")
            progress(f"[RL-PROGRESS] {done_fits}/{total_fits}")

        progress(f"[RL-EVAL] pli {fold.index + 1}/{len(folds)} : évaluation déterministe sur {hi - lo} dates")
        ens = rollout(core_eval, ensemble_policy(policies), lo, hi, carry[0])
        carry[0] = float(ens["positions"][-1])
        for si, policy in enumerate(policies):
            one = rollout(core_eval, policy, lo, hi, carry[si + 1])
            carry[si + 1] = float(one["positions"][-1])
            seed_net[si].append(one["net_returns"])
        test_rows = np.arange(fold.test_lo, fold.test_hi)
        fwd_test = data.fwd_ret[test_rows]
        mpos = momentum_positions(data.price.reset_index(drop=True), test_rows, s)
        mnet, _mc = _net_from_positions(mpos, fwd_test, fee, mom_prev)
        mom_prev = float(mpos[-1])
        out_dates.extend(data.dates[test_rows])
        pos_all.append(ens["positions"])
        net_all.append(ens["net_returns"])
        cost_all.append(ens["costs"])
        bh_net.append(fwd_test.copy())
        mom_net.append(mnet)
        mom_pos.append(mpos)
        dates_fold = pd.DatetimeIndex(data.dates[test_rows])
        fold_rows.append({
            "fold": fold.index + 1, "train_start": f"{data.dates[fold.train_lo]:%Y-%m-%d}", "train_end": f"{data.dates[fold.train_hi - 1]:%Y-%m-%d}",
            "test_start": f"{data.dates[fold.test_lo]:%Y-%m-%d}", "test_end": f"{data.dates[fold.test_hi - 1]:%Y-%m-%d}",
            "n_train": int(len(rows_train)), "n_test": int(len(test_rows)), "features": cols,
            "strategy": rl_metrics.summarize(ens["net_returns"], ens["positions"], ens["costs"], dates_fold),
            "buy_hold": rl_metrics.summarize(fwd_test, np.ones(len(fwd_test)), np.zeros(len(fwd_test)), dates_fold),
        })

    dates = pd.DatetimeIndex(out_dates)
    pos = np.concatenate(pos_all)
    net = np.concatenate(net_all)
    costs = np.concatenate(cost_all)
    bh = np.concatenate(bh_net)
    mom = np.concatenate(mom_net)
    mpos = np.concatenate(mom_pos)
    flat = np.zeros(len(net))
    strategy = rl_metrics.summarize(net, pos, costs, dates)
    baselines = {
        "buy_hold": rl_metrics.summarize(bh, np.ones(len(bh)), np.zeros(len(bh)), dates),
        "momentum": rl_metrics.summarize(mom, mpos, np.abs(np.diff(np.concatenate([[0.0], mpos]))) * fee, dates),
        "flat": rl_metrics.summarize(flat, flat, flat, dates),
    }
    seeds = []
    for si in range(int(s.n_seeds)):
        sn = np.concatenate(seed_net[si])
        seeds.append({"seed": si + 1, "sharpe": sim_metrics.sharpe_ratio(pd.Series(sn, index=dates)),
                      "total_return": float(rl_metrics.equity_curve(sn)[-1] - 1.0)})
    from patrick.validation.dsr import deflated_sharpe_ratio
    stats = {
        "vs_buy_hold": rl_metrics.bootstrap_sharpe_diff(net, bh, int(s.bootstrap_samples), seed=base_seed),
        "vs_momentum": rl_metrics.bootstrap_sharpe_diff(net, mom, int(s.bootstrap_samples), seed=base_seed + 1),
        "psr": rl_metrics.probabilistic_sharpe(net),
        "dsr": deflated_sharpe_ratio(net, max(int(n_trials), 1)),
        "n_trials": int(n_trials),
    }
    idx = np.unique(np.linspace(0, len(net) - 1, min(len(net), MAX_CURVE_POINTS)).astype(int))
    curves = {
        "dates": [f"{dates[i]:%Y-%m-%d}" for i in idx],
        "strategy": rl_metrics.equity_curve(net)[idx].tolist(), "buy_hold": rl_metrics.equity_curve(bh)[idx].tolist(),
        "momentum": rl_metrics.equity_curve(mom)[idx].tolist(), "position": pos[idx].tolist(),
    }
    return {"folds": fold_rows, "strategy": strategy, "baselines": baselines, "seeds": seeds, "stats": stats, "curves": curves,
            "oos": {"dates": dates, "position": pos, "net": net, "cost": costs, "buy_hold": bh, "momentum": mom},
            "feature_usage": sorted(feature_usage.items(), key=lambda kv: -kv[1])[:30], "elapsed_s": time.time() - t0, "n_folds": len(folds)}
