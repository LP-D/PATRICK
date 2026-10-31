# ADR 0013 — Efficacité du F1 : cibles macro retirées, décision de direction, critère AUC, signal regroupé

Date : 2026-10-31. Statut : appliqué aux nouveaux runs ; les anciens runs sont relus comme avant.

## Contexte

Analyse de 3 431 runs terminés (base locale, holdout = 15 derniers mois, jamais vus à l'entraînement) :

- F1_dir moyen 0,506 (test) et 0,503 (holdout) ; 0,495 hors cibles FRED et change. L'AUC de direction (P(hausse) = p2 + p3) vaut 0,528 sur tous
  les runs et 0,519 sur le périmètre sans défaut connu : un signal minuscule mais réel (12 % des runs à p < 0,05 par permutation, 5 % attendu).
- **Fuite sur les cibles FRED.** `data/alignment.py::decide` n'audite les colonnes FRED que pour une cible cotée. Pour une cible FRED, des séries
  dérivées du même taux (`T10Y3M_Spread` AUC 0,77 avec le label du jour, `T10Y2Y`, `T10YIE`, `T5YIE`, `T5YIFR`) gardaient un retard de 0. 341 runs
  macro : AUC 0,61 en moyenne, DGS10 à 1 jour 0,95, SP500 1,00. Ces runs gonflaient le F1 moyen.
- **Décision de direction.** `F1_dir` vient de la classe la plus probable parmi quatre, ramenée à sa direction. Une décision tirée de P(hausse)
  avec un seuil qui suit la médiane des prédictions récentes gagne +0,009 de F1 (± 0,002) sur le holdout, jusqu'à +0,03 aux horizons ≥ 5 jours ; la
  médiane globale du holdout (non causale) donnait +0,014 : cet écart est de l'information venue du futur, il n'est pas retenu.
- **Sélection.** À l'intérieur d'un run (130 runs, 36 essais comparés), le classement par F1 de validation croisée prédit mal le holdout
  (corrélation de rang +0,11) contre +0,37 pour l'AUC de direction. Le gagnant par F1 vaut +0,007 ± 0,007 un essai tiré au hasard.
- **Bruit.** Sur 15 mois de holdout, l'écart-type de l'AUC sous le hasard est de 0,04 à 1 jour et de 0,12 à 30 jours : un run seul ne distingue rien.

## Décisions

1. **Les séries macro (FRED) ne sont plus des cibles** (`config/defaults.py::NON_TARGET_GROUPS`, `NON_TARGET_SOURCES`). Elles restent des variables
   d'entraînement (univers inchangé, mêmes familles de variables), la page Macro et l'exploration. `run_pipeline` et `start_run` les refusent
   (`config/targets.py`) ; un run déjà commencé peut être repris. Les anciens runs à cible FRED sont marqués suspects (`suspicion.alignment_reason`) :
   hors des moyennes, des champions et des candidats du fonds. Rien n'est supprimé.
2. **Métriques de direction à chaque évaluation** (`validation/direction.py`) : `AUC_dir` (sans seuil), `F1_dir_p` et `Acc_dir_p` pour la décision
   « P(hausse) au-dessus de la médiane des 120 prédictions précédentes » (0,5 sans historique). Aucune ligne n'utilise une ligne qui la suit. `F1_dir`
   (argmax) reste calculé : les runs d'avant ne changent pas.
3. **Critère de sélection configurable** (`selection.criterion`) : `AUC_dir` par défaut pour les nouveaux runs, `F1_dir` pour tout run enregistré avant
   le champ (`RunConfig.from_stored_json`) ; il reste hors du hachage tant qu'il vaut `F1_dir`. Le schéma CPCV garde `F1_dir` (il agrège des F1 par
   chemin). Optuna optimise le même critère. Un tableau de résultats renvoie toujours les moyennes `F1_dir` et `AUC_dir` de la configuration choisie.
4. **Signal regroupé par paire cible-horizon** (`validation/pooled_signal.py`, table `pooled_signal`, `patrick audit signal`) : le score moyen de tous les
   runs d'une paire sur leur holdout, un test de permutation par décalage circulaire (qui garde l'autocorrélation due au chevauchement des horizons) et
   la correction de Benjamini-Hochberg sur l'ensemble des paires. Affiché sur la Synthèse ; l'AUC regroupée par classe d'actifs classe les cartes de lots
   (la classe où le signal est mesuré passe en tête). Recalculé chaque nuit.
5. **Placebo de l'Asie** (`audit_placebo.py`, `patrick audit placebo-panel` / `placebo-report`) : un panel de runs légers (huit indices asiatiques, trois
   témoins) pour obtenir le placebo de décalage existant (ADR 0008) sur la classe dont l'AUC à 1 jour (0,59) retombe à 0,52 dès 3 jours.

## Conséquences

- `F1_dir` d'un run ancien (argmax, critère F1) et celui d'un run neuf (critère AUC) ne se comparent plus directement ; la Synthèse garde `F1_dir` pour
  continuer à comparer, `F1_dir_p` et `AUC_dir` sont dans `fold_metric`.
- Le golden walk-forward change (lignes `fold_metric` ajoutées, sélection par AUC) : régénéré par la CI (`golden-regen/<nom>`). Le golden CPCV est inchangé.
- Le duel de champions compare toujours le F1 du holdout : seul le choix À L'INTÉRIEUR d'un run passe à l'AUC. Un chantier suivant devra l'aligner.
- Gain attendu, honnêtement : la décision causale rend ~0,01 de F1 ; le reste de l'écart au hasard est le signal lui-même, qui est faible.
