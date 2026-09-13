-- Chantier feature/drift-psi-infrastructure -- on-demand data-drift (PSI)
-- monitoring, built on the same feature-reconstruction path already used
-- by `explain.py::explain_last_prediction` (no parallel data path).
--
-- `drift_feature_reference`: ONE row per (symbol, horizon, feature) --
-- REPLACED (upsert), never accumulated, at each re-fit (`export_best_model`)
-- -- this is a decile reference (bin edges + expected proportions,
-- `patrick.validation.drift.decile_reference`), not a raw sample dump, so
-- it stays small regardless of training-window size.
CREATE TABLE drift_feature_reference (
    symbol TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    feature TEXT NOT NULL,
    reference_json TEXT NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, horizon, feature)
);

-- `drift_psi_history`: the ONE legitimate accumulating time series here --
-- one row per on-demand PSI computation (never a periodic job, never a
-- batch precompute over every ticker -- see
-- `explain.py::compute_drift_for_ticker_horizon`'s docstring for why).
CREATE TABLE drift_psi_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    feature TEXT NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    psi REAL NOT NULL
);
CREATE INDEX idx_drift_psi_history_symbol_horizon ON drift_psi_history(symbol, horizon, computed_at);
