-- Suivi des relances conseillées (2026-11-07). Un réentraînement sur deux est jeté par le duel des champions (539 « champion garde » contre 475
-- « challenger gagne » sur les journaux), mais rien ne disait QUELLE suggestion du conseiller avait produit quel job : impossible de savoir lesquelles valent leur
-- temps de calcul. Trois petites tables locales (jamais fusionnées entre PC) :
--   relaunch_log   : le job lancé depuis une suggestion (lot « runs conseillés » ou formulaire pré-rempli) ;
--   duel_outcome   : l'issue de chaque duel, y compris pour un challenger élagué (son run disparaît, cette ligne reste) ;
--   live_failure   : les modèles qui ne savent plus prédire (série d'entrée écartée par les portes de qualité), avec le nombre d'échecs de suite.
CREATE TABLE IF NOT EXISTS relaunch_log (
    job_id TEXT PRIMARY KEY,
    parent_run_id TEXT NOT NULL,
    suggestion_key TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS duel_outcome (
    duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    run_id TEXT NOT NULL,
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    decision TEXT NOT NULL,
    criterion TEXT,
    challenger_score REAL,
    champion_score REAL,
    duration_s REAL,
    shadow_stop_fold INTEGER,
    shadow_best REAL,
    shadow_champion REAL,
    n_folds INTEGER,
    decided_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_duel_outcome_job ON duel_outcome(job_id);
CREATE TABLE IF NOT EXISTS live_failure (
    run_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    detail TEXT,
    n INTEGER NOT NULL DEFAULT 1,
    first_at TEXT NOT NULL,
    last_at TEXT NOT NULL
);
