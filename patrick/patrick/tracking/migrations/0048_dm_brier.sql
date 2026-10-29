-- Test de Diebold-Mariano sur un score CONTINU (2026-10-29, ADR 0010) : l'erreur quadratique de P(hausse) du modèle (Brier) contre celle
-- d'une baseline probabiliste, le taux de hausse de l'entraînement. Une perte 0/1 jette l'information de confiance du modèle et manque de
-- puissance sur un holdout de quelques centaines de lignes. Table à part : `dm_result.kind` est contraint à 'class_specific' / 'common'.
CREATE TABLE IF NOT EXISTS dm_brier_result (
    run_id TEXT NOT NULL PRIMARY KEY REFERENCES run(run_id) ON DELETE CASCADE,
    baseline TEXT NOT NULL,
    brier_model REAL NOT NULL,
    brier_baseline REAL NOT NULL,
    dm_stat REAL,
    p_value REAL,
    n_obs INTEGER,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
