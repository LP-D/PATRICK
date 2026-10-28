-- Placebo de décalage par run (2026-10-28, ADR 0008) : les mêmes réglages, évalués sur le holdout avec TOUTES les variables retardées d'un
-- jour de plus. `variant` : 'real' (le holdout du run) ou 'lag1'. Un signal qui s'effondre entre les deux repose sur l'information du jour
-- même : souvent un décalage de date (les barres de change du début de journée l'ont montré), parfois un vrai effet de court terme.
CREATE TABLE IF NOT EXISTS run_placebo (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (run_id, variant, metric)
);
