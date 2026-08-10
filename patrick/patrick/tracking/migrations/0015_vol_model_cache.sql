-- Cache for the parametric volatility-model computations (EGARCH/Kalman/HMM,
-- see features/vol_models.py::_PARAMETRIC_MODELS) -- same reasoning as
-- shap_selection_cache (migration 0014): a snapshot is immutable once
-- created, so a cache entry here never goes stale on its own. The only
-- invalidation is a change in one of the key fields.
--
-- Key: (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash).
-- `data_hash` (sha256 of the actual series content passed in) is the
-- correctness guarantee, same role as the SHAP cache's data_hash -- two
-- calls with the same fit_end_idx/test_end_idx but a different series
-- content (e.g. after a data correction) must not share an entry.
--
-- `model` alone (no per-model hyperparameter columns, e.g. no p/o/q) is
-- deliberate, not an oversight: EGARCH/Kalman/HMM/AR/MA/ARMA/ARIMA each
-- have entirely different hyperparameter shapes (p/o/q, n_states+seed,
-- lags, ...), and NONE of them are exposed via RunConfig anywhere in the
-- codebase today -- every one is a hardcoded default inside its own
-- function. `model` is therefore already a complete discriminator among
-- everything actually reachable through this cache. If a future change
-- exposes any of these hyperparameters via config, THIS KEY MUST BE
-- EXTENDED (or the corresponding call sites must stop sharing this cache) --
-- otherwise two genuinely different configurations of the same model could
-- silently collide under one cache entry.
-- fit_end_idx/test_end_idx are stored as -1 rather than NULL when absent
-- (e.g. the final production model, fit on the whole series -- see
-- vol_models.py module docstring): SQLite does not treat NULL as equal to
-- itself for composite PRIMARY KEY uniqueness, so two "no fit_end_idx"
-- inserts would not conflict/dedupe correctly if left NULL. -1 is a safe
-- sentinel since fit_end_idx/test_end_idx are otherwise always >= 0 indices.
CREATE TABLE vol_model_cache (
    snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    model TEXT NOT NULL,
    fit_end_idx INTEGER NOT NULL,
    test_end_idx INTEGER NOT NULL,
    data_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash)
);
