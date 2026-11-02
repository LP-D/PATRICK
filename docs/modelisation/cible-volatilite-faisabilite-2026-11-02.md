# Cible de volatilité : mesure de faisabilité (2026-11-02)

Suite du point 5.1 de la critique du 28/10 (ADR 0011, « Non fait »). Rien n'est codé dans le pipeline : l'ADR refusait d'écrire de la plomberie non branchée avant
de savoir si la cible valait la peine. Cette note mesure d'abord. Script : `patrick/scripts/vol_target_study.py` (lit le cache local des cours, ne touche à aucune base).

## Protocole

- 40 actifs tirés au hasard dans le cache `series_*` (cours depuis 2000, séries à jour en 2026), horizons 5 et 20 séances.
- Étiquette : `1` si `log(σ_futur / σ_passé) > 0`, σ = racine de la moyenne des rendements² sur `h` séances (la même fenêtre que l'horizon, comme prévu par l'ADR 0011).
- Hors échantillon : réajustement annuel de 2012 à 2026, entraînement sur le passé seulement, trou de `h` séances avant l'année de test.
- Deux scores : `mr` (aucun modèle : retour à la moyenne, `-(log σ_passé − log σ_252)`) et `har` (régression logistique sur les variables HAR : log σ sur 1, 5, 22, 66, 252 séances et l'écart au niveau long).
- Référence : l'AUC de la direction du PRIX sur les mêmes séries, mêmes variables.

## Résultats (AUC moyenne sur 40 actifs)

| Horizon | Volatilité, retour à la moyenne (sans modèle) | Volatilité, HAR | Prix, mêmes variables |
|---|---|---|---|
| 5 séances | 0,771 | 0,778 (10e-90e centile : 0,765-0,796) | 0,512 |
| 20 séances | 0,731 | 0,734 (0,683-0,784) | 0,514 |

100 % des actifs ont une AUC de volatilité HAR > 0,60 ; 5 % (h = 5) et 15 % (h = 20) ont une AUC de prix > 0,55.

## Lecture

1. **La volatilité se prévoit, le prix non** : 0,73-0,78 contre 0,51. Ce n'est pas du talent du modèle : le modèle HAR n'ajoute que **+0,007** (h = 5) et **+0,003** (h = 20) au score sans modèle.
   La quasi-totalité de l'AUC est le retour à la moyenne, mécanique : l'étiquette compare `σ_futur` à `σ_passé`, et `σ_passé` est justement ce qui la prédit (un σ passé élevé revient vers sa moyenne).
2. **Conséquence de conception, la plus importante** : une cible de volatilité brancherait des AUC de 0,75 dans des tableaux que le projet lit comme « 0,52 = presque rien, 0,60 = énorme »
   (familles Diebold-Mariano / Benjamini-Hochberg, signal regroupé, cartes de lots classées par AUC regroupée, conseiller, simulateur). Sans précaution, elle passerait en tête de tout.
   Il faudrait une baseline obligatoire à battre (le retour à la moyenne ci-dessus, pas la persistance du prix), des familles BH séparées et un affichage qui ne la range jamais avec les directions de prix.
3. **La valeur de la volatilité pour le fonds n'est pas une direction à parier mais une taille de position** : le pilote automatique dimensionne déjà à volatilité inverse (`fund/autopilot`). Une vraie
   prévision de σ (et non sa direction) servirait à ce dimensionnement ; elle se juge en RMSE/QLIKE sur le niveau de volatilité, contre HAR-RV, pas en AUC d'une direction.
4. Limites : 40 actifs, un seul modèle (logistique), pas de coûts ni d'instrument (aucune option ni futures de volatilité dans les sources : la direction de σ ne se négocie pas ici), `σ` à partir de
   rendements de clôture à clôture (pas de volatilité réalisée intrajournalière), horizons 5 et 20 seulement.

## Décision proposée (non codée)

Ne pas ajouter `target_kind="vol"` au pipeline (20 consommateurs à décider, AUC trompeuses). Si l'objectif est le dimensionnement : une **prévision du niveau de σ** (HAR-RV, QLIKE) branchée sur le
dimensionnement à volatilité inverse du fonds, évaluée contre la volatilité réalisée passée, sans passer par les classes, le BH ni les champions. À ouvrir sur accord.
