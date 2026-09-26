-- F03 -- registre d'essais persistant, source du n_trials du Deflated Sharpe
-- Ratio (tracking/stats.py::count_cumulative_trials/count_registered_trials).
--
-- Append-only, SANS clé étrangère : un run supprimé (trial.run_id est
-- ON DELETE CASCADE) ne doit jamais faire disparaître les configurations
-- qu'il a évaluées du compte cumulé -- c'est précisément ce compte qui
-- déflate le Sharpe du gagnant. Une ligne = un événement « n configurations
-- évaluées » : essai de scan (trackdb.create_trial), essai Optuna (callback
-- par essai terminé, tuning/optuna_runner.py), simulation sauvegardée
-- (simulate/engine.py::save_simulation), catégorie de modèle.
CREATE TABLE IF NOT EXISTS trial_registry (
    registry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    target TEXT NOT NULL,
    horizon INTEGER,
    source TEXT NOT NULL CHECK (source IN ('scan', 'optuna', 'simulation', 'category',
                                           'backfill_scan', 'backfill_optuna', 'backfill_simulation')),
    run_id TEXT,
    n_trials INTEGER NOT NULL CHECK (n_trials >= 0),
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_trial_registry_target_horizon ON trial_registry(target, horizon);

-- Reprise de l'historique existant. Essais de scan : 1 chacun. Essais
-- tunés (params_json non vide) : une ligne `trial` résume tout un tuning
-- Optuna -- compté pour le `tuning.n_trials` configuré du run (borne
-- haute : un tuning interrompu en a évalué moins, sans trace). Simulations :
-- 1 chacune.
INSERT INTO trial_registry (target, horizon, source, run_id, n_trials, detail)
SELECT run.target, run.horizon, 'backfill_scan', run.run_id, COUNT(*), 'migration 0021'
FROM trial JOIN run ON trial.run_id = run.run_id
WHERE trial.params_json IS NULL OR trial.params_json IN ('', '{}')
GROUP BY run.run_id;

INSERT INTO trial_registry (target, horizon, source, run_id, n_trials, detail)
SELECT run.target, run.horizon, 'backfill_optuna', run.run_id,
       COUNT(*) * COALESCE(
           CASE WHEN json_valid(run.config_json)
                THEN json_extract(run.config_json, '$.tuning.n_trials') END, 1),
       'migration 0021'
FROM trial JOIN run ON trial.run_id = run.run_id
WHERE trial.params_json IS NOT NULL AND trial.params_json NOT IN ('', '{}')
GROUP BY run.run_id;

INSERT INTO trial_registry (target, horizon, source, run_id, n_trials, detail)
SELECT run.target, run.horizon, 'backfill_simulation', run.run_id, COUNT(*), 'migration 0021'
FROM simulation
JOIN trial ON simulation.trial_id = trial.trial_id
JOIN run ON trial.run_id = run.run_id
GROUP BY run.run_id;
