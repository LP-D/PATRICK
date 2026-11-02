"""Étude du carry de change (`patrick/features/fx_carry.py`) : taux à 3 mois de l'OCDE (FRED, clé `FRED_API_KEY` du poste) et cours de change du cache local.

Usage : python scripts/fx_carry_study.py [--cost-bps 2] [--out rapport.md]

Lecture seule pour les données du projet (cours du cache, aucune écriture dans la base). Les taux sont téléchargés pour l'occasion (8 requêtes) et gardés en mémoire.
Deux stratégies fixées avant la mesure (séries chronologiques, coupe transversale), comptées comme 2 essais pour le Sharpe déflaté."""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from patrick import paths
from patrick.data.sources import fred_source
from patrick.features import fx_carry as fc
from patrick.validation.dsr import deflated_sharpe_ratio

START = "1999-01-01"
SAMPLE_START, SAMPLE_END = "2000-06-01", "2025-11-30"       # l'écart de taux de la zone euro cesse en fin 2025 (série interrompue côté OCDE)


def load_rates() -> pd.DataFrame:
    cols = {"USD": fc.USD_RATE, **{ccy: sid for ccy, (sid, _p, _d) in fc.CURRENCIES.items()}}
    out = {}
    for name, sid in cols.items():
        s = fred_source.download_series(name, sid, START)
        if s is None or s.empty:
            raise SystemExit(f"taux {sid} indisponible")
        s.index = pd.to_datetime(s.index).to_period("M").to_timestamp()
        out[name] = s[~s.index.duplicated(keep="last")]
        print(f"  {name}: {sid} jusqu'à {s.index.max().date()}", flush=True)
    return pd.DataFrame(out).sort_index()


def load_spot() -> pd.DataFrame:
    out = {}
    for _sid, pair, _direct in fc.CURRENCIES.values():
        path = paths.cache_dir() / f"series_{pair}_2000-01-01.parquet"
        s = pd.read_parquet(path).iloc[:, 0].astype(float).dropna()
        s.index = pd.to_datetime(s.index)
        out[pair] = s[~s.index.duplicated()].sort_index()
    return pd.DataFrame(out)


def bootstrap_mean_ci(r: pd.Series, n_boot: int = 5000, block: int = 6, seed: int = 7) -> tuple[float, float]:
    """IC à 95 % de la moyenne mensuelle par bootstrap par blocs (6 mois : l'autocorrélation des rendements de carry)."""
    rng = np.random.default_rng(seed)
    x = r.dropna().to_numpy()
    n = len(x)
    starts = rng.integers(0, n - block + 1, size=(n_boot, int(np.ceil(n / block))))
    means = np.array([np.concatenate([x[s:s + block] for s in row])[:n].mean() for row in starts])
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-bps", type=float, default=fc.COST_BPS)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if not os.environ.get(fred_source.FRED_API_KEY_ENV):
        raise SystemExit("FRED_API_KEY absente de l'environnement")
    print("Taux à 3 mois :", flush=True)
    rates, spot = load_rates(), load_spot()
    lines = [f"# Carry de change : {fc.PUBLICATION_LAG_MONTHS} mois de retard de publication, {args.cost_bps:g} pb de frais par unité de rotation, {SAMPLE_START} -> {SAMPLE_END}", ""]
    lines += ["| stratégie | période | n | rendement annuel | vol | Sharpe | pire perte | asymétrie | t(moyenne) | IC95 de la moyenne mensuelle | Sharpe sans portage (change seul) |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    nets: dict[str, pd.Series] = {}
    for strategy in ("time_series", "cross_section"):
        res = fc.backtest(spot, rates, strategy, cost_bps=args.cost_bps, start=SAMPLE_START, end=SAMPLE_END)
        nets[strategy] = res["net"]
        for label, sl in (("2000-2025", slice(None)), ("2000-2012", slice(None, "2012-12-31")), ("2013-2025", slice("2013-01-01", None))):
            r, so = res["net"].loc[sl], res["spot_only"].loc[sl]
            st, st_so = fc.stats(r), fc.stats(so)
            if st.get("n", 0) < 12:
                continue
            lo, hi = bootstrap_mean_ci(r)
            lines.append(f"| {strategy} | {label} | {st['n']} | {st['ann_return']:+.1%} | {st['ann_vol']:.1%} | {st['sharpe']:.2f} | {st['max_drawdown']:.0%} | {st['skew']:+.2f} | "
                         f"{st['t_mean']:+.2f} | [{lo:+.4f} ; {hi:+.4f}] | {st_so.get('sharpe', float('nan')):.2f} |")
    lines.append("")
    for strategy, r in nets.items():
        d = deflated_sharpe_ratio(r.to_numpy(), n_trials=2, periods_per_year=fc.TRADING_MONTHS)
        lines.append(f"Sharpe déflaté de {strategy} (2 stratégies essayées) : {d['dsr']:.3f} (Sharpe {d['sr_annualized']:.2f}, seuil sous H0 {d['benchmark_sr']:.3f} par mois)")
    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
