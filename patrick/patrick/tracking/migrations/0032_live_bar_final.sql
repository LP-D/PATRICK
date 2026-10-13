-- Valeur de référence d'un signal live : la barre du jour était-elle déjà TERMINÉE quand le signal a été calculé ?
-- 1 = le signal part de la clôture de sa séance ; 0 = il part du cours en séance (barre du jour encore partielle, ce
-- n'est pas la clôture) ; NULL = inconnu (signal antérieur à cette colonne). Mémorisé à l'instant du signal : la barre
-- est complétée plus tard par la source, mais le signal, lui, ne change plus.
ALTER TABLE prediction ADD COLUMN live_bar_final INTEGER;
