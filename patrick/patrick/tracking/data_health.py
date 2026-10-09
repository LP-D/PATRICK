"""État de santé des données, tel que les entraînements l'ont réellement vécu (page `/data-quality`).

Trois sources, toutes lues sans réseau :
- la base de suivi : runs et jobs en échec (cause classée), séries exclues à l'ingestion (`data_quality_issue`,
  `excluded_symbol`), alignements temporels décidés par la garde anti-fuite (`data/alignment.py`), runs au score suspect ;
- le data lake local (`data/store.py`) : profondeur d'historique de chaque cible déjà ingérée, comparée au seuil
  « Historique minimum (années) » du formulaire de lancement.

Ce module ne corrige rien : il rend visible ce qui s'est passé et pourquoi, avec la correction appliquée quand il y en a une.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone

from patrick.clock import utc_today
from patrick.config import defaults as D
from patrick.config import equity_universe as EQ
from patrick.config import universe_extension as UX
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.validation import suspicion

# (clé, motif d'erreur, titre, ce que cela veut dire, état de la correction)
ERROR_KINDS: list[tuple[str, str, str, str, str]] = [
    ("float32_overflow", r"XGBoostError.*(inf|too large)", "Valeur hors plage dans la matrice de features",
     ("Une feature a pris une valeur finie mais astronomique (ratio sur un dénominateur ~1e-300, ajustement paramétrique "
      "divergent sur un fold court). XGBoost lit ses entrées en float32 (limite 3,4e38) : la matrice est refusée."),
     ("Corrigé le 2026-10-09 (`features/sanitize.py`, `features/vol_models.py`) : toute valeur au-delà de 1e30 est traitée "
      "comme manquante, avant et après la mise à l'échelle, et un ajustement ARIMA divergent ne produit plus de feature. "
      "Relancer ces cibles.")),
    ("orphaned", r"orphaned", "Processus perdu",
     ("Le worker qui exécutait ce run a disparu (fermeture de l'application, mise en veille, plantage) : le run n'a "
      "jamais pu se terminer."),
     ("Pas un défaut de données. Lancer les entraînements longs depuis un PowerShell ouvert par vous, hors de "
      "l'application.")),
    ("stopped", r"Stopped by user", "Arrêté à la main", "Le run a été interrompu depuis la page Lancer.", "Rien à corriger."),
    ("class_missing", r"IndexError.*out of bounds for axis 1 with size 3",
     "Classe absente d'un fold d'entraînement",
     ("Un fold d'entraînement ne contenait que 3 des 4 classes de mouvement : le calibrage a indexé une 4e colonne "
      "inexistante."),
     "Corrigé le 2026-10-02 (`fix/calibration-missing-class`)."),
    ("db_locked", r"database is locked", "Base verrouillée",
     "Une autre écriture a tenu le verrou plus longtemps que le délai d'attente.",
     "Corrigé le 2026-09-27 (délai de 30 s, un worker vivant n'est jamais pris pour mort)."),
    ("insufficient_history", r"Insufficient history", "Historique insuffisant",
     "La série cible ne remonte pas assez loin pour le seuil « Historique minimum (années) ».",
     "Baisser le seuil ou choisir une autre cible : la page Lancer grise désormais ces cibles."),
    ("fetch", r"Could not fetch|ConnectionError|HTTPError|Timeout|timed out", "Récupération impossible",
     "La source (Yahoo Finance, FRED) n'a pas répondu ou a refusé la requête.", "Réessayer plus tard."),
]
_OTHER = ("other", "Autre erreur", "Cause non classée : voir le message complet.", "À examiner.")

REASON_INFO: dict[str, tuple[str, str, str]] = {
    # clé : (titre, signification, effet)
    "couverture_insuffisante": (
        "Couverture insuffisante",
        ("Moins de 85 % des jours ouvrés renseignés depuis le début de la période demandée (2000). Cas typique d'un actif "
         "récent : BTC-USD (Yahoo : depuis 2014), ETH-USD (depuis 2017)."),
        "La série est retirée des features de TOUS les runs. Elle reste utilisable comme cible."),
    "prix_figes": (
        "Cours figés",
        "Plus de 4 clôtures identiques consécutives (seuil `max_frozen_run`).",
        ("Série retirée. Faux positifs probables sur les ETF obligataires à très faible volatilité (SHY, HYG) et les "
         "indices de taux au plancher zéro (^IRX) : relever le seuil dans « Qualité des données » du formulaire de "
         "lancement.")),
    "rendement_aberrant": (
        "Rendement aberrant",
        "Une variation à plus de 40 écarts robustes (z robuste) du reste de la série.",
        ("Série retirée. Les séries FRED en sont dispensées depuis le 2026-10-09 : leurs chocs (COVID, repo 2019) sont "
         "réels.")),
    "trou_de_cotation": (
        "Trou de cotation", "Plus de 10 jours ouvrés consécutifs sans cotation.", "Série retirée."),
    "fin_de_serie_precoce": (
        "Fin de série prématurée",
        ("La dernière observation est très antérieure à la date demandée : série probablement abandonnée (TED_Spread "
         "s'arrête en janvier 2022)."), "Série retirée."),
    "fred_absent_ou_discontinue": (
        "Série FRED absente",
        "FRED n'a renvoyé aucune observation (série discontinuée, identifiant invalide ou échec réseau).",
        "Série absente du pool."),
    "alignement_temporel": (
        "Décalage anti-fuite",
        ("Série de marché retardée (ou retirée) pour que ses dates ne recouvrent pas la fenêtre du label "
         "(`data/alignment.py`)."),
        "Série conservée, décalée : aucune information du futur n'entre plus dans le modèle."),
}


def classify_error(message: str | None) -> tuple[str, str, str, str]:
    """(clé, titre, signification, état de la correction) pour un message d'erreur de run ou de job."""
    text = message or ""
    for key, pattern, title, meaning, status in ERROR_KINDS:
        if re.search(pattern, text, re.DOTALL):
            return key, title, meaning, status
    return _OTHER[0], _OTHER[1], _OTHER[2], _OTHER[3]


def failures(conn: sqlite3.Connection) -> list[dict]:
    """Jobs en échec (soumission web) et runs `failed` sans job associé, avec leur cause classée."""
    out: list[dict] = []
    seen_runs: set[str] = set()
    for job_id, cfg_json, error, finished_at, phase in conn.execute(
            "SELECT job_id, config_json, error, finished_at, phase FROM job WHERE status = 'error' ORDER BY finished_at"):
        name, target = job_id, ""
        try:
            cfg = json.loads(cfg_json)
            name = cfg.get("name") or job_id
            target = (cfg.get("objective") or {}).get("target_symbol") or ""
        except (TypeError, ValueError):
            pass
        key, title, meaning, status = classify_error(error)
        out.append({"id": job_id, "name": name, "target": target, "kind": key, "title": title, "meaning": meaning,
                    "status": status, "phase": phase, "error": (error or "")[:240], "at": (finished_at or "")[:16]})
        seen_runs.add(name)
    for run_id, target, error, finished_at in conn.execute(
            "SELECT run_id, target, error, finished_at FROM run WHERE status = 'failed' ORDER BY finished_at"):
        if any(run_id.startswith(f"{n}_h") for n in seen_runs):
            continue                      # déjà compté via son job
        key, title, meaning, status = classify_error(error)
        out.append({"id": run_id, "name": run_id, "target": target, "kind": key, "title": title, "meaning": meaning,
                    "status": status, "phase": "", "error": (error or "")[:240], "at": (finished_at or "")[:16]})
    return out


def failure_summary(items: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for it in items:
        g = groups.setdefault(it["kind"], {"kind": it["kind"], "title": it["title"], "meaning": it["meaning"],
                                           "status": it["status"], "n": 0, "targets": [], "last": ""})
        g["n"] += 1
        if it["target"] and it["target"] not in g["targets"]:
            g["targets"].append(it["target"])
        g["last"] = max(g["last"], it["at"])
    return sorted(groups.values(), key=lambda g: -g["n"])


def quality_issues(conn: sqlite3.Connection) -> list[dict]:
    """Séries écartées ou décalées à l'ingestion, regroupées par motif, une ligne par (série, motif)."""
    rows = conn.execute(
        "SELECT d.series, d.reason, d.detail, s.created_at, d.snapshot_id FROM data_quality_issue d "
        "JOIN snapshot s ON s.snapshot_id = d.snapshot_id ORDER BY s.created_at").fetchall()
    latest: dict[tuple[str, str], dict] = {}
    count: dict[tuple[str, str], int] = defaultdict(int)
    for series, reason, detail, created_at, _sid in rows:
        k = (series, reason)
        count[k] += 1
        latest[k] = {"series": series, "reason": reason, "detail": detail, "last_seen": str(created_at)[:10]}
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for k, item in latest.items():
        item["n_snapshots"] = count[k]
        by_reason[k[1]].append(item)
    out = []
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        title, meaning, effect = REASON_INFO.get(reason, (reason, "", ""))
        out.append({"reason": reason, "title": title, "meaning": meaning, "effect": effect,
                    "series": sorted(items, key=lambda i: (-i["n_snapshots"], i["series"]))})
    return out


def excluded_symbols(conn: sqlite3.Connection) -> list[dict]:
    return trackdb.list_excluded_symbols(conn)


def suspect_runs(conn: sqlite3.Connection) -> list[dict]:
    """Runs dont le meilleur essai affiche un score au-delà du plausible (`validation/suspicion.py`)."""
    out: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT r.run_id, r.target, r.horizon, r.status, t.trial_id, h.metric, h.value "
        "FROM holdout_diagnostic h JOIN trial t ON t.trial_id = h.trial_id JOIN run r ON r.run_id = t.run_id "
        "WHERE (h.metric = 'F1_dir' AND h.value >= ?) OR (h.metric = 'AUC_ovr_4cls' AND h.value >= ?) "
        "ORDER BY r.started_at DESC",
        (suspicion.SUSPECT_F1_DIR, suspicion.SUSPECT_AUC)).fetchall()
    for run_id, target, horizon, status, trial_id, metric, value in rows:
        item = out.setdefault(run_id, {"run_id": run_id, "target": target, "horizon": horizon, "status": status,
                                       "F1_dir": None, "AUC": None, "trial_id": trial_id})
        if metric == "F1_dir":
            item["F1_dir"] = max(item["F1_dir"] or 0.0, value)
        else:
            item["AUC"] = max(item["AUC"] or 0.0, value)
    for item in out.values():
        item["cause"] = ("Cible FRED publiée avec retard : le marché du jour reproduisait le label"
                         if item["target"] in _fred_targets() else
                         "Horodatage décalé entre deux séries de marché")
    return list(out.values())


def _fred_targets() -> set[str]:
    return {sym for sym, _ in D.DEFAULT_TARGET_GROUPS.get(D.FRED_TARGET_GROUP, [])}


def history_depths(store: DataStore | None = None) -> dict[str, dict]:
    """{symbole: {first, last, n_obs}} pour chaque cible déjà ingérée, lu dans l'index du data lake (aucun parquet
    n'est ouvert). `first`/`n_obs` portent sur la cible elle-même : la table jointe est élaguée sur ses dates."""
    store = store or DataStore()
    out: dict[str, dict] = {}
    for key, entry in store.info().items():
        if not key.startswith("raw_") or "__alpha_" in key:
            continue
        snaps = entry.get("snapshots") or []
        last_snap = snaps[-1] if snaps else entry
        first, last, rows = last_snap.get("date_min"), last_snap.get("date_max"), last_snap.get("rows")
        if not first:
            continue
        out[key[4:]] = {"first": str(first)[:10], "last": str(last)[:10] if last else None, "n_obs": int(rows or 0)}
    return out


def declared_first_dates() -> dict[str, str]:
    """Première cotation vérifiée (`config/universe_extension.py`, `config/equity_universe.py`) des cibles jamais ingérées :
    permet de griser une cible trop récente AVANT son premier téléchargement."""
    out = {sym: first for items in UX.EXTENDED_TARGET_GROUPS.values() for sym, _label, first in items}
    out.update({sym: meta["first_listed"] for sym, meta in EQ.EQUITY_UNIVERSE.items() if meta.get("first_listed")})
    return out


def years_available(first: str | None, today: date | None = None) -> float | None:
    if not first:
        return None
    today = today or utc_today()
    return round((today - date.fromisoformat(first[:10])).days / 365.25, 1)


def history_status(depth: dict | None, min_years: int, today: date | None = None) -> str:
    """`ok` | `short` | `unknown` -- même règle que `data/ingest.py` : début de série antérieur à aujourd'hui - N ans."""
    if not depth:
        return "unknown"
    years = years_available(depth["first"], today)
    return "ok" if years is not None and years >= min_years else "short"


def history_table(groups: dict[str, list[tuple[str, str]]], min_years: int, store: DataStore | None = None,
                  today: date | None = None) -> list[dict]:
    depths = history_depths(store)
    declared = declared_first_dates()
    rows = []
    for group, items in groups.items():
        for sym, label in items:
            depth, source = depths.get(sym), "store"
            if depth is None and sym in declared:
                depth, source = {"first": declared[sym], "last": None, "n_obs": None}, "declared"
            rows.append({"group": group, "symbol": sym, "label": label,
                         "first": depth["first"] if depth else None, "n_obs": depth["n_obs"] if depth else None,
                         "years": years_available(depth["first"], today) if depth else None,
                         "status": history_status(depth, min_years, today), "source": source if depth else None})
    return rows


def overview(conn: sqlite3.Connection, groups: dict[str, list[tuple[str, str]]], min_years: int | None = None,
             store: DataStore | None = None) -> dict:
    min_years = D.DEFAULT_MIN_HISTORY_YEARS if min_years is None else min_years
    fails = failures(conn)
    issues = quality_issues(conn)
    table = history_table(groups, min_years, store)
    counts = {"ok": 0, "short": 0, "unknown": 0}
    for row in table:
        counts[row["status"]] += 1
    n_runs = conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    n_done = conn.execute("SELECT COUNT(*) FROM run WHERE status = 'done'").fetchone()[0]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "min_history_years": min_years,
        "runs": {"total": n_runs, "done": n_done, "failed": n_runs - n_done},
        "failures": fails, "failure_summary": failure_summary(fails),
        "issues": issues,
        "n_issue_series": sum(len(g["series"]) for g in issues),
        "excluded": excluded_symbols(conn),
        "suspects": suspect_runs(conn),
        "history": table, "history_counts": counts,
    }


def depth_by_symbol_for_form(store: DataStore | None = None) -> dict[str, str]:
    """{symbole: première date} -- exposé à la page Lancer pour griser les cibles dont l'historique est trop court
    (profondeur réellement ingérée d'abord, première cotation vérifiée à défaut)."""
    out = dict(declared_first_dates())
    out.update({sym: d["first"] for sym, d in history_depths(store).items()})
    return out
