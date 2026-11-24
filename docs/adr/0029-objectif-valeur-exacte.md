# ADR 0029 — Objectif « valeur exacte » : régression intégrée au pipeline, catégorie de champions à part

Date : 2026-11-24. Statut : acceptée. Code : `config/target_label.py` (`__val`, `split_task`, `is_value_label`), `config/schema.py`
(`ObjectiveConfig.task`, critères `IC` / `R2_oos`, `RunConfig._check_value_task`), `features/target.py` (`attrs["ret"]`, `attrs["bounds"]`),
`models/value.py` (`get_regressor`, `ValueModel`, `class_proba`, `value_metrics`), `models/deep.py` (`DeepRegressor`), `pipeline/engine.py`
(`ValueData`, `_value_data`, `_fit_eval_value`, `_criterion`), `tuning/optuna_runner.py` (`r`), `tracking/export.py`, `live/predict.py`,
`validation/metric_panel.py` (règle `IC` du duel), migration `0055_prediction_value.sql`, formulaire de lancement (`task`, `value_criterion`),
historique (onglet « Valeur exacte »), fiche d'un actif (colonne « Valeur exacte prévue »).
Tests : `tests/pipeline/test_value_pipeline.py`.

## Contexte

Demande de Léon (23-24/11) : pouvoir entraîner, en ML comme en DL, un modèle qui prédit la valeur exacte et pas seulement la direction ; un objectif
différent fait une autre catégorie (« pour un même objectif, ML ou DL, on garde le meilleur ; sinon autre catégorie ») ; dans le pipeline, choisi dans
une liste déroulante comme l'alpha, sans page en plus. Tout le pipeline était en classification (4 classes de direction et d'amplitude) : mesures,
baselines, Diebold-Mariano, duels de champions, signaux live et fonds lisent des probabilités de classes.

## Décisions

1. **Un champ `objective.task`** : `direction` (défaut, comportement historique, hors du hachage de configuration) ou `value`.
2. **Une catégorie par étiquette**, comme l'alpha : `run.target = symbole__val` (`symbole__alpha_benchmark__val`). Champions, registre d'essais, familles
   DM/BH et historique se séparent sans filtre ; le snapshot de données reste celui de la direction (`raw_cache_key` sans l'objectif).
3. **Un régresseur qui parle aussi en classes** (`ValueModel`) : il prédit le rendement à l'horizon, puis les probabilités des 4 classes par la
   distribution de ses erreurs hors échantillon (ajusté sur le début de l'entraînement, erreurs mesurées sur la fin après un trou d'un horizon, puis
   réajusté sur tout l'entraînement ; bornes de classe du régime de chaque ligne). Tout l'aval reste commun ; un pipeline parallèle aurait doublé les
   baselines, les tests et les écrans.
4. **Mesures et critères propres** : `IC` (Spearman prévu / réalisé, défaut), `R2_oos` (contre « rendement nul »), `MAE`, `RMSE`, `Hit_sign`. Le
   critère de classement est `IC` ou `R2_oos` ; le réglage Optuna note un régresseur nu sur ce critère ; le duel de la catégorie classe sur l'IC du
   contrôle final, ML et DL confondus.
5. **Limites assumées** : walk-forward seulement, sans rééchantillonnage ni empilement ; sélection de variables et interactions découvertes sur les
   classes de direction ; coût d'un ajustement doublé (mesure des erreurs puis réajustement) ; les fonds n'utilisent pas encore ces champions.
6. **Affichage** : la prévision live est enregistrée (`prediction.y_value`) et affichée sur la fiche de l'actif ; mesures dans le panneau d'un run.

## Conséquences

Les runs de direction existants ne changent pas (hachage, étiquette, mesures). « Autre » objectif (volatilité réalisée, probabilité d'un grand
mouvement) : même mécanisme, une valeur de `task` et une cible continue de plus.
