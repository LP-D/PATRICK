-- Fonds, chantier 3 : règles du mode systématique « modèle ML avec seuils ».
-- Une règle lie une stratégie à un essai de modèle et à un instrument; les ordres
-- qu'elle génère sont de vrais `fund_order` (note `auto:<rule_id>:<date>:<action>`).
-- Le préfixe `fund_` la range parmi les tables personnelles : jamais exportée
-- vers GitHub par `patrick sync`.
CREATE TABLE fund_rule (
    rule_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_fund_rule_strategy ON fund_rule(strategy_id);
