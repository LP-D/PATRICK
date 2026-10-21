-- Journal de prédictions horodaté et chaîné (feuille de route 2026-10-20, bloc 5).
--
-- La table `prediction` est réécrite (INSERT OR REPLACE, jugement des issues) : elle ne peut pas servir de preuve qu'un signal a été émis AVANT
-- son issue. Ce journal est APPEND-ONLY : une ligne par signal émis (`kind = 'signal'`) et une par issue connue (`kind = 'outcome'`, un jugement
-- corrigé ajoute une ligne, l'ancienne reste). Chaque ligne porte l'empreinte du modèle qui l'a produite (`model_hash`, SHA-256 du fichier
-- exporté) et celle de la ligne précédente : modifier ou supprimer une ligne casse la chaîne, que `tracking/journal.py::verify` détecte.
-- Des déclencheurs créés à l'usage (`journal.ensure_triggers`) refusent UPDATE et DELETE ; ils ne sont pas dans ce script car le découpeur de
-- migrations coupe sur « ; ».
--
-- Sans clé étrangère, comme `trial_registry` et `holdout_access` : un run supprimé ne doit pas effacer ses signaux.
-- `origin = 'backfill'` : ligne ajoutée après coup pour sceller une prédiction déjà stockée (horodatage = scellement, pas émission).
CREATE TABLE IF NOT EXISTS prediction_journal (
    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('signal', 'outcome')),
    origin TEXT NOT NULL DEFAULT 'live' CHECK (origin IN ('live', 'backfill')),
    run_id TEXT,
    trial_id INTEGER,
    target TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    signal_date TEXT NOT NULL,
    y_pred REAL,
    p_up REAL,
    y_true REAL,
    model_hash TEXT,
    config_hash TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_prediction_journal_key ON prediction_journal(trial_id, signal_date, kind);
CREATE INDEX IF NOT EXISTS idx_prediction_journal_target ON prediction_journal(target, horizon);
