-- Notes libres datées posées sur la courbe d'un actif (VI24, 2026-11-26) : « changement de pilote », « annonce BCE »… ; affichées comme
-- repères verticaux sur le graphique de cours de la fiche de l'actif. Texte saisi par l'utilisateur, jamais lu par un calcul.
CREATE TABLE IF NOT EXISTS chart_note (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    day TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chart_note_symbol ON chart_note(symbol, day);
