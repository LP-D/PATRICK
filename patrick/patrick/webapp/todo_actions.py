"""Pages dédiées des lignes « À faire » de la Synthèse (`tracking/home.py::action_items`) : pour chacune, ce qui est concerné, la cause, et
les réentraînements adaptés à cette cause.

Ce module ne lance rien par lui-même : `detail` lit la base, `launch` ne met en file que ce que `detail` propose. Un réentraînement proposé
est un groupe (`id`) dont chaque ligne (`source` : le run ou le job d'origine) est refaite avec la modification des réglages du groupe
(`patch`, champs du formulaire de lancement ; `{}` = les mêmes réglages, quand la cause est déjà corrigée ou passagère). Le navigateur ne
dit jamais que « ce groupe, ces sources » : `launch` relit tout côté serveur, patch compris.

Une ligne a un état : `todo` (à relancer), `pending` (déjà en file ou en cours), `replaced` (un run plus récent couvre déjà sa cible et
ses horizons), `blocked` (non relançable ici, `problem` dit pourquoi), `inspect` (rien à relancer automatiquement : à lire).
Seules les lignes `todo` se lancent.
"""
from __future__ import annotations

import html
import json
import sqlite3
import statistics
from collections.abc import Callable

from patrick.config import defaults as D
from patrick.config.target_label import split_run_label
from patrick.tracking import data_health, retrain_advisor
from patrick.tracking import db as trackdb
from patrick.tracking import home as trackhome
from patrick.validation import suspicion
from patrick.webapp import forms, launch_batches

KEYS = ("failures", "suspect", "fx_legacy", "queue")

# Cause d'un échec -> modification des réglages qui la répare (`{}` : relancer tel quel, la cause est corrigée ou passagère). Une cause
# absente n'a pas de relance automatique : « historique insuffisant » demande un autre seuil ou une autre cible, une cause inconnue se lit.
FAILURE_PATCH: dict[str, dict] = {
    "staged_cpcv": {"staged_screening": False},
    "store_locked": {}, "float32_overflow": {}, "class_missing": {}, "db_locked": {}, "orphaned": {}, "fetch": {},
}
# Propositions du conseiller qui répondent à un score trop beau (`retrain_advisor._rule_fix_leak`).
LEAK_SUGGESTIONS = ("fix_leak", "derived_target")


class _Ctx:
    def __init__(self, conn: sqlite3.Connection, history: dict | None):
        self.conn = conn
        self.history = history if history is not None else data_health.history_depths()
        self.pending = launch_batches.pending_pairs(conn)


def _factor(config, patch: dict) -> float:
    """Coût relatif du réentraînement à celui des mêmes réglages (`retrain_advisor.cost_factor`) ; 1 quand rien ne change."""
    if not patch:
        return 1.0
    before = forms.to_view(config.model_dump())
    return round(retrain_advisor.cost_factor(before, {**before, **{k: v for k, v in patch.items() if k in before}}), 2)


def _item(source: str, *, state: str, at: str = "", detail: str = "", target: str = "", horizons=(), name: str = "", patch=None,
          factor: float | None = None, problem: str | None = None, n_runs: int = 1, family: str = "ml") -> dict:
    return {"source": source, "state": state, "at": at, "detail": detail, "target": target, "horizons": sorted(horizons), "name": name,
            "patch": patch or {}, "factor": factor, "problem": problem, "n_runs": n_runs, "family": family}


def _resolve(ctx: _Ctx, source: str, patch: dict, *, at: str, detail: str, is_replaced: Callable) -> dict:
    """La ligne d'un réentraînement : l'état de `source` (config lisible ? déjà en file ? déjà remplacé ? cible encore proposée ?). Le reste
    (historique assez long, réglages acceptés par le formulaire) se valide à la mise en file : `launch_batches.refit` coûte ~0,2 s par ligne."""
    config, errors = launch_batches.source_config(ctx.conn, source)
    if config is None:
        return _item(source, state="blocked", at=at, detail=detail, problem=errors[0])
    obj = config.objective
    fields = {"at": at, "detail": detail, "target": obj.run_label(), "horizons": obj.horizons, "name": config.name, "family": config.family}
    if obj.horizons and set(obj.horizons) <= ctx.pending.get(obj.target_symbol, set()):
        return _item(source, state="pending", **fields)
    if is_replaced(config):
        return _item(source, state="replaced", **fields)
    if forms.TARGET_SOURCE_BY_SYMBOL.get(obj.target_symbol, "fred") in D.NON_TARGET_SOURCES:
        return _item(source, state="blocked", problem=f"{obj.target_symbol} : cible retirée de l'univers (série macro ou hors univers).", **fields)
    return _item(source, state="todo", patch=patch, factor=_factor(config, patch), **fields)


def _replaced_after(conn: sqlite3.Connection, since: str) -> Callable:
    """Test « déjà remplacé » d'un échec : un run plus récent que `since` couvre chaque horizon de la configuration d'origine."""
    return lambda config: _replaced_since(conn, config.objective.run_label(), config.objective.horizons, since)


def _replaced_since(conn: sqlite3.Connection, label: str, horizons, since: str) -> bool:
    """Un run terminé ou en cours, plus récent que `since`, couvre déjà CHAQUE horizon de `label`."""
    horizons = list(horizons)
    return bool(horizons) and all(
        conn.execute("SELECT 1 FROM run WHERE target = ? AND horizon = ? AND status IN ('done', 'running') AND started_at > ? LIMIT 1",
                     (label, h, since)).fetchone() for h in horizons)


def _group(gid: str, items: list[dict], retrain: bool) -> dict:
    """Un groupe : ses lignes, ce qui se relance (`n_todo`), la modification des réglages (celle de ses lignes à relancer) et son coût relatif."""
    todo = [i for i in items if i["state"] == "todo"]
    factor = round(statistics.median(i["factor"] for i in todo), 2) if todo else None
    return {"id": gid, "kind": "retrain" if retrain else "inspect", "lines": items, "n": len(items),
            "n_runs": sum(i["n_runs"] for i in items), "n_todo": len(todo), "changes": [f"{k} = {json.dumps(v)}" for k, v in (todo[0]["patch"] if todo else {}).items()],
            "patch": todo[0]["patch"] if todo else {}, "factor": factor,
            "cost": (retrain_advisor.cost_class(factor) if factor and factor != 1.0 else "same") if todo else None}


def _order(groups: list[dict]) -> list[dict]:
    return sorted(groups, key=lambda g: (g["kind"] != "retrain", -g["n_todo"], -g["n"]))


# ---------------------------------------------------------------------------------------------------------------- échecs

def _failures(ctx: _Ctx) -> tuple[int, list[dict]]:
    recent = trackhome.recent_failures(data_health.failures(ctx.conn))
    by_kind: dict[str, list[dict]] = {}
    for f in recent:
        patch = FAILURE_PATCH.get(f["kind"])
        if patch is None:
            by_kind.setdefault(f["kind"], []).append(_item(f["id"], state="inspect", at=f["at"], detail=f["error"], target=f["target"],
                                                          name=f["name"]))
            continue
        by_kind.setdefault(f["kind"], []).append(_resolve(ctx, f["id"], patch, at=f["at"], detail=f["error"],
                                                          is_replaced=_replaced_after(ctx.conn, f["at"])))
    groups = [_group(kind, items, kind in FAILURE_PATCH) for kind, items in by_kind.items()]
    return len(recent), _order(groups)


# ---------------------------------------------------------------------------------------------------------------- runs suspects

def _suspect_category(row: dict) -> str:
    """`macro` (cible macro retirée : rien à relancer), `fx` (change d'avant la règle d'alignement 2) ou `score` (score trop beau)."""
    symbol = split_run_label(html.unescape(row["target"]))[0]
    if (row["suspect"] == suspicion.MACRO_TARGET_REASON or symbol not in forms.TARGET_SOURCE_BY_SYMBOL
            or forms.TARGET_SOURCE_BY_SYMBOL[symbol] in D.NON_TARGET_SOURCES):
        return "macro"
    return "fx" if row["suspect"].startswith(suspicion.ALIGNMENT_LABEL) else "score"


def _leak_patch(ctx: _Ctx, run_id: str, suspect: str) -> tuple[str, dict] | None:
    """`(clé, patch)` de la proposition du conseiller qui répond à un score trop beau pour ce run, ou `None`. Seuls le motif et la garde
    anti-fuite du run comptent pour cette règle : pas de diagnostic complet (`advise_run` : plusieurs secondes par run)."""
    config, _ = launch_batches.source_config(ctx.conn, run_id)
    if config is None:
        return None
    diagnosis = retrain_advisor.Diagnosis(run_id=run_id, target=config.objective.run_label(), horizon=0, suspect=suspect,
                                          guard_active=config.objective.alignment.version >= 1)
    for s in retrain_advisor.advise(diagnosis, limit=20):
        if s.key in LEAK_SUGGESTIONS and s.available and not s.manual:
            return s.key, s.patch
    return None


def _sane_after(sane_latest: dict[tuple[str, int], str], pairs: list[tuple[str, int]], newest: str) -> Callable:
    """Test « déjà remplacé » d'un run suspect : chaque couple (cible, horizon) a un run sain plus récent que lui."""
    return lambda config: all(sane_latest.get(pair, "") > newest for pair in pairs)


def _suspect(ctx: _Ctx) -> tuple[int, list[dict]]:
    runs = [r for r in trackdb.list_all_runs(ctx.conn, with_balance=False) if r["status"] == "done"]
    sane_latest: dict[tuple[str, int], str] = {}
    for r in runs:
        if not r.get("suspect"):
            key = (html.unescape(r["target"]), r["horizon"])
            sane_latest[key] = max(sane_latest.get(key, ""), r["started_at"] or "")
    suspects = [r for r in runs if r.get("suspect")]

    macro: dict[str, dict] = {}
    launches: dict[str, list[dict]] = {}
    for r in suspects:                                       # les plus récents d'abord
        if _suspect_category(r) == "macro":
            m = macro.setdefault(r["target"], _item(r["run_id"], state="inspect", at=(r["started_at"] or "")[:16], detail=r["suspect"],
                                                    target=html.unescape(r["target"]), n_runs=0))
            m["n_runs"] += 1
        else:
            launches.setdefault(r.get("name") or r["run_id"], []).append(r)

    by_group: dict[str, list[dict]] = {"fx_rule1": [], "fix_leak": [], "derived_target": [], "manual": []}
    for rows in launches.values():
        newest = max(r["started_at"] or "" for r in rows)
        replaced = _sane_after(sane_latest, [(html.unescape(r["target"]), r["horizon"]) for r in rows], newest)
        rep = rows[0]
        at, detail = (rep["started_at"] or "")[:16], rep["suspect"]
        if _suspect_category(rep) == "fx":
            item = _resolve(ctx, rep["run_id"], {}, at=at, detail=detail, is_replaced=replaced)
            by_group["fx_rule1"].append({**item, "n_runs": len(rows)})
            continue
        leak = _leak_patch(ctx, rep["run_id"], detail)
        if leak is None:
            by_group["manual"].append(_item(rep["run_id"], state="inspect", at=at, detail=detail, target=html.unescape(rep["target"]),
                                            name=rep.get("name") or "", n_runs=len(rows)))
            continue
        key, patch = leak
        by_group[key].append({**_resolve(ctx, rep["run_id"], patch, at=at, detail=detail, is_replaced=replaced), "n_runs": len(rows)})

    groups = [_group(gid, items, gid != "manual") for gid, items in by_group.items() if items]
    if macro:
        groups.append(_group("macro", sorted(macro.values(), key=lambda i: -i["n_runs"]), False))
    return len(suspects), _order(groups)


# ---------------------------------------------------------------------------------------------------------------- champions de change

def _fx_legacy(ctx: _Ctx) -> tuple[int, list[dict]]:
    rows = ctx.conn.execute("SELECT target, horizon, run_id FROM champion WHERE target LIKE '%=X%'").fetchall()
    reasons = trackdb.alignment_reasons(ctx.conn, [r[2] for r in rows])
    legacy = [r for r in rows if r[2] in reasons]
    merged: dict[str, dict] = {}                                           # un lancement porte plusieurs horizons : une seule ligne
    for target, horizon, run_id in legacy:
        item = _resolve(ctx, run_id, {}, at="", detail=reasons[run_id], is_replaced=lambda config: False)
        key = item["name"] or run_id
        if key in merged:
            merged[key]["n_runs"] += 1
        else:
            merged[key] = item
    items = sorted(merged.values(), key=lambda i: i["target"])
    return len(legacy), [_group("fx_champions", items, True)] if items else []


# ---------------------------------------------------------------------------------------------------------------- file d'attente

def _queue(ctx: _Ctx) -> tuple[int, list[dict]]:
    by_status: dict[str, list[dict]] = {"running": [], "queued": []}
    for job_id, status, raw, phase, created in ctx.conn.execute(
            "SELECT job_id, status, config_json, phase, created_at FROM job WHERE status IN ('running', 'queued') ORDER BY created_at, job_id"):
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError):
            cfg = {}
        obj = cfg.get("objective") or {}
        by_status[status].append(_item(job_id, state="inspect", at=(created or "")[:16], detail=phase or "",
                                       target=obj.get("target_symbol") or "", horizons=obj.get("horizons") or [], name=cfg.get("name") or job_id))
    groups = [_group(status, items, False) for status, items in by_status.items() if items]
    return sum(g["n"] for g in groups), groups


_BUILDERS = {"failures": _failures, "suspect": _suspect, "fx_legacy": _fx_legacy, "queue": _queue}


def detail(conn: sqlite3.Connection, key: str, history: dict | None = None) -> dict | None:
    """La page de la ligne `key` : `{"key", "n", "groups": [...], "totals": {état: nombre de lignes}}`, ou `None` si `key` est inconnue.
    `n` est le nombre de la ligne de la synthèse. Un groupe `retrain` propose un réentraînement ; un groupe `inspect` se lit seulement."""
    if key not in _BUILDERS:
        return None
    n, groups = _BUILDERS[key](_Ctx(conn, history))
    totals: dict[str, int] = {}
    for g in groups:
        for i in g["lines"]:
            totals[i["state"]] = totals.get(i["state"], 0) + 1
    return {"key": key, "n": n, "groups": groups, "totals": totals}


def launch(conn: sqlite3.Connection, key: str, group_id: str, sources: list[str], start: Callable[[object], dict],
           history: dict | None = None) -> tuple[list[dict], list[str]]:
    """Met en file les `sources` du groupe `group_id` de la page `key`, chacune refaite avec le patch que `detail` propose : `(runs, erreurs)`.
    Une source que le formulaire refuse (historique devenu trop court…) est signalée sans retenir les autres ; une source qui n'est plus
    à relancer (déjà en file, déjà remplacée : la page a changé) annule tout. `start` : `run_manager.start_run`."""
    page = detail(conn, key, history)
    group = next((g for g in (page or {}).get("groups", []) if g["id"] == group_id and g["kind"] == "retrain"), None)
    if group is None:
        return [], [f"Réentraînement « {group_id} » introuvable : la page a changé, rechargez-la."]
    todo = {i["source"]: i for i in group["lines"] if i["state"] == "todo"}
    wanted = list(dict.fromkeys(sources))
    if not wanted:
        return [], ["Aucun run sélectionné."]
    stale = [s for s in wanted if s not in todo]
    if stale:
        return [], [f"{s} : n'est plus à relancer (déjà remplacé, en file ou introuvable) ; rechargez la page." for s in stale]
    runs: list[dict] = []
    errors: list[str] = []
    for source in wanted:                                  # un à un : le nom du run suivant tient compte du job qui vient d'être mis en file
        config, errs = launch_batches.source_config(conn, source)
        new_config, errs = launch_batches.refit(config, todo[source]["patch"]) if config is not None else (None, errs)
        if new_config is None:
            errors.extend(errs)
            continue
        view = start(new_config)
        runs.append({"run_id": view["id"], "status": view["status"], "queue_position": view["queue_position"],
                     "target": new_config.objective.run_label()})
    return runs, errors
