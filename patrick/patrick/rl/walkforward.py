"""Validation walk-forward du RL : entraîner sur le passé, évaluer sur la période suivante, avancer.

Plis en fenêtre élargie (tout le passé) ou glissante (`rolling_bars` dernières dates). Le premier pli teste après `min_train_frac` de
l'historique ; les `n_folds` blocs de test suivants se suivent sans trou ni recouvrement et leurs résultats sont recollés en UNE
courbe hors échantillon. Un pli n'entraîne que sur des dates dont le rendement suivant est connu AVANT son premier jour de test (un
jour d'écart) ; la sélection des variables et leur mise à l'échelle sont faites sur l'entraînement seul. La position tenue en fin de
pli est reportée au pli suivant (le passage coûte ce qu'il coûte).

Moteur 2 (ADR 0022) : la fin de chaque fenêtre d'entraînement (`val_frac`, un jour d'écart) n'est pas apprise. Elle sert à choisir le point
de contrôle de chaque agent (le meilleur score en validation, pas le dernier) et, avec `gate`, à décider du pli : si l'ensemble des agents ne
bat pas l'achat-conservation en validation (frais compris), le pli tient l'achat-conservation. Le score est la log-croissance annualisée au-delà
de l'achat-conservation, nette des vrais frais. Sélection des variables et mise à l'échelle n'utilisent que la partie apprise. La courbe de
l'agent sans repli (`agent_ungated`) reste publiée : on voit ce que le repli a évité ou coûté.
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
MIN_VAL_ROWS = 60              # en deçà, la validation d'un pli est abandonnée (le pli apprend sur toute sa fenêtre, sans repli)
MOMENTUM_WINDOW = 20
TREND_WINDOW = 200             # filtre de tendance : long quand le cours est au-dessus de sa moyenne des 200 dernières barres, sinon à plat
MAX_CURVE_POINTS = 1500
DELAY_ARMED_SHARPE = 1.0       # test du décalage d'un jour : armé quand le Sharpe BRUT hors échantillon dépasse ce seuil...
DELAY_KEEP_RATIO = 0.3         # ... et signalé quand décaler les positions d'une barre en garde moins de 30 %


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


def split_validation(n_train: int, s: RLSettings) -> int:
    """Nombre de lignes APPRISES d'une fenêtre d'entraînement de `n_train` lignes. La validation suit, après un jour d'écart (le rendement de
    la dernière ligne apprise est réalisé avant la première décision de validation) : lignes [n_fit + 1, n_train). Sans validation possible
    (`val_frac` nul, validation de moins de `MIN_VAL_ROWS` lignes ou partie apprise de moins de `MIN_TRAIN_ROWS`) : `n_train`."""
    if s.val_frac <= 0:
        return n_train
    n_val = round(n_train * float(s.val_frac))
    n_fit = n_train - n_val - 1
    if n_val < MIN_VAL_ROWS or n_fit < MIN_TRAIN_ROWS:
        return n_train
    return n_fit


def excess_score(net_returns: np.ndarray, asset_returns: np.ndarray) -> float:
    """Log-croissance annualisée au-delà de l'achat-conservation : moyenne de log(1 + net) − log(1 + rendement de l'actif), × 252. Positif =
    la stratégie a fait mieux que garder l'actif sur la période (frais compris)."""
    net = np.log1p(np.maximum(np.asarray(net_returns, dtype=float), -0.999))
    bh = np.log1p(np.maximum(np.asarray(asset_returns, dtype=float), -0.999))
    n = min(len(net), len(bh))
    return float(np.mean(net[:n] - bh[:n]) * rl_metrics.PERIODS) if n else float("nan")


def momentum_positions(price: pd.Series, rows: np.ndarray, settings: RLSettings) -> np.ndarray:
    """Position du momentum simple : signe du rendement des 20 dernières périodes (causal), au levier maximal."""
    back = price.shift(MOMENTUM_WINDOW)
    sig = np.sign((price / back - 1.0).to_numpy())
    sig = np.nan_to_num(sig[rows], nan=0.0)
    if not settings.allow_short:
        sig = np.maximum(sig, 0.0)
    return sig * settings.max_leverage


def trend_positions(price: pd.Series, rows: np.ndarray, settings: RLSettings) -> np.ndarray:
    """Filtre de tendance (règle classique, longue seulement) : investi quand le cours de la date dépasse sa moyenne des `TREND_WINDOW`
    dernières barres (causal : la moyenne de la date i ne lit que les cours jusqu'à i), à plat sinon et avant d'avoir 200 cours."""
    sma = price.rolling(TREND_WINDOW, min_periods=TREND_WINDOW).mean()
    sig = ((price > sma) & sma.notna()).to_numpy(dtype=float)
    return sig[rows] * settings.benchmark_position


def _net_from_positions(pos: np.ndarray, fwd: np.ndarray, fee: float, prev: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    costs = np.abs(np.diff(np.concatenate([[prev], pos]))) * fee
    return pos * fwd - costs, costs


def delay_test(positions: np.ndarray, asset_returns: np.ndarray) -> dict:
    """Sharpe BRUT (avant frais) des positions, puis des mêmes positions décalées d'une barre. Un vrai signal survit en partie au décalage ;
    une information du jour même (la fuite des barres de change du début de journée, ADR 0007) s'effondre : sur les runs du moteur 1, les
    devises passaient d'un Sharpe brut de 3,5 à environ 0, les indices de volatilité gardaient l'essentiel."""
    pos = np.asarray(positions, dtype=float)
    ret = np.asarray(asset_returns, dtype=float)
    gross = rl_metrics._sharpe(pos * ret)
    lagged = rl_metrics._sharpe(np.concatenate([[0.0], pos[:-1]]) * ret) if len(pos) else float("nan")
    suspect = bool(np.isfinite(gross) and gross >= DELAY_ARMED_SHARPE and (not np.isfinite(lagged) or lagged < DELAY_KEEP_RATIO * gross))
    return {"gross_sharpe": gross, "lagged_sharpe": lagged, "suspect": suspect}


def run_walkforward(data: rl_data.RLData, config: RLRunConfig, train_agent: Callable, policy_from_model: Callable,
                    ensemble_policy: Callable, progress: Callable[[str], None] = print, n_trials: int = 1,
                    on_model: Callable[[int, int, object], None] | None = None) -> dict:
    """Entraîne et évalue tous les plis. `train_agent(core, settings, seed, start, end, on_progress[, validate=])`, `policy_from_model` et
    `ensemble_policy` sont injectés (`rl/agents.py`) : les tests de la logique de plis n'ont besoin ni de PyTorch ni de SB3. `validate` n'est
    passé que si le pli a une validation."""
    s = config.rl
    folds = make_folds(data.n, s)
    fee = (s.cost_bps + s.slippage_bps) / 1e4
    every = int(s.rebalance_every)
    bench = s.benchmark_position
    base_seed = int(config.output.seed)
    n_seeds = int(s.n_seeds)
    total_fits = len(folds) * n_seeds
    done_fits = 0
    t0 = time.time()
    carry = [0.0] * (n_seeds + 2)      # position reportée : [stratégie, agent sans repli, graine 1, graine 2, ...]
    out_dates: list[pd.Timestamp] = []
    pos_all: list[np.ndarray] = []
    net_all: list[np.ndarray] = []
    cost_all: list[np.ndarray] = []
    agent_net: list[np.ndarray] = []
    agent_pos: list[np.ndarray] = []
    agent_cost: list[np.ndarray] = []
    controlled: list[np.ndarray] = []
    bh_net: list[np.ndarray] = []
    mom_net: list[np.ndarray] = []
    mom_pos: list[np.ndarray] = []
    trend_pos: list[np.ndarray] = []
    seed_net: dict[int, list[np.ndarray]] = {i: [] for i in range(n_seeds)}
    fold_rows: list[dict] = []
    mom_prev = 0.0
    feature_usage: dict[str, int] = {}
    price_by_row = data.price.reset_index(drop=True)
    progress(f"[RL-DATA] {data.n} dates ({data.dates[0]:%Y-%m-%d} -> {data.dates[-1]:%Y-%m-%d}), {data.features.shape[1]} variables causales, "
             f"{len(folds)} plis, une décision toutes les {every} barre(s)")
    progress(f"[RL-PROGRESS] 0/{total_fits}")

    for fold in folds:
        rows_train = np.arange(fold.train_lo, fold.train_hi)
        rows_all = np.arange(fold.train_lo, fold.test_hi)
        n_train = len(rows_train)
        n_fit = split_validation(n_train, s)
        has_val = n_fit < n_train
        rows_fit = rows_train[:n_fit]
        fit_frame = data.features.iloc[rows_fit]
        fwd_fit = data.fwd_ret[rows_fit]
        fwd_all = data.fwd_ret[rows_all]
        cols = rl_data.select_columns(fit_frame, fwd_fit, int(s.max_features), s.feature_selection)
        for c in cols:
            feature_usage[c] = feature_usage.get(c, 0) + 1
        x_fit, x_all = rl_data.scale_fold(fit_frame, data.features.iloc[rows_all], cols)
        sd = float(np.std(fwd_fit))
        reward_scale = 1.0 / sd if sd > 0 else 1.0
        core_train = TradingCore(x_fit, fwd_fit, s, reward_scale, fee_mult=float(s.train_cost_mult))
        core_eval = TradingCore(x_all, fwd_all, s, reward_scale)
        lo, hi = fold.test_lo - fold.train_lo, fold.test_hi - fold.train_lo
        val_lo, val_hi = n_fit + 1, n_train

        def score(policy, _core=core_eval, _lo=val_lo, _hi=val_hi, _fwd=fwd_all):
            one = rollout(_core, policy, _lo, _hi, 0.0, every)
            return excess_score(one["net_returns"], _fwd[_lo:_hi])

        val_text = (f", validation {data.dates[fold.train_lo + val_lo]:%Y-%m-%d} -> {data.dates[fold.train_hi - 1]:%Y-%m-%d} ({val_hi - val_lo} dates)"
                    if has_val else (", sans validation (fenêtre trop courte)" if s.val_frac > 0 else ""))
        progress(f"[RL-TRAIN] pli {fold.index + 1}/{len(folds)} : entraînement {data.dates[fold.train_lo]:%Y-%m-%d} -> "
                 f"{data.dates[fold.train_lo + n_fit - 1]:%Y-%m-%d} ({n_fit} dates, {len(cols)} variables){val_text}, "
                 f"test {data.dates[fold.test_lo]:%Y-%m-%d} -> {data.dates[fold.test_hi - 1]:%Y-%m-%d} ({fold.test_hi - fold.test_lo} dates)")

        policies, seed_val, best_steps = [], [], []
        for si in range(n_seeds):
            seed = base_seed + 100 * fold.index + si
            t_fit = time.time()
            if has_val:
                model = train_agent(core_train, s, seed, 0, n_fit, None, validate=score)
            else:
                model = train_agent(core_train, s, seed, 0, n_fit, None)
            policy = policy_from_model(model, s)
            policies.append(policy)
            info = getattr(model, "patrick_validation", None)
            best_steps.append(info.get("best_step") if isinstance(info, dict) else None)
            seed_val.append(score(policy) if has_val else None)
            if on_model is not None:
                on_model(fold.index, si, model)
            done_fits += 1
            progress(f"[RL-TRAIN] pli {fold.index + 1}/{len(folds)} graine {si + 1}/{n_seeds} : {time.time() - t_fit:.0f} s")
            progress(f"[RL-PROGRESS] {done_fits}/{total_fits}")

        agent = ensemble_policy(policies)
        val_score = score(agent) if has_val else None
        gated = bool(s.gate and has_val and not (val_score is not None and np.isfinite(val_score) and val_score > 0))
        verdict = ""
        if has_val:
            verdict = (f" ; validation {100 * val_score:+.1f} %/an contre l'achat-conservation"
                       + (" : repli sur l'achat-conservation" if gated else " : agent retenu"))
        progress(f"[RL-EVAL] pli {fold.index + 1}/{len(folds)} : évaluation déterministe sur {hi - lo} dates{verdict}")
        ens = rollout(core_eval, (lambda obs: bench) if gated else agent, lo, hi, carry[0], every)
        # L'agent sans repli : la même trajectoire quand il garde la main et part de la même position, sinon rejoué à part.
        raw = ens if not gated and carry[1] == carry[0] else rollout(core_eval, agent, lo, hi, carry[1], every)
        carry[0] = float(ens["positions"][-1])
        carry[1] = float(raw["positions"][-1])
        for si, policy in enumerate(policies):
            one = rollout(core_eval, policy, lo, hi, carry[si + 2], every)
            carry[si + 2] = float(one["positions"][-1])
            seed_net[si].append(one["net_returns"])
        test_rows = np.arange(fold.test_lo, fold.test_hi)
        fwd_test = data.fwd_ret[test_rows]
        mpos = momentum_positions(price_by_row, test_rows, s)
        mnet, _mc = _net_from_positions(mpos, fwd_test, fee, mom_prev)
        mom_prev = float(mpos[-1])
        out_dates.extend(data.dates[test_rows])
        pos_all.append(ens["positions"])
        net_all.append(ens["net_returns"])
        cost_all.append(ens["costs"])
        agent_net.append(raw["net_returns"])
        agent_pos.append(raw["positions"])
        agent_cost.append(raw["costs"])
        controlled.append(np.full(len(test_rows), not gated))
        bh_net.append(fwd_test.copy())
        mom_net.append(mnet)
        mom_pos.append(mpos)
        trend_pos.append(trend_positions(price_by_row, test_rows, s))
        dates_fold = pd.DatetimeIndex(data.dates[test_rows])
        fold_rows.append({
            "fold": fold.index + 1, "train_start": f"{data.dates[fold.train_lo]:%Y-%m-%d}", "train_end": f"{data.dates[fold.train_hi - 1]:%Y-%m-%d}",
            "fit_end": f"{data.dates[fold.train_lo + n_fit - 1]:%Y-%m-%d}",
            "val_start": f"{data.dates[fold.train_lo + val_lo]:%Y-%m-%d}" if has_val else None,
            "test_start": f"{data.dates[fold.test_lo]:%Y-%m-%d}", "test_end": f"{data.dates[fold.test_hi - 1]:%Y-%m-%d}",
            "n_train": n_train, "n_fit": n_fit, "n_val": (val_hi - val_lo) if has_val else 0, "n_test": len(test_rows), "features": cols,
            "val_score": val_score, "seed_val_scores": seed_val, "best_steps": best_steps, "gated": gated,
            "strategy": rl_metrics.summarize(ens["net_returns"], ens["positions"], ens["costs"], dates_fold),
            "agent": rl_metrics.summarize(raw["net_returns"], raw["positions"], raw["costs"], dates_fold),
            "buy_hold": rl_metrics.summarize(fwd_test, np.ones(len(fwd_test)), np.zeros(len(fwd_test)), dates_fold),
        })

    dates = pd.DatetimeIndex(out_dates)
    pos = np.concatenate(pos_all)
    net = np.concatenate(net_all)
    costs = np.concatenate(cost_all)
    bh = np.concatenate(bh_net)
    mom = np.concatenate(mom_net)
    mpos = np.concatenate(mom_pos)
    tpos = np.concatenate(trend_pos)
    flat = np.zeros(len(net))
    # Ruine : le compte vide reste vide sur toute la fenêtre hors échantillon (les plis suivants repartent chacun d'un capital neuf dans leur
    # propre résumé, mais la courbe recollée, le CSV et les tests statistiques voient une seule vie de compte).
    net, pos, costs, _ruin = rl_metrics.apply_ruin(net, pos, costs)
    a_net, a_pos, a_cost, _ = rl_metrics.apply_ruin(np.concatenate(agent_net), np.concatenate(agent_pos), np.concatenate(agent_cost))
    mom_costs = np.abs(np.diff(np.concatenate([[0.0], mpos]))) * fee
    mom, mpos, mom_costs, _ = rl_metrics.apply_ruin(mom, mpos, mom_costs)
    trend, trend_costs = _net_from_positions(tpos, bh, fee)
    strategy = rl_metrics.summarize(net, pos, costs, dates)
    control = np.concatenate(controlled)
    strategy["agent_share"] = float(control.mean()) if len(control) else float("nan")
    baselines = {
        "buy_hold": rl_metrics.summarize(bh, np.ones(len(bh)), np.zeros(len(bh)), dates),
        "momentum": rl_metrics.summarize(mom, mpos, mom_costs, dates),
        "trend": rl_metrics.summarize(trend, tpos, trend_costs, dates),
        "flat": rl_metrics.summarize(flat, flat, flat, dates),
    }
    seeds = []
    for si in range(n_seeds):
        sn = np.concatenate(seed_net[si])
        sn, _, _, seed_ruin = rl_metrics.apply_ruin(sn, np.zeros(len(sn)), np.zeros(len(sn)))
        seeds.append({"seed": si + 1, "sharpe": sim_metrics.sharpe_ratio(pd.Series(sn, index=dates)),
                      "total_return": float(rl_metrics.equity_curve(sn)[-1] - 1.0), "ruined": seed_ruin is not None})
    from patrick.validation.dsr import deflated_sharpe_ratio
    delay = delay_test(pos, bh)
    stats = {
        "vs_buy_hold": rl_metrics.bootstrap_sharpe_diff(net, bh, int(s.bootstrap_samples), seed=base_seed),
        "vs_momentum": rl_metrics.bootstrap_sharpe_diff(net, mom, int(s.bootstrap_samples), seed=base_seed + 1),
        "vs_trend": rl_metrics.bootstrap_sharpe_diff(net, trend, int(s.bootstrap_samples), seed=base_seed + 2),
        "psr": rl_metrics.probabilistic_sharpe(net),
        "dsr": deflated_sharpe_ratio(net, max(int(n_trials), 1)),
        "n_trials": int(n_trials),
        "delay": delay,
        "excess_log_growth": excess_score(net, bh),
    }
    diagnostics = []
    if delay["suspect"]:
        diagnostics.append(
            f"Le gain brut de la stratégie (Sharpe {delay['gross_sharpe']:.2f}) tombe à {delay['lagged_sharpe']:.2f} quand ses positions sont "
            "décalées d'un jour : il tient à une information du jour même, connue après la décision (fuite de date probable, comme les "
            "devises avant la correction de l'alignement). Ne pas s'y fier.")
    n_gated = sum(1 for f in fold_rows if f["gated"])
    if fold_rows and n_gated == len(fold_rows):
        diagnostics.append("L'agent n'a battu l'achat-conservation en validation dans aucun pli : la stratégie est l'achat-conservation (repli). "
                           "Rien d'exploitable sur cette cible avec ces réglages.")
    idx = np.unique(np.linspace(0, len(net) - 1, min(len(net), MAX_CURVE_POINTS)).astype(int))
    curves = {
        "dates": [f"{dates[i]:%Y-%m-%d}" for i in idx],
        "strategy": rl_metrics.equity_curve(net)[idx].tolist(), "buy_hold": rl_metrics.equity_curve(bh)[idx].tolist(),
        "momentum": rl_metrics.equity_curve(mom)[idx].tolist(), "trend": rl_metrics.equity_curve(trend)[idx].tolist(),
        "agent": rl_metrics.equity_curve(a_net)[idx].tolist(), "position": pos[idx].tolist(),
    }
    return {"folds": fold_rows, "strategy": strategy, "agent_ungated": rl_metrics.summarize(a_net, a_pos, a_cost, dates),
            "baselines": baselines, "seeds": seeds, "stats": stats, "curves": curves, "diagnostics": diagnostics,
            "oos": {"dates": dates, "position": pos, "net": net, "cost": costs, "buy_hold": bh, "momentum": mom, "trend": trend,
                    "agent_position": a_pos, "agent_net": a_net, "agent_controls": control},
            "feature_usage": sorted(feature_usage.items(), key=lambda kv: -kv[1])[:30], "elapsed_s": time.time() - t0, "n_folds": len(folds)}
