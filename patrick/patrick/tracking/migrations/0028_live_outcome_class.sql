-- Suivi live sur les 4 mouvements (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT).
-- `y_true` des lignes split='live' reste BINAIRE (1 = hausse, 0 = baisse) :
-- sa semantique n'est pas touchee. Pour juger aussi « fort / faible », la
-- prediction live memorise, a l'instant du signal, les seuils causaux de
-- classification (quantiles 25 %/75 % du rendement du regime du jour, ajustes
-- uniquement sur l'historique deja connu : features/target.py), puis, quand
-- l'horizon est ecoule, la classe REELLEMENT realisee dans `y_class`.
-- `live_backfill` = 1 : ligne reconstituee apres coup avec le modele deja
-- exporte (jour ou l'app n'etait pas ouverte), jamais ecrite avant le resultat.
ALTER TABLE prediction ADD COLUMN live_thr_lo REAL;
ALTER TABLE prediction ADD COLUMN live_thr_hi REAL;
ALTER TABLE prediction ADD COLUMN y_class INTEGER;
ALTER TABLE prediction ADD COLUMN live_backfill INTEGER NOT NULL DEFAULT 0;
