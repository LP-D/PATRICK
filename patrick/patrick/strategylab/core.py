"""Cœur du laboratoire : rendement de chaque événement pour chaque jour de sortie, et évaluation honnête de la règle.

Pour un événement dont le jour 0 est la première séance concernée (`event_day_zero`) et un jour de sortie k = 1..K :
- `close_prev` : achat à la clôture de la séance PRÉCÉDANT le jour 0, vente à la clôture k séances plus tard (k = 1 : clôture du jour 0) ;
- `open_day0`  : achat à l'ouverture du jour 0, vente à la clôture du jour k - 1 (k = 1 : le soir même) ;
- `close_day0` : achat à la clôture du jour 0, vente à la clôture k séances plus tard ;
- `price`      : achat au prix imposé de l'événement (prix d'offre d'une IPO), vente à la clôture du jour k - 1 (k = 1 : première clôture).
Les frais (`cost_bps`, aller-retour) sont retirés de chaque rendement.

Évaluation (fonctions pures sur la matrice `événements x jours`) : courbe moyenne / médiane / taux de gain / P5-P95 par jour de sortie ; intervalle
bootstrap de la moyenne et STABILITÉ du meilleur jour (à quelle fréquence il reste le meilleur quand on rééchantillonne les événements) ; validation
chronologique (le jour choisi sur les événements anciens tient-il sur les récents ?) ; courbe de capital à mise fixe ; concentration (un titre, une
année, quelques coups d'éclat) ; Monte Carlo d'une campagne de transactions.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.research.event_study import event_day_zero

ENTRIES = ("close_prev", "open_day0", "close_day0", "price")
MAX_K = 60
MIN_COMPLETE = 10
NEAR_DAYS = 7            # entrée au prix imposé : le jour 0 doit tomber à moins de 7 jours de l'événement (cours qui commencent à la cotation)


class StrategyError(ValueError):
    """Étude impossible avec ces données : le message (en français) dit quoi corriger."""


@dataclass
class EventParams:
    entry: str = "close_prev"
    max_exit: int = 20
    cost_bps: float = 10.0
    split_frac: float = 0.7
    n_boot: int = 2000
    seed: int = 42
    stake: float = 10_000.0
    history_days: int = 40

    def validate(self) -> None:
        if self.entry not in ENTRIES:
            raise StrategyError("Mode d'entrée inconnu.")
        if not 1 <= self.max_exit <= MAX_K:
            raise StrategyError(f"Le jour de sortie maximal doit être compris entre 1 et {MAX_K}.")
        if not 0 <= self.cost_bps <= 500:
            raise StrategyError("Les frais aller-retour doivent être compris entre 0 et 500 points de base.")
        if not 0.3 <= self.split_frac <= 0.9:
            raise StrategyError("La part d'événements anciens doit être comprise entre 30 % et 90 %.")
        if not 200 <= self.n_boot <= 20_000:
            raise StrategyError("Le nombre de rééchantillonnages doit être compris entre 200 et 20 000.")
        if not 0 < self.stake < 1e9:
            raise StrategyError("La mise doit être strictement positive.")


# ------------------------------------------------------------------ construction de la matrice
def build_returns(events: pd.DataFrame, source, params: EventParams, progress: Callable[[float, str], None] | None = None) -> tuple[pd.DataFrame, dict]:
    """`(table, écartés)` : une ligne par événement retenu (`symbol`, `day0`, `group`, `entry_px`, `k1`..`kK`), les rendements manquants (séances pas encore
    écoulées) restant NaN. `écartés` : `{motif: nombre}`."""
    say = progress or (lambda _f, _m: None)
    skipped: dict[str, int] = {}
    rows = []
    K = params.max_exit
    symbols = list(events["symbol"].unique())
    for n, symbol in enumerate(symbols):
        say(0.05 + 0.60 * n / max(1, len(symbols)), f"Cours de {symbol} ({n + 1}/{len(symbols)})")
        sub = events[events["symbol"] == symbol]
        start = (sub["at"].min() - pd.Timedelta(days=params.history_days + 10)).strftime("%Y-%m-%d")
        px = source.ohlc(symbol, start)
        if px is None or px.empty:
            skipped["cours introuvables"] = skipped.get("cours introuvables", 0) + len(sub)
            continue
        days = px.index
        opens, closes = px["open"].to_numpy(float), px["close"].to_numpy(float)
        for _, ev in sub.iterrows():
            day0 = event_day_zero(ev["at"], days)
            if day0 is None:
                skipped["hors des cours disponibles"] = skipped.get("hors des cours disponibles", 0) + 1
                continue
            i0 = int(days.searchsorted(day0))
            if params.entry == "price":
                entry_px = float(ev["entry_price"]) if pd.notna(ev["entry_price"]) else float("nan")
                if not entry_px > 0:
                    skipped["prix d'entrée absent"] = skipped.get("prix d'entrée absent", 0) + 1
                    continue
                if (day0 - pd.Timestamp(ev["at"]).normalize()).days > NEAR_DAYS:
                    skipped["cours trop éloignés de la date"] = skipped.get("cours trop éloignés de la date", 0) + 1
                    continue
                # Cours rétro-ajustés des fractionnements ou unités différentes : un prix d'offre n'est comparable aux cours que si la première clôture
                # reste plausible (-80 % à +400 %, garde-fou de l'étude IPO) ; sinon l'événement fausserait toute la moyenne.
                if not -0.8 <= closes[i0] / entry_px - 1 <= 4.0:
                    skipped["prix d'offre incohérent avec les cours"] = skipped.get("prix d'offre incohérent avec les cours", 0) + 1
                    continue
                exit_idx = [i0 + k - 1 for k in range(1, K + 1)]
            elif params.entry == "open_day0":
                entry_px = opens[i0]
                exit_idx = [i0 + k - 1 for k in range(1, K + 1)]
            elif params.entry == "close_day0":
                entry_px = closes[i0]
                exit_idx = [i0 + k for k in range(1, K + 1)]
            else:  # close_prev
                if i0 < 1:
                    skipped["pas de séance avant l'événement"] = skipped.get("pas de séance avant l'événement", 0) + 1
                    continue
                entry_px = closes[i0 - 1]
                exit_idx = [i0 - 1 + k for k in range(1, K + 1)]
            if not entry_px > 0 or not math.isfinite(entry_px):
                skipped["prix d'entrée invalide"] = skipped.get("prix d'entrée invalide", 0) + 1
                continue
            path = [closes[j] / entry_px - 1 - params.cost_bps / 10_000 if j < len(closes) else float("nan") for j in exit_idx]
            if all(math.isnan(v) for v in path):
                skipped["horizon pas encore écoulé"] = skipped.get("horizon pas encore écoulé", 0) + 1
                continue
            rows.append({"symbol": symbol, "day0": day0, "group": ev["group"], "entry_px": float(entry_px), **{f"k{k}": path[k - 1] for k in range(1, K + 1)}})
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("day0", kind="stable").reset_index(drop=True)
    return table, skipped


def matrix(table: pd.DataFrame, K: int) -> np.ndarray:
    return table[[f"k{k}" for k in range(1, K + 1)]].to_numpy(dtype=float)


# ------------------------------------------------------------------ évaluation (fonctions pures)
def curve(V: np.ndarray) -> list[dict]:
    """Par jour de sortie k : n, moyenne, médiane, écart-type, taux de gain, P5, P95, t de Student de la moyenne."""
    out = []
    for j in range(V.shape[1]):
        v = V[:, j][~np.isnan(V[:, j])]
        n = len(v)
        if n == 0:
            out.append({"k": j + 1, "n": 0})
            continue
        sd = float(v.std(ddof=1)) if n > 1 else float("nan")
        out.append({"k": j + 1, "n": n, "mean": float(v.mean()), "median": float(np.median(v)), "std": sd, "win": float((v > 0).mean()),
                    "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
                    "t": float(v.mean() / (sd / math.sqrt(n))) if n > 1 and sd and sd > 0 else float("nan")})
    return out


def complete_rows(V: np.ndarray) -> np.ndarray:
    return V[~np.isnan(V).any(axis=1)]


def bootstrap(C: np.ndarray, n_boot: int, seed: int) -> dict:
    """Rééchantillonne les événements (trajectoires complètes) : IC 95 % de la moyenne de chaque jour, fréquence à laquelle chaque jour est le meilleur,
    écart du meilleur jour au dernier jour."""
    rng = np.random.default_rng(seed)
    m, K = C.shape
    means = np.empty((n_boot, K))
    for b in range(n_boot):
        means[b] = C[rng.integers(0, m, m)].mean(axis=0)
    lo, hi = np.percentile(means, [2.5, 97.5], axis=0)
    best = int(np.argmax(C.mean(axis=0)))
    freq = np.bincount(np.argmax(means, axis=1), minlength=K) / n_boot
    diff = means[:, best] - means[:, K - 1]
    return {"ci_low": [float(x) for x in lo], "ci_high": [float(x) for x in hi], "best_freq": [float(x) for x in freq],
            "best_k": best + 1, "diff_vs_last": {"mean": float(diff.mean()), "low": float(np.percentile(diff, 2.5)), "high": float(np.percentile(diff, 97.5))}}


def split_validation(V: np.ndarray, frac: float, n_boot: int, seed: int) -> dict:
    """Le jour qui gagne sur les événements les plus ANCIENS (`frac`) tient-il sur les plus récents ? `V` est supposé trié par date.

    Le jour est choisi sur l'apprentissage seul (moyenne la plus haute parmi les jours à au moins 10 événements) ; on lit ensuite sa moyenne, son taux de
    gain et son intervalle bootstrap sur le test, et on les compare au dernier jour (la règle « on garde jusqu'au bout »)."""
    C = complete_rows(V)
    cut = int(len(C) * frac)
    train, test = C[:cut], C[cut:]
    if len(train) < MIN_COMPLETE or len(test) < 5:
        return {"available": False, "n_train": len(train), "n_test": len(test)}
    k = int(np.argmax(train.mean(axis=0)))
    rng = np.random.default_rng(seed)
    t = test[:, k]
    boots = np.array([t[rng.integers(0, len(t), len(t))].mean() for _ in range(n_boot)])
    return {"available": True, "n_train": len(train), "n_test": len(test), "k": k + 1, "train_mean": float(train[:, k].mean()),
            "train_win": float((train[:, k] > 0).mean()), "test_mean": float(t.mean()), "test_win": float((t > 0).mean()),
            "test_ci_low": float(np.percentile(boots, 2.5)), "test_ci_high": float(np.percentile(boots, 97.5)),
            "test_last_mean": float(test[:, -1].mean()), "holds": bool(t.mean() > 0 and (t > 0).mean() > 0.5)}


def trade_metrics(r: np.ndarray, stake: float) -> dict:
    """Indicateurs d'une série de transactions (rendements, ordre chronologique) à mise fixe, sans chevauchement supposé."""
    r = np.asarray(r, dtype=float)
    pnl = stake * r
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    q05 = np.percentile(r, 5)
    down = r[r < 0].std(ddof=1) if (r < 0).sum() > 1 else float("nan")
    streak = best = 0
    for v in pnl:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    return {"n": len(r), "win_rate": float((pnl > 0).mean()), "mean": float(r.mean()), "median": float(np.median(r)),
            "total_pnl": float(pnl.sum()), "mean_pnl": float(pnl.mean()),
            "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else None,
            "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() != 0 else None,
            "best": float(r.max()), "worst": float(r.min()), "var95": float(q05), "cvar95": float(r[r <= q05].mean()),
            "sharpe_trade": float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else None,
            "sortino_trade": float(r.mean() / down) if down and down > 0 else None,
            "max_drawdown": float((equity - peak).min()) if len(equity) else 0.0, "max_losing_streak": int(best)}


def concentration(r: np.ndarray, symbols: np.ndarray, years: np.ndarray, top_share: float = 0.05) -> dict:
    """Le résultat repose-t-il sur quelques coups d'éclat ? Moyenne sans les 5 % meilleures transactions, part du gain total due aux 5 titres les plus
    rentables, et résultat par année."""
    r = np.asarray(r, dtype=float)
    order = np.argsort(r)
    n_cut = max(1, round(len(r) * top_share))
    trimmed = float(r[order[:-n_cut]].mean()) if len(r) > n_cut else float("nan")
    by_symbol = pd.Series(r).groupby(symbols).sum().sort_values(ascending=False)
    gains = by_symbol[by_symbol > 0].sum()
    top5 = by_symbol.head(5)
    by_year = pd.DataFrame({"year": years, "r": r}).groupby("year")["r"].agg(["count", "mean", lambda s: (s > 0).mean()])
    return {"trimmed_mean": trimmed, "n_trimmed": int(n_cut),
            "top5_symbols": [{"symbol": str(s), "sum": float(v)} for s, v in top5.items()],
            "top5_share_of_gains": float(top5[top5 > 0].sum() / gains) if gains > 0 else None,
            "by_year": [{"year": int(y), "n": int(row["count"]), "mean": float(row["mean"]), "win": float(row.iloc[2])} for y, row in by_year.iterrows()]}


def campaign(r: np.ndarray, stake: float, n_trades: int | None = None, n: int = 10_000, seed: int = 1) -> dict:
    """Monte Carlo : `n_trades` transactions tirées au hasard (avec remise) dans les résultats observés ; distribution du gain final sur la mise."""
    rng = np.random.default_rng(seed)
    k = n_trades or min(len(r), 50)
    final = stake * rng.choice(np.asarray(r, dtype=float), size=(n, k)).sum(axis=1)
    return {"n_trades": int(k), "p05": float(np.percentile(final, 5)), "p50": float(np.percentile(final, 50)), "p95": float(np.percentile(final, 95)),
            "mean": float(final.mean()), "proba_loss": float((final < 0).mean())}


def extremes(table: pd.DataFrame, k: int, top: int = 8) -> dict:
    col = f"k{k}"
    sub = table.dropna(subset=[col])
    cols = ["symbol", "day0", "group", col]
    fmt = lambda df: [{"symbol": r.symbol, "date": r.day0.date().isoformat(), "group": r.group, "ret": float(getattr(r, col))} for r in df[cols].itertuples()]
    return {"best": fmt(sub.nlargest(top, col)), "worst": fmt(sub.nsmallest(top, col))}


def verdict(n_complete: int, best: dict, boot: dict, split: dict, conc: dict) -> dict:
    """Le verdict, en drapeaux lisibles. `robust` exige : assez d'événements (>= 30), IC bootstrap de la moyenne du meilleur jour au-dessus de zéro,
    moyenne positive et taux de gain > 50 % hors échantillon, et moyenne sans les 5 % meilleurs coups toujours positive. Le meilleur jour étant un maximum
    de K essais, seul le test hors échantillon prouve quelque chose."""
    k = best["k"] - 1
    flags = {
        "enough_events": n_complete >= 30,
        "ci_above_zero": boot["ci_low"][k] > 0,
        "oos_holds": bool(split.get("available") and split.get("holds")),
        "not_concentrated": bool(conc["trimmed_mean"] == conc["trimmed_mean"] and conc["trimmed_mean"] > 0),
        "stable_best_day": boot["best_freq"][k] >= 0.25,
        "positive_mean": best["mean"] > 0,
    }
    core = flags["enough_events"] and flags["ci_above_zero"] and flags["oos_holds"] and flags["not_concentrated"]
    label = "robust" if core else ("fragile" if flags["positive_mean"] else "none")
    return {"label": label, "flags": flags, "oos_available": bool(split.get("available"))}
