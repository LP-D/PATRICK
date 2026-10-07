"""Campagne alpha sur plusieurs valeurs : configurations générées, exécution séquentielle, rapport selon le protocole.

Le protocole (univers, critère de découverte, correction de multiplicité) est écrit AVANT les runs dans
`docs/research/alpha-campagne-valeurs-moyennes-2026-10.md` ; ce module n'en est que l'exécution :

- une configuration par valeur, copie du modèle dont seuls la cible, le nom et le dossier de sortie changent ;
- un rapport qui applique le critère à la lettre : **découverte** si le test de Diebold-Mariano du modèle final sur le
  holdout (unilatéral, ajusté de Šidák sur les runs de la valeur) est significatif après Benjamini-Hochberg sur TOUTE la
  famille (une valeur sans run compte avec p = 1, aucune n'est retirée) ET si le Sharpe net de la simulation couverte sur ce
  holdout est strictement positif.
"""
from __future__ import annotations

import copy
import os
import re
import sqlite3
from pathlib import Path

import yaml

from patrick.config.schema import RunConfig
from patrick.config.target_label import ALPHA_SEP
from patrick.tracking import stats as trackstats
from patrick.validation.fdr import benjamini_hochberg

DEFAULT_COST_BPS = 10.0          # par jambe (aller-retour), protocole


def slug(symbol: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", symbol.lower()).strip("_") + "_alpha"


def make_config(template: dict, symbol: str) -> dict:
    """Copie du modèle pour `symbol` : cible, nom et dossier de sortie changent, rien d'autre."""
    if (template.get("objective") or {}).get("target_kind") != "alpha":
        raise ValueError("le modèle de campagne doit être une configuration alpha (objective.target_kind: alpha)")
    cfg = copy.deepcopy(template)
    cfg["objective"]["target_symbol"] = symbol
    cfg["name"] = slug(symbol)
    cfg.setdefault("output", {})["dir"] = f"runs/{slug(symbol)}"
    return cfg


def write_configs(template: dict, symbols: list[str], folder: Path) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for symbol in symbols:
        cfg = make_config(template, symbol)
        RunConfig.model_validate(cfg)                       # refuse tout de suite une configuration invalide
        path = folder / f"{slug(symbol)}.yaml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- critère de découverte

def _db_path(conn: sqlite3.Connection) -> str:
    return next(r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main")


def default_holdout_sharpe(cost_bps: float = DEFAULT_COST_BPS):
    """Sharpe net de la simulation couverte sur le holdout, paramètres par défaut du protocole, sans rien enregistrer
    au registre d'essais (`simulate` seul, jamais `save_simulation`)."""
    from patrick.simulate import engine as sim

    def holdout_sharpe(conn: sqlite3.Connection, trial_id: int) -> float | None:
        params = sim.SimParams(spread_bps=cost_bps / 2, commission_bps=cost_bps / 2)
        result = sim.simulate(trial_id, params, db_path=_db_path(conn), segment="holdout")
        return float(result["strategy"]["sharpe"]) if result.get("ok") else None
    return holdout_sharpe


def _final_run(conn: sqlite3.Connection, label: str, kind: str = "class_specific") -> dict | None:
    """Le run dont le modèle final a un test DM sur le holdout (un seul par valeur dans le protocole ; s'il y en a
    plusieurs, celui du plus petit p unilatéral, comme la famille)."""
    rows = conn.execute(
        "SELECT run.run_id, run.horizon, dm_result.dm_stat, dm_result.p_value FROM dm_result "
        "JOIN run ON run.run_id = dm_result.run_id "
        "WHERE run.target = ? AND run.status = 'done' AND dm_result.kind = ? AND dm_result.sample = 'holdout' "
        "AND dm_result.p_value IS NOT NULL", (label, kind)).fetchall()
    if not rows:
        return None
    def one_sided(row):
        stat, p = row[2], row[3]
        return p / 2 if stat is not None and stat < 0 else 1 - p / 2
    run_id, horizon, dm_stat, p_value = min(rows, key=one_sided)
    trial = conn.execute("SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1 ORDER BY trial_id DESC LIMIT 1",
                         (run_id,)).fetchone()
    return {"run_id": run_id, "horizon": horizon, "dm_stat": dm_stat, "p_two_sided": p_value,
            "trial_id": trial[0] if trial else None}


def _labels_by_symbol(conn: sqlite3.Connection, symbols: list[str]) -> dict[str, str | None]:
    labels = {r[0] for r in conn.execute("SELECT DISTINCT target FROM run WHERE target LIKE ? ESCAPE '\\'",
                                         ("%" + ALPHA_SEP.replace("_", "\\_") + "%",))}
    return {s: next((lab for lab in sorted(labels) if lab.startswith(s + ALPHA_SEP)), None) for s in symbols}


def evaluate_campaign(conn: sqlite3.Connection, symbols: list[str], *, q: float = 0.10,
                      cost_bps: float = DEFAULT_COST_BPS, holdout_sharpe=None) -> dict:
    """Applique le critère du protocole à `symbols` (famille alpha, m = len(symbols))."""
    holdout_sharpe = holdout_sharpe or default_holdout_sharpe(cost_bps)
    labels = _labels_by_symbol(conn, symbols)
    family = trackstats.fdr_across_targets(conn, family="alpha", one_sided=True)["results"]

    p_values: dict[str, float] = {}
    per_symbol: dict[str, dict] = {}
    for symbol in symbols:
        label = labels[symbol]
        info = family.get(label) if label else None
        final = _final_run(conn, label) if label else None
        status = "ok" if (info and not info.get("untestable") and final) else ("absent" if not label else "non testable")
        p_values[symbol] = float(info["p_value"]) if status == "ok" else 1.0
        per_symbol[symbol] = {"symbol": symbol, "label": label, "status": status, "final": final, "info": info}

    bh = benjamini_hochberg(p_values, alpha=q)
    rows = []
    for symbol in symbols:
        d = per_symbol[symbol]
        final, info = d["final"], d["info"]
        entry = bh["results"][symbol]
        # le sens du test (le modèle doit faire MIEUX) est déjà dans la p-value unilatérale : un modèle moins bon a p ~ 1
        significant = bool(entry["significant"]) and d["status"] == "ok"
        sharpe = None
        if d["status"] == "ok" and final["trial_id"] is not None:
            sharpe = holdout_sharpe(conn, final["trial_id"])
        rows.append({
            "symbol": symbol, "label": d["label"], "status": d["status"],
            "horizon": final["horizon"] if final else None,
            "dm_stat": final["dm_stat"] if final else None,
            "p_two_sided": final["p_two_sided"] if final else None,
            "p_campaign": p_values[symbol], "p_adjusted_campaign": entry["adjusted_p_value"],
            "significant": significant, "sharpe_net": sharpe,
            "discovery": bool(significant and sharpe is not None and sharpe > 0),
            "best_run_p_value": info["best_run_p_value"] if info else None,
        })
    return {"rows": rows, "m": len(symbols), "q": q, "cost_bps": cost_bps,
            "n_discoveries": sum(1 for r in rows if r["discovery"])}


def render_markdown(report: dict, title: str = "Campagne alpha") -> str:
    n, m = report["n_discoveries"], report["m"]
    intro = (f"Famille alpha, m = {m} cibles ; Benjamini-Hochberg à q = {report['q']:g}, test de Diebold-Mariano "
             f"unilatéral contre la persistance de l'alpha sur le holdout ; Sharpe net de {report['cost_bps']:g} points "
             "de base par jambe (simulation couverte, paramètres par défaut, rien d'enregistré au registre d'essais).")
    lines = [f"# {title}", "", intro, "",
             "| Valeur | Statut | Horizon | DM | p bilatéral | p famille | q (BH) | Sharpe net | Découverte |",
             "|---|---|---|---|---|---|---|---|---|"]
    def fmt(v, spec=".3f"):
        return "—" if v is None else format(v, spec)
    for r in report["rows"]:
        lines.append(f"| {r['symbol']} | {r['status']} | {fmt(r['horizon'], 'd') if r['horizon'] is not None else '—'} "
                     f"| {fmt(r['dm_stat'], '+.2f')} | {fmt(r['p_two_sided'])} | {fmt(r['p_campaign'])} "
                     f"| {fmt(r['p_adjusted_campaign'])} | {fmt(r['sharpe_net'], '+.2f')} "
                     f"| {'oui' if r['discovery'] else 'non'} |")
    plural = "s" if n > 1 else ""
    lines += ["", f"**Verdict : {n} découverte{plural} sur m = {m}.**",
              "Aucune évidence d'alpha exploitable avec ce protocole sur ces valeurs." if n == 0 else
              "Candidate(s) à une confirmation sur une autre période, jamais à un déploiement (voir le protocole)."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- exécution

def run_campaign(config_paths: list[Path], log_dir: Path, python: str | None = None, skip_done: bool = True,
                 runner=None) -> list[dict]:
    """Un run après l'autre, chacun dans son processus (mémoire libérée entre deux). Un run qui échoue n'arrête pas la
    campagne : il est consigné (le protocole le compte avec p = 1). `runner(cmd, log_path) -> returncode` est injectable."""
    import subprocess
    import sys

    python = python or sys.executable
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    def default_runner(cmd, log_path):
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        with open(log_path, "w", encoding="utf-8") as log:
            return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, check=False).returncode

    runner = runner or default_runner
    out = []
    for path in config_paths:
        log_path = log_dir / (path.stem + ".log")
        if skip_done and log_path.exists() and "[TERMIN" in log_path.read_text(encoding="utf-8", errors="replace"):
            out.append({"config": str(path), "log": str(log_path), "returncode": 0, "skipped": True})
            continue
        code = runner([python, "-m", "patrick.cli", "run", "--config", str(path)], log_path)
        out.append({"config": str(path), "log": str(log_path), "returncode": code, "skipped": False})
    return out
