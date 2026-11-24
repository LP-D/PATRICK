-- Positions « live » des agents RL (ADR 0030, 2026-11-23). Un run RL ne produit des positions que sur sa fenêtre hors échantillon ; les fonds de
-- test combinés (`fund/combo.py`) ont besoin de la position que l'agent du dernier pli prendrait chaque jour depuis. `rl/live.py` rejoue cet
-- agent sur les données du jour et écrit ici une ligne par séance, jamais réécrite ensuite (la première décision enregistrée fait foi, comme un
-- signal ML live). `backfill` = séance rattrapée après coup (application fermée ce jour-là) ; `agreement` = part des positions rejouées sur la
-- fenêtre hors échantillon d'origine qui retombent sur celles du run (contrôle que les variables recalculées n'ont pas dérivé). Locale, jamais
-- fusionnée entre PC.
CREATE TABLE IF NOT EXISTS rl_live_position (
    job_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    position REAL NOT NULL,
    backfill INTEGER NOT NULL DEFAULT 0,
    agreement REAL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, ts)
);
