-- Correctif de 0029 : les bases migrées par une version préliminaire de 0029 ont une table fund_price sans
-- la colonne split (ratio d'un fractionnement à cette date, 0 sinon) : chaque aperçu d'ordre échouait
-- (« no such column: split », HTTP 500). Sur une base neuve la colonne existe déjà : le lanceur de migrations
-- saute un ADD COLUMN dont la colonne est présente.
ALTER TABLE fund_price ADD COLUMN split REAL NOT NULL DEFAULT 0;
