-- Ordres limite des fonds simulés (A12, 2026-11-25) : un ordre en attente, exécuté sur une séance suivante quand le cours touche la limite,
-- éventuellement en plusieurs fois (part du volume du jour). Chaque exécution est un vrai `fund_order` (note `limit:<id>`) ; cette table ne
-- garde que l'intention et son état. `request_json` : la demande d'ordre de `fund.service.place_order` (sans date ni prix).
CREATE TABLE IF NOT EXISTS fund_limit_order (
    limit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('buy', 'sell')),
    quantity REAL NOT NULL CHECK (quantity > 0),
    filled_quantity REAL NOT NULL DEFAULT 0,
    limit_price REAL NOT NULL CHECK (limit_price > 0),
    participation REAL NOT NULL DEFAULT 0.1 CHECK (participation > 0 AND participation <= 1),
    placed_on TEXT NOT NULL,
    expires_on TEXT NOT NULL,
    checked_through TEXT,                -- dernière séance examinée (une séance n'est jamais examinée deux fois)
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'partial', 'filled', 'expired', 'cancelled', 'rejected')),
    request_json TEXT NOT NULL,
    fills_json TEXT NOT NULL DEFAULT '[]',
    message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fund_limit_order_strategy ON fund_limit_order(strategy_id, status);
