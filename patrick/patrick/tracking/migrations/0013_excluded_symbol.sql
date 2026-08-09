-- M1: persisted registry of symbols confirmed unavailable at the data
-- source (delisted, invalid, or otherwise never resolvable via yfinance),
-- so the webapp's startup market-mover refresh (webapp/alerts.py) stops
-- silently retrying a download that has already failed identically at
-- every previous startup. Seeded here with the 9 tickers confirmed by
-- repeated real-world observation (identical failure at every `patrick
-- serve` startup) rather than a live re-detection pass -- see
-- `data/universe.py::active_yf_tickers`.
CREATE TABLE excluded_symbol (
    symbol TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    excluded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO excluded_symbol (symbol, reason) VALUES
    ('LBS=F', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('HYLD', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('TBP', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('GXG', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('LVRK', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('TERM', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('^EVZ', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('CYB', 'delisted or invalid symbol, confirmed 2026-08-09'),
    ('BZF', 'delisted or invalid symbol, confirmed 2026-08-09');
