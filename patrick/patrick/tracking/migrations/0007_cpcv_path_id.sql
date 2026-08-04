-- Phase 6.1 (P6.1) -- CPCV : une même date de test peut être évaluée par
-- PLUSIEURS combinaisons différentes (chaque groupe de test apparaît dans
-- C(N-1,k-1) combinaisons), chacune assignée à un chemin de backtest
-- distinct (`path_id`) -- (trial_id, ts) seul ne suffit plus à identifier
-- une prédiction. `path_id = -1` (pas NULL, pour éviter la sémantique
-- "chaque NULL distinct" de SQLite dans une clé composite) : sentinelle
-- "sans objet" pour toute prédiction walk-forward (comportement inchangé).
-- Recréation de table (SQLite ne permet pas d'ALTER une PRIMARY KEY).
CREATE TABLE prediction_new (
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    fold_index INTEGER,
    split TEXT NOT NULL,
    y_true REAL,
    y_pred REAL NOT NULL,
    y_proba REAL,
    path_id INTEGER NOT NULL DEFAULT -1,
    PRIMARY KEY (trial_id, ts, path_id)
);
INSERT INTO prediction_new (trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id)
    SELECT trial_id, ts, fold_index, split, y_true, y_pred, y_proba, -1 FROM prediction;
DROP TABLE prediction;
ALTER TABLE prediction_new RENAME TO prediction;
CREATE INDEX idx_pred_split ON prediction(split, ts);
CREATE INDEX idx_pred_path ON prediction(path_id);
