-- Partage des fonds entre deux PC (`patrick sync`) : chaque stratégie porte la date de sa dernière
-- modification (ses ordres et ses règles comptent), et une stratégie supprimée laisse une trace datée.
-- Au moment d'un échange, la version la plus récente d'une stratégie l'emporte. Rien n'est jamais
-- supprimé sans cette trace, et une modification postérieure à la suppression ressuscite la stratégie.
ALTER TABLE fund_strategy ADD COLUMN updated_at TEXT;
UPDATE fund_strategy SET updated_at = created_at WHERE updated_at IS NULL;
CREATE TABLE fund_deleted (
    strategy_id TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);
