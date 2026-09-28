"""Champion / challenger duel (option A, 2026-09-28), run at the end of a
walk-forward run, once per exported horizon.

Rule: the new run's model (challenger) replaces the model in title
(champion) only if it scores a strictly better F1_dir on the SAME holdout,
both configurations being retrained on the SAME pre-holdout data. The
champion's exported model cannot be scored as-is: it was retrained on its
whole history (`tracking/export.py`), which may overlap this holdout. Its
CONFIGURATION is replayed instead -- feature families and settings,
selection method, N, sampler, algorithm, hyperparameters -- on this run's
data snapshot and pre-holdout bars, with this run's target definition
(`objective`) and split (`validation`), through the very function that
scores the challenger (`engine._evaluate_holdout`). Its feature pool is
rebuilt only if its feature settings differ from this run's.

When a duel cannot compare both on the same holdout (no holdout: CPCV or a
history too short; one side below the minimum row counts), nothing changes:
no promotion, nothing archived or pruned. A duel that fails keeps the status
quo too -- it never fails the run. The loser is archived then pruned
(`tracking/champions.py`).
"""
from __future__ import annotations

import math
import time
import traceback

from patrick.config.schema import RunConfig
from patrick.pipeline import engine
from patrick.tracking import champions

RULE = ("F1_dir strictly greater on the same holdout, both configurations retrained on the "
        "same pre-holdout data; tie -> the champion stays")


def _f1(evaluation: dict | None) -> float | None:
    if evaluation is None:
        return None
    value = evaluation.get("metrics", {}).get("F1_dir")
    return None if value is None or math.isnan(value) else float(value)


def _champion_setup(st, champion: dict, horizon: int):
    """(best_cfg, duel_config, pool_builder, feature_pool, universe, pool_mode) replaying
    the champion's configuration on this run's data."""
    run = st.conn.execute("SELECT config_json FROM run WHERE run_id = ?", (champion["run_id"],)).fetchone()
    if run is None:
        raise ValueError(f"champion run {champion['run_id']} not found")
    trial = champions.best_trial(st.conn, champion["run_id"])
    if trial is None:
        raise ValueError(f"champion run {champion['run_id']} has no best trial")
    meta = champions.model_meta(trial["artifact_path"])
    best_params = meta.get("best_params")
    if best_params is None:
        best_params = engine._parse_params(trial["params_json"]) if trial["params_json"] else {}
    best_cfg = {"horizon": horizon, "regime": meta.get("regime", trial["regime"]),
                "N": int(meta.get("N", trial["n_features"])), "sampler": meta.get("sampler", trial["sampler"]),
                "algo": meta.get("algo", trial["algo"]), "best_params": best_params}
    champion_config = RunConfig.model_validate_json(run[0])
    duel_config = champion_config.model_copy(update={
        "objective": st.config.objective, "validation": st.config.validation, "output": st.config.output})
    if duel_config.features.model_dump() == st.config.features.model_dump():
        pool_builder, feature_pool, pool_mode = st.pool_builder, st.feature_pool, "reused"
    else:
        base_pool = engine.build_base_feature_pool(st.raw, duel_config, st.target_col)
        fold_cuts = st.pool_builder.fold_cuts
        pool_builder = engine._FoldPoolBuilder(st.raw, duel_config, st.target_col, base_pool, fold_cuts,
                                               conn=st.conn, snapshot_id=st.snapshot_id)
        feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != st.target_col]
        pool_mode = "rebuilt"
    universe = engine._FoldUniverse(st.raw, st.target_col, duel_config)
    return best_cfg, duel_config, pool_builder, feature_pool, universe, pool_mode


def _describe(side_run_id: str, trial_id: int, cfg: dict, evaluation: dict | None) -> dict:
    return {"run_id": side_run_id, "trial_id": trial_id, "algo": cfg["algo"], "N": int(cfg["N"]),
            "sampler": cfg["sampler"], "regime": cfg["regime"], "f1_dir": _f1(evaluation),
            "metrics": (evaluation or {}).get("metrics")}


def _duel_one(st, horizon: int, best_h: dict, trial_id: int, known_eval: dict | None) -> dict:
    target = st.config.objective.target_symbol
    run_id = st.run_ids[horizon]
    champion = champions.current(st.conn, target, horizon, exclude_run_ids=list(st.run_ids.values()))
    if not (st.is_walkforward and st.has_holdout):
        if champion is None:
            champions.promote(st.conn, target, horizon, run_id, trial_id, reason="first_no_holdout")
            return {"decision": "promoted_first", "run_id": run_id}
        return {"decision": "not_compared", "why": "no holdout for this run", "champion": champion["run_id"]}

    chal_eval = known_eval if known_eval is not None else engine._evaluate_holdout(
        st.conn, st.snapshot_id, st.pool_builder, st.target_col, st.feature_pool, st.config,
        st.all_dates_full, st.n_wf, best_h, st.seed, universe=st.universe)
    chal_f1 = _f1(chal_eval)
    if champion is None:
        champions.promote(st.conn, target, horizon, run_id, trial_id, reason="first", holdout_f1_dir=chal_f1)
        return {"decision": "promoted_first", "run_id": run_id, "challenger_f1_dir": chal_f1}
    if chal_f1 is None:
        return {"decision": "not_compared", "why": "challenger not evaluable on the holdout",
                "champion": champion["run_id"]}

    champ_cfg, duel_config, pool_builder, feature_pool, universe, pool_mode = _champion_setup(st, champion, horizon)
    champ_eval = engine._evaluate_holdout(
        st.conn, st.snapshot_id, pool_builder, st.target_col, feature_pool, duel_config,
        st.all_dates_full, st.n_wf, champ_cfg, st.seed, universe=universe)
    champ_f1 = _f1(champ_eval)
    if champ_f1 is None:
        return {"decision": "not_compared", "why": "champion configuration not evaluable on this holdout",
                "champion": champion["run_id"]}

    challenger_wins = chal_f1 > champ_f1
    duel = {
        "rule": RULE,
        "holdout_start": str(st.all_dates_full[st.n_wf].date()),
        "holdout_end": str(st.all_dates_full[-1].date()),
        "data_snapshot": st.snapshot_id,
        "champion_pool": pool_mode,
        "challenger": _describe(run_id, trial_id, best_h, chal_eval),
        "champion": _describe(champion["run_id"], champion["trial_id"], champ_cfg, champ_eval),
        "winner": "challenger" if challenger_wins else "champion",
    }
    if challenger_wins:
        champions.promote(st.conn, target, horizon, run_id, trial_id, reason="won_duel", holdout_f1_dir=chal_f1)
        champions.archive(st.conn, champion["run_id"], role="replaced_champion", duel=duel)
        champions.prune_run(st.conn, champion["run_id"])
        loser = champion["run_id"]
    else:
        champions.promote(st.conn, target, horizon, champion["run_id"], champion["trial_id"],
                          reason="won_duel", holdout_f1_dir=champ_f1)
        champions.archive(st.conn, run_id, role="rejected_challenger", duel=duel)
        champions.prune_run(st.conn, run_id)
        loser = run_id
    return {"decision": duel["winner"] + "_wins", "challenger_f1_dir": chal_f1, "champion_f1_dir": champ_f1,
            "pruned_run": loser}


def duel_and_promote(st, final_best_by_horizon: dict[int, dict], trial_id_by_horizon: dict[int, int],
                     holdout_evals: dict[int, dict] | None = None) -> dict[int, dict]:
    """One duel per exported horizon. `holdout_evals`: challenger holdout
    evaluations already computed by the run (`_final_holdout`), reused."""
    holdout_evals = holdout_evals or {}
    decisions: dict[int, dict] = {}
    for horizon, best_h in final_best_by_horizon.items():
        trial_id = trial_id_by_horizon.get(horizon)
        if trial_id is None:
            continue
        t_start = time.time()
        try:
            decisions[horizon] = _duel_one(st, horizon, best_h, trial_id, holdout_evals.get(horizon))
        except Exception as exc:  # noqa: BLE001 -- a failed duel keeps the status quo, it never fails a finished run
            traceback.print_exc()
            decisions[horizon] = {"decision": "error", "error": f"{type(exc).__name__}: {exc}"}
        d = decisions[horizon]
        scores = ""
        if "champion_f1_dir" in d:
            scores = f" (challenger F1_dir={d['challenger_f1_dir']:.4f} vs champion {d['champion_f1_dir']:.4f})"
        print(f"[CHAMPION] h={horizon}d: {d['decision']}{scores} [{time.time() - t_start:.0f}s]")
    return decisions
