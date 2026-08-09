-- Réparation ciblée : sur une base dont `schema_version` a été bloqué à la
-- valeur 10 par l'ancienne numérotation de `phase9_tracking` (avant sa
-- renumérotation en 0011, suite à la collision avec ce projet), la boucle
-- `migrate()` (`if version <= current: continue`) saute pour toujours le
-- vrai `0010_dm_result_kind.sql` -- puisque la version 10 "semble" déjà
-- appliquée, alors qu'elle correspond en réalité à l'ancien contenu
-- phase9, jamais à celui-ci. Résultat : `dm_result` reste bloqué sur son
-- schéma pré-migration 0010 (colonne `kind` absente).
--
-- Contenu strictement identique à `0010_dm_result_kind.sql` (même
-- reconstruction de table, même valeur par défaut `class_specific`, même
-- clé primaire composite (run_id, kind) -- requise par le
-- `ON CONFLICT(run_id, kind)` de `save_dm_result()`, que SQLite ne permet
-- pas d'ajouter via un simple ALTER TABLE ADD COLUMN). Numérotée
-- séparément plutôt que réappliquée sous le numéro 0010 : voir
-- `db.py::_dm_result_already_has_kind` et `_CUSTOM_IDEMPOTENCY_CHECKS`
-- pour la garde qui rend cette migration sans effet (mais toujours
-- enregistrée) sur une base où 0010 s'est déjà exécutée normalement.
CREATE TABLE dm_result_new (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'class_specific' CHECK (kind IN ('class_specific', 'common')),
    baseline TEXT NOT NULL,
    dm_stat REAL,
    p_value REAL NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, kind)
);
INSERT INTO dm_result_new (run_id, kind, baseline, dm_stat, p_value, computed_at)
    SELECT run_id, 'class_specific', baseline, dm_stat, p_value, computed_at FROM dm_result;
DROP TABLE dm_result;
ALTER TABLE dm_result_new RENAME TO dm_result;
