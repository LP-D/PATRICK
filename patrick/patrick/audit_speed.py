"""`patrick audit speed` -- are the expensive feature components actually
used?

Three measurements, joined per feature FAMILY:

1. share of the feature POOL (columns built);
2. share of what models actually RETAIN: features of the exported models
   (`drift_feature_reference`, one row per selected feature of every
   exported (symbol, horizon) model) and walk-forward selection frequencies
   (`feature_stability`, per run);
3. measured build COST per family on a given raw frame (optional: builds
   every family once and times it).

A family that costs a large share of the build time and is (almost) never
retained is a candidate for removal from the defaults; one that is costly
AND retained is worth caching (`features/pool_cache.py`), not removing.
Read-only: never trains or exports a model.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

import pandas as pd

# Ordered: first match wins (suffix patterns of the feature builders).
_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("interactions", r"__(minus|prod|ratio|zrel|sum|max|min)__"),
    ("guida", r"_estimated$"),
    ("particle_filter", r"_particle_vol$"),
    ("egarch", r"_egarch_vol$"),
    ("kalman", r"_kalman_filtered$"),
    ("hmm", r"_hmm_filtered_stress_prob$"),
    ("heston_proxy", r"_heston_(theta|spread)(_\d+_\d+d)?$"),
    ("vrp_proxy", r"_vrp_proxy(_truncated|_\d+_\d+d)?$"),
    ("arima_family", r"_(ar|ma|arma|arima)_resid$"),
    ("spike_rolling", r"_(hurst|semivar|skew)_\d+d$"),
    ("ohlc_vol", r"_(pk|gk|rs|yz)_\d+d$"),
    ("macro", r"_(level|lag\d+)$"),
    ("technical", r"_(ret|zscore|vs_ma|vol|rsi)_?\d+d?$"),
)

# Families whose build fits a model (re-fit per walk-forward fold).
PARAMETRIC_FAMILIES = frozenset({"particle_filter", "egarch", "kalman", "hmm", "arima_family"})


def classify_feature(name: str) -> str:
    for family, pattern in _FAMILY_PATTERNS:
        if re.search(pattern, name):
            return family
    return "raw_level"


@dataclass
class FamilyUsage:
    family: str
    pool_columns: int = 0
    exported: int = 0
    selection_freq_sum: float = 0.0
    cost_s: float | None = None

    @property
    def parametric(self) -> bool:
        return self.family in PARAMETRIC_FAMILIES


def usage_from_db(conn: sqlite3.Connection) -> dict[str, FamilyUsage]:
    out: dict[str, FamilyUsage] = {}
    for (feature,) in conn.execute("SELECT feature FROM drift_feature_reference"):
        fam = classify_feature(feature)
        out.setdefault(fam, FamilyUsage(fam)).exported += 1
    for feature, freq in conn.execute("SELECT feature, selection_freq FROM feature_stability"):
        fam = classify_feature(feature)
        out.setdefault(fam, FamilyUsage(fam)).selection_freq_sum += float(freq)
    return out


def add_pool(usage: dict[str, FamilyUsage], pool_columns) -> None:
    for col in pool_columns:
        fam = classify_feature(str(col))
        usage.setdefault(fam, FamilyUsage(fam)).pool_columns += 1


def measure_family_costs(raw: pd.DataFrame, series_cols: list[str] | None = None,
                         fit_end_idx: int | None = None) -> dict[str, float]:
    """Wall-clock seconds to build each family on `raw` (all columns, or
    `series_cols`), one fold cut -- the parametric families are rebuilt per
    walk-forward fold in a real run, the others once."""
    from patrick.features import spike, technical, vol_models

    cols = series_cols or list(raw.columns)
    timers: dict[str, float] = {}

    def timed(family, fn):
        t0 = time.perf_counter()
        for c in cols:
            fn(raw[c])
        timers[family] = timers.get(family, 0.0) + time.perf_counter() - t0

    timed("technical", lambda s: technical.build_technical_features(s, prefix=s.name))
    timed("spike_rolling", lambda s: spike.build_spike_features_base(s, prefix=s.name))
    timed("particle_filter", lambda s: spike.build_spike_features_parametric(s, prefix=s.name, fit_end_idx=fit_end_idx))
    for model, family in (("egarch", "egarch"), ("kalman", "kalman"), ("hmm", "hmm"),
                          ("heston_proxy", "heston_proxy"), ("vrp_proxy", "vrp_proxy"), ("arima", "arima_family")):
        timed(family, lambda s, m=model: (
            vol_models.build_vol_model_features_base(s, prefix=s.name, models=[m]),
            vol_models.build_vol_model_features_parametric(s, prefix=s.name, models=[m], fit_end_idx=fit_end_idx)))
    return timers


def render_markdown(usage: dict[str, FamilyUsage], n_folds: int = 5) -> str:
    """Report table; parametric families' cost is multiplied by the number of
    walk-forward folds (they are re-fit per fold)."""
    total_pool = sum(u.pool_columns for u in usage.values()) or 1
    total_exported = sum(u.exported for u in usage.values()) or 1
    run_cost = {f: (u.cost_s or 0.0) * (n_folds if u.parametric else 1) for f, u in usage.items()}
    # A family with no column in the audited pool was not enabled in that
    # run: its measured cost is hypothetical ("if enabled") and must not
    # count in the run's cost shares, nor read as wasted compute.
    enabled = {f for f, u in usage.items() if u.pool_columns > 0 or u.exported > 0}
    total_cost = sum(c for f, c in run_cost.items() if f in enabled) or None
    lines = ["| Famille | Paramétrique | Colonnes du pool | Part du pool | Retenues (modèles exportés) | Part retenue | Σ fréq. sélection | Coût mesuré/run | Part du coût |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for fam, u in sorted(usage.items(), key=lambda kv: -run_cost.get(kv[0], 0.0)):
        if u.cost_s is None:
            cost, cost_share = "—", "—"
        elif fam not in enabled:
            cost, cost_share = f"non activée ({run_cost[fam]:.1f} s si activée)", "—"
        else:
            cost = f"{run_cost[fam]:.1f} s"
            cost_share = f"{run_cost[fam] / total_cost:.0%}" if total_cost else "—"
        lines.append(f"| {fam} | {'oui' if u.parametric else 'non'} | {u.pool_columns} | "
                     f"{u.pool_columns / total_pool:.1%} | {u.exported} | {u.exported / total_exported:.0%} | "
                     f"{u.selection_freq_sum:.2f} | {cost} | {cost_share} |")
    return "\n".join(lines)
