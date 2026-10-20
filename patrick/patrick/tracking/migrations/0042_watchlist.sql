-- Listes de suivi (feuille de route 2026-10-20, bloc 3) : regrouper des symboles sous un nom et des étiquettes (« à surveiller », « énergie »...).
--
-- Les symboles sont ceux du data lake (`raw_<symbole>`) ; la liste n'écrit rien d'autre et ne déclenche aucun calcul.
-- `symbols` et `tags` sont des tableaux JSON. Sans clé étrangère : un symbole retiré du lake ne casse pas la liste, l'écran l'indique.
CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    symbols TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
