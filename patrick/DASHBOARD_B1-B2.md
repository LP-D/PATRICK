# Synthèse `/` — rapport B1-B2 (branchement aux données réelles)

Livrable intermédiaire du chantier de remplacement de `/` par une nouvelle page de synthèse, réutilisant la structure de `/phase9` branchée aux vraies données. Arrêt avant B3-B6 (états vides, pas de cache, tests, devenir de `/phase9`), conformément à la consigne. Aucun fichier de production modifié à ce stade — investigation et plan uniquement.

---

## B1 — Structure de la page

Ordre proposé confirmé (aucun doute réel, structure alignée sur ce qui existe déjà) :

1. **Bandeau de couverture** : `n_targets` entraînées / 550 (univers théorique, `config/defaults.py::DEFAULT_TARGET_GROUPS`) + `MAX(prediction.ts)` tous splits confondus, toutes cibles.
2. **Qualité par cible** : `trackstats.fdr_across_targets()` — voir B2, c'est la vraie source, pas `phase9.signal_dm_summary`.
3. **Dernière prédiction par cible** : table `prediction` (réelle, déjà peuplée par le pipeline — `y_true`/`y_pred`/`y_proba`/`ts`), dernière ligne par cible (`split='live'` si présente, sinon dernier `test`/`holdout`).
4. **Métriques du modèle gagnant, ventilées par direction** : **gap réel identifié**, voir B2.
5. **Historique récent** : `tracking.history.list_runs()` (déjà utilisée par `/runs`), tronquée — aucune nouvelle requête.

---

## B2 — Branchement aux données réelles

### `regime_summary` / `classify_regime_daily`

Confirmé par recherche exhaustive (`grep` sur tout `patrick/patrick/`) : **jamais appelée en dehors de `phase9.py` et de ses propres tests**. Aucune ligne de code de production (`pipeline/engine.py`, `worker.py`, `predict.py`, `cli.py`) ne l'invoque, aucune table de la base ne stocke de classification de régime.

Ce n'est pas une donnée qui existe et que j'aurais dû aller chercher ailleurs : **elle n'a jamais tourné en production, point final**. Conformément à l'anti-pattern explicite de la consigne, je ne la branche pas — section en état vide explicite (B3) :

> « Classification de régime jamais exécutée en production — fonctionnalité disponible (`patrick.phase9.classify_regime_daily`) mais non intégrée au pipeline. »

### `determine_signal_quality_status` / `signal_dm_summary`

Écart à signaler avant de continuer : ces deux fonctions `phase9.py` ne sont **pas** le chemin réel de production. Le vrai chemin, déjà câblé et déjà utilisé par `/runs/{id}` et `/targets/{ticker}`, est :

- `dm_result` (table réelle, peuplée par `pipeline/engine.py` via le vrai `diebold_mariano()`, **pas** la copie de `phase9.py`) ;
- `tracking/stats.py::fdr_across_targets()` — MIN(p-value) par cible × `benjamini_hochberg()` (même fonction de correction que `signal_dm_summary` appelle en interne) → `{target: {p_value, adjusted_p_value, rank, significant}}`.

Utiliser `phase9.signal_dm_summary` littéralement obligerait à recharger les tableaux de prédictions bruts et à recalculer le DM — redondant, et risque réel d'obtenir une p-value différente de celle déjà affichée sur `/runs/{id}`/`/targets/{ticker}` (incohérence au clic, contraire à B4).

**Proposition** : `fdr_across_targets()` comme source réelle pour le point 2 du bandeau, pas `signal_dm_summary`. `determine_signal_quality_status` reste utilisable tel quel pour le verdict agrégé, alimenté par les p-values réelles de `fdr_across_targets()` au lieu du dict codé en dur — ou, alternative plus proche de l'existant : `history.station_verdict()` fait déjà exactement ce rôle de verdict agrégé et sert déjà le bandeau actuel.

**À trancher** : réutiliser `station_verdict()` (zéro nouveau code) ou brancher `determine_signal_quality_status` sur les p-values réelles (répond plus littéralement à la consigne initiale) ?

### Gap réel trouvé pour B1.4 (métriques par direction)

Aucune métrique par direction (hausse/baisse séparées) n'est actuellement stockée — `fold_metric` ne contient que des agrégats macro (`F1_dir`, `Acc_dir`, `AUC_ovr_4cls`, calculés sur DOWN/UP fusionnés). Ce qui existe par « force » (`F1_UP_FORT`/`F1_DOWN_FORT`) est un axe différent (amplitude dans une direction, pas performance par direction).

Solution sans toucher au pipeline : la table `prediction` (réelle, `y_true`/`y_pred`/`y_proba` par ligne, `split='test'`/`'holdout'`) permet de **recalculer en lecture seule**, au chargement de la page, le F1/accuracy/AUC par classe DOWN vs UP — même philosophie que `tracking/stats.py`/`holdout_diagnostic.py` (« recomputed on the fly on request, no cache »), aucune nouvelle colonne, aucun changement de pipeline.

---

## Points à trancher avant B3-B6

1. Verdict agrégé section 2 : `station_verdict()` (déjà existant) ou `determine_signal_quality_status` rebranché sur les p-values réelles ?
2. Confirmation de l'état vide pour la classification de régime (jamais exécutée en production), plutôt que d'ouvrir un chantier séparé pour l'intégrer ?

Aucun fichier de production modifié par ce rapport.
