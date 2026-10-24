-- Pilote automatique des fonds : réglages d'une stratégie (JSON). Colonne de la stratégie, donc elle voyage avec elle
-- quand deux PC partagent leurs fonds. NULL = pilote jamais configuré.
ALTER TABLE fund_strategy ADD COLUMN autopilot_json TEXT;
