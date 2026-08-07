-- Phase 9 (P9) -- persistance minimale de la traçabilité et des snapshots de
-- la plateforme de trading. C'est une couche d'application, pas un backtest
-- complet : elle donne un cadre d'enregistrement fiable pour les décisions,
-- les écrasements, les snapshots et les vues d'observation / analyse.
CREATE TABLE phase9_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE phase9_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    before_json TEXT,
    after_json TEXT,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
