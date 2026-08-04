-- Phase 6.1 (P6.1) -- `fold_metric.split` avait un CHECK figé sur les valeurs
-- walk-forward ('train', 'valid', 'test', 'holdout', 'live') : `split='test_path'`
-- (une ligne par CHEMIN de backtest CPCV, écrite par `pipeline/engine.py::
-- _run_cpcv_scan`, cf. `tracking/stats.py::pbo_for_target_cpcv`) violait cette
-- contrainte. Recréation de table (SQLite ne permet pas d'ALTER un CHECK).
CREATE TABLE fold_metric_new (
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('train', 'valid', 'test', 'holdout', 'live', 'test_path')),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (trial_id, fold_index, split, metric)
);
INSERT INTO fold_metric_new SELECT * FROM fold_metric;
DROP TABLE fold_metric;
ALTER TABLE fold_metric_new RENAME TO fold_metric;
CREATE INDEX idx_fold_trial ON fold_metric(trial_id, split, metric);
