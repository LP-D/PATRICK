-- Transparent first-fold screening decisions. The complete first-fold score
-- remains visible for every candidate; only later walk-forward folds are
-- restricted to finalists. Deleting a run cascades its screening detail.
CREATE TABLE IF NOT EXISTS screening_decision (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    horizon INTEGER NOT NULL,
    regime TEXT NOT NULL,
    n_features INTEGER NOT NULL,
    sampler TEXT NOT NULL,
    algo TEXT NOT NULL,
    score REAL,
    rank INTEGER,
    decision TEXT NOT NULL CHECK (decision IN ('finalist', 'screened_out')),
    reason TEXT NOT NULL,
    PRIMARY KEY (run_id, regime, n_features, sampler, algo)
);

CREATE INDEX IF NOT EXISTS idx_screening_decision_run ON screening_decision(run_id, rank);
