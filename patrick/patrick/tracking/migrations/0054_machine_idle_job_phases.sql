-- Temps de calcul réel (2026-11-23). Deux tables locales à la machine (jamais partagées entre PC) :
--
-- `machine_idle` : les périodes où AUCUN calcul ne tourne alors qu'un run est en cours -- veille ou hibernation du PC (`reason = 'sleep'`,
-- détectée par le fil de battement du worker : écart entre horloge murale et horloge « éveillée », `system/awake_clock.py`) et pause demandée
-- depuis l'interface (`reason = 'pause'`, ouverte à la pause, refermée à la reprise ou à la fin du job). Le chronomètre d'un run, l'estimation
-- de la file et les durées moyennes par étape retranchent ces périodes. Horodatages UTC 'YYYY-MM-DD HH:MM:SS' comme `job.started_at` ;
-- `ended_at` NULL = période encore ouverte (pause en cours).
--
-- `job_phase_timing` : une ligne par étape d'un job, dans le vocabulaire de `job.phase` (ingestion, features, scan, tuning, export ; rl_data,
-- rl_train, rl_eval, rl_save), écrite par le worker au changement d'étape. Sert aux moyennes par étape « à réglages identiques » qui estiment
-- la durée des runs en file (`tracking/eta.py`).
CREATE TABLE IF NOT EXISTS machine_idle (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    reason      TEXT NOT NULL,
    job_id      TEXT
);
CREATE INDEX IF NOT EXISTS ix_machine_idle_end ON machine_idle(ended_at);

CREATE TABLE IF NOT EXISTS job_phase_timing (
    job_id      TEXT NOT NULL,
    phase       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_job_phase_timing_job ON job_phase_timing(job_id);
