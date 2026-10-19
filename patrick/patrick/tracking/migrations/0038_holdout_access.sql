-- Registre d'accès au holdout terminal (audit externe du 2026-10-19, point 5).
--
-- Le holdout n'est protégé que par discipline. Il est pourtant lu à plusieurs endroits : l'évaluation finale d'un
-- run ('final_eval'), le diagnostic qui note TOUS les essais de la grille ('diagnostic'), et le duel champion /
-- challenger ('champion_duel_challenger', 'champion_duel_champion') qui SÉLECTIONNE sur lui. Une ligne = une
-- lecture, écrite par l'unique fonction qui lit le holdout (`pipeline/engine.py::_evaluate_holdout`).
--
-- Append-only et SANS clé étrangère, comme `trial_registry` : un run supprimé (duel perdu, nettoyage) ne doit pas
-- faire disparaître ses lectures. Pas de reprise de l'historique : on ne sait pas reconstituer les lectures
-- passées, le registre démarre à sa création (la requête renvoie la date de la première ligne).
-- `holdout_start`/`holdout_end` : la fenêtre lue (elle glisse avec les données, d'où la comparaison par chevauchement).
CREATE TABLE IF NOT EXISTS holdout_access (
    access_id INTEGER PRIMARY KEY AUTOINCREMENT,
    accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('final_eval', 'diagnostic',
                                             'champion_duel_challenger', 'champion_duel_champion')),
    run_id TEXT,
    holdout_start TEXT,
    holdout_end TEXT,
    n_rows INTEGER,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_holdout_access_target_horizon ON holdout_access(target, horizon);
