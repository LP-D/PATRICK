__version__ = "0.1.0"

# Re-export explicite (PEP 484 `X as X`) -- signale à ruff (et à un
# typechecker) que ces symboles sont intentionnellement exposés au niveau
# du package, pas juste importés puis oubliés. Aucun de ces symboles n'a
# d'appelant réel ailleurs dans le code applicatif à ce jour (cf. rapport
# d'audit, lot 2, item C) -- la surface reste large par prudence, un
# consommateur externe du package pouvant en dépendre directement.
from patrick.phase9 import (
    DEFAULT_REGIME_THRESHOLDS as DEFAULT_REGIME_THRESHOLDS,
    DecisionJournal as DecisionJournal,
    ExecutionOrder as ExecutionOrder,
    RegimeThresholds as RegimeThresholds,
    StrategyEngine as StrategyEngine,
    StrategyRule as StrategyRule,
    StrategyVersion as StrategyVersion,
    aggregate_signals as aggregate_signals,
    build_event_calendar as build_event_calendar,
    classify_regime_daily as classify_regime_daily,
    compare_test_holdout as compare_test_holdout,
    credit_risk_regime as credit_risk_regime,
    determine_signal_quality_status as determine_signal_quality_status,
    enforce_risk_constraints as enforce_risk_constraints,
    p_value_histogram as p_value_histogram,
    parameter_grid_summary as parameter_grid_summary,
    reduce_correlated_signals as reduce_correlated_signals,
    regime_alignment_score as regime_alignment_score,
    regime_summary as regime_summary,
    risk_parity_weights as risk_parity_weights,
    signal_dm_summary as signal_dm_summary,
    simulate_execution as simulate_execution,
    take_snapshot as take_snapshot,
    trend_follow_signal as trend_follow_signal,
    validate_aggregate_signal_quality as validate_aggregate_signal_quality,
)
