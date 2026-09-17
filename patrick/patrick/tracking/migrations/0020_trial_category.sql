-- CHANTIER B (feature/model-categories-comparison) -- tags each trial with
-- the model CATEGORY it belongs to (global / per_regime / stacking, see
-- pipeline/model_categories_training.py). DEFAULT 'global': every existing
-- trial row (produced before this chantier existed) is retroactively and
-- correctly labeled -- the pre-existing grid scan only ever produced
-- "global"-category trials, so backfilling the default is not a guess, it
-- is the actual historical fact for every row already in the table.
ALTER TABLE trial ADD COLUMN category TEXT NOT NULL DEFAULT 'global';
