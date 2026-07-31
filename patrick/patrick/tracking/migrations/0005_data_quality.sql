-- Phase 6.5 (P6.5) -- persistance des exclusions de qualité de données
-- (`data/quality.py`) décidées à l'ingestion, liées au snapshot qu'elles ont
-- produit -- jamais un simple `[WARN]` perdu dans les logs (même classe de
-- défaut que le repli FRED silencieux, déjà corrigé ailleurs).
CREATE TABLE data_quality_issue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    series TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_data_quality_issue_snapshot ON data_quality_issue(snapshot_id);
