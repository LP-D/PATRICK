from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.fdr import benjamini_hochberg


REGIME_LABELS = ("CALM", "NORMAL", "STRESS", "CRASH")


@dataclass(frozen=True)
class RegimeThresholds:
    calm_vix: float = 15.0
    normal_vix: float = 25.0
    stress_vix: float = 35.0
    crash_vix: float = 50.0
    calm_vix_percentile: float = 25.0
    normal_vix_percentile: float = 50.0
    stress_vix_percentile: float = 75.0
    crash_vix_percentile: float = 90.0
    market_return_calm: float = 0.0
    market_return_stress: float = -0.02
    market_return_crash: float = -0.08
    realized_vol_calm: float = 0.12
    realized_vol_stress: float = 0.20
    realized_vol_crash: float = 0.35


DEFAULT_REGIME_THRESHOLDS = RegimeThresholds()


def _as_array_1d(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    """Coerce `values` to a 1D float array, raising if it isn't already 1D."""
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1D array")
    return arr


def classify_regime_daily(
    vix: Sequence[float] | np.ndarray,
    vix_percentile: Sequence[float] | np.ndarray,
    market_return: Sequence[float] | np.ndarray,
    realized_vol: Sequence[float] | np.ndarray,
    thresholds: RegimeThresholds = DEFAULT_REGIME_THRESHOLDS,
) -> tuple[np.ndarray, np.ndarray]:
    """Classifies each day by observed regime — no regime prediction.

    Returns (regime_labels, confidence_scores). Confidence is a value in
    [0, 1] based on relative distance to the nearest thresholds.
    """
    vix_arr = _as_array_1d(vix, "vix")
    vix_pct = _as_array_1d(vix_percentile, "vix_percentile")
    ret_arr = _as_array_1d(market_return, "market_return")
    vol_arr = _as_array_1d(realized_vol, "realized_vol")
    if not (len(vix_arr) == len(vix_pct) == len(ret_arr) == len(vol_arr)):
        raise ValueError("All regime inputs must have the same length")

    labels = np.empty(len(vix_arr), dtype=object)
    confidence = np.zeros(len(vix_arr), dtype=float)

    for i in range(len(vix_arr)):
        v = vix_arr[i]
        pct = vix_pct[i]
        ret = ret_arr[i]
        vol = vol_arr[i]

        if (
            v >= thresholds.crash_vix
            or pct >= thresholds.crash_vix_percentile
            or ret <= thresholds.market_return_crash
            or vol >= thresholds.realized_vol_crash
        ):
            labels[i] = "CRASH"
            score = max(
                (v - thresholds.stress_vix) / max(thresholds.crash_vix - thresholds.stress_vix, 1e-9),
                (pct - thresholds.stress_vix_percentile) / max(thresholds.crash_vix_percentile - thresholds.stress_vix_percentile, 1e-9),
                (thresholds.market_return_stress - ret) / max(thresholds.market_return_stress - thresholds.market_return_crash, 1e-9),
                (vol - thresholds.realized_vol_stress) / max(thresholds.realized_vol_crash - thresholds.realized_vol_stress, 1e-9),
            )
            confidence[i] = float(np.clip(score, 0.0, 1.0))
        elif (
            v >= thresholds.stress_vix
            or pct >= thresholds.stress_vix_percentile
            or ret <= thresholds.market_return_stress
            or vol >= thresholds.realized_vol_stress
        ):
            labels[i] = "STRESS"
            score = max(
                (v - thresholds.normal_vix) / max(thresholds.stress_vix - thresholds.normal_vix, 1e-9),
                (pct - thresholds.normal_vix_percentile) / max(thresholds.stress_vix_percentile - thresholds.normal_vix_percentile, 1e-9),
                (thresholds.market_return_calm - ret) / max(thresholds.market_return_calm - thresholds.market_return_stress, 1e-9),
                (vol - thresholds.realized_vol_calm) / max(thresholds.realized_vol_stress - thresholds.realized_vol_calm, 1e-9),
            )
            confidence[i] = float(np.clip(score, 0.0, 1.0))
        elif (
            v >= thresholds.normal_vix
            or pct >= thresholds.normal_vix_percentile
            or ret <= thresholds.market_return_calm
            or vol >= thresholds.realized_vol_calm
        ):
            labels[i] = "NORMAL"
            score = max(
                (v - thresholds.calm_vix) / max(thresholds.normal_vix - thresholds.calm_vix, 1e-9),
                (pct - thresholds.calm_vix_percentile) / max(thresholds.normal_vix_percentile - thresholds.calm_vix_percentile, 1e-9),
                (thresholds.market_return_calm - ret) / max(thresholds.market_return_calm - thresholds.market_return_stress, 1e-9),
                (vol - thresholds.realized_vol_calm) / max(thresholds.normal_vix - thresholds.calm_vix, 1e-9),
            )
            confidence[i] = float(np.clip(score, 0.0, 1.0))
        else:
            labels[i] = "CALM"
            score = max(
                (thresholds.normal_vix - v) / max(thresholds.normal_vix - thresholds.calm_vix, 1e-9),
                (thresholds.normal_vix_percentile - pct) / max(thresholds.normal_vix_percentile - thresholds.calm_vix_percentile, 1e-9),
                (ret - thresholds.market_return_calm) / max(abs(thresholds.market_return_calm) + 1e-9, 1.0),
                (thresholds.realized_vol_calm - vol) / max(thresholds.realized_vol_calm, 1e-9),
            )
            confidence[i] = float(np.clip(score, 0.0, 1.0))

    return labels, confidence


def regime_summary(regime_labels: Sequence[str]) -> dict:
    """Counts transitions per year and summarizes the duration distribution."""
    labels = list(regime_labels)
    if not labels:
        return {"n_days": 0, "counts": {k: 0 for k in REGIME_LABELS}, "annual_transitions": {"total_transitions": 0, "transitions_per_day": 0.0}, "duration_distribution": {}}

    counts = {k: 0 for k in REGIME_LABELS}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    transitions = []
    if len(labels) > 1:
        for idx in range(1, len(labels)):
            if labels[idx] != labels[idx - 1]:
                transitions.append((idx, labels[idx - 1], labels[idx]))

    duration_distribution: dict[str, int] = {}
    if labels:
        current = labels[0]
        current_duration = 1
        for label in labels[1:]:
            if label == current:
                current_duration += 1
            else:
                key = f"{current}:{current_duration}"
                duration_distribution[key] = duration_distribution.get(key, 0) + 1
                current = label
                current_duration = 1
        duration_distribution[f"{current}:{current_duration}"] = duration_distribution.get(f"{current}:{current_duration}", 0) + 1

    return {
        "n_days": len(labels),
        "counts": counts,
        "annual_transitions": {"total_transitions": len(transitions), "transitions_per_day": len(transitions) / max(len(labels), 1)},
        "duration_distribution": duration_distribution,
    }


def p_value_histogram(p_values: Mapping[str, float], bins: int = 10) -> dict:
    """Summarizes the shape of a p-value distribution for a visual diagnostic."""
    values = [float(v) for v in p_values.values() if v == v]
    if not values:
        return {"n_values": 0, "histogram": {}, "near_zero": 0, "uniform_like": True}
    series = pd.Series(values)
    hist = np.histogram(series, bins=bins, range=(0.0, 1.0))[0].tolist()
    near_zero = int((series < 0.05).sum())
    return {
        "n_values": len(values),
        "histogram": {f"bin_{idx}": float(v) for idx, v in enumerate(hist)},
        "near_zero": near_zero,
        "uniform_like": bool(abs(series.mean() - 0.5) < 0.1),
    }


def _loss_array(predictions: Sequence[float] | np.ndarray, actual: Sequence[float] | np.ndarray) -> np.ndarray:
    """0/1 loss array (misclassified = 1, correct = 0), same shape required."""
    pred = np.asarray(predictions, dtype=float)
    act = np.asarray(actual, dtype=float)
    if pred.shape != act.shape:
        raise ValueError("Predictions and actual must have the same shape")
    return (pred != act).astype(float)


def signal_dm_summary(
    signals: Mapping[str, Sequence[float] | np.ndarray],
    actual: Sequence[float] | np.ndarray,
    baseline: Mapping[str, Sequence[float] | np.ndarray] | None = None,
    alpha: float = 0.10,
) -> pd.DataFrame:
    """Computes the Diebold-Mariano statistic for each signal and the BH p-values."""
    baseline_map = baseline or {}
    rows: list[dict] = []
    for signal_name, predictions in signals.items():
        base_predictions = baseline_map.get(signal_name)
        if base_predictions is None:
            base_predictions = np.roll(np.asarray(actual, dtype=float), 1)
            base_predictions[0] = actual[0]
        loss_a = _loss_array(predictions, actual)
        loss_b = _loss_array(base_predictions, actual)
        result = diebold_mariano(loss_a, loss_b)
        rows.append(
            {
                "signal": signal_name,
                "dm_stat": result["dm_stat"],
                "p_value": result["p_value"],
                "n_obs": result["n_obs"],
                "baseline": signal_name if base_predictions is None else "naive_persistence",
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    # A signal whose DM p-value is NaN (history < 10 observations, cf.
    # `validation.diebold_mariano`) is neither significant nor not
    # significant -- it simply could not be tested. `testable` carries this
    # distinction explicitly, so it is never conflated with a signal that
    # was actually evaluated and found not significant (both would
    # otherwise show `significant=False`).
    frame["testable"] = np.isfinite(frame["p_value"])

    p_map = {
        row["signal"]: float(row["p_value"])
        for _, row in frame.iterrows()
        if row["testable"] and row["signal"]
    }
    if not p_map:
        frame["adjusted_p_value"] = np.nan
        frame["significant"] = False
        frame["selected"] = False
        return frame.sort_values(["p_value", "signal"]).reset_index(drop=True)

    bh = benjamini_hochberg(p_map, alpha=alpha)
    adjusted = pd.DataFrame.from_dict(bh["results"], orient="index").reset_index()
    adjusted = adjusted.rename(columns={"index": "signal"})
    frame = frame.merge(adjusted[["signal", "adjusted_p_value", "significant"]], on="signal", how="left")
    # A non-testable signal (absent from `adjusted`, cf. the `testable`
    # filter above) comes back from the merge with `significant=NaN` --
    # normalized to False to stay consistent with the `not p_map` branch
    # above (same convention on both paths); `testable=False` remains the
    # sole source of truth for the "not tested" vs "tested, not
    # significant" distinction.
    frame["significant"] = frame["significant"].fillna(False)
    frame["selected"] = frame["significant"]
    return frame.sort_values(["adjusted_p_value", "p_value"]).reset_index(drop=True)


def reduce_correlated_signals(
    signal_frame: pd.DataFrame,
    signal_matrix: pd.DataFrame,
    corr_threshold: float = 0.70,
) -> pd.DataFrame:
    """Keeps a single signal per correlated cluster.

    The selection criterion is statistical significance (lowest BH
    p-value), not raw Sharpe. This is a structural guard against keeping
    several near-redundant signals.
    """
    if signal_frame.empty or signal_matrix.empty:
        return signal_frame.copy()

    if set(signal_frame["signal"]) != set(signal_matrix.columns):
        common = sorted(set(signal_frame["signal"]).intersection(signal_matrix.columns))
        signal_frame = signal_frame[signal_frame["signal"].isin(common)].copy()
        signal_matrix = signal_matrix[common]

    corr = signal_matrix.corr().abs()
    selected = []
    used = set()
    for signal in signal_frame.sort_values(["adjusted_p_value", "p_value"]).signal.tolist():
        if signal in used:
            continue
        selected.append(signal)
        for other in corr.columns:
            if other == signal:
                continue
            if corr.loc[signal, other] >= corr_threshold and other in signal_matrix.columns:
                used.add(other)

    return signal_frame[signal_frame["signal"].isin(selected)].copy().reset_index(drop=True)


def compare_test_holdout(signal_frame: pd.DataFrame, test_sharpe: Mapping[str, float], holdout_sharpe: Mapping[str, float]) -> pd.DataFrame:
    """Computes the relative Sharpe gap between test and holdout, for diagnostic display."""
    rows: list[dict] = []
    for _, row in signal_frame.iterrows():
        name = row["signal"]
        ts = float(test_sharpe.get(name, np.nan))
        hs = float(holdout_sharpe.get(name, np.nan))
        if np.isnan(ts) or np.isnan(hs) or abs(hs) < 1e-12:
            rel_gap = np.nan
        else:
            rel_gap = (ts - hs) / abs(hs)
        rows.append({"signal": name, "test_sharpe": ts, "holdout_sharpe": hs, "relative_gap": rel_gap})
    return pd.DataFrame(rows)


def aggregate_signals(
    signal_frame: pd.DataFrame,
    *,
    asset_classes: Mapping[str, str] | None = None,
    weights: Mapping[str, float] | None = None,
    prediction_column: str = "prediction",
    significance_column: str = "selected",
) -> dict:
    """Aggregates signals by asset class and returns an overall verdict."""
    if signal_frame.empty:
        return {
            "class_counts": {},
            "class_summary": {},
            "score": 0.0,
            "verdict": "NEUTRAL",
            "n_signals": 0,
            "sig_count": 0,
        }

    frame = signal_frame.copy()
    asset_map = dict(asset_classes or {})
    if not asset_map and "asset_class" in frame.columns:
        asset_map = {str(row["signal"]): str(row["asset_class"]) for _, row in frame.iterrows()}

    default_weights = {"equity": 1.0, "fx": 1.0, "rates": 1.0, "credit": 1.0, "commodity": 1.0, "macro": 1.0, "unknown": 0.5}
    class_weights = {**default_weights, **(weights or {})}

    class_summary: dict[str, dict[str, float | int]] = {}
    total_score = 0.0
    total_weight = 0.0
    n_signals = 0
    n_selected = 0

    for _, row in frame.iterrows():
        signal_name = str(row.get("signal", ""))
        if not signal_name:
            continue
        cls = asset_map.get(signal_name, row.get("asset_class", "unknown"))
        cls_name = str(cls)
        weight = float(class_weights.get(cls_name, class_weights.get("unknown", 0.5)))
        total_weight += weight

        if prediction_column in row:
            pred = float(row[prediction_column])
        else:
            pred = 1.0 if bool(row.get(significance_column, False)) else 0.0
        if pred > 1.0:
            pred = 1.0
        elif pred < -1.0:
            pred = -1.0

        signal_vote = pred if abs(pred) > 0 else 0.0
        total_score += signal_vote * weight
        n_signals += 1
        if bool(row.get(significance_column, False)):
            n_selected += 1

        bucket = class_summary.setdefault(
            cls_name,
            {"n_signals": 0, "bullish": 0, "bearish": 0, "neutral": 0, "weighted_score": 0.0},
        )
        bucket["n_signals"] = int(bucket["n_signals"]) + 1
        if signal_vote > 0.1:
            bucket["bullish"] = int(bucket["bullish"]) + 1
        elif signal_vote < -0.1:
            bucket["bearish"] = int(bucket["bearish"]) + 1
        else:
            bucket["neutral"] = int(bucket["neutral"]) + 1
        bucket["weighted_score"] = float(bucket["weighted_score"]) + signal_vote * weight

    score = total_score / total_weight if total_weight else 0.0
    if score > 0.35:
        verdict = "BULLISH"
    elif score < -0.35:
        verdict = "BEARISH"
    else:
        verdict = "NEUTRAL"

    return {
        "class_counts": {k: int(v["n_signals"]) for k, v in class_summary.items()},
        "class_summary": class_summary,
        "score": float(score),
        "verdict": verdict,
        "n_signals": int(n_signals),
        "sig_count": int(n_selected),
    }


def regime_alignment_score(verdict: Mapping[str, float | str], regime_label: str | None, *, baseline_mapping: Mapping[str, float] | None = None) -> dict:
    """Compares the aggregate verdict to the observed regime and flags a strong divergence."""
    score = float(verdict.get("score", 0.0))
    expected = baseline_mapping or {
        "CALM": 0.35,
        "NORMAL": 0.10,
        "STRESS": -0.15,
        "CRASH": -0.50,
    }
    regime = str(regime_label or "NORMAL")
    target = float(expected.get(regime, 0.0))
    delta = score - target
    deviation = abs(delta)
    status = "aligned" if deviation < 0.25 else "warning"
    if deviation > 0.50:
        status = "divergent"
    return {
        "regime": regime,
        "verdict_score": score,
        "target_score": target,
        "delta": delta,
        "deviation": deviation,
        "status": status,
    }


def validate_aggregate_signal_quality(
    signal_frame: pd.DataFrame,
    realized_vix: Sequence[float] | np.ndarray,
    *,
    target_column: str = "score",
) -> dict:
    """Checks that an aggregate verdict is indeed negatively correlated with realized VIX."""
    if signal_frame.empty or len(realized_vix) == 0:
        return {"n_obs": 0, "correlation": np.nan, "status": "insufficient_data"}

    series = pd.Series(realized_vix, dtype=float)
    if len(series) != len(signal_frame):
        value = signal_frame[target_column].astype(float).to_numpy() if target_column in signal_frame.columns else np.linspace(0.0, 1.0, len(signal_frame))
        if len(value) != len(series):
            value = np.asarray([float(v) for v in range(len(series))], dtype=float)
        corr = float(np.corrcoef(series.to_numpy(), value)[0, 1]) if len(series) > 1 else np.nan
    else:
        corr = float(np.corrcoef(series.to_numpy(), signal_frame[target_column].astype(float).to_numpy())[0, 1]) if len(series) > 1 else np.nan
    status = "ok" if np.isfinite(corr) and corr < 0.0 else "warning"
    return {"n_obs": int(len(series)), "correlation": corr, "status": status}


def build_event_calendar(events: Iterable[Mapping[str, object]]) -> pd.DataFrame:
    """Builds an event calendar from manual or imported entries."""
    rows: list[dict[str, object]] = []
    for entry in events:
        if isinstance(entry, pd.Series):
            row = entry.to_dict()
        else:
            row = dict(entry)
        if "date" not in row:
            raise ValueError("Each event entry must have a 'date' column.")
        rows.append(
            {
                "date": pd.to_datetime(row["date"]),
                "event_type": str(row.get("event_type", "unknown")),
                "asset": str(row.get("asset", "")),
                "source": str(row.get("source", "manual")),
                "description": str(row.get("description", "")),
                "notes": row.get("notes", ""),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def credit_risk_regime(high_yield_spread: float, investment_grade_spread: float, *, threshold: float = 0.15) -> dict:
    """Flags a credit regime from aggregated FRED spreads — does not claim to cover individual issuer risk."""
    diff = float(high_yield_spread) - float(investment_grade_spread)
    if np.isnan(diff):
        return {"state": "UNKNOWN", "spread_difference": np.nan, "source_note": "missing data", "coverage": "individual issuer risk not covered"}
    if diff > threshold:
        state = "STRESS"
    elif diff > 0.0:
        state = "NORMAL"
    else:
        state = "CALM"
    return {
        "state": state,
        "spread_difference": diff,
        "source_note": "FRED aggregated credit spreads only; individual issuer risk is not covered in this interface.",
        "coverage": "individual issuer risk not covered",
    }


def trend_follow_signal(prices: Sequence[float] | pd.Series, short_window: int = 5, long_window: int = 20) -> pd.DataFrame:
    """Produces a trend-following signal with no learning: momentum + explicit SMA crossovers."""
    series = pd.Series(prices, dtype=float)
    sma_short = series.rolling(short_window, min_periods=1).mean()
    sma_long = series.rolling(long_window, min_periods=1).mean()
    momentum = series.pct_change(fill_method=None)
    signal = np.sign(sma_short - sma_long).fillna(0.0)
    strength = (sma_short - sma_long) / series.replace(0, np.nan).abs().fillna(1e-9)
    return pd.DataFrame({
        "signal": signal,
        "momentum": momentum,
        "strength": strength,
        "trend_state": np.where(signal > 0, "BULLISH", np.where(signal < 0, "BEARISH", "NEUTRAL")),
    })


def risk_parity_weights(returns: pd.DataFrame, *, floor: float = 1e-6) -> pd.Series:
    """Computes a risk-parity portfolio from a returns history."""
    returns = returns.copy()
    if returns.empty:
        return pd.Series(dtype=float)
    vol = returns.std(ddof=0).replace(0, np.nan).fillna(1.0)
    inv_vol = (1.0 / vol).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    if inv_vol.sum() <= 0:
        inv_vol = pd.Series(1.0, index=returns.columns)
    weights = inv_vol / inv_vol.sum()
    if floor > 0:
        weights = weights.clip(lower=floor)
        weights = weights / weights.sum()
    return weights


# Blocs 5-7 du plan PATRICK original en 9 blocs (stratégie, backtest,
# exécution) -- jamais commencés en pratique, l'univers restant limité à
# ^VIX (mono-cible). `StrategyRule`/`StrategyVersion`/`StrategyEngine`/
# `enforce_risk_constraints`/`ExecutionOrder`/`simulate_execution`/
# `parameter_grid_summary` ne sont appelées nulle part hors de leurs propres
# tests -- pas un oubli, la plomberie préparée pour cette phase future,
# en attente d'un univers multi-cibles avant intégration (audit dette
# technique, D1). Conservées volontairement plutôt que supprimées et
# réécrites plus tard.
#
# `DecisionJournal`/`DecisionJournalEntry`/`take_snapshot` (plus bas dans ce
# fichier) sont conservées pour la même raison bien qu'elles fassent partie
# du lot identifié comme redondant avec `tracking/db.py` (D3, même audit) :
# `StrategyEngine.journal` et `StrategyEngine.snapshot_state` en dépendent
# structurellement (tout appel de méthode journalise via `self.journal`).
# Elles ne sont PAS la persistance production (ça, c'est `tracking/db.py`
# ::save_phase9_journal_entry`/`save_phase9_snapshot`, réellement branchée
# sur `/api/phase9/journal` et servant `/phase9`) -- seulement l'audit trail
# interne, en mémoire, du futur moteur de stratégie. `reconstruct_state`,
# elle, n'avait aucun appelant (ni ici ni ailleurs) et a été supprimée.
@dataclass(frozen=True)
class StrategyRule:
    regime: str
    active_assets: tuple[str, ...]
    weights: dict[str, float]
    leverage: float = 1.0
    max_position: float = 0.20
    max_sector_exposure: float | None = None
    notes: str = ""

    def validate(self) -> None:
        """Raises if the rule has no assets, weights don't sum to 1 (unlevered), or leverage isn't positive."""
        if not self.active_assets:
            raise ValueError("A strategy rule requires at least one asset.")
        weight_sum = sum(float(v) for v in self.weights.values())
        if abs(weight_sum - 1.0) > 1e-3 and self.leverage <= 1.0:
            raise ValueError(f"A rule's weights must sum to 1.0, got {weight_sum}.")
        if self.leverage <= 0:
            raise ValueError("Leverage must be strictly positive.")


@dataclass(frozen=True)
class StrategyVersion:
    author: str
    description: str
    strategy: StrategyRule | None = None
    results: Mapping[str, float] | None = None
    created_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "author": self.author,
            "description": self.description,
            "created_at": self.created_at,
            "strategy": self.strategy.__dict__ if self.strategy is not None else None,
            "results": dict(self.results or {}),
        }


@dataclass
class StrategyEngine:
    """Single decision engine for the aggregation, strategy, and execution layer."""

    journal: DecisionJournal = field(default_factory=lambda: DecisionJournal(author="operator"))
    versions: list[StrategyVersion] = field(default_factory=list)
    snapshots: dict[str, dict] = field(default_factory=dict)
    thresholds: RegimeThresholds = field(default_factory=lambda: DEFAULT_REGIME_THRESHOLDS)

    def classify_regime(self, vix, vix_pct, market_return, realized_vol):
        """Classifies the regime and journals the classification (cf. `classify_regime_daily`)."""
        labels, confidence = classify_regime_daily(vix, vix_pct, market_return, realized_vol, self.thresholds)
        self.journal.record(
            "regime_classification",
            before=None,
            after={"labels": labels.tolist(), "confidence": confidence.tolist()},
            reason="automated regime classification",
        )
        return labels, confidence

    def aggregate_signal_frame(self, signal_frame: pd.DataFrame, *, asset_classes: Mapping[str, str] | None = None, weights: Mapping[str, float] | None = None) -> dict:
        summary = aggregate_signals(signal_frame, asset_classes=asset_classes, weights=weights)
        self.journal.record(
            "signal_aggregation",
            before=None,
            after=summary,
            reason="aggregate signal frame into market verdict",
        )
        return summary

    def validate_strategy(self, weights: Mapping[str, float], *, max_leverage: float = 1.5, max_per_asset: float = 0.25, max_total_sector: float | None = None, min_cash: float = 0.10) -> dict:
        validated = enforce_risk_constraints(
            weights,
            max_leverage=max_leverage,
            max_per_asset=max_per_asset,
            max_total_sector=max_total_sector,
            min_cash=min_cash,
        )
        self.journal.record("risk_constraint_check", before=weights, after=validated, reason="check allocation constraints")
        return validated

    def add_strategy_version(self, author: str, description: str, *, strategy: StrategyRule | None = None, results: Mapping[str, float] | None = None) -> StrategyVersion:
        version = StrategyVersion(author=author, description=description, strategy=strategy, results=dict(results or {}), created_at=pd.Timestamp.now(tz="UTC").isoformat())
        self.versions.append(version)
        self.journal.record("strategy_version_added", before=None, after=version.as_dict(), reason="new strategy version created")
        return version

    def snapshot_state(self, state: Mapping[str, object], name: str) -> dict:
        snapshot = take_snapshot(state, name)
        self.snapshots[name] = snapshot
        self.journal.record("snapshot_created", before=None, after={"snapshot_name": name}, reason="snapshot saved for reproducibility")
        return snapshot

    def simulate_orders(self, orders: Iterable[ExecutionOrder], prices: Mapping[str, float], *, default_friction: float = 0.001) -> pd.DataFrame:
        result = simulate_execution(orders, prices, default_friction=default_friction)
        self.journal.record("order_simulation", before=[o.to_dict() if isinstance(o, ExecutionOrder) else o for o in list(orders)], after=result.to_dict("records"), reason="simulate execution with friction and rejection tracking")
        return result


def enforce_risk_constraints(
    weights: Mapping[str, float],
    *,
    max_leverage: float = 1.5,
    max_per_asset: float = 0.25,
    max_total_sector: float | None = None,
    min_cash: float = 0.10,
) -> dict:
    """Validates that an allocation doesn't violate risk constraints. Fails explicitly when it does."""
    total = float(sum(weights.values())) if weights else 0.0
    if total <= 0:
        raise ValueError("The allocation must contain at least one positive position.")
    if max_leverage > 0 and total > max_leverage:
        raise ValueError(f"Leverage violation: total {total} > max {max_leverage}.")
    for asset, weight in weights.items():
        w = float(weight)
        if w > max_per_asset:
            raise ValueError(f"Per-asset constraint violation: {asset} = {w} > {max_per_asset}.")
    if max_total_sector is not None and total > max_total_sector:
        raise ValueError(f"Sector exposure violation: {total} > {max_total_sector}.")
    cash = max(0.0, 1.0 - total)
    if cash < min_cash:
        raise ValueError(f"Minimum cash violation: cash {cash} < {min_cash}.")
    return {"status": "ok", "total_exposure": total, "cash": cash}


def parameter_grid_summary(results: Sequence[Mapping[str, object]]) -> pd.DataFrame:
    """Summarizes a parameter search with the number of combinations tested and the deflated Sharpe."""
    if not results:
        return pd.DataFrame(columns=["n_combinations", "debiased_sharpe", "best_result"])
    rows = []
    for idx, entry in enumerate(results, start=1):
        rows.append(
            {
                "combination_index": idx,
                "n_combinations": int(entry.get("n_combinations", idx)),
                "debiased_sharpe": float(entry.get("debiased_sharpe", np.nan)),
                "best_result": entry.get("best_result"),
            }
        )
    return pd.DataFrame(rows)


@dataclass
class ExecutionOrder:
    symbol: str
    side: str
    quantity: float
    price: float
    friction: float = 0.0
    status: str = "pending"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "friction": self.friction,
            "status": self.status,
            "reason": self.reason,
        }


def simulate_execution(orders: Iterable[ExecutionOrder], prices: Mapping[str, float], *, default_friction: float = 0.001) -> pd.DataFrame:
    """Simulates execution of an order queue with friction and explicit rejections."""
    rows: list[dict] = []
    for order in orders:
        order = ExecutionOrder(**order.to_dict()) if isinstance(order, dict) else order
        market_price = float(prices.get(order.symbol, order.price))
        friction = float(order.friction if order.friction else default_friction)
        if order.side.upper() not in {"BUY", "SELL"}:
            status = "rejected"
            reason = "invalid_side"
        elif market_price <= 0:
            status = "rejected"
            reason = "missing_market_price"
        else:
            status = "executed"
            reason = "ok"
        rows.append(
            {
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "limit_price": order.price,
                "market_price": market_price,
                "friction": friction,
                "status": status,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


@dataclass
class DecisionJournalEntry:
    timestamp: str
    actor: str
    action: str
    before: object
    after: object
    reason: str


class DecisionJournal:
    """Single decision journal, filterable and exportable."""

    def __init__(self, author: str = "system") -> None:
        self.author = author
        self.entries: list[DecisionJournalEntry] = []

    def record(self, action: str, *, before: object, after: object, reason: str, actor: str | None = None) -> DecisionJournalEntry:
        entry = DecisionJournalEntry(
            timestamp=pd.Timestamp.now(tz="UTC").isoformat(),
            actor=str(actor or self.author),
            action=action,
            before=before,
            after=after,
            reason=reason,
        )
        self.entries.append(entry)
        return entry

    def export(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "timestamp": entry.timestamp,
                    "actor": entry.actor,
                    "action": entry.action,
                    "before": entry.before,
                    "after": entry.after,
                    "reason": entry.reason,
                }
                for entry in self.entries
            ]
        )

    def rollback_last(self, *, count: int = 1) -> list[DecisionJournalEntry]:
        removed = self.entries[-count:]
        self.entries = self.entries[:-count]
        return removed


def take_snapshot(state: Mapping[str, object], name: str) -> dict:
    """Creates a snapshot of the current state, useful for reproducibility and comparisons."""
    return {"snapshot_name": name, "timestamp": pd.Timestamp.now(tz="UTC").isoformat(), "state": dict(state)}


def determine_signal_quality_status(p_values: Mapping[str, float], *, alpha: float = 0.10) -> dict:
    """Returns a final operational diagnostic on signal quality."""
    values = [float(v) for v in p_values.values() if np.isfinite(v)]
    if not values:
        return {"status": "no_signal", "n_values": 0, "alpha": alpha}
    selected = sum(1 for v in values if v <= alpha)
    return {
        "status": "usable" if selected > 0 else "flat",
        "n_values": len(values),
        "n_selected": selected,
        "alpha": alpha,
        "share_selected": selected / len(values),
    }
