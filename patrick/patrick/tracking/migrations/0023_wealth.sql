-- Roadmap bloc 4 -- PATRIMOINE : comptes (PEA, CTO, assurance-vie, livret,
-- dépôt à terme...) réels ou fictifs, et leurs mouvements. Aucune position
-- n'est stockée : elles se déduisent des mouvements (patrick/wealth/ledger.py),
-- une seule source de vérité.
--
-- `mode` : `real` (le patrimoine effectif) ou `fictive` (bac à sable : clone
-- d'un compte réel ou compte vierge, pour tester une allocation sans toucher
-- au réel). Un mouvement ne passe jamais d'un compte fictif à un compte réel
-- (règle appliquée par le code, pas par le schéma).
CREATE TABLE wealth_account (
    account_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('PEA', 'CTO', 'AV', 'LIVRET', 'DAT', 'AUTRE')),
    mode TEXT NOT NULL CHECK (mode IN ('real', 'fictive')),
    currency TEXT NOT NULL DEFAULT 'EUR',
    benchmark TEXT,
    opened_on TEXT,
    source_account_id TEXT REFERENCES wealth_account(account_id) ON DELETE SET NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- `amount` : impact sur les liquidités du compte, signé, dans la devise du
-- compte (achat = -(quantité × prix) - frais ; vente = +quantité × prix -
-- frais ; apport +, retrait -, dividende/intérêts +, frais -). Un dépôt à
-- terme (`term_deposit`) sort `amount` des liquidités vers une position
-- `symbol` valorisée au taux `rate` jusqu'à `maturity`.
CREATE TABLE wealth_movement (
    movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES wealth_account(account_id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('deposit', 'withdrawal', 'buy', 'sell', 'dividend', 'fee',
                                       'interest', 'term_deposit')),
    symbol TEXT,
    quantity REAL,
    price REAL,
    amount REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    rate REAL,
    maturity TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_wealth_movement_account ON wealth_movement(account_id, ts);
