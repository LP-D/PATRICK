# Fonds, chantier 3 — pilote automatique : sélection des modèles et simulation systématique

Suite de `2026-10-06-fonds-mode-ml-seuils-design.md`. Demande de Léon (16/10/2026) : « implémente les simulations
systématiques, et une auto-sélection des modèles pertinents à utiliser ».

## 1. Pourquoi

Le mode « ML à seuils » existe, mais chaque règle se monte à la main : choisir l'essai, les seuils, l'instrument, la
taille. Les deux portefeuilles du 11/10 ont été construits par des scripts jetables : des instantanés, que rien ne
renouvelle ni ne ferme. Le pilote automatique fait la même chose **dans le produit** : il choisit seul les modèles qui
méritent d'être tradés, ouvre une position sur chaque signal, la ferme à l'horizon du modèle, la renouvelle tant que le
signal tient, et recommence chaque jour.

## 2. Périmètre

Livré : sélection automatique (§3), règle « direction + sortie à l'horizon » (§4), dimensionnement à volatilité inverse
(§5), cycle quotidien (§6), page, API et commande.
Hors périmètre, dit une fois : **carry trade** (il faut des taux de référence que FRED non configuré ne fournit pas),
dimensionnement proportionnel au score, optimisation de portefeuille (corrélations), ordres au comptant sur un titre
cotant en devise sans paire de change.
Non-objectif : trouver des seuils qui gagnent. Aucun seuil n'est ajusté ; la sélection ne s'appuie que sur des preuves
statistiques déjà calculées par l'application.

## 3. Sélection automatique des modèles (`fund/selection.py`)

Lecture seule. Une cellule = un couple (cible, horizon) ; son modèle est le **champion** en titre. Une cellule est
retenue si, dans l'ordre (le premier échec est le motif d'exclusion affiché) :

| Critère | Niveau `strict` (défaut) | Niveau `large` |
|---|---|---|
| négociable : cible hors séries FRED, cotation disponible, instrument possible dans l'enveloppe | oui | oui |
| score non suspect (`validation/suspicion.py` : F1 ≥ 0,80 ou AUC ≥ 0,85 = fuite) | oui | oui |
| signal live frais (dernier `split='live'` datant d'au plus `fresh_days` = 7 jours) | oui | oui |
| la cible survit à la correction de Benjamini-Hochberg (`fdr_across_targets`, α = 0,10) | oui | non |
| Diebold-Mariano de la cellule sur le holdout : p < `alpha_dm` = 0,05 | oui | non |

Classement : p de Diebold-Mariano croissant, puis signal le plus récent. Plafond `max_models` = 40. Le résultat porte,
pour chaque modèle retenu, ses preuves (p DM, p BH, taux de réussite live s'il existe) et, pour les exclus, le compte par
motif. **Mon choix** : `strict` par défaut, parce que sur 160 cibles seules quelques-unes survivent à la correction pour
tests multiples ; `large` existe pour reproduire le portefeuille « tous les signaux non suspects » du 11/10.
Honnêteté : la sélection utilise des résultats du holdout, donc seul le segment **live** (après l'entraînement) est une
mesure hors échantillon ; les règles automatiques n'utilisent que lui.

## 4. Règle « direction + sortie à l'horizon » (`fund/systematic.py`)

Deux ajouts à la configuration d'une règle, les règles existantes ne changent pas :

- `signal: {mode: "direction", min_confidence}` : le sens vient de la classe prédite (haussière = long, baissière =
  short) ; un signal dont `y_proba` < `min_confidence` (0 par défaut) est neutre. Raison : le score à seuils de
  `_directional_score` mélange sens et confiance et, pour un modèle à 4 classes dont la classe gagnante dépasse rarement
  0,6, un seuil proche de 0,5 transforme un haussier peu confiant en vendeur.
- `hold: {mode: "horizon", sessions: h}` : une position ouverte à l'exécution d'un signal est fermée `h` séances plus tard ;
  un signal de même sens avant l'échéance la **renouvelle** (nouvelle échéance, aucun ordre) ; un signal de sens opposé
  ferme et rouvre le même jour ; un signal neutre ne change rien. Sans signal, la position se ferme à son échéance : c'est
  la sortie automatique. L'exécution reste la première séance du titre à partir de *t + 1 jour*, au cours de clôture.
- `since` : ignore les signaux antérieurs à la date (jour avant l'ouverture de la stratégie) ; `retired_on` : plus aucune
  ouverture ni renouvellement après cette date, les positions ouvertes se ferment à leur échéance.
- Quantité d'un CFD : décimale (≥ 0,0001) ; entière pour un future, comme dans le service.

Idempotence inchangée : note `auto:<règle>:<date>:<action>`, la fermeture d'échéance porte la date d'échéance.

## 5. Dimensionnement

Budget par cible = volatilité inverse (σ des rendements de 60 séances) normalisée sur les cibles retenues, partagé à
parts égales entre les modèles de la cible ; somme des budgets = `gross` (100 % du capital par défaut). Une règle ne tient
qu'une position à la fois : l'exposition brute maximale vaut donc `gross`. Instrument : ETF et actions en achat au
comptant (montant), tout le reste en CFD (quantité = budget / cours converti, fixée à la création et recalculée à chaque
cycle pour les prochaines ouvertures) ; enveloppe PEA : comptant et long seulement, les modèles qui exigent un CFD sont
exclus avec ce motif. Un future continu (`=F`) se négocie en CFD avec l'avertissement existant.

## 6. Cycle (`fund/autopilot.py`)

Politique par stratégie dans `fund_strategy.autopilot_json` (migration 0036) : `enabled`, `tier`, `gross`, `max_models`,
`allow_short`, `min_confidence`, `fresh_days`, dernière exécution. `run(strategy)` : sélectionne → complète/ajuste les règles
**gérées** (`config.managed`) → retire (`retired_on`) celles dont le modèle n'est plus retenu ou dont le champion a changé →
applique chaque règle → rend un compte rendu (créées, ajustées, retirées, ordres placés, refusés avec motifs). Les règles
saisies à la main ne sont jamais touchées. Les règles gérées ne comptent pas comme « configuration essayée » (aucun seuil
n'est cherché). Déclenchement : bouton, commande `patrick fund autopilot-run`, et après les prédictions du jour
(`live_refresh`, tâche `Patrick-DailyPredict` et application ouverte) pour toutes les stratégies activées ; une erreur n'arrête
jamais les prédictions.

Partage entre PC : `autopilot_json` est une colonne de la stratégie, elle voyage avec elle (`fund/share.py`) ; version
minimale du schéma relevée à 36.

## 7. Page, API, commande

Panneau d'une stratégie sur `/fonds`, section « Pilote automatique » : état, réglages (niveau, exposition brute, nombre
maximal de modèles, vente à découvert), boutons *Prévisualiser* (sélection + tailles, rien n'est écrit), *Activer / appliquer*
et *Désactiver* (les règles gérées sont retirées, les ordres passés restent), tableau des modèles retenus avec leurs preuves et
décompte des exclusions par motif. API : `GET|PUT|DELETE /api/fund/strategies/{id}/autopilot`, `POST .../autopilot/preview`,
`POST .../autopilot/run`. Commande : `patrick fund autopilot-select|autopilot-run`.

## 8. Choix que j'ai faits seul

`strict` par défaut ; fraîcheur 7 jours ; plafond 40 modèles ; exposition brute 100 % ; aucun levier explicite (le défaut du
service) ; sortie après `h` séances comptées depuis l'exécution ; pas de carry ; les règles gérées ne passent pas par le
registre des essais.
