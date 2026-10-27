-- Texte complet des nouvelles de banque centrale (patrick/text/fulltext.py) : le flux RSS ne donne qu'une phrase, le ton
-- « faucon / colombe » est calculé sur la page liée. Une ligne par nouvelle dont la page a été tentée.
-- `status` : ok (texte lu) | failed (illisible, retentée jusqu'à 3 fois) | skipped (hôte non autorisé ou lien absent).
CREATE TABLE IF NOT EXISTS news_body (
    item_id    INTEGER PRIMARY KEY REFERENCES news_item(item_id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    status     TEXT NOT NULL,
    text       TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);
