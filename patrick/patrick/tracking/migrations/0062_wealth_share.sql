-- Patrimoine partagé entre PC SANS PC de référence (`patrick/wealth/share.py`, 2026-11-27) : chaque PC publie le sien et fusionne
-- ceux des autres ligne par ligne, comme un git merge qui se résout tout seul.
-- `uid` : identité d'un mouvement, la même sur tous les PC (`movement_id` reste un numéro propre à chaque base). Les mouvements
-- existants la dérivent du compte, du numéro et de la date de saisie : deux PC qui ont la même copie du patrimoine (celle que le
-- PC de référence publiait) obtiennent les mêmes. Les nouveaux reçoivent un identifiant aléatoire (`ledger._insert_movement`).
-- `updated_at` : date de la dernière modification d'un compte ou d'un mouvement (UTC au millième, se compare comme du texte) ;
-- la version la plus récente l'emporte quand deux PC ont modifié la même ligne.
-- `wealth_deleted` : trace datée d'une suppression (`kind` = 'account' ou 'movement', `uid` = account_id ou uid du mouvement),
-- pour qu'elle se propage au lieu que l'autre PC ressuscite la ligne.
ALTER TABLE wealth_account ADD COLUMN updated_at TEXT;
UPDATE wealth_account SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE wealth_movement ADD COLUMN uid TEXT;
ALTER TABLE wealth_movement ADD COLUMN updated_at TEXT;
UPDATE wealth_movement SET uid = 'mv_' || account_id || '_' || movement_id || '_' || replace(replace(replace(created_at, ' ', 'T'), ':', ''), '-', '')
    WHERE uid IS NULL;
UPDATE wealth_movement SET updated_at = created_at WHERE updated_at IS NULL;
CREATE UNIQUE INDEX idx_wealth_movement_uid ON wealth_movement(uid);
CREATE TABLE wealth_deleted (
    kind TEXT NOT NULL CHECK (kind IN ('account', 'movement')),
    uid TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    PRIMARY KEY (kind, uid)
);
