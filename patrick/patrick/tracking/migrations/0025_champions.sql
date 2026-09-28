-- Champion / challenger (2026-09-28): one model "in title" per (target,
-- horizon). A new run's model replaces it only if it scores a strictly
-- better F1_dir on the SAME holdout, both configurations retrained on the
-- SAME pre-holdout data (`pipeline/champion_duel.py`). The loser keeps only
-- its descriptive record in `model_archive`; its heavy rows (predictions,
-- fold metrics, trials, run) and model files are pruned. `trial_registry`
-- is never pruned: the DSR n_trials must count every configuration ever
-- tested.
CREATE TABLE IF NOT EXISTS champion (
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    trial_id INTEGER NOT NULL,
    promoted_at TEXT NOT NULL DEFAULT (datetime('now')),
    reason TEXT NOT NULL,
    holdout_f1_dir REAL,
    PRIMARY KEY (target, horizon)
);

CREATE TABLE IF NOT EXISTS model_archive (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    trial_id INTEGER,
    role TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT (datetime('now')),
    run_started_at TEXT,
    run_finished_at TEXT,
    snapshot_id TEXT,
    git_sha TEXT,
    algo TEXT,
    sampler TEXT,
    regime TEXT,
    n_features INTEGER,
    feature_names_json TEXT,
    params_json TEXT,
    wf_metrics_json TEXT,
    holdout_metrics_json TEXT,
    duel_json TEXT,
    live_json TEXT,
    config_json TEXT,
    pruned INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_model_archive_target_horizon ON model_archive (target, horizon, decided_at);
