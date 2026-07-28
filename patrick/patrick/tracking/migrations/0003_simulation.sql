-- Phase 4.5 (garde-fou anti-surapprentissage) : une ligne par simulation
-- LANCÉE (pas seulement la meilleure) -- symétrique à `trial` (Phase 1.3, une
-- ligne par config de modèle testée, pas seulement le vainqueur) : le nombre
-- de configs de simulation essayées sur une cible doit être visible en
-- permanence dans l'UI, pas caché, sinon le simulateur reproduit exactement
-- le biais de sur-optimisation qu'il est censé exposer.
--
-- `metrics_json` regroupe métriques + courbes (equity/drawdown) + journal des
-- trades en un seul blob JSON (comme `job.result_json`, Phase 3.1) plutôt que
-- d'exploser en tables normalisées : ces données ne sont jamais filtrées par
-- SQL ailleurs, seulement relues telles quelles pour l'affichage.
CREATE TABLE simulation (
    simulation_id TEXT PRIMARY KEY,
    trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    params_json TEXT NOT NULL,
    metrics_json TEXT,
    error TEXT
);
CREATE INDEX idx_simulation_trial ON simulation(trial_id, created_at);
