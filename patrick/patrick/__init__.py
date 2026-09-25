__version__ = "0.1.0"

# Re-export explicite (PEP 484 `X as X`) -- signale à ruff (et à un
# typechecker) que ces symboles sont intentionnellement exposés au niveau
# du package, pas juste importés puis oubliés. Aucun de ces symboles n'a
# d'appelant réel ailleurs dans le code applicatif à ce jour (cf. rapport
# d'audit, lot 2, item C) -- la surface reste large par prudence, un
# consommateur externe du package pouvant en dépendre directement.
from patrick.phase9 import (
    DEFAULT_REGIME_THRESHOLDS as DEFAULT_REGIME_THRESHOLDS,
)
from patrick.phase9 import (
    DecisionJournal as DecisionJournal,
)
from patrick.phase9 import (
    ExecutionOrder as ExecutionOrder,
)
from patrick.phase9 import (
    RegimeThresholds as RegimeThresholds,
)
from patrick.phase9 import (
    StrategyEngine as StrategyEngine,
)
from patrick.phase9 import (
    StrategyRule as StrategyRule,
)
from patrick.phase9 import (
    StrategyVersion as StrategyVersion,
)
from patrick.phase9 import (
    aggregate_signals as aggregate_signals,
)
from patrick.phase9 import (
    build_event_calendar as build_event_calendar,
)
from patrick.phase9 import (
    classify_regime_daily as classify_regime_daily,
)
from patrick.phase9 import (
    compare_test_holdout as compare_test_holdout,
)
from patrick.phase9 import (
    credit_risk_regime as credit_risk_regime,
)
from patrick.phase9 import (
    determine_signal_quality_status as determine_signal_quality_status,
)
from patrick.phase9 import (
    enforce_risk_constraints as enforce_risk_constraints,
)
from patrick.phase9 import (
    p_value_histogram as p_value_histogram,
)
from patrick.phase9 import (
    parameter_grid_summary as parameter_grid_summary,
)
from patrick.phase9 import (
    reduce_correlated_signals as reduce_correlated_signals,
)
from patrick.phase9 import (
    regime_alignment_score as regime_alignment_score,
)
from patrick.phase9 import (
    regime_summary as regime_summary,
)
from patrick.phase9 import (
    risk_parity_weights as risk_parity_weights,
)
from patrick.phase9 import (
    signal_dm_summary as signal_dm_summary,
)
from patrick.phase9 import (
    simulate_execution as simulate_execution,
)
from patrick.phase9 import (
    take_snapshot as take_snapshot,
)
from patrick.phase9 import (
    trend_follow_signal as trend_follow_signal,
)
from patrick.phase9 import (
    validate_aggregate_signal_quality as validate_aggregate_signal_quality,
)
