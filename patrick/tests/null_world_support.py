"""Monde nul / monde à signal : le pipeline complet sur des séries dont on connaît la vérité.

Une marche aléatoire n'a aucune structure à prédire : tout ce que le protocole y « découvre » est du hasard. Un monde
à signal (rendements autocorrélés) est le contrôle positif : si le protocole ne le voit pas non plus, le test du monde
nul ne prouve rien (il serait aveugle, pas prudent).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.data.publication_lag import PIT_VERSION
from patrick.data.store import DataStore
from patrick.pipeline import engine
from patrick.simulate import engine as simulate
from patrick.tracking import db as trackdb

FEATURES = ["WORLD_A", "WORLD_B", "WORLD_C"]
N_BARS = 1000
FACTOR_PERSISTENCE = 0.98   # persistance du facteur lent du monde à signal
SIGNAL_LOADING = 0.004      # poids du facteur (de la veille) dans le rendement quotidien de la cible
HORIZON = 5


def make_raw(kind: str, seed: int, target: str, n: int = N_BARS) -> pd.DataFrame:
    """`kind`: "null" (quatre marches aléatoires indépendantes, rendements N(0, 1 %)) ou "signal" : WORLD_A est le
    NIVEAU d'un facteur lent a (AR(1), persistance 0,98, écart-type 1), exp(0,01 a), et le rendement de la cible en
    dépend, r_t = 0,004 a_{t-1} + bruit : environ 45 % de la variance du rendement à 5 jours est prévisible en lisant le
    niveau de WORLD_A. Le signal passe par un NIVEAU, pas par le rendement du jour de WORLD_A : un rendement de la veille
    corrélé au lendemain de la cible serait écarté par le garde anti-fuite d'alignement (`data/alignment.py`, seuil
    0,30), à raison -- c'est ce qu'il doit faire, et ce n'est pas ce qu'on mesure ici."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    eps = rng.normal(0, 0.01, n)
    drivers = {name: np.cumsum(rng.normal(0, 0.01, n)) for name in FEATURES}      # niveaux logarithmiques
    if kind == "signal":
        a = np.zeros(n)
        shocks = rng.normal(0, np.sqrt(1 - FACTOR_PERSISTENCE ** 2), n)
        for t in range(1, n):
            a[t] = FACTOR_PERSISTENCE * a[t - 1] + shocks[t]
        drivers["WORLD_A"] = 0.01 * a
        returns = eps.copy()
        returns[1:] += SIGNAL_LOADING * a[:-1]
    elif kind == "null":
        returns = eps
    else:
        raise ValueError(f"unknown world kind {kind!r}")
    raw = pd.DataFrame({target: 100 * np.exp(np.cumsum(returns))}, index=idx)
    for name in FEATURES:
        raw[name] = 100 * np.exp(drivers[name])
    return raw


def make_config(target: str, out_dir: Path) -> RunConfig:
    """Léger mais complet : 6 plis (le PBO en demande au moins 6), 4 essais par pli, holdout de 12 mois, sans réglage
    Optuna ; tout le reste est le protocole par défaut."""
    return RunConfig.model_validate({
        "name": target.lower(),
        "objective": {"target_symbol": target, "horizons": [HORIZON], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": FEATURES, "fred_series": {}, "start_date": "2018-01-01"},
        "features": {"families": ["technical"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 6, "min_train_frac": 0.4, "holdout_months": 12},
        "selection": {"method": "shap", "n_features_grid": [3, 5, 8, 12], "shap_sample": 60},
        "sampler": {"candidates": ["none"]},
        "models": {"algos": ["XGBoost"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(out_dir / target.lower()), "seed": 42},
    })


@dataclass
class WorldResult:
    target: str
    kind: str
    dm_p_two_sided: float | None
    dm_stat: float | None
    holdout_f1: float | None
    pbo: float | None
    pbo_blocks: int | None
    sharpe: float | None
    dsr: float | None


def run_world(kind: str, k: int, tmp_dir: Path, db_path: str, store: DataStore) -> WorldResult:
    """Un monde, un run complet du pipeline (walk-forward + holdout), puis la simulation de son modèle sur le holdout.
    Une cible par monde (`NULL_03`, `SIGNAL_01`...), toutes dans la même base : la correction BH porte sur la famille."""
    target = f"{kind.upper()}_{k:02d}"
    raw = make_raw(kind, seed=(1000 if kind == "null" else 5000) + k, target=target)
    store.save(f"raw_{target}", raw, meta={"pit_version": f"{PIT_VERSION}:publication_lag"})
    result = engine.run_pipeline(make_config(target, tmp_dir), store=store, db_path=db_path)

    dm = ((result.get("diebold_mariano") or {}).get("class_specific")) or {}
    pbo = result.get("pbo") or {}
    sharpe = dsr = None
    conn = trackdb.connect(db_path)
    try:
        row = conn.execute("SELECT t.trial_id FROM trial t JOIN run r ON r.run_id = t.run_id "
                           "WHERE r.target = ? AND t.is_best = 1 ORDER BY t.trial_id DESC LIMIT 1", (target,)).fetchone()
    finally:
        conn.close()
    if row:
        sim = simulate.simulate(row[0], simulate.SimParams(), db_path=db_path, store_root=store.root, segment="holdout")
        if sim.get("ok"):
            sharpe, dsr = sim["strategy"].get("sharpe"), sim["strategy"].get("deflated_sharpe")
    return WorldResult(target=target, kind=kind, dm_p_two_sided=dm.get("p_value"), dm_stat=dm.get("dm_stat"),
                       holdout_f1=(result.get("holdout") or {}).get("F1_dir"), pbo=pbo.get("pbo"),
                       pbo_blocks=pbo.get("n_blocks"), sharpe=sharpe, dsr=dsr)


def one_sided_p(world: WorldResult) -> float:
    """p unilatérale « le modèle fait mieux que sa baseline » : la seule direction qui compte (même règle que
    `tracking/stats.py::fdr_across_targets`). Non testable : 1."""
    if world.dm_p_two_sided is None or world.dm_stat is None or np.isnan(world.dm_p_two_sided):
        return 1.0
    p = float(world.dm_p_two_sided)
    return p / 2 if world.dm_stat < 0 else 1 - p / 2
