-- Phase 3.1 — file de jobs SQLite : un job = une soumission de config (un
-- appel `patrick run` / une soumission du formulaire web), consommée par un
-- worker en process séparé (patrick/worker.py) qui interroge cette table en
-- boucle plutôt qu'un thread interne au process web (BackgroundTasks-like) :
-- tuer le process web pendant un run ne perd plus le run, le worker (process
-- séparé) le termine, et un nouveau process web au redémarrage retrouve son
-- état en relisant cette table plutôt qu'un état perdu en mémoire.
--
-- Distinct de `run` (une ligne par (target, horizon) de la config, créée par
-- `run_pipeline` lui-même une fois le job pris en charge) : un job multi-
-- horizons produit plusieurs `run` — lien de traçabilité via `run.job_id`.

CREATE TABLE job (
    job_id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'error')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    result_json TEXT,
    phase TEXT NOT NULL DEFAULT 'queued',
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 1,
    log_tail TEXT NOT NULL DEFAULT '[]',
    worker_pid INTEGER
);
CREATE INDEX idx_job_status_created ON job(status, created_at);

ALTER TABLE run ADD COLUMN job_id TEXT;

-- Une seule ligne (id=1) : heartbeat du worker actif, pour que
-- `run_manager.ensure_worker_running` sache s'il doit en relancer un
-- (process séparé mort/absent) sans jamais en faire tourner deux en parallèle
-- (un seul worker consomme la file, mono-utilisateur local).
CREATE TABLE worker_heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pid INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
