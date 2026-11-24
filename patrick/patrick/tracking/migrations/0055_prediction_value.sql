-- Objectif « valeur exacte » (2026-11-24, `models/value.py`) : le rendement à l'horizon prédit par le modèle, pour les lignes live
-- (signal du jour). NULL pour tout modèle de direction et pour les lignes de validation.
ALTER TABLE prediction ADD COLUMN y_value REAL;
