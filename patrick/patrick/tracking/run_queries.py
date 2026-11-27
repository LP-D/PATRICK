"""Lectures groupées des runs (B8 : sorties de `tracking/db.py`, lecture seule, sans changement de comportement).

Liste et index des runs de /runs, meilleurs essais, métriques et références en lots, résultats de Diebold-Mariano en lots, raisons
d'alignement. Aucune écriture ici : `tracking/db.py` garde la création, les migrations et tout ce qui écrit. `db` réexporte ces
fonctions : `trackdb.list_all_runs(...)` reste valable partout.
"""
from __future__ import annotations

import html
import json
import math
import sqlite3

from patrick.config.defaults import ALL_DL_ALGOS
from patrick.config.target_label import ALPHA_SEP, VALUE_SUFFIX
from patrick.tracking import class_balance
from patrick.tracking.db import status_label
from patrick.validation import metric_panel, suspicion
from patrick.validation.diebold_mariano import one_sided_better_p


def dm_reading(*, dm_stat, p_value, **fields) -> dict:
    """Résultat Diebold-Mariano tel que les pages le lisent (CO2/CO3 du 25/11).

    `dm_result.p_value` est BILATÉRALE (ADR 0003) : la comparer telle quelle au seuil affichait « significatif » pour un modèle
    nettement MOINS BON que sa référence. `p_value` devient ici la p unilatérale « le modèle fait mieux » ; la bilatérale reste dans
    `p_two_sided` et `worse` dit que le modèle a la perte la plus haute."""
    worse = dm_stat is not None and not math.isnan(float(dm_stat)) and float(dm_stat) > 0
    return {**fields, "dm_stat": dm_stat, "p_value": one_sided_better_p(p_value, dm_stat), "p_two_sided": p_value, "worse": worse}


def _chunks(items: list, size: int = 500):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def best_trials(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, int]:
    """`{run_id: trial_id}` du meilleur essai (`is_best = 1`, posé à l'export du modèle) des runs donnés."""
    out: dict[str, int] = {}
    for chunk in _chunks(run_ids):
        marks = ",".join("?" for _ in chunk)
        out.update(conn.execute(f"SELECT run_id, trial_id FROM trial WHERE run_id IN ({marks}) AND is_best = 1", chunk))
    return out


def partial_best_trials(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, int]:
    """`{run_id: trial_id}` du MEILLEUR ESSAI PROVISOIRE d'un run interrompu (arrêté à la main, worker disparu) : il n'a jamais exporté de
    modèle, donc aucun essai n'est `is_best`, mais ses essais et leurs métriques sont en base. Même critère que le classement final (AUC_dir
    moyenne sur les plis de test depuis l'ADR 0013 ; F1_dir pour un essai d'avant, qui n'a pas d'AUC_dir), restreint aux essais évalués sur
    le plus de plis : sans cela un essai de dépistage n'ayant vu qu'un pli, et chanceux, passerait devant les finalistes. Rien n'est écrit :
    c'est une lecture, pour l'affichage."""
    out: dict[str, int] = {}
    for chunk in _chunks(run_ids, 200):
        marks = ",".join("?" for _ in chunk)
        best: dict[str, tuple[int, int, float, int]] = {}
        for run_id, trial_id, n_folds, auc, f1 in conn.execute(
                "SELECT t.run_id, t.trial_id, COUNT(DISTINCT fm.fold_index), "
                "AVG(CASE WHEN fm.metric = 'AUC_dir' THEN fm.value END), AVG(CASE WHEN fm.metric = 'F1_dir' THEN fm.value END) FROM trial t "
                "JOIN fold_metric fm ON fm.trial_id = t.trial_id "
                f"WHERE t.run_id IN ({marks}) AND fm.split IN ('test', 'test_path') AND fm.metric IN ('AUC_dir', 'F1_dir') "
                "GROUP BY t.trial_id", chunk):
            key = (n_folds, int(auc is not None), auc if auc is not None else (f1 if f1 is not None else float("-inf")))
            if run_id not in best or key > best[run_id][:3]:
                best[run_id] = (*key, trial_id)
        out.update({run_id: trial_id for run_id, (*_key, trial_id) in best.items()})
    return out


def batch_best_f1_dir(conn: sqlite3.Connection, run_ids: list[str],
                      best_trial_by_run: dict[str, int] | None = None) -> dict[str, float | None]:
    """Batched `best trial -> avg test/test_path F1_dir` lookup for every
    run_id in `run_ids`: TWO fixed queries (best-trial ids, then their
    fold_metric average) regardless of len(run_ids), instead of up to two
    queries PER run in a Python loop (the N+1 `list_all_runs` used to have,
    and the same shape `tracking.history.list_runs`/`target_detail` had
    independently -- see those functions, which call this instead of
    duplicating the pattern: `history.py` already depends on `db.py`, never
    the reverse). A run_id with no best trial, or a best trial with no
    matching fold_metric row, is simply absent from the returned dict. `best_trial_by_run` : essais déjà choisis (voir `best_trials`),
    sinon lus (`is_best = 1`)."""
    if not run_ids:
        return {}
    if best_trial_by_run is None:
        best_trial_by_run = best_trials(conn, run_ids)
    trial_ids = list(best_trial_by_run.values())
    best_f1_by_trial: dict[int, float] = {}
    if trial_ids:
        trial_placeholders = ",".join("?" for _ in trial_ids)
        best_f1_by_trial = dict(conn.execute(
            f"SELECT trial_id, AVG(value) FROM fold_metric WHERE trial_id IN ({trial_placeholders}) "
            "AND split IN ('test', 'test_path') AND metric = 'F1_dir' GROUP BY trial_id",
            trial_ids,
        ))
    return {run_id: best_f1_by_trial.get(trial_id) for run_id, trial_id in best_trial_by_run.items()}


# Le panneau d'un modèle (ADR 0023, `validation/metric_panel.py`), puis l'AUC à 4 classes et le F1 : ces deux-là ne s'affichent plus dans
# les aperçus mais servent encore à repérer un score impossible (`suspicion.suspect_reason`).
HEADLINE_METRICS = (*metric_panel.PANEL_KEYS, "AUC_ovr_4cls", "F1_dir",
                    *metric_panel.VALUE_PANEL_KEYS, *metric_panel.VALUE_EXTRA_KEYS)    # la fin : valeur exacte (ADR 0032)


def batch_best_metrics(conn: sqlite3.Connection, run_ids: list[str], metrics: tuple[str, ...] = HEADLINE_METRICS,
                       best_trial_by_run: dict[str, int] | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """Headline metrics (the metric panel, then AUC 4 classes and F1 for the suspicion check) of each run's best trial, in TWO fixed queries whatever `len(run_ids)`:
    `{run_id: {"test": {metric: mean over the walk-forward test folds / CPCV paths}, "holdout": {metric: value}}}`.
    A run without a best trial, or a best trial without these rows, is simply absent / has an empty dict. `best_trial_by_run` : voir
    `batch_best_f1_dir`."""
    if not run_ids:
        return {}
    if best_trial_by_run is None:
        best_trial_by_run = best_trials(conn, run_ids)
    if not best_trial_by_run:
        return {}
    trial_ids = list(best_trial_by_run.values())
    t_ph = ",".join("?" for _ in trial_ids)
    m_ph = ",".join("?" for _ in metrics)
    by_trial: dict[int, dict[str, dict[str, float]]] = {}
    for trial_id, split, metric, value in conn.execute(
            f"SELECT trial_id, split, metric, AVG(value) FROM fold_metric WHERE trial_id IN ({t_ph}) "
            f"AND split IN ('test', 'test_path', 'holdout') AND metric IN ({m_ph}) GROUP BY trial_id, split, metric",
            [*trial_ids, *metrics]):
        key = "holdout" if split == "holdout" else "test"
        by_trial.setdefault(trial_id, {}).setdefault(key, {})[metric] = value
    return {run_id: by_trial.get(trial_id, {}) for run_id, trial_id in best_trial_by_run.items()}


BENCHMARK_BASELINE = "BASELINE_persistence"


def batch_baseline_metric(conn: sqlite3.Connection, run_ids: list[str], metric: str,
                          baseline: str = BENCHMARK_BASELINE) -> dict[str, float]:
    """La mesure `metric` de la référence `baseline` (persistance par défaut) sur les plis de test, par run ; une requête par lot."""
    out: dict[str, float] = {}
    for chunk in _chunks(run_ids):
        placeholders = ",".join("?" for _ in chunk)
        out.update({run_id: float(value) for run_id, value in conn.execute(
            f"SELECT run_id, value FROM baseline_metric WHERE run_id IN ({placeholders}) "
            "AND baseline = ? AND split = 'test' AND metric = ?", (*chunk, baseline, metric))})
    return out


def batch_baseline_f1_dir(conn: sqlite3.Connection, run_ids: list[str],
                          baseline: str = BENCHMARK_BASELINE) -> dict[str, float]:
    """Roadmap bloc 4 ("benchmark column everywhere"): the common reference
    baseline's F1_dir per run -- persistence, the class-agnostic reference
    fixed across asset classes (Phase X5), aggregated over the test folds
    exactly like the model's F1_dir. One query; runs without it are absent."""
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    return {run_id: float(value) for run_id, value in conn.execute(
        f"SELECT run_id, value FROM baseline_metric WHERE run_id IN ({placeholders}) "
        "AND baseline = ? AND split = 'test' AND metric = 'F1_dir'", (*run_ids, baseline))}


def batch_dm_results(conn: sqlite3.Connection, run_ids: list[str],
                      kind: str = "class_specific") -> dict[str, dict]:
    """Batched `dm_result` lookup for every run_id in `run_ids`, filtered to
    a single `kind` -- `dm_result`'s primary key is (run_id, kind), up to
    TWO rows per run (see `save_dm_result`'s docstring: `class_specific` vs
    `common`), so an unfiltered per-run `SELECT ... WHERE run_id = ?` (the
    bug this replaces, see `list_all_runs` below) returns whichever of the
    two SQLite happens to pick, not necessarily the one every other page
    (`run_detail`/`target_detail`, via `history._dm_result_for_run`, same
    `class_specific` default) actually displays. ONE query regardless of
    len(run_ids), same batching rationale as `batch_best_f1_dir` above. A
    run_id with no matching row is simply absent."""
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    return {
        run_id: dm_reading(baseline=baseline, dm_stat=dm_stat, p_value=p_value, computed_at=computed_at, sample=sample)
        for run_id, baseline, dm_stat, p_value, computed_at, sample in conn.execute(
            f"SELECT run_id, baseline, dm_stat, p_value, computed_at, sample FROM dm_result "
            f"WHERE run_id IN ({placeholders}) AND kind = ?",
            (*run_ids, kind),
        )
    }


def run_family(cfg: dict) -> str:
    """« dl » si tous les algorithmes du run sont des réseaux de neurones, « ml » sinon -- même règle que `RunConfig.family`, lue
    sur la configuration enregistrée (un run ancien sans `models.algos` reste « ml »)."""
    models = cfg.get("models")
    algos = models.get("algos") if isinstance(models, dict) else None
    return "dl" if isinstance(algos, list) and algos and all(a in ALL_DL_ALGOS for a in algos) else "ml"


def list_run_index(conn: sqlite3.Connection, include_archived: bool = False, run_ids: list[str] | None = None) -> list[dict]:
    """Index LÉGER des runs, le plus récent d'abord : ce qu'il faut pour compter, filtrer et paginer sans rien calculer (0,1 s pour
    4 000 runs). Les chiffres (AUC, F1, DM, répartition haut / bas) viennent de `enrich_runs`, sur les seules lignes affichées : la page
    Historique relisait avant les prédictions de tous les runs (17 s) et rendait 12 Mo de HTML. `run_ids` : seulement ces runs.

    Chaque ligne : `run_id`, `target`, `horizon`, `status` (celui de la base), `status_label` (« stopped » pour un arrêt manuel),
    `started_at`, `finished_at`, `n_trials`, `error`, `name`, `scheme`, `algorithms`, `family`, `kind`, `has_trials` et `empty` (échoué ou
    arrêté avant le moindre essai : rien n'a été effectué). `target` et `name` sont BRUTS (le gabarit les échappe) ; `config_json` est
    illisible tel quel : il est valide ou NULL, d'où `json_valid`."""
    where, params = [], []
    if not include_archived:
        where.append("r.is_archived = 0")
    if run_ids is not None:
        if not run_ids:
            return []
        where.append(f"r.run_id IN ({','.join('?' for _ in run_ids)})")
        params.extend(run_ids)
    query = (
        "SELECT r.run_id, r.target, r.horizon, r.status, r.started_at, r.finished_at, r.n_trials, r.error, "
        "CASE WHEN json_valid(r.config_json) THEN json_extract(r.config_json, '$.name') END, "
        "CASE WHEN json_valid(r.config_json) THEN json_extract(r.config_json, '$.validation.scheme') END, "
        "CASE WHEN json_valid(r.config_json) THEN json_extract(r.config_json, '$.models.algos') END, "
        "EXISTS (SELECT 1 FROM trial t WHERE t.run_id = r.run_id) FROM run r"
        + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY r.started_at DESC")
    out = []
    for run_id, target, horizon, status, started_at, finished_at, n_trials, error, name, scheme, algos_json, has_trials in conn.execute(query, params):
        try:
            algos = [a for a in json.loads(algos_json) if isinstance(a, str)] if algos_json else []
        except (TypeError, ValueError):
            algos = []
        label = status_label(status, error)
        out.append({
            "run_id": run_id, "target": target, "horizon": horizon, "status": status, "status_label": label,
            "started_at": started_at, "finished_at": finished_at, "n_trials": n_trials, "error": error,
            "name": name if isinstance(name, str) else None, "scheme": scheme if isinstance(scheme, str) else "walkforward",
            "algorithms": algos, "family": run_family({"models": {"algos": algos}}),
            # valeur exacte d'abord (une cible alpha peut l'être aussi : elle est rangée avec les valeurs exactes, sa propre catégorie)
            "kind": "value" if (target or "").endswith(VALUE_SUFFIX) else "alpha" if ALPHA_SEP in (target or "") else "directional",
            "has_trials": bool(has_trials), "empty": status == "failed" and not has_trials,
        })
    return out


def enrich_runs(conn: sqlite3.Connection, index_rows: list[dict], with_balance: bool = True) -> list[dict]:
    """Lignes de `list_run_index` complétées de leurs chiffres, en requêtes GROUPÉES (le coût ne dépend pas du nombre de runs mais de leur
    taille) : même forme que `list_all_runs`. Un run interrompu sans modèle exporté (arrêté à la main, worker disparu) montre ses
    résultats PROVISOIRES -- meilleur essai parmi ceux déjà évalués (`partial_best_trials`) -- et porte `partial = True`.
    `with_balance=False` saute la répartition haut / bas (`class_balance`), la seule lecture de la table `prediction` : 17 s pour les
    4 000 runs, inutile à qui n'affiche pas ces deux colonnes (`class_balance` vaut alors `None`)."""
    run_ids = [r["run_id"] for r in index_rows]
    if not run_ids:
        return []
    configs: dict[str, str | None] = {}
    for chunk in _chunks(run_ids):
        marks = ",".join("?" for _ in chunk)
        configs.update(conn.execute(f"SELECT run_id, config_json FROM run WHERE run_id IN ({marks})", chunk))
    best = best_trials(conn, run_ids)
    unfinished = [r["run_id"] for r in index_rows if r["status"] == "failed" and r["has_trials"] and r["run_id"] not in best]
    provisional = partial_best_trials(conn, unfinished) if unfinished else {}
    chosen = {**best, **provisional}
    best_f1_by_run = batch_best_f1_dir(conn, run_ids, chosen)
    dm_by_run = batch_dm_results(conn, run_ids)
    benchmark_by_run = batch_baseline_f1_dir(conn, run_ids)
    benchmark_mcc_by_run = batch_baseline_metric(conn, run_ids, "MCC_4cls")
    headline_by_run = batch_best_metrics(conn, run_ids, best_trial_by_run=chosen)
    balance_by_run = class_balance.for_runs(conn, run_ids, best_trial_by_run=chosen) if with_balance else {}

    out = []
    for r in index_rows:
        run_id, target, config_json = r["run_id"], r["target"], configs.get(r["run_id"])
        try:
            cfg = json.loads(config_json) if config_json else {}
        except (TypeError, ValueError):
            cfg = {}
        cfg = cfg if isinstance(cfg, dict) else {}
        dm_result = dm_by_run.get(run_id)
        headline = headline_by_run.get(run_id, {})
        test_m, holdout_m = headline.get("test", {}), headline.get("holdout", {})
        name = r["name"]
        out.append({
            **r,
            "target": html.escape(target) if isinstance(target, str) else target,
            "name": html.escape(name) if isinstance(name, str) else name,
            "suspect": (suspicion.suspect_reason(holdout_m) or suspicion.suspect_reason(test_m)
                        or suspicion.alignment_reason(target, cfg)),
            "best_auc": test_m.get("AUC_ovr_4cls"), "holdout_auc": holdout_m.get("AUC_ovr_4cls"),
            # valeur exacte : IC et R² hors échantillon (test, contrôle final), None pour un modèle de direction
            "value_ic": test_m.get("IC"), "holdout_ic": holdout_m.get("IC"), "holdout_r2": holdout_m.get("R2_oos"),
            "panel": metric_panel.panel(test_m), "holdout_panel": metric_panel.panel(holdout_m),
            "value_panel": metric_panel.value_panel(test_m), "holdout_value_panel": metric_panel.value_panel(holdout_m),
            "holdout_f1_dir": holdout_m.get("F1_dir"),
            "config_json": config_json,
            "best_f1_dir": best_f1_by_run.get(run_id),
            "dm_p_value": dm_result["p_value"] if dm_result else None,
            "dm_sample": dm_result["sample"] if dm_result else None,
            "benchmark_f1_dir": benchmark_by_run.get(run_id),
            "benchmark_mcc": benchmark_mcc_by_run.get(run_id),
            "class_balance": balance_by_run.get(run_id),
            "partial": run_id in provisional,
        })
    return out


def run_rows(conn: sqlite3.Connection, run_ids: list[str], include_archived: bool = False) -> list[dict]:
    """Les runs donnés, complets (`enrich_runs`), sans relire les autres : le panneau d'un run et la comparaison de runs relisaient les
    4 000 runs de l'Historique pour n'en garder que deux ou trois."""
    return enrich_runs(conn, list_run_index(conn, include_archived, run_ids))


def list_all_runs(conn: sqlite3.Connection, include_archived: bool = False, with_balance: bool = True) -> list[dict]:
    """All runs, most recent first — for exploratory surfaces (Phase 5).
    Includes `scheme`/`best_f1_dir`/`dm_p_value` (same queries as
    `tracking.history.list_runs`, duplicated here rather than imported:
    `db.py` is the low-level layer, `history.py` depends on it, not the
    other way around) -- `runs.html` displays them directly (`r.scheme`,
    `r.best_f1_dir`, `r.dm_p_value`).

    `include_archived` (chore/db-cleanup-legacy-tickers, migration 0018):
    this is the one genuinely unconditional "every run" listing in the
    codebase, so it is the one that needs to hide `is_archived` rows by
    default -- `archive_legacy_ticker_runs`'s report covers why archiving
    (not deleting) was chosen. `/predictions`/`/portfolio` need no
    equivalent change: both build their queries from the CURRENT universe
    (`config.defaults.DEFAULT_TARGET_GROUPS`), never from `run` directly,
    so a legacy-ticker run was already invisible there.

    Performance (N+1 fix): used to run up to THREE extra queries per run
    inside this loop (best trial, its avg F1_dir, its dm_result) -- now two
    fixed batched lookups (`batch_best_f1_dir`/`batch_dm_results`) plus this
    one query, regardless of how many runs are listed.

    Security (stored XSS, `runs.html`'s `data_table` renders every cell via
    `{{ cell | safe }}`): `target`/`name` can be arbitrary strings for a run
    started via CLI (never sanitized the way the web form's `slug_target`
    sanitizes a web-submitted target) -- escaped here, at the source, since
    `_components.html::data_table` legitimately needs raw HTML for other
    cells (links, badges) and so cannot escape indiscriminately itself."""
    return enrich_runs(conn, list_run_index(conn, include_archived), with_balance)


def legacy_alignment_champions(conn: sqlite3.Connection) -> list[tuple[str, int, str, str]]:
    """Champions à refaire pour l'alignement : `(cible, horizon, run_id, motif)` des champions de change entraînés sous la règle des séances
    1 et des champions d'Asie d'avant l'alignement version 2 (séries FRED du jour). Les cibles macro retirées ont leur propre traitement.
    Seuls les champions de change ou d'Asie voient leur config relue."""
    from patrick.config.target_label import split_run_label
    from patrick.data.session_calendar import classify_asset_class, is_yahoo_fx_pair

    def candidate(target) -> bool:
        symbol = split_run_label(target)[0] if isinstance(target, str) else None
        return bool(symbol) and (is_yahoo_fx_pair(symbol) or classify_asset_class(symbol) in suspicion.FRED_DAY_CLASSES)

    rows = [r for r in conn.execute("SELECT target, horizon, run_id FROM champion").fetchall() if candidate(r[0])]
    reasons = alignment_reasons(conn, [r[2] for r in rows])
    return [(target, horizon, run_id, reasons[run_id]) for target, horizon, run_id in rows
            if run_id in reasons and reasons[run_id] != suspicion.MACRO_TARGET_REASON]


def alignment_reasons(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, str]:
    """`{run_id: motif}` des runs de change entraînés avant la règle d'alignement 2, des runs à cible macro retirée et des cibles d'Asie
    d'avant l'alignement version 2 qui voyaient les séries FRED du jour (`validation/suspicion.py::alignment_reason`). Seuls les candidats
    (`=X`, source FRED, ou alignement < 2 en mode FRED du jour) sont relus, et seulement l'objectif et les champs FRED de leur config."""
    from patrick.config.target_label import split_run_label
    from patrick.data.session_calendar import classify_asset_class, is_yahoo_fx_pair

    def candidate(target, source) -> bool:
        if source == "fred":
            return True
        symbol = split_run_label(target)[0] if isinstance(target, str) else None
        return bool(symbol) and (is_yahoo_fx_pair(symbol) or classify_asset_class(symbol) in suspicion.FRED_DAY_CLASSES)

    out: dict[str, str] = {}
    for start in range(0, len(run_ids), 500):
        chunk = run_ids[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        wanted = [run_id for run_id, target, source in conn.execute(
            f"SELECT run_id, target, json_extract(config_json, '$.objective.target_source') FROM run WHERE run_id IN ({marks})", chunk)
            if candidate(target, source)]
        if not wanted:
            continue
        marks = ",".join("?" for _ in wanted)
        for run_id, target, objective, fpit, fred_series in conn.execute(
                f"SELECT run_id, target, json_extract(config_json, '$.objective'), json_extract(config_json, '$.universe.fred_point_in_time'), "
                f"json_extract(config_json, '$.universe.fred_series') FROM run WHERE run_id IN ({marks})", wanted):
            try:
                cfg = {"objective": json.loads(objective) if objective else {},
                       "universe": {"fred_point_in_time": fpit, "fred_series": json.loads(fred_series) if fred_series else {}}}
            except (TypeError, ValueError):
                cfg = {}
            reason = suspicion.alignment_reason(target, cfg)
            if reason:
                out[run_id] = reason
    return out


def list_done_runs(conn: sqlite3.Connection, limit: int = 50, include_archived: bool = False) -> list[dict]:
    """Finished runs (`status='done'`), most recent first -- feeds the
    simulator's run selector (Phase 4.7). `include_archived`: see
    `list_all_runs`'s docstring."""
    query = "SELECT run_id, target, horizon, started_at, finished_at, config_json FROM run WHERE status = 'done'"
    if not include_archived:
        query += " AND is_archived = 0"
    query += " ORDER BY started_at DESC LIMIT ?"
    rows = conn.execute(query, (limit,)).fetchall()
    out = []
    for run_id, target, horizon, started_at, finished_at, config_json in rows:
        name = None
        try:
            name = json.loads(config_json).get("name")
        except (TypeError, ValueError, AttributeError):
            pass
        out.append({"run_id": run_id, "target": target, "horizon": horizon, "name": name,
                     "started_at": started_at, "finished_at": finished_at})
    return out


def list_trials_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, is_best "
        "FROM trial WHERE run_id = ? ORDER BY is_best DESC, trial_id", (run_id,),
    ).fetchall()
    return [{"trial_id": r[0], "regime": r[1], "algo": r[2], "sampler": r[3],
             "n_features": r[4], "selector": r[5], "is_best": bool(r[6])} for r in rows]
