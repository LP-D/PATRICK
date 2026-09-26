# Politique d'alerte de dérive

Décidée le 2026-09-26. Code : `patrick/validation/drift_policy.py` (règles), `validation/drift.py`
(Page-Hinkley recalibré), `tracking/history.drift_badges` (badge), `scripts/daily_predict.py` (re-mesure
nocturne). Badge affiché dans la colonne « Dérive » de `/predictions`.

## Les quatre états

| Badge | Condition | Action attendue |
|---|---|---|
| **réentraîner** (rouge) | Dérive de concept : Page-Hinkley détecte une baisse du taux de réussite sur les appels live **indépendants** (≥ 30) | Relancer un run pour ce (ticker, horizon) |
| **surveiller** (orange) | ≥ 10 % des features du modèle ont un PSI > 0,25 (niveau « dérive » au-delà de 30 %) | Aucune action automatique ; regarder quelles features ont bougé |
| **stable** (vert) | Mesuré, aucun des deux signaux | — |
| **non mesurée** (gris) | Aucune mesure PSI encore | Mesure au prochain passage nocturne ou bouton « Mesurer la dérive » |

« · périmée » s'ajoute quand la dernière mesure PSI a plus de 14 jours.

## Pourquoi ces règles

1. **La dérive des données ne déclenche jamais de réentraînement.** Les entrées peuvent bouger sans que
   le modèle se trompe. Chaque réentraînement ajoute des essais au registre (F03) et dégonfle donc le
   Sharpe déflaté de la cible. Seule une baisse mesurée de la réussite justifie ce coût.
2. **Part des features en dérive, pas le PSI maximal.** Sur 20 features, le PSI maximal est un maximum de
   20 variables bruitées : il dépasse le seuil par construction bien plus souvent qu'une feature isolée.
3. **Appels indépendants seulement.** Deux appels live à horizon 20 j émis à un jour d'écart partagent
   19 jours de résultat : leurs réussites sont autocorrélées. Sur 750 appels quotidiens simulés sans
   aucune dérive, avec le réglage ci-dessous, les fausses alertes valent 10 % (h = 5) et 16 % (h = 20)
   sur les appels chevauchants, 0 % une fois un appel sur h conservé ; 5 % à h = 1, où rien ne change.
   Contrepartie : à h = 20, il faut 600 séances de live pour avoir 30 appels indépendants.
4. **Page-Hinkley recalibré.** Les valeurs de la littérature (δ = 0,005, λ = 5) donnaient 41 % de
   fausses alertes sur 250 appels indépendants et 63 % sur 750 : le badge « rupture » finissait par
   s'allumer quel que soit le modèle. Avec δ = 0,05, λ = 12, et l'alarme au premier franchissement :
   1,3 % sur 250 appels, 5,7 % sur 750. Une chute de 15 points (55 % → 40 %) est détectée dans environ
   60 % des cas en 250 appels, avec un délai médian d'environ 107 appels. Le réglage est volontairement
   conservateur, pour la raison du point 1.

## Re-mesure

`scripts/daily_predict.py` (planifié à 22:05 sur le PC A) re-mesure, après les prédictions, le PSI des
couples jamais mesurés ou mesurés il y a plus de 7 jours. Au plus 10 par nuit (`--drift-limit`), car chaque
mesure reconstruit le pool de features (~30 s) ; les suivants sont reportés au lendemain. `--no-drift`
désactive la re-mesure. Un échec est journalisé sans changer le code de sortie du script.

## Limites

- Les seuils PSI (0,10 / 0,25) sont des conventions de l'industrie du crédit, pas calibrés sur ce projet.
- La puissance de détection de la dérive de concept est faible aux horizons longs : c'est une propriété des
  données (peu d'appels indépendants), pas du test.
