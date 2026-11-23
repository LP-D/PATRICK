"""Durées estimées des runs (run en cours, file d'attente), apprises des runs passés « à réglages identiques », hors veille et hors pause.

Principe (demande du 2026-11-23) :

- **temps actif** : toute durée (chronomètre d'un run, durée d'un run passé, durée d'une étape) est le temps d'horloge MOINS les périodes où
  rien ne pouvait tourner -- veille du PC détectée par le worker et pauses demandées depuis l'interface (table `machine_idle`, migration 0054).
- **réglages identiques** : la durée d'un run dépend de ce qu'il calcule (algorithmes, essais Optuna, nombre d'horizons, validation,
  sélection, variables, taille de l'univers, réglages des réseaux), pas de sa cible ni de son nom. `signatures` en tire trois clés de plus en
  plus larges : `exact` (tout ce qui pèse sur le temps de calcul), `near` (famille, algorithmes, essais, horizons) et `family` (ml / dl / rl).
  L'estimation prend la clé la plus précise qui a au moins un run terminé, et le dit (`basis`, `n`).
- **moyenne par étape** : chaque étape d'un job (ingestion, variables, balayage, réglage, export ; données, entraînement, évaluation,
  sauvegarde en RL) est chronométrée par le worker (`job_phase_timing`). La durée attendue d'un run en file est la somme des moyennes de ses
  étapes ; pour le run en cours, c'est le reste de l'étape en cours plus les étapes suivantes. Les jobs antérieurs à ce chronométrage n'ont que
  leur durée totale : ils servent quand aucune durée par étape n'existe encore.
- **moyenne robuste** : moyenne tronquée à 10 % de chaque côté (à partir de 5 runs) -- un run passé gonflé par une veille d'avant le
  chronométrage, ou un téléchargement exceptionnellement lent, ne doit pas tirer toute l'estimation.

Tout est relu depuis la base ; l'historique (quelques milliers de configurations JSON) est mis en cache et ne se recalcule que quand un job se
termine ou qu'une veille est consignée (`_history_version`).
"""
from __future__ import annotations

import bisect
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from patrick.config import defaults as D

TRIM = 0.10
MIN_TRIM_N = 5
PHASES_ML = ("ingestion", "features", "scan", "tuning", "export")
PHASES_RL = ("rl_data", "rl_train", "rl_eval", "rl_save")
# Une étape qui dépasse sa moyenne n'est pas supposée finie : on lui laisse encore cette fraction de sa moyenne.
OVERRUN_TAIL = 0.05


# ---------------------------------------------------------------------------------------------------------------- temps actif

def parse_utc(value: str | None) -> float | None:
    """'YYYY-MM-DD HH:MM:SS' (UTC, éventuellement avec fraction de seconde) -> secondes epoch."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def load_idle(conn: sqlite3.Connection, now: float | None = None) -> list[tuple[float, float]]:
    """Toutes les périodes sans calcul (veille, pause), fusionnées et triées ; une pause encore ouverte court jusqu'à `now`."""
    now = time.time() if now is None else now
    try:
        rows = conn.execute("SELECT started_at, ended_at FROM machine_idle").fetchall()
    except sqlite3.OperationalError:              # base pas encore migrée (0054)
        return []
    spans = []
    for started_at, ended_at in rows:
        start = parse_utc(started_at)
        end = parse_utc(ended_at) if ended_at else now
        if start is not None and end is not None:
            spans.append((start, end))
    return merge_intervals(spans)


def active_seconds(start: float, end: float, idle: list[tuple[float, float]]) -> float:
    """Durée de `[start, end]` moins son recouvrement avec les périodes sans calcul (`idle` fusionnées et triées, cf. `load_idle`)."""
    if end <= start:
        return 0.0
    total = end - start
    i = max(0, bisect.bisect_right(idle, (start, float("inf"))) - 1)
    while i < len(idle) and idle[i][0] < end:
        lo, hi = max(start, idle[i][0]), min(end, idle[i][1])
        if hi > lo:
            total -= hi - lo
        i += 1
    return max(0.0, total)


# ---------------------------------------------------------------------------------------------------------------- réglages

def family_of(cfg: dict) -> str:
    if cfg.get("kind") == "rl":
        return "rl"
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    algos = models.get("algos") or []
    return "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"


def _digest(payload) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _d(cfg: dict, key: str) -> dict:
    value = cfg.get(key)
    return value if isinstance(value, dict) else {}


def signatures(cfg: dict) -> tuple[str, str, str]:
    """`(exact, near, family)` : clés de « réglages identiques », de « réglages proches » et de famille d'un job (cible et nom exclus)."""
    family = family_of(cfg)
    obj = _d(cfg, "objective")
    n_horizons = len(obj.get("horizons") or [1])
    if family == "rl":
        rl = _d(cfg, "rl")
        exact = {k: v for k, v in rl.items() if k not in ("device",)}
        exact["horizons"] = n_horizons
        near = [rl.get("algo"), rl.get("total_timesteps"), rl.get("n_seeds"), rl.get("n_folds"), n_horizons]
        return "rl:" + _digest(exact), "rl:" + _digest(near), "rl"
    models, tuning, val = _d(cfg, "models"), _d(cfg, "tuning"), _d(cfg, "validation")
    sel, feat, uni = _d(cfg, "selection"), _d(cfg, "features"), _d(cfg, "universe")
    tuned = bool(tuning.get("enabled"))
    algos = sorted(models.get("algos") or [])
    trials = tuning.get("n_trials") if tuned else None
    exact = {
        "algos": algos, "deep": models.get("deep") if family == "dl" else None,
        "stacking": models.get("stacking"), "calibration": models.get("calibration"),
        "tuning": [tuned, trials, tuning.get("top_k") if tuned else None, tuning.get("cv_splits") if tuned else None],
        "validation": [val.get("scheme"), val.get("n_wf_folds"), val.get("n_groups"), val.get("k_test_groups"), val.get("holdout_months")],
        "selection": [sel.get("method"), sel.get("n_features_grid"), sel.get("screening_mode"), sel.get("shap_sample")],
        "features": [sorted(feat.get("families") or []), sorted(feat.get("vol_models") or []), feat.get("pool_prefilter"),
                     feat.get("interact_top_base"), feat.get("interact_top_pairs"), feat.get("interact_final_n"),
                     feat.get("enable_guida_features"), feat.get("enable_fundamentals_features"), feat.get("enable_equity_context_features")],
        "horizons": n_horizons, "regimes": len(obj.get("regimes") or []), "target_kind": obj.get("target_kind"),
        "universe": [len(uni.get("yf_tickers") or []), len(uni.get("fred_series") or {}), uni.get("start_date")],
        "sampler": cfg.get("sampler"), "sampling": cfg.get("sampling"),
    }
    near = [family, algos, tuned, trials, n_horizons]
    return f"{family}:" + _digest(exact), f"{family}:n:" + _digest(near), family


# ---------------------------------------------------------------------------------------------------------------- historique

def trimmed_mean(values: list[float]) -> float:
    vals = sorted(values)
    k = int(len(vals) * TRIM) if len(vals) >= MIN_TRIM_N else 0
    kept = vals[k:len(vals) - k] or vals
    return sum(kept) / len(kept)


@dataclass
class _Bucket:
    totals: list[float] = field(default_factory=list)
    phases: dict[str, list[float]] = field(default_factory=dict)
    offsets: dict[str, list[float]] = field(default_factory=dict)       # début moyen de l'étape dans le run : ordre des étapes


@dataclass
class Estimate:
    total_s: float
    phases: dict[str, float]          # moyenne par étape (vide si aucun run comparable n'a été chronométré par étape)
    order: list[str]                  # étapes dans l'ordre où elles se déroulent
    basis: str                        # exact | near | family
    n: int                            # runs terminés sur lesquels repose l'estimation
    n_phases: int = 0                 # dont chronométrés par étape


@dataclass
class History:
    version: tuple
    buckets: dict[str, _Bucket]

    def estimate(self, cfg: dict) -> Estimate | None:
        for basis, key in zip(("exact", "near", "family"), signatures(cfg)):
            bucket = self.buckets.get(key)
            if bucket and bucket.totals:
                # Famille seule : des runs aux étapes différentes (avec ou sans réglage Optuna...) -- seule la durée totale a un sens.
                phases = {p: trimmed_mean(v) for p, v in bucket.phases.items() if v} if basis != "family" else {}
                n_phased = max((len(v) for v in bucket.phases.values()), default=0)
                order = sorted(phases, key=lambda p: trimmed_mean(bucket.offsets.get(p) or [0.0]))
                total = trimmed_mean(bucket.totals)
                if phases and n_phased >= 1:
                    # Les jobs chronométrés par étape sont la mesure la plus récente et la plus fine : leur somme fait foi quand elle existe.
                    total = sum(phases.values())
                return Estimate(total_s=total, phases=phases, order=order, basis=basis, n=len(bucket.totals), n_phases=n_phased)
        return None


def _history_version(conn: sqlite3.Connection) -> tuple:
    row = conn.execute("SELECT COUNT(*), MAX(finished_at) FROM job WHERE status = 'done'").fetchone()
    try:
        idle = conn.execute("SELECT COUNT(*), MAX(started_at) FROM machine_idle WHERE ended_at IS NOT NULL").fetchone()
        phases = conn.execute("SELECT COUNT(*) FROM job_phase_timing").fetchone()
    except sqlite3.OperationalError:
        idle, phases = (0, None), (0,)
    return (*row, *idle, *phases)


def _reconstructed_phases(conn: sqlite3.Connection) -> dict[str, list[tuple[str, float, float]]]:
    """Étapes des jobs ML / DL antérieurs au chronométrage par job, reconstituées depuis `run_phase_timing` (migration 0016, une ligne par
    phase du pipeline et par horizon) dans le vocabulaire de `job.phase` : ingestion jusqu'à la fin du téléchargement, variables jusqu'au
    premier balayage, balayage (avec stabilité et diagnostic de contrôle, qui le suivent sans nouveau marqueur) jusqu'au premier réglage
    Optuna ou au premier export, réglage jusqu'au premier export, export jusqu'à la fin du job. Étapes contiguës : leur somme est la durée du
    job. Seul le dernier lancement d'un job repris compte (lignes postérieures à `job.started_at`)."""
    try:
        rows = conn.execute(
            "SELECT r.job_id, p.phase, MIN(p.started_at), MAX(p.finished_at), j.started_at, j.finished_at "
            "FROM run_phase_timing p JOIN run r ON r.run_id = p.run_id JOIN job j ON j.job_id = r.job_id "
            "WHERE j.status = 'done' AND p.started_at >= j.started_at GROUP BY r.job_id, p.phase").fetchall()
    except sqlite3.OperationalError:
        return {}
    marks: dict[str, dict] = {}
    for job_id, phase, first_start, last_end, job_start, job_end in rows:
        m = marks.setdefault(job_id, {"start": parse_utc(job_start), "end": parse_utc(job_end)})
        m[phase] = (parse_utc(first_start), parse_utc(last_end))
    out: dict[str, list[tuple[str, float, float]]] = {}
    for job_id, m in marks.items():
        start, end = m["start"], m["end"]
        scan = [m[k][0] for k in ("scan", "stability", "holdout_diagnostic") if k in m and m[k][0] is not None]
        if start is None or end is None or not scan or "export" not in m:
            continue
        ing_end = m["ingestion"][1] if "ingestion" in m and m["ingestion"][1] is not None else start
        scan_start, export_start = min(scan), m["export"][0]
        tune_start = m["tuning"][0] if "tuning" in m else None
        bounds = [("ingestion", start, ing_end), ("features", ing_end, scan_start),
                  ("scan", scan_start, tune_start if tune_start is not None else export_start)]
        if tune_start is not None:
            bounds.append(("tuning", tune_start, export_start))
        bounds.append(("export", export_start, end))
        if all(b[1] is not None and b[2] is not None and b[2] >= b[1] for b in bounds):
            out[job_id] = bounds
    return out


def build_history(conn: sqlite3.Connection, now: float | None = None) -> History:
    idle = load_idle(conn, now)
    phase_rows: dict[str, list[tuple[str, float, float]]] = {}
    try:
        for job_id, phase, started_at, finished_at in conn.execute(
                "SELECT job_id, phase, started_at, finished_at FROM job_phase_timing ORDER BY rowid"):
            start, end = parse_utc(started_at), parse_utc(finished_at)
            if start is not None and end is not None:
                phase_rows.setdefault(job_id, []).append((phase, start, end))
    except sqlite3.OperationalError:
        pass
    for job_id, bounds in _reconstructed_phases(conn).items():
        phase_rows.setdefault(job_id, bounds)        # le chronométrage du worker, quand il existe, prime
    buckets: dict[str, _Bucket] = {}
    for job_id, config_json, started_at, finished_at in conn.execute(
            "SELECT job_id, config_json, started_at, finished_at FROM job WHERE status = 'done'"):
        start, end = parse_utc(started_at), parse_utc(finished_at)
        if start is None or end is None or end <= start:
            continue
        try:
            cfg = json.loads(config_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        total = active_seconds(start, end, idle)
        # Étapes du DERNIER lancement seulement (un job repris après un arrêt du PC a aussi les lignes du lancement interrompu).
        steps: dict[str, float] = {}
        offsets: dict[str, float] = {}
        for phase, p_start, p_end in phase_rows.get(job_id, ()):
            if p_start + 1 < start:
                continue
            steps[phase] = steps.get(phase, 0.0) + active_seconds(p_start, p_end, idle)
            offsets.setdefault(phase, active_seconds(start, p_start, idle))
        for key in signatures(cfg):
            bucket = buckets.setdefault(key, _Bucket())
            bucket.totals.append(total)
            for phase, seconds in steps.items():
                bucket.phases.setdefault(phase, []).append(seconds)
                bucket.offsets.setdefault(phase, []).append(offsets[phase])
    return History(version=_history_version(conn), buckets=buckets)


_cache: dict[str, History] = {}
_cache_lock = threading.Lock()


_rebuilding: set[str] = set()


def _rebuild_in_background(db_path: str) -> None:
    from patrick.tracking import db as trackdb

    try:
        conn = trackdb.connect(db_path)
        try:
            built = build_history(conn)
        finally:
            conn.close()
        with _cache_lock:
            _cache[db_path] = built
    except sqlite3.Error:
        pass
    finally:
        with _cache_lock:
            _rebuilding.discard(db_path)


def history(conn: sqlite3.Connection) -> History:
    """Historique mis en cache par base ; recalculé seulement quand un job se termine ou qu'une veille / pause est refermée. Le recalcul
    (~1,5 s sur 3 000 jobs) se fait en arrière-plan : la carte « File d'attente », relue toutes les 4 s, garde l'estimation précédente en
    attendant. Seul le tout premier appel (aucun cache) attend le calcul."""
    key = str(conn.execute("PRAGMA database_list").fetchone()[2])
    version = _history_version(conn)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached.version == version:
            return cached
        if cached is not None and key:
            if key not in _rebuilding:
                _rebuilding.add(key)
                threading.Thread(target=_rebuild_in_background, args=(key,), name="patrick-eta-history", daemon=True).start()
            return cached
    built = build_history(conn)
    with _cache_lock:
        _cache[key] = built
    return built


# ---------------------------------------------------------------------------------------------------------------- run en cours

def phase_elapsed(conn: sqlite3.Connection, job_id: str, job_start: float, phase: str | None, now: float,
                  idle: list[tuple[float, float]]) -> dict[str, float]:
    """Temps actif déjà passé dans chaque étape par le lancement en cours (une étape peut revenir : réglage puis export, horizon après
    horizon), étape en cours comprise jusqu'à `now`."""
    out: dict[str, float] = {}
    last_end = job_start
    try:
        rows = conn.execute("SELECT phase, started_at, finished_at FROM job_phase_timing WHERE job_id = ? ORDER BY rowid",
                            (job_id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for name, started_at, finished_at in rows:
        start, end = parse_utc(started_at), parse_utc(finished_at)
        if start is None or end is None or start + 1 < job_start:
            continue
        out[name] = out.get(name, 0.0) + active_seconds(start, end, idle)
        last_end = max(last_end, end)
    if phase:
        out[phase] = out.get(phase, 0.0) + active_seconds(last_end, now, idle)
    return out


def remaining_seconds(estimate: Estimate, phase: str | None, active_elapsed: float,
                      elapsed_by_phase: dict[str, float] | None = None) -> tuple[float, bool]:
    """`(reste estimé, dépassement)` d'un run en cours.

    Par étape quand l'historique le permet : pour chaque étape, sa moyenne moins le temps qu'on y a déjà passé -- l'étape en cours garde au
    moins `OVERRUN_TAIL` de sa moyenne (elle n'est pas finie), une étape antérieure déjà traversée compte pour terminée, une étape à venir
    compte sa moyenne entière. Sinon, sur la durée totale. `dépassement` : le run dure déjà plus que la moyenne des runs comparables."""
    overdue = active_elapsed > estimate.total_s
    if estimate.phases and phase in estimate.phases:
        spent = elapsed_by_phase or {phase: 0.0}
        idx = estimate.order.index(phase)
        rest = 0.0
        for i, name in enumerate(estimate.order):
            mean, done = estimate.phases[name], spent.get(name, 0.0)
            if name == phase:
                rest += max(mean - done, OVERRUN_TAIL * mean)
            elif i > idx:
                rest += max(mean - done, 0.0)
            # étape antérieure : traversée (ou sautée) -- rien à ajouter
        return rest, overdue
    return max(estimate.total_s - active_elapsed, 0.0), overdue
