-- Calendrier économique (A17, 2026-11-25) : dates officielles des publications macro américaines (API FRED `release/dates`, passées ET à
-- venir), rafraîchies par `patrick news refresh` (donc chaque nuit). Les décisions de taux des banques centrales ne sont pas stockées ici :
-- elles sont reconnues à la lecture dans les titres des communiqués de `news_item` (`data/econ_calendar.py`).
CREATE TABLE IF NOT EXISTS econ_release (
    day TEXT NOT NULL,
    release_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (day, release_id)
);
CREATE INDEX IF NOT EXISTS idx_econ_release_day ON econ_release(day);
