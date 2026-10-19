-- P(hausse) du jour réellement calibrée : 1 quand `predict_live` a appliqué le calibrateur ajusté à l'export (isotonique ou Platt,
-- sur des lignes réelles chronologiquement postérieures à l'ajustement), NULL sinon (lignes du walk-forward, anciens exports, run
-- sans calibration : la `p_up` est alors un score brut). Black-Litterman ne lit que les lignes à 1.
ALTER TABLE prediction ADD COLUMN p_up_calibrated INTEGER;
