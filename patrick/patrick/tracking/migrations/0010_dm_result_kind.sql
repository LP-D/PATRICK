-- Phase X5 -- deux comparaisons Diebold-Mariano par run (walk-forward) au lieu
-- d'une seule : `class_specific` (meilleure baseline parmi les candidats de la
-- classe d'actif de la cible, `validation.baseline_by_asset_class`) ET `common`
-- (persistance de classe, référence fixe permettant de comparer les classes
-- entre elles). La table `dm_result` (migration 0009) avait `run_id` seul
-- comme clé primaire (une ligne par run) -- recréée ici avec (run_id, kind)
-- (SQLite ne permet pas d'ALTER une PRIMARY KEY). Toute ligne pré-existante
-- (comportement d'avant cette migration, un seul DM par run) est reclassée
-- `class_specific` -- c'était déjà la baseline "meilleure sur ce fold",
-- sémantiquement la plus proche des deux nouvelles catégories.
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
