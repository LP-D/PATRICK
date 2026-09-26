-- F08 -- on which data a Diebold-Mariano result was computed.
--
-- `holdout`      : the terminal holdout, never used for any choice (the only
--                  sample whose p-value is evidence);
-- `last_wf_fold` : the most recent walk-forward fold -- part of the
--                  selection criterion (mean F1_dir over all folds), so the
--                  p-value is biased towards significance. Every row written
--                  before this migration was computed there.
--
-- `n_obs`: number of paired losses the statistic was computed on (NULL for
-- legacy rows, the count was never stored).
ALTER TABLE dm_result ADD COLUMN sample TEXT NOT NULL DEFAULT 'last_wf_fold'
    CHECK (sample IN ('holdout', 'last_wf_fold'));
ALTER TABLE dm_result ADD COLUMN n_obs INTEGER;
