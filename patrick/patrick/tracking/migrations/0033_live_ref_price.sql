-- Valeur de départ d'un signal live : le cours de la cible à la date du signal, tel que le modèle l'a vu (clôture de la
-- séance, ou cours en séance si `live_bar_final` = 0). Mémorisé à l'instant du signal, car la barre du jour est ensuite
-- complétée par la source. NULL = inconnu (signal antérieur à cette colonne).
ALTER TABLE prediction ADD COLUMN live_ref_price REAL;
