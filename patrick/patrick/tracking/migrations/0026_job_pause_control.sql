ALTER TABLE job ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0
    CHECK (pause_requested IN (0, 1));
