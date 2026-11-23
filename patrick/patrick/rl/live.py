"""Positions « live » d'un agent RL (ADR 0029) : ce que l'agent du dernier pli d'un run ferait chaque jour depuis la fin de sa fenêtre hors
échantillon.

Un run RL (`rl/run.py`) s'arrête à la dernière date connue à son lancement. Pour qu'un fonds de test combine son avis avec les signaux ML
(`fund/combo.py`), on rejoue l'agent du dernier pli sur les données du jour : mêmes variables (celles que le pli avait retenues), même mise à
l'échelle (ajustée sur les dates d'entraînement du pli), mêmes modèles (les graines sauvegardées, en ensemble), même cadence de décision
(`rebalance_every`), en partant de la position que le run tenait au début de ce pli. Les positions des dates postérieures au run sont écrites
dans `rl_live_position`, une ligne par séance, jamais réécrite (la première décision enregistrée fait foi : un fonds ne doit jamais voir son
passé changer).

Garde-fous :
- un dernier pli « replié » (l'agent n'avait pas battu l'achat-conservation en validation : `gated`) n'a pas d'avis : rien n'est écrit, le fonds
  combiné ignore le RL sur cette cible ;
- `agreement` : part des positions rejouées sur la fenêtre d'origine du pli qui retombent sur celles du fichier hors échantillon du run. Les
  variables sont recalculées sur un historique plus long (les modèles de volatilité réestiment leurs paramètres) : si l'accord tombe sous
  `MIN_AGREEMENT`, l'agent ne voit plus le même monde, rien n'est écrit ;
- les séances rattrapées après coup (application fermée) sont marquées `backfill` : elles sont calculées avec les données d'aujourd'hui.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from patrick.core.clock import utc_today

logger = logging.getLogger("patrick.rl.live")

MIN_AGREEMENT = 0.8              # part minimale des positions d'origine retrouvées par le rejeu
LONG_THRESHOLD = 0.5             # position (rapportée au levier maximal) au-delà de laquelle l'agent est « acheteur »


@dataclass(frozen=True)
class LiveResult:
    job_id: str
    status: str                  # ok | gated | drift | error | no_models
    positions: pd.Series         # dates postérieures au run -> position (vide sauf `ok`)
    agreement: float | None = None
    detail: str | None = None


def _project_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_artifact(path: str) -> str | None:
    """Chemin d'un fichier du run : tel quel (absolu, ou relatif au dossier du serveur qui a fait le run), sinon relatif au projet."""
    if not path:
        return None
    for candidate in (Path(path), _project_dir() / path):
        if candidate.exists():
            return str(candidate)
    return None


def load_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT job_id, status, phase, config_json, result_json FROM job WHERE job_id = ?", (job_id,)).fetchone()
    if row is None or row[1] != "done" or row[2] == "deleted" or not row[4]:
        return None
    return {"job_id": row[0], "config": json.loads(row[3]) if row[3] else {}, "result": json.loads(row[4])}


def _sb3_loader(algo: str):
    from patrick.rl import agents

    agents.require_rl()
    from stable_baselines3 import A2C, DQN, PPO, SAC

    cls = {"PPO": PPO, "A2C": A2C, "DQN": DQN, "SAC": SAC}[algo]
    return lambda path: cls.load(path, device="cpu")


def _default_data(config, store, raw_cache: dict | None):
    from patrick.data.ingest import ingest
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore
    from patrick.pipeline.engine import _align_raw
    from patrick.rl import data as rl_data

    store = store or DataStore()
    key = (config.objective.model_dump_json(exclude={"horizons"}), config.universe.model_dump_json(), config.data_quality.model_dump_json())
    if raw_cache is not None and key in raw_cache:
        raw = raw_cache[key]
    else:
        raw = ingest(config.objective, config.universe, store, force=True, data_quality=config.data_quality)
        raw = _align_raw(raw, config.to_run_config(), resumed=False)
        if raw_cache is not None:
            raw_cache[key] = raw
    return rl_data.build_rl_data(raw, config, clean_symbol(config.objective.target_symbol), keep_last=True)


def _start_position(result: dict, test_start: pd.Timestamp) -> float:
    """Position que le run tenait la veille du dernier pli (fichier hors échantillon), 0 à défaut : c'est de là que repart le rejeu."""
    path = resolve_artifact((result.get("artifacts") or {}).get("oos_csv") or "")
    if not path:
        return 0.0
    try:
        oos = pd.read_csv(path, usecols=["date", "position"], parse_dates=["date"])
    except (OSError, ValueError):
        return 0.0
    before = oos[oos["date"] < test_start]
    return float(before["position"].iloc[-1]) if len(before) else 0.0


def _original_positions(result: dict, test_start: pd.Timestamp) -> pd.Series | None:
    path = resolve_artifact((result.get("artifacts") or {}).get("oos_csv") or "")
    if not path:
        return None
    try:
        oos = pd.read_csv(path, usecols=["date", "position"], parse_dates=["date"])
    except (OSError, ValueError):
        return None
    oos = oos[oos["date"] >= test_start]
    return pd.Series(oos["position"].to_numpy(dtype=float), index=pd.DatetimeIndex(oos["date"]))


def compute(job: dict, *, store=None, raw_cache: dict | None = None, build_data=None, load_model=None) -> LiveResult:
    """Rejoue l'agent du dernier pli de `job` (`load_job`) jusqu'à la dernière date connue. `build_data(config) -> RLData` et
    `load_model(path) -> modèle` sont injectables (tests sans réseau ni PyTorch)."""
    from patrick.rl import agents
    from patrick.rl import data as rl_data
    from patrick.rl.config import RLRunConfig
    from patrick.rl.core import TradingCore, rollout

    job_id, result = job["job_id"], job["result"]
    folds = result.get("folds") or []
    if not folds:
        return LiveResult(job_id, "error", pd.Series(dtype=float), detail="aucun pli dans le résultat")
    fold = folds[-1]
    if fold.get("gated"):
        return LiveResult(job_id, "gated", pd.Series(dtype=float), detail="dernier pli replié sur l'achat-conservation : pas d'avis")
    config = RLRunConfig.model_validate(result.get("config") or job["config"])
    if result.get("session_rule") is not None:
        config.objective.session_rule = int(result["session_rule"])
    settings = config.rl
    paths = [resolve_artifact(p) for k, p in sorted((result.get("artifacts") or {}).items()) if k.startswith("model_seed")]
    paths = [p for p in paths if p]
    if not paths:
        return LiveResult(job_id, "no_models", pd.Series(dtype=float), detail="modèles du dernier pli introuvables")
    data = build_data(config) if build_data is not None else _default_data(config, store, raw_cache)
    dates = pd.DatetimeIndex(data.dates)
    train_start, fit_end, test_start = (pd.Timestamp(fold[k]) for k in ("train_start", "fit_end", "test_start"))
    cols = [c for c in fold.get("features") or [] if c in data.features.columns]
    if len(cols) != len(fold.get("features") or []):
        return LiveResult(job_id, "drift", pd.Series(dtype=float), detail="variables du pli absentes des données recalculées")
    start_all = int(dates.searchsorted(train_start))
    test_lo = int(dates.searchsorted(test_start))
    fit_rows = (dates >= train_start) & (dates <= fit_end)
    if not fit_rows.any() or test_lo >= len(dates):
        return LiveResult(job_id, "error", pd.Series(dtype=float), detail="dates du pli hors des données recalculées")
    _x_fit, x_all = rl_data.scale_fold(data.features.loc[fit_rows], data.features.iloc[start_all:], cols)
    core = TradingCore(x_all, np.asarray(data.fwd_ret[start_all:], dtype=float), settings, reward_scale=1.0)
    loader = load_model or _sb3_loader(settings.algo)
    agent = agents.ensemble_policy([agents.policy_from_model(loader(p), settings) for p in paths])
    replay = rollout(core, agent, test_lo - start_all, len(x_all), _start_position(result, test_start), int(settings.rebalance_every))
    positions = pd.Series(replay["positions"], index=dates[test_lo:test_lo + len(replay["positions"])])

    original = _original_positions(result, test_start)
    agreement = None
    if original is not None and len(original):
        common = original.index.intersection(positions.index)
        if len(common):
            same = np.sign(np.round(original.loc[common].to_numpy(), 6)) == np.sign(np.round(positions.loc[common].to_numpy(), 6))
            agreement = float(same.mean())
    if agreement is not None and agreement < MIN_AGREEMENT:
        return LiveResult(job_id, "drift", pd.Series(dtype=float), agreement,
                          f"le rejeu ne retrouve que {agreement:.0%} des positions d'origine : variables trop changées")
    end = pd.Timestamp(result.get("end")) if result.get("end") else positions.index[0] - pd.Timedelta(days=1)
    live = positions[positions.index > end] / max(float(settings.max_leverage), 1e-9)
    return LiveResult(job_id, "ok", live, agreement)


def record(conn: sqlite3.Connection, res: LiveResult, today: dt.date | None = None) -> int:
    """Écrit les positions nouvelles (jamais une séance déjà enregistrée). Une séance antérieure à la veille de `today` est un rattrapage."""
    if res.status != "ok" or res.positions.empty:
        return 0
    today = today or utc_today()
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=4)               # week-end prolongé : la dernière séance peut dater de vendredi
    rows = [(res.job_id, ts.date().isoformat(), float(pos), int(ts < cutoff), res.agreement) for ts, pos in res.positions.items()]
    with conn:
        cur = conn.executemany("INSERT OR IGNORE INTO rl_live_position (job_id, ts, position, backfill, agreement) VALUES (?, ?, ?, ?, ?)", rows)
    return int(cur.rowcount or 0)


def positions(conn: sqlite3.Connection, job_id: str) -> pd.Series:
    """Positions live enregistrées d'un agent (rapportées au levier maximal : 1 = pleinement acheteur, 0 = à plat, -1 = vendeur)."""
    rows = conn.execute("SELECT ts, position FROM rl_live_position WHERE job_id = ? ORDER BY ts", (job_id,)).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series([float(r[1]) for r in rows], index=pd.DatetimeIndex([r[0] for r in rows]))


def direction(position: float | None) -> int | None:
    """+1 acheteur, -1 vendeur, 0 à plat (un agent du moteur 2 n'achète ou ne reste à plat : à plat est son avis baissier), None sans avis."""
    if position is None or not np.isfinite(position):
        return None
    if position > LONG_THRESHOLD:
        return 1
    if position < -LONG_THRESHOLD:
        return -1
    return 0


def refresh(conn: sqlite3.Connection, job_ids: list[str], *, today: dt.date | None = None, store=None, build_data=None,
            load_model=None) -> list[dict]:
    """Calcule et enregistre les positions live de ces agents (une erreur sur l'un n'arrête pas les autres). Compte rendu par agent."""
    raw_cache: dict = {}
    out = []
    for job_id in dict.fromkeys(job_ids):
        job = load_job(conn, job_id)
        if job is None:
            out.append({"job_id": job_id, "status": "missing"})
            continue
        try:
            res = compute(job, store=store, raw_cache=raw_cache, build_data=build_data, load_model=load_model)
            written = record(conn, res, today)
        except Exception as exc:                                     # un agent illisible ne bloque pas le cycle des fonds
            logger.exception("position live RL %s", job_id)
            out.append({"job_id": job_id, "status": "error", "detail": str(exc)[:300]})
            continue
        out.append({"job_id": job_id, "status": res.status, "written": written, "agreement": res.agreement, "detail": res.detail})
    return out

