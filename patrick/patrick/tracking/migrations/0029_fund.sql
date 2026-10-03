-- Refonte Simulation + page Fonds, chantier 1 : stratégies, ordres, cotations
-- persistantes. Aucune position ni aucun solde n'est stocké : tout se recalcule
-- depuis les ordres (patrick/fund/engine.py).
CREATE TABLE fund_strategy (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wrapper TEXT NOT NULL CHECK (wrapper IN ('PEA', 'CTO')),
    base_currency TEXT NOT NULL DEFAULT 'EUR',
    initial_capital REAL NOT NULL CHECK (initial_capital > 0),
    opened_on TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- `instrument_kind` sans CHECK : le code le valide, les chantiers 2 et 3
-- ajoutent des types (options, swaps) sans reconstruire la table.
-- `fees` est en devise de base ; `fx_rate` = devise de base par unité de la
-- devise de l'instrument à la date d'exécution ; `spec_json` porte les
-- composantes (multiplicateur, mois de contrat, levier, marge, stop, objectif).
CREATE TABLE fund_order (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    position_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('open', 'increase', 'reduce', 'close', 'modify')),
    instrument_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    quantity REAL NOT NULL CHECK (quantity >= 0),
    price REAL,
    price_source TEXT CHECK (price_source IN ('market', 'manual')),
    currency TEXT NOT NULL,
    fx_rate REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    fees_source TEXT CHECK (fees_source IN ('manual', 'estimated')),
    fee_seed INTEGER,
    spec_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_fund_order_strategy ON fund_order(strategy_id, ts, order_id);
CREATE INDEX idx_fund_order_position ON fund_order(position_id);

-- Cotations conservées DÉFINITIVEMENT : Yahoo retire les contrats expirés et la
-- valeur d'une stratégie doit rester calculable après l'échéance. Prix en
-- unités de la devise ISO (les pence sont convertis à l'écriture).
CREATE TABLE fund_price (
    symbol TEXT NOT NULL,
    day TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL NOT NULL DEFAULT 0,
    dividend REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, day)
);
CREATE TABLE fund_price_meta (
    symbol TEXT PRIMARY KEY,
    currency TEXT,
    refreshed_at TEXT
);
