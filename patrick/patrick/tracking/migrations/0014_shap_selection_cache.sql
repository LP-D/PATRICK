-- S3: dedicated table for the feature-selection cache (SHAP/RFE/LASSO), not
-- an extension of cache_manager.py::LocalCache -- that class is built around
-- a hardcoded TTL (`max_age_days`, weekly by default), which does not fit
-- data keyed by an immutable snapshot (no expiration, ever -- see S4). A
-- SQLite table matches this project's existing pattern for persisted,
-- non-expiring, keyed data (e.g. excluded_symbol, migration 0013).
--
-- Key: (target, horizon, snapshot_id, data_hash, selector_config_hash).
-- `data_hash` (sha256 of the actual X_tr/y_tr bytes) is the correctness
-- guarantee -- `target`/`horizon`/`snapshot_id` alone under-specify the
-- training data, since the SAME snapshot produces DIFFERENT (X_tr, y_tr)
-- per regime and per fold/CPCV-combo. `selector_config_hash` covers the
-- selector parameters that actually influence the result (method, n_feat,
-- shap_sample, pool_prefilter, seed) -- NOT sampler/algo/model
-- hyperparameters, which never reach the selection step.
CREATE TABLE shap_selection_cache (
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    selector_config_hash TEXT NOT NULL,
    selected_columns TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target, horizon, snapshot_id, data_hash, selector_config_hash)
);
