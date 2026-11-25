-- Historique des réglages du pilote automatique d'un fonds (FO12, 2026-11-25) : chaque activation, changement de réglage ou désactivation
-- est daté, avec les réglages avant et après ; le panneau d'un fonds montre la liste, la courbe permet de lire l'effet de chaque changement.
CREATE TABLE IF NOT EXISTS fund_settings_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL CHECK (action IN ('enable', 'update', 'disable')),
    before_json TEXT,
    after_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_fund_settings_log ON fund_settings_log(strategy_id, changed_at);
