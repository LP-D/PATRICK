-- Journal des remplacements de modèle dans les fonds (2026-11-13). Quand un nouveau champion prend une cellule, la règle de l'ancien
-- modèle est supprimée avec ses ordres (`fund/systematic.purge_rule`) : son P&L sort du fonds et plus rien ne disait qu'il y avait été.
-- Cette table garde la trace lisible de chaque remplacement. Locale, jamais fusionnée entre PC.
CREATE TABLE IF NOT EXISTS fund_replacement (
    replacement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    target TEXT,
    horizon INTEGER,
    old_trial_id INTEGER,
    new_trial_id INTEGER,
    n_orders INTEGER NOT NULL DEFAULT 0,
    pnl_removed REAL,
    replaced_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fund_replacement_strategy ON fund_replacement(strategy_id, replaced_at);
