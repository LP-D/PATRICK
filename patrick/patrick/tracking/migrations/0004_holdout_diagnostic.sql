-- Rapport d'audit (session de correction), C4 -- diagnostic holdout EN LECTURE
-- SEULE : `fold_metric[split='holdout']` (Phase 2.1) n'est peuplé QUE pour le
-- trial gagnant (`is_best=1`), jamais pour l'ensemble de la grille SCAN --
-- structurellement, il n'existe donc qu'un seul point (test, holdout) par run,
-- rendant impossible toute corrélation de rang entre classement test et
-- classement holdout (constat de l'audit, section E : Spearman non calculable,
-- n=1). `holdout_diagnostic` stocke le score holdout de TOUS les trials de la
-- grille SCAN dans une table SÉPARÉE de `fold_metric`, pour permettre ce
-- diagnostic -- jamais lue par la sélection/le leaderboard/le tuning (garanti
-- par tests/test_holdout_diagnostic_isolation.py), seulement par le rapport.
CREATE TABLE holdout_diagnostic (
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (trial_id, metric)
);
CREATE INDEX idx_holdout_diag_trial ON holdout_diagnostic(trial_id);
