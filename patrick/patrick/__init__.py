__version__ = "0.1.0"

# Ré-exports de `patrick.phase9`, chargés À LA DEMANDE (PEP 562) : un `import patrick` ne doit pas tirer
# pandas/scikit-learn (~1,7 s) pour le lanceur de bureau (`patrick.desktop`) et les réglages, qui n'en ont
# pas besoin. `from patrick import DecisionJournal` fonctionne comme avant. Aucun de ces symboles n'a
# d'appelant réel dans le code applicatif (rapport d'audit, lot 2, item C) : la surface reste large par
# prudence, un consommateur externe pouvant en dépendre.
_PHASE9_EXPORTS = (
    "DEFAULT_REGIME_THRESHOLDS",
    "DecisionJournal",
    "ExecutionOrder",
    "RegimeThresholds",
    "StrategyEngine",
    "StrategyRule",
    "StrategyVersion",
    "aggregate_signals",
    "build_event_calendar",
    "classify_regime_daily",
    "compare_test_holdout",
    "credit_risk_regime",
    "determine_signal_quality_status",
    "enforce_risk_constraints",
    "p_value_histogram",
    "parameter_grid_summary",
    "reduce_correlated_signals",
    "regime_alignment_score",
    "regime_summary",
    "risk_parity_weights",
    "signal_dm_summary",
    "simulate_execution",
    "take_snapshot",
    "trend_follow_signal",
    "validate_aggregate_signal_quality",
)


def __getattr__(name: str):
    if name in _PHASE9_EXPORTS:
        from patrick import phase9

        value = getattr(phase9, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'patrick' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_PHASE9_EXPORTS})
