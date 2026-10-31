-- Signal d'une paire cible-horizon en regroupant tous ses runs (2026-10-31, `validation/pooled_signal.py`) : AUC du score moyen des runs sur le
-- holdout, p-value d'un test de permutation par décalage circulaire (respecte le chevauchement des horizons), q-value de Benjamini-Hochberg
-- sur l'ensemble des paires. Table de RÉSULTATS recalculable (`patrick audit signal`), jamais une donnée de run : rien n'y est partagé
-- entre PC, chacun la recalcule depuis les prédictions du holdout.
CREATE TABLE IF NOT EXISTS pooled_signal (
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    n_runs INTEGER NOT NULL,
    n_dates INTEGER NOT NULL,
    auc REAL,
    auc_run_mean REAL,
    p_value REAL,
    q_value REAL,
    significant INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target, horizon)
);
