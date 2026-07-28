-- Phase 1.2 — schéma de suivi des runs. Écart assumé par rapport au DDL fourni
-- initialement, documenté dans le rapport de phase : `trial.regime` ajouté (le
-- moteur boucle aussi sur les régimes, dimension absente du schéma d'origine —
-- sans elle, deux trials de régimes différents partageant (horizon, N, sampler,
-- algo) seraient indiscernables). `run` reste scopé à un seul (target, horizon) :
-- une invocation `patrick run` avec plusieurs horizons dans la config écrit
-- plusieurs lignes `run` (une par horizon), qui partagent le même snapshot_id.

CREATE TABLE snapshot (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    n_tickers INTEGER,
    n_fred_series INTEGER,
    fred_source TEXT CHECK (fred_source IN ('api', 'scrape'))
);

CREATE TABLE run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    git_sha TEXT NOT NULL,
    seed INTEGER NOT NULL,
    lib_versions TEXT NOT NULL,
    n_trials INTEGER,
    error TEXT
);

CREATE TABLE trial (
    trial_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    regime TEXT NOT NULL,
    algo TEXT NOT NULL,
    sampler TEXT NOT NULL,
    n_features INTEGER NOT NULL,
    selector TEXT NOT NULL,
    params_json TEXT NOT NULL,
    is_best INTEGER NOT NULL DEFAULT 0,
    artifact_path TEXT
);

CREATE TABLE fold_metric (
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('train', 'valid', 'test', 'holdout', 'live')),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (trial_id, fold_index, split, metric)
);

CREATE TABLE baseline_metric (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    baseline TEXT NOT NULL,
    split TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (run_id, baseline, split, metric)
);

CREATE TABLE prediction (
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    fold_index INTEGER,
    split TEXT NOT NULL,
    y_true REAL,
    y_pred REAL NOT NULL,
    y_proba REAL,
    PRIMARY KEY (trial_id, ts)
);

CREATE INDEX idx_run_target ON run(target, horizon, started_at);
CREATE INDEX idx_trial_run ON trial(run_id);
CREATE INDEX idx_fold_trial ON fold_metric(trial_id, split, metric);
CREATE INDEX idx_pred_split ON prediction(split, ts);
