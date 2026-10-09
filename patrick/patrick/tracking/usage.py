"""Usage des séries, des features et des modèles : « qu'est-ce que mes modèles utilisent réellement ? ».

Deux sources, lues sans calcul de modèle :
- le **modèle final** de chaque run terminé (`*_meta.json` écrit à côté du modèle exporté : algorithme, nombre de features,
  noms des features retenues, pool d'origine) -- ce que le modèle utilise vraiment ;
- la **stabilité de sélection** (`feature_stability`) -- la fréquence à laquelle chaque feature a été retenue d'un fold à l'autre
  pendant le scan, y compris pour les runs dont le modèle a été élagué.

Une feature s'appelle `<série>_<transformation>` (`IDX_GSPC_ret_1d`, `XLV_arima_resid`) ou croise deux séries
(`IDX_GSPC_ret_1d__ratio__XLI`). On remonte à la série d'origine pour répondre aux deux questions utiles : quelles séries
reviennent le plus, lesquelles ne servent jamais.

Un modèle au score impossible (`validation/suspicion.py`) est écarté des comptes : ses features sont celles qui ont fuité,
les compter ferait passer une fuite pour un signal.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from patrick.config.target_label import split_run_label
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.tracking import db as trackdb
from patrick.validation import suspicion

_OPERATORS = re.compile(r"__(?:prod|ratio|sum|minus|zrel)__")
ARTIFACT_BASE_ENV = "PATRICK_ARTIFACT_BASE"

# (famille, motif sur ce qui suit le nom de la série). Ordre = priorité.
_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("volatility_model", re.compile(r"^(egarch_vol|kalman\w*|hmm\w*|heston\w*|vrp\w*|particle_vol|ar_resid|ma_resid|arma_resid|arima_resid)$")),
    ("long_cycle", re.compile(r"^lc_\w+$")),
    ("spike", re.compile(r"^(hurst\w*|semivar\w*|skew\w*|kurt\w*|jump\w*|spike\w*)$")),
    ("technical", re.compile(r"^(ret_\w+|zscore_\w+|rsi_\w+|macd\w*|bb_\w+|vs_ma\w*|ma_\w+|vol_\w+|pk_\w+|gk_\w+|rs_\w+|yz_\w+|roc_\w+|atr_\w+)$")),
    ("macro", re.compile(r"^(lag\d+|level|chg\w*|yoy\w*|mom\w*|diff\w*)$")),
]
FAMILY_ORDER = ("technical", "volatility_model", "long_cycle", "spike", "macro", "interaction", "other")


def artifact_roots() -> list[Path]:
    """Dossiers où chercher les fichiers d'un run : `artifact_path` est relatif au dossier de travail du worker (`patrick/`)."""
    roots = []
    env = os.environ.get(ARTIFACT_BASE_ENV)
    if env:
        roots.append(Path(env))
    here = Path(__file__).resolve()
    roots += [Path.cwd(), here.parents[2], here.parents[3] / "patrick", Path.home() / ".patrick"]
    return list(dict.fromkeys(roots))


def read_meta(artifact_path: str | None) -> dict | None:
    """`*_meta.json` du modèle exporté, ou None s'il a été élagué (modèle remplacé) ou n'est pas sur ce PC."""
    if not artifact_path or not artifact_path.endswith(".joblib"):
        return None
    rel = Path(artifact_path.replace("\\", "/")[: -len(".joblib")] + "_meta.json")
    for root in ([Path("")] if rel.is_absolute() else artifact_roots()):
        path = rel if rel.is_absolute() else root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def base_series(name: str, known: list[str]) -> str | None:
    """Série d'origine d'une feature simple : le plus long nom connu qui la préfixe (`IDX_GSPC_ret_1d` -> `IDX_GSPC`)."""
    for series in known:                                   # `known` est trié du plus long au plus court
        if name == series or name.startswith(series + "_"):
            return series
    return None


def feature_family(name: str, series: str | None) -> str:
    if _OPERATORS.search(name):
        return "interaction"
    if series is None:
        return "other"
    suffix = name[len(series) + 1:] if name != series else "level"
    for family, pattern in _FAMILIES:
        if pattern.match(suffix):
            return family
    return "other"


def feature_series(name: str, known: list[str]) -> list[str]:
    """Séries qui composent une feature (une, ou deux pour une interaction)."""
    out = []
    for part in _OPERATORS.split(name):
        s = base_series(part, known)
        if s and s not in out:
            out.append(s)
    return out


def _universe_series(config_json: str | None, asset: str) -> list[str]:
    """Séries d'origine d'un run, sous le nom qu'elles ont dans les features : tickers Yahoo nettoyés, libellés FRED, cible."""
    try:
        cfg = json.loads(config_json or "{}")
    except ValueError:
        cfg = {}
    uni = cfg.get("universe") or {}
    names = {clean_symbol(t) for t in uni.get("yf_tickers") or []} | set((uni.get("fred_series") or {}).keys())
    names.add(clean_symbol(asset))
    return sorted(names)


def final_models(conn: sqlite3.Connection) -> list[dict]:
    """Un enregistrement par run terminé : modèle final (méta si présent), scores d'en-tête, famille, champion, suspect."""
    runs = conn.execute(
        "SELECT r.run_id, r.target, r.horizon, r.started_at, t.trial_id, t.algo, t.sampler, t.regime, t.n_features, "
        "t.artifact_path, t.category, r.config_json FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "WHERE r.status = 'done' AND r.is_archived = 0").fetchall()
    scores = trackdb.batch_best_metrics(conn, [r[0] for r in runs])
    champions = {row[0] for row in conn.execute("SELECT run_id FROM champion")}
    out = []
    for run_id, target, horizon, started, trial_id, algo, sampler, regime, n_features, artifact, category, cfg_json in runs:
        asset, kind, benchmark = split_run_label(target)
        sc = scores.get(run_id, {})
        hold, test = sc.get("holdout", {}), sc.get("test", {})
        meta = read_meta(artifact)
        out.append({
            "run_id": run_id, "target": target, "asset": asset, "kind": kind, "benchmark": benchmark, "horizon": int(horizon),
            "started_at": started, "trial_id": trial_id, "algo": (meta or {}).get("algo", algo),
            "sampler": (meta or {}).get("sampler", sampler), "regime": (meta or {}).get("regime", regime),
            "n_features": (meta or {}).get("N", n_features), "category": category or "global",
            "features": list((meta or {}).get("feature_names") or []), "universe": _universe_series(cfg_json, asset),
            "has_meta": meta is not None, "champion": run_id in champions,
            "auc": test.get("AUC_ovr_4cls"), "f1": test.get("F1_dir"),
            "holdout_auc": hold.get("AUC_ovr_4cls"), "holdout_f1": hold.get("F1_dir"),
            "suspect": suspicion.suspect_reason(hold) or suspicion.suspect_reason(test),
        })
    return out


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def group_models(models: list[dict], key) -> list[dict]:
    """Tableau par modalité (`key(model) -> str`) : effectif, AUC et F1 moyens, meilleur F1, champions."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in models:
        groups[str(key(m))].append(m)
    rows = [{"key": k, "n": len(v), "auc": _mean(m["auc"] for m in v), "f1": _mean(m["f1"] for m in v),
             "best_f1": max((m["f1"] for m in v if m["f1"] is not None), default=None),
             "champions": sum(1 for m in v if m["champion"])} for k, v in groups.items()]
    return sorted(rows, key=lambda r: (-r["n"], r["key"]))


def stability_by_feature(conn: sqlite3.Connection) -> dict[str, dict]:
    """`{feature: {n_runs, mean_freq, max_freq}}` : combien de runs ont retenu la feature pendant le scan, et à quelle fréquence."""
    return {name: {"n_runs": n, "mean_freq": mean, "max_freq": mx} for name, n, mean, mx in conn.execute(
        "SELECT feature, COUNT(*), AVG(selection_freq), MAX(selection_freq) FROM feature_stability GROUP BY feature")}


def analyse(conn: sqlite3.Connection) -> dict:
    """Vue d'ensemble de l'usage des modèles, séries et features (page `/analysis`)."""
    models = final_models(conn)
    sane = [m for m in models if not m["suspect"]]
    suspects = [m for m in models if m["suspect"]]
    with_features = [m for m in sane if m["features"]]

    feat: dict[str, dict] = {}
    series_use: dict[str, dict] = {}
    own_features: set[str] = set()
    for m in with_features:
        known = sorted(m["universe"], key=lambda x: (-len(x), x))
        for name in m["features"]:
            series = feature_series(name, known)
            rec = feat.setdefault(name, {"feature": name, "family": feature_family(name, series[0] if series else None),
                                         "series": series, "n_models": 0, "targets": set(), "best_auc": None, "best_f1": None,
                                         "best_run": None})
            rec["n_models"] += 1
            rec["targets"].add(m["asset"])
            if m["f1"] is not None and (rec["best_f1"] is None or m["f1"] > rec["best_f1"]):
                rec["best_f1"], rec["best_auc"], rec["best_run"] = m["f1"], m["auc"], m["run_id"]
            own = clean_symbol(m["asset"])
            for s in series:
                if s == own:                      # la cible elle-même n'est pas une série « explicative »
                    own_features.add(name)
                    continue
                u = series_use.setdefault(s, {"series": s, "n_models": 0, "features": set(), "targets": set(),
                                              "best_f1": None, "best_run": None})
                u["n_models"] += 1
                u["features"].add(name)
                u["targets"].add(m["asset"])
                if m["f1"] is not None and (u["best_f1"] is None or m["f1"] > u["best_f1"]):
                    u["best_f1"], u["best_run"] = m["f1"], m["run_id"]
    stability = stability_by_feature(conn)
    for name, rec in feat.items():
        rec["n_targets"] = len(rec.pop("targets"))
        st = stability.get(name) or {}
        rec["mean_freq"], rec["n_runs_stab"] = st.get("mean_freq"), st.get("n_runs")
    for u in series_use.values():
        u["n_features"] = len(u.pop("features"))
        u["n_targets"] = len(u.pop("targets"))
    pool_series = {s for m in with_features for s in m["universe"]}
    unused = sorted(pool_series - set(series_use))
    families = Counter(r["family"] for r in feat.values())
    features = sorted(feat.values(), key=lambda r: (-r["n_models"], -(r["mean_freq"] or 0), r["feature"]))
    series_rows = sorted(series_use.values(), key=lambda r: (-r["n_models"], -r["n_features"], r["series"]))
    single = [f for f in features if f["n_models"] == 1]
    least_used = sorted(single, key=lambda f: (f["mean_freq"] if f["mean_freq"] is not None else 0.0, f["feature"]))[:30]
    return {
        "n_models": len(models), "n_sane": len(sane), "n_suspect": len(suspects), "n_with_features": len(with_features),
        "n_champions": sum(1 for m in sane if m["champion"]),
        "auc_median": _median([m["auc"] for m in sane]), "f1_median": _median([m["f1"] for m in sane]),
        "by_algo": group_models(sane, lambda m: m["algo"]),
        "by_sampler": group_models(sane, lambda m: m["sampler"]),
        "by_kind": group_models(sane, lambda m: m["kind"]),
        "by_horizon": sorted(group_models(sane, lambda m: m["horizon"]), key=lambda r: int(r["key"])),
        "by_n_features": sorted(group_models(sane, lambda m: m["n_features"]), key=lambda r: int(r["key"]) if str(r["key"]).isdigit() else 0),
        "by_regime": group_models(sane, lambda m: m["regime"]),
        "features": features, "least_used": least_used, "n_single": len(single), "series": series_rows, "unused_series": unused, "n_own_features": len(own_features),
        "families": [(f, families.get(f, 0)) for f in FAMILY_ORDER if families.get(f)],
        "n_features_distinct": len(features), "suspects": suspects,
        "models": sorted(sane, key=lambda m: (-(m["f1"] or 0), m["run_id"])),
    }


def _median(values) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
