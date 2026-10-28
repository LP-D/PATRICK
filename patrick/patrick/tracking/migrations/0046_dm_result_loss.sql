-- Perte du test de Diebold-Mariano (2026-10-28, ADR 0008) : 'class4' = erreur 0/1 sur les 4 classes (méthode 1, valeur de toutes les lignes
-- d'avant), 'direction' = erreur 0/1 sur le SENS hausse / baisse (méthode 2). Une baseline « toujours la classe 2 » (marche aléatoire sans
-- dérive) était battue par un modèle qui ne prévoyait que l'amplitude : le test ne mesurait pas ce que le fonds négocie.
ALTER TABLE dm_result ADD COLUMN loss TEXT NOT NULL DEFAULT 'class4';
