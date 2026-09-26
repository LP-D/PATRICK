-- Roadmap bloc 3 -- P(up) per prediction: P(slight up) + P(strong up),
-- calibrated when the run enables calibration (isotonic or Platt, fitted on
-- real chronological rows of each fold's train, models/calibration.py), raw
-- otherwise. `y_proba` keeps its meaning (probability of the PREDICTED
-- class): Black-Litterman v2 needs a probability of the up move, not a
-- confidence in whichever class won. NULL for legacy rows and for models
-- without predict_proba.
ALTER TABLE prediction ADD COLUMN p_up REAL;
