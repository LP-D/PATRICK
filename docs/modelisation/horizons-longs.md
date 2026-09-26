# Horizons 252 / 504 / 756 jours — ce que les données permettent de valider

Date : 2026-09-26. Question de la roadmap (bloc 3) : « features de cycle long pour justifier les horizons
252/504/756 j ». Les features existent désormais (famille `long_cycle`, optionnelle). Elles donnent au modèle
la bonne information ; elles ne règlent pas le problème principal, qui est statistique.

## Mesure sur prix réels (Yahoo, 2026-09-26)

N_eff = nombre d'observations non chevauchantes (séances / horizon). « Précision requise » : taux de bonnes
directions nécessaire pour battre, au seuil unilatéral de 5 %, la règle naïve « toujours la classe
majoritaire », **sur tout l'historique** (le holdout, 12–24 mois, est bien plus court).

| Actif | Horizon | P(hausse) | N_eff | Précision requise |
|---|---:|---:|---:|---:|
| ^GSPC (1990–2026) | 20 | 0,64 | 463 | 0,67 |
| | 252 | 0,81 | 37 | 0,91 |
| | 504 | 0,84 | 18 | 0,98 |
| | 756 | 0,83 | 12 | 1,00 |
| ^FCHI (1990–2026) | 252 | 0,66 | 37 | 0,79 |
| | 756 | 0,73 | 12 | 0,94 |
| EURUSD=X (2004–2026) | 252 | 0,52 | 23 | 0,69 |
| | 756 | 0,44 | 8 | 0,85 |
| GC=F (2001–2026) | 252 | 0,75 | 26 | 0,89 |
| | 756 | 0,83 | 8,5 | 1,00 |

Script de mesure : rendement `s.shift(-h) / s - 1`, taux de hausse, N_eff = T / h, seuil
`base + z_0,95 · sqrt(base(1-base)/N_eff)` (approximation normale — optimiste pour N_eff < 20).

## Lecture

1. **504 et 756 j ne sont pas validables** avec ces historiques : même un modèle parfait sur tout
   l'échantillon ne se distinguerait pas significativement de « toujours hausse » sur les indices actions
   et l'or. Dans le holdout de 15 mois par défaut (~315 séances), toutes les prédictions à 756 j partagent
   l'essentiel de leur fenêtre : moins d'une observation indépendante.
2. **252 j n'est testable que sur un actif sans dérive dominante** (EUR/USD : 69 % requis), et encore
   sur tout l'historique, pas sur le seul holdout.
3. Sur les actions, le taux de hausse de base (0,81–0,84 pour le S&P 500) fait que l'exactitude brute est
   trompeuse à long horizon : F1 directionnel, Brier et comparaison à la persistance sont les seuls
   indicateurs honnêtes — déjà la colonne « benchmark » de `/runs`.

## Décision (2026-09-26)

- **504 et 756 j sont descriptifs** (`D.DESCRIPTIVE_HORIZONS`) : toujours lançables pour l'exploration, mais
  hors de la famille Benjamini-Hochberg (une cible testée seulement à ces horizons n'est pas « testée »,
  leurs p-values n'entrent jamais dans le minimum d'une cible), hors de tout signal de portefeuille
  (`/portfolio`, rejeu des signaux sur un compte de patrimoine), et marqués « descriptif » sur toutes les
  pages. La synthèse indique combien de runs sont ainsi hors famille.
- **252 j reste testé** : validable sur un actif sans dérive dominante (EUR/USD), avec la même prudence
  qu'au point 2 ci-dessus.
- Pour un signal long terme exploitable, préférer une cible continue (rendement à 252 j régressé) ou un
  panel multi-actifs (N_eff × nombre d'actifs faiblement corrélés) plutôt qu'une classification par actif.
- Les taux zone euro étaient absents : ECBDFR (facilité de dépôt BCE, quotidien depuis 1999) est désormais
  dans l'univers de features (pas comme cible) et donne au carry EUR/USD sa jambe euro. Niveau biaisé vers le
  bas avant 2009 (plancher du corridor BCE) ; les variations sont l'information utile.
