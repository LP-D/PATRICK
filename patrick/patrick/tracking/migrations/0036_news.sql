-- Analyse textuelle des news (patrick/text) : magasin point-in-time, scores par outil, rattachement aux actifs.
-- `published_at` : heure de publication annoncée par la source (UTC, ISO 8601). `first_seen_at` : heure à laquelle PATRICK
-- (ou le fournisseur d'historique, pour un rattrapage) a vu la news pour la première fois. Une news n'est utilisable qu'à
-- partir de max(published_at, first_seen_at) : une news rattrapée après coup n'est jamais visible dans le passé.
-- `date_only` : la source ne donnait qu'une date, lue à 23:59:59 UTC (hypothèse la plus tardive, jamais de fuite).
CREATE TABLE IF NOT EXISTS news_item (
    item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    date_only     INTEGER NOT NULL DEFAULT 0,
    title         TEXT NOT NULL,
    summary       TEXT,
    url           TEXT,
    language      TEXT,
    content_hash  TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_news_item_published ON news_item (published_at);
CREATE INDEX IF NOT EXISTS idx_news_item_hash ON news_item (source, content_hash);

CREATE TABLE IF NOT EXISTS news_score (
    item_id     INTEGER NOT NULL REFERENCES news_item(item_id) ON DELETE CASCADE,
    scorer      TEXT NOT NULL,
    version     TEXT NOT NULL,
    score       REAL,
    detail_json TEXT,
    PRIMARY KEY (item_id, scorer, version)
);

CREATE TABLE IF NOT EXISTS news_link (
    item_id INTEGER NOT NULL REFERENCES news_item(item_id) ON DELETE CASCADE,
    symbol  TEXT NOT NULL,
    method  TEXT NOT NULL,
    PRIMARY KEY (item_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_news_link_symbol ON news_link (symbol);
