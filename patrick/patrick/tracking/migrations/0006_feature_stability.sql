-- Phase 6.3 (P6.3) -- stabilité de la sélection de features entre folds
-- (walk-forward aujourd'hui, chemins CPCV demain -- P6.1). Calculée pour la
-- configuration (regime, N) GAGNANTE de chaque run, sur ses folds.
CREATE TABLE feature_stability (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    feature TEXT NOT NULL,
    selection_freq REAL NOT NULL,
    PRIMARY KEY (run_id, feature)
);
CREATE INDEX idx_feature_stability_run ON feature_stability(run_id);

-- Scalaire par run, table séparée plutôt qu'une colonne ALTERée sur `run`
-- (moins invasif, `run`/`_RUN_COLUMNS` déjà lus par nom ailleurs).
-- `mean_jaccard` NULLABLE : non calculable avec moins de 2 folds utilisables
-- (`feature_selection_stability` renvoie NaN dans ce cas) -- stocké comme
-- NULL SQL (jamais NaN, cf. `db.py::save_feature_stability`), pas une valeur
-- numérique trompeuse.
CREATE TABLE run_feature_stability (
    run_id TEXT PRIMARY KEY REFERENCES run(run_id) ON DELETE CASCADE,
    mean_jaccard REAL,
    n_folds INTEGER NOT NULL
);
