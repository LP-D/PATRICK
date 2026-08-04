-- Phase 6.4 (P6.4) -- persiste le résultat Diebold-Mariano (Phase 2.5) dans
-- une table dédiée, queryable à travers TOUT l'historique de runs (y compris
-- `patrick run`/`patrick resume` en CLI, sans job web associé) -- jusqu'ici,
-- ce résultat n'existait que dans `job.result_json` (limite documentée dans
-- `tracking/report.py::_job_stats_for_run`), donc invisible pour un run CLI
-- et impossible à agréger PAR CIBLE à travers plusieurs runs (nécessaire à
-- `stats.py::fdr_across_targets`, correction FDR inter-cibles). Une ligne
-- par run (pas par trial) : le DM n'est calculé qu'une fois, pour la config
-- gagnante de CE run_pipeline() (cf. `pipeline/engine.py::run_pipeline`).
CREATE TABLE dm_result (
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    baseline TEXT NOT NULL,
    dm_stat REAL,
    p_value REAL NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id)
);
