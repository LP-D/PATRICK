-- Test de Diebold-Mariano sur la LOG-LOSS de P(hausse) (2026-11-24, ADR 0003 « un score continu serait plus puissant ») : en plus du Brier
-- (0048, ADR 0010). La log-loss pénalise bien plus fort une probabilité confiante et fausse : un modèle bien calibré mais trop sûr de lui
-- peut gagner au Brier et perdre ici. Même baseline (taux de hausse de l'entraînement), table à part comme `dm_brier_result`.
CREATE TABLE IF NOT EXISTS dm_logloss_result (
    run_id TEXT NOT NULL PRIMARY KEY REFERENCES run(run_id) ON DELETE CASCADE,
    baseline TEXT NOT NULL,
    logloss_model REAL NOT NULL,
    logloss_baseline REAL NOT NULL,
    dm_stat REAL,
    p_value REAL,
    n_obs INTEGER,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
