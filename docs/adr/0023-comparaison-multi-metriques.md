# ADR 0023 — Comparaison des modèles sur plusieurs mesures : AUC de direction + Brier, panneau partout, F1 retiré des aperçus

Date : 2026-11-16. Statut : codée (branche `feat/comparaison-multi-metriques`), à fusionner.

## Contexte

- L'ADR 0013 a montré que le F1 de direction départage mal les modèles : il dépend d'un seuil (la classe la plus probable parmi quatre),
  son classement en validation croisée prédit mal le holdout (corrélation de rang +0,11 contre +0,37 pour l'AUC de direction) et il ne dit
  rien de la fiabilité des probabilités dont se servent le fonds systématique et le conseiller.
- Le duel champion / challenger comparait l'AUC de direction depuis l'ADR 0014, mais retombait sur le F1 dès qu'un côté n'avait pas
  d'AUC, et ignorait la calibration : un challenger qui classe un peu mieux avec des probabilités nettement moins fiables prenait le titre.
- Partout ailleurs (Historique, classes d'actifs, Synthèse, Analyses, fiche d'une cible, accueil, comparaison de runs, fiche d'un run),
  l'en-tête était « AUC (4 classes) · F1 ». L'AUC affichée n'était même pas celle qui sélectionne (AUC une-contre-toutes sur 4 classes,
  et non l'AUC de P(hausse)).
- Couverture mesurée le 2026-11-16 sur 4 317 meilleurs essais : `AUC_dir` et `Acc_dir_p` pour 726 seulement (calculés depuis le
  2026-10-31), `Brier_up` et `MCC_4cls` pour presque tous. Les prédictions de test et de holdout de ces essais sont en base.

## Décisions

1. **Un panneau de quatre mesures, toujours les mêmes, toujours dans cet ordre** (`validation/metric_panel.py`) :
   `AUC_dir` (classement des hausses avant les baisses, sans seuil, 0,5 = hasard), `Brier_up` (fiabilité de P(hausse), plus bas = mieux,
   0,25 = pile ou face), `MCC_4cls` (décisions sur les quatre mouvements, 0 = hasard, insensible au déséquilibre), `Acc_dir_p` (part des
   jours où la direction annoncée par P(hausse), décision causale de l'ADR 0013, était juste).
2. **Règle du duel** : le challenger prend le titre si son `AUC_dir` est strictement plus haute sur le même holdout ET si son `Brier_up`
   ne dépasse pas celui du champion de plus de `BRIER_TOLERANCE` = 0,005 (le réglage baisse le Brier de 0,006 en moyenne, audit du
   2026-10-23). Égalité ou doute : le champion reste. Un côté sans Brier : l'AUC seule. Un côté sans P(hausse) : le MCC. **Le F1
   n'intervient plus dans aucune comparaison**, y compris pour un run enregistré avec le critère F1. Le duel archive le panneau des deux
   côtés et la raison (`better`, `auc_not_better`, `brier_worse`, `mcc_not_better`). Le garde-fou « score impossible » (F1 ≥ 0,80,
   AUC 4 classes ≥ 0,85) est inchangé : c'est une détection de fuite, pas une comparaison.
3. **Classements des listes** (meilleur modèle d'un actif, tableaux de la page Analyses, synthèse d'un lancement) : `AUC_dir` puis `Brier_up`
   (`metric_panel.rank_key`), MCC pour un lancement d'avant l'AUC de direction. Le choix À L'INTÉRIEUR d'un run ne change pas (critère de
   l'ADR 0013) ; le meilleur essai provisoire d'un run interrompu suit désormais ce critère (AUC, F1 pour un essai d'avant).
4. **Le panneau remplace « AUC · F1 » partout** : Historique, panneau latéral d'un run, classes d'actifs, Synthèse (médianes), page Analyses
   (indicateurs, tableaux par modalité, variables, séries, liste des modèles), fiche d'une cible (directionnels et alpha), signaux d'un
   actif (holdout du champion), derniers runs (accueil, page de lancement), comparaison de runs (meilleure valeur marquée), fiche d'un run
   (indicateur du holdout, synthèse du lancement, en-têtes du tableau par pli), analyse d'un run (essais, plis), carte cible × horizon et
   distribution par algorithme (sélecteur de mesure), registre des modèles, explorateur de variables, `patrick champions list`.
   Le F1 reste dans le tableau complet des métriques par pli et dans les matrices de confusion, plus dans aucun aperçu.
5. **Écart à la persistance en MCC** : la référence de persistance n'a pas de probabilités, son MCC remplace son F1 dans le panneau d'un run.
6. **Rattrapage** (`tracking/metric_backfill.py`, `patrick audit panel-backfill`, chaque nuit après les prédictions et dans le cycle de
   l'application) : les mesures du panneau manquantes sont recalculées pli par pli depuis les prédictions en base, avec les fonctions mêmes
   de l'évaluation. Ajout seulement (`INSERT OR IGNORE`), idempotent. Vérifié en lecture seule sur 60 essais récents : 360 plis recalculés,
   écart nul avec les valeurs enregistrées pour les cinq mesures.

## Conséquences

- Un challenger aux probabilités nettement moins fiables ne remplace plus un champion ; certaines relances conseillées « perdront » un
  duel qu'elles auraient gagné. C'est voulu : le fonds et le conseiller consomment P(hausse).
- Les essais non retenus d'un ancien run n'ont pas de prédictions en base : leur `AUC_dir` reste absente, d'où le repli sur le MCC dans
  les classements de leur synthèse.
- `champion.holdout_f1_dir` reste écrit (détection de fuite) ; aucune migration de schéma.
- `duel_outcome.criterion` vaut désormais `AUC_dir+Brier_up` (ou `AUC_dir`, `MCC_4cls`) pour les nouveaux duels.
