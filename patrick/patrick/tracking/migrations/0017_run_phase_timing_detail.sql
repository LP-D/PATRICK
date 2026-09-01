-- Elargit run_phase_timing (migration 0016) aux trois sous-phases qui
-- composaient le bucket "non instrumente" (824s / 34% de la mesure GSPC du
-- 25/08 -- ingestion+pool_construction+scan+tuning ne couvraient pas 100%
-- du run, cf. history.py::phase_breakdown_for_run docstring) : stabilite de
-- selection (P6.3), diagnostic holdout (audit report C4), export CSV/modele.
-- SQLite ne permet pas d'ALTER une contrainte CHECK -- meme pattern de
-- reconstruction de table que 0010_dm_result_kind.sql : table _new avec la
-- contrainte elargie, copie des lignes existantes, drop, rename.
CREATE TABLE run_phase_timing_new (
    phase_timing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN (
        'ingestion', 'pool_construction', 'scan', 'tuning',
        'stability', 'holdout_diagnostic', 'export'
    )),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
INSERT INTO run_phase_timing_new (phase_timing_id, run_id, phase, started_at, finished_at)
    SELECT phase_timing_id, run_id, phase, started_at, finished_at FROM run_phase_timing;
DROP TABLE run_phase_timing;
ALTER TABLE run_phase_timing_new RENAME TO run_phase_timing;

CREATE INDEX idx_phase_timing_run ON run_phase_timing(run_id, phase);
