-- Carnet de recherche (feuille de route 2026-10-20, bloc 8) : notes, hypothèses, résultats et décisions, liés à une cible, un horizon, un run.
--
-- Sert de discipline contre le p-hacking : une hypothèse écrite AVANT un run, avec son statut (ouverte, confirmée, réfutée) rempli après,
-- laisse une trace de ce qui était attendu. `created_at` ne change jamais ; `revisions` compte les modifications du texte ou du statut.
-- Pas de suppression dans l'interface : une note qui ne sert plus passe en `archived`.
-- Sans clé étrangère (comme `trial_registry`) : un run supprimé ne doit pas effacer ce qu'on en avait dit.
CREATE TABLE IF NOT EXISTS research_note (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL CHECK (kind IN ('hypothesis', 'note', 'result', 'decision')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'refuted', 'archived')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    target TEXT,
    horizon INTEGER,
    run_id TEXT,
    revisions INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_research_note_run ON research_note(run_id);
CREATE INDEX IF NOT EXISTS idx_research_note_target ON research_note(target, horizon);
