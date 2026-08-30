-- Phase-timing instrumentation for run_pipeline() (pipeline/engine.py):
-- answers "where does the wall time go" without a manual DB read-out after
-- the fact (2026-08-23 performance investigation -- GDAXI/FTSE/FCHI/GSPC
-- batches took as long or longer than a same-scale VIX batch with FEWER
-- Optuna trials and FEWER algos, and no phase breakdown existed anywhere
-- to explain why: `run.started_at`/`finished_at` was the only timing this
-- schema had before this migration).
--
-- One row per PHASE OCCURRENCE, not one row per (run_id, phase):
-- - `ingestion` and `pool_construction` happen ONCE per pipeline
--   invocation, before any run_id even exists (ingestion runs before
--   trackdb.create_run() is called for any horizon, see
--   pipeline/engine.py::run_pipeline) -- the same occurrence gets recorded
--   once per horizon's run_id afterwards, exactly like `run.started_at`
--   itself is already identical across a batch's horizons.
-- - `scan` is one row per run_id (the whole walk-forward/CPCV scan loop
--   for that horizon).
-- - `tuning` can be MULTIPLE rows per run_id: tune_config() is called once
--   per top-config, and a horizon can have more than one top-config. A
--   fixed PRIMARY KEY on (run_id, phase) would silently drop all but the
--   last occurrence -- autoincrement instead, sum per phase at query time
--   for a total (see tracking/history.py::phase_breakdown_for_run).
--
-- Known limitation, not fixed by this migration: in walk-forward mode,
-- `_FoldPoolBuilder` builds each fold's feature pool LAZILY, from inside
-- the scan loop (pipeline/engine.py::_FoldContext.prepare) -- only the
-- FIRST fold's pool build (before the scan loop starts) is cleanly
-- attributable to `pool_construction`; the remaining folds' pool
-- construction time is unavoidably counted inside `scan`. CPCV does not
-- have this issue (its pool is built entirely before its scan loop).
CREATE TABLE run_phase_timing (
    phase_timing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN ('ingestion', 'pool_construction', 'scan', 'tuning')),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE INDEX idx_phase_timing_run ON run_phase_timing(run_id, phase);
