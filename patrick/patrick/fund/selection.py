"""Fonds, pilote automatique : sélection automatique des modèles pertinents à trader.

Lecture seule. Une cellule est un couple (cible, horizon) ; son modèle est le champion en titre (table `champion`).
Les critères, dans l'ordre (le premier échec est le motif d'exclusion) : pas une série FRED, pas un modèle d'alpha, pas
un horizon descriptif, score non suspect, signal live frais ; puis, au niveau `strict`, la cible survit à la correction
de Benjamini-Hochberg et le test de Diebold-Mariano de la cellule conclut (p < `alpha_dm`). Au niveau `large`, seuls les
quatre premiers critères comptent. Spécification : `docs/superpowers/specs/2026-10-16-fonds-pilote-automatique-design.md`.

Ce module ne regarde ni les cotations ni l'instrument : ce qui rend une cellule négociable (cotation disponible,
instrument possible dans l'enveloppe) se vérifie dans `fund.autopilot`, qui ajoute ses propres motifs d'exclusion.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
from dataclasses import asdict, dataclass

from patrick.clock import utc_today
from patrick.config import defaults as D
from patrick.config.target_label import is_alpha_label
from patrick.fund import store
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.tracking import stats as trackstats
from patrick.validation import suspicion

TIERS = ("strict", "large")
_CHUNK = 500

LABELS = {
    "fred": "série FRED (non négociable)",
    "alpha": "modèle d'alpha (paire couverte : non gérée par le pilote)",
    "descriptive": "horizon descriptif (pas un signal de portefeuille)",
    "suspect": "score suspect (fuite de données probable)",
    "no_live": "aucun signal live",
    "stale": "signal live trop ancien",
    "bh": "cible écartée par la correction pour tests multiples (Benjamini-Hochberg)",
    "dm": "test de Diebold-Mariano non concluant",
    "cap": "au-delà du nombre maximal de modèles",
}


@dataclass(frozen=True)
class Policy:
    """Réglages de la sélection (valeurs par défaut : voir la spec, §3)."""
    tier: str = "strict"
    alpha_dm: float = 0.05
    alpha_bh: float = 0.10
    fresh_days: int = 7
    max_models: int = 40

    @classmethod
    def from_dict(cls, raw: dict | None) -> Policy:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise store.FundError("politique de sélection invalide : objet attendu")
        base = cls()
        tier = raw.get("tier", base.tier)
        if tier not in TIERS:
            raise store.FundError(f"tier inconnu : {tier!r} ({', '.join(TIERS)})")
        return cls(tier=tier,
                   alpha_dm=_probability(raw.get("alpha_dm", base.alpha_dm), "alpha_dm"),
                   alpha_bh=_probability(raw.get("alpha_bh", base.alpha_bh), "alpha_bh"),
                   fresh_days=_count(raw.get("fresh_days", base.fresh_days), "fresh_days", 365),
                   max_models=_count(raw.get("max_models", base.max_models), "max_models", 500))

    def to_dict(self) -> dict:
        return asdict(self)


def _probability(value, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise store.FundError(f"{name} invalide : nombre attendu ({value!r})") from exc
    if isinstance(value, bool) or not math.isfinite(out) or not 0.0 < out < 1.0:
        raise store.FundError(f"{name} invalide : entre 0 et 1 exclus attendu")
    return out


def _count(value, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise store.FundError(f"{name} invalide : entier entre 1 et {maximum} attendu")
    return value


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fred_symbols() -> frozenset[str]:
    return frozenset(sym for sym, _, src in D.DEFAULT_TARGET_CHOICES if src == "fred")


def _latest_live(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for chunk in _chunks(trial_ids):
        marks = ",".join("?" for _ in chunk)
        out.update(conn.execute(f"SELECT trial_id, MAX(ts) FROM prediction WHERE split = 'live' "
                                f"AND trial_id IN ({marks}) GROUP BY trial_id", chunk).fetchall())
    return out


def _dm_results(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for chunk in _chunks(run_ids):
        marks = ",".join("?" for _ in chunk)
        for run_id, p_value, sample in conn.execute(
                f"SELECT run_id, p_value, sample FROM dm_result WHERE kind = 'class_specific' "
                f"AND run_id IN ({marks})", chunk):
            out[run_id] = {"p_value": p_value, "sample": sample}
    return out


def select_models(conn: sqlite3.Connection, policy: Policy | None = None, today: dt.date | None = None) -> dict:
    """Les modèles à trader selon `policy`.

    Renvoie `selected` (classés par p de Diebold-Mariano croissant, puis signal le plus récent), `excluded` (par motif :
    `code`, `label`, `n`), `excluded_cells` (chaque cellule exclue avec son `detail`) et `n_cells` (champions examinés)."""
    policy = policy or Policy()
    today = today or utc_today()
    champions = conn.execute(
        "SELECT champion.target, champion.horizon, champion.run_id, champion.trial_id, trial.algo "
        "FROM champion LEFT JOIN trial ON trial.trial_id = champion.trial_id "
        "ORDER BY champion.target, champion.horizon").fetchall()
    run_ids = sorted({c[2] for c in champions})
    metrics = {}
    for chunk in _chunks(run_ids):
        metrics.update(trackdb.batch_best_metrics(conn, chunk))
    latest_live = _latest_live(conn, [c[3] for c in champions])
    dm = _dm_results(conn, run_ids)
    fdr = trackstats.fdr_across_targets(conn, alpha=policy.alpha_bh)["results"] if policy.tier == "strict" else {}
    fred = _fred_symbols()
    freshest = (today - dt.timedelta(days=policy.fresh_days)).isoformat()

    selected: list[dict] = []
    excluded_cells: list[dict] = []

    def reject(target: str, horizon: int, code: str, detail: str | None = None) -> None:
        excluded_cells.append({"target": target, "horizon": horizon, "code": code, "label": LABELS[code],
                               "detail": detail or LABELS[code]})

    for target, horizon, run_id, trial_id, algo in champions:
        if target in fred:
            reject(target, horizon, "fred")
        elif is_alpha_label(target):
            reject(target, horizon, "alpha")
        elif horizon in D.DESCRIPTIVE_HORIZONS:
            reject(target, horizon, "descriptive")
        else:
            scores = metrics.get(run_id, {})
            suspect = suspicion.suspect_reason(scores.get("holdout")) or suspicion.suspect_reason(scores.get("test"))
            last_ts = latest_live.get(trial_id)
            if suspect:
                reject(target, horizon, "suspect", f"score suspect : {suspect}".replace(".", ","))
            elif last_ts is None:
                reject(target, horizon, "no_live")
            elif str(last_ts)[:10] < freshest:
                reject(target, horizon, "stale", f"dernier signal live le {str(last_ts)[:10]} (plus de {policy.fresh_days} jours)")
            else:
                evidence = fdr.get(target, {})
                dm_row = dm.get(run_id)
                if policy.tier == "strict" and not evidence.get("significant"):
                    reject(target, horizon, "bh", f"p corrigé de la cible : {_p(evidence.get('p_value'))}")
                elif policy.tier == "strict" and (dm_row is None or dm_row["p_value"] is None
                                                  or dm_row["p_value"] >= policy.alpha_dm):
                    reject(target, horizon, "dm", "pas de test de Diebold-Mariano" if dm_row is None
                           else f"test de Diebold-Mariano non concluant (p = {_p(dm_row['p_value'])})")
                else:
                    selected.append({"target": target, "horizon": horizon, "trial_id": trial_id, "run_id": run_id,
                                     "algo": algo, "last_signal": {"ts": str(last_ts)[:10], "direction": None},
                                     "dm_p": dm_row["p_value"] if dm_row else None,
                                     "dm_sample": dm_row["sample"] if dm_row else None,
                                     "bh_p": evidence.get("p_value"), "bh_significant": evidence.get("significant"),
                                     "live_hit_rate": None, "live_n": None})

    selected.sort(key=lambda m: (m["target"], m["horizon"]))                    # trois tris stables : le dernier prime
    selected.sort(key=lambda m: m["last_signal"]["ts"], reverse=True)
    selected.sort(key=lambda m: 1.0 if m["dm_p"] is None else m["dm_p"])
    for over in selected[policy.max_models:]:
        reject(over["target"], over["horizon"], "cap", f"au-delà de {policy.max_models} modèles")
    selected = selected[:policy.max_models]
    _describe(conn, selected, latest_live)
    counts: dict[str, int] = {}
    for cell in excluded_cells:
        counts[cell["code"]] = counts.get(cell["code"], 0) + 1
    return {"selected": selected, "n_cells": len(champions), "excluded_cells": excluded_cells,
            "excluded": [{"code": code, "label": LABELS[code], "n": n} for code, n in counts.items()]}


def _p(value) -> str:
    return "n.d." if value is None else f"{value:.3f}".replace(".", ",")


def _describe(conn: sqlite3.Connection, selected: list[dict], latest_live: dict[int, str]) -> None:
    """Sens du dernier signal et taux de réussite live (pour affichage) des seuls modèles retenus."""
    for model in selected:
        row = conn.execute("SELECT y_pred FROM prediction WHERE trial_id = ? AND split = 'live' AND ts = ?",
                           (model["trial_id"], latest_live[model["trial_id"]])).fetchone()
        up = row is not None and round(row[0]) in sim_engine._UP_CLASSES
        model["last_signal"]["direction"] = "UP" if up else "DOWN"
    if not selected:
        return
    rates = trackhistory.live_hit_rate_by_target_and_horizon(
        conn, sorted({m["target"] for m in selected}), sorted({m["horizon"] for m in selected}))
    for model in selected:
        rate = rates.get((model["target"], model["horizon"]))
        if rate:
            model["live_hit_rate"], model["live_n"] = rate.get("hit_rate"), rate.get("n")
