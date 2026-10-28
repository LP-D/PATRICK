# ADR 0008 — Méthode d'évaluation 2

Date : 2026-10-28 · Statut : acceptée · Code : `config/schema.py` (`ValidationConfig.method_version`), `config/defaults.py` (`CURRENT_METHOD_VERSION`), `features/target.py` (`TargetSpec`, `METHOD_1`, `METHOD_2`, `spec_for`, `regime_series`, `non_flat_mask`), `features/alpha_target.py`, `pipeline/engine.py` (`_dm_losses`, `_dm_against_baselines`, `_placebo_lag`, masques d'entraînement, `_config_hash`, `_selector_config_hash`), `selection/shap_select.py`, `tracking/export.py`, `tracking/db.py` (`save_dm_result(loss=)`, `save_placebo`), `tracking/stats.py` (famille BH), migrations 0046 et 0047 · Tests : `tests/test_method_v2.py`

## Contexte

Une critique du 28/10/2026, vérifiée dans le code, a confirmé quatre défauts de méthode (le cinquième, les barres de change, est l'ADR 0007) :

1. **Le test de Diebold-Mariano portait sur les 4 classes**, pas sur la direction que le fonds négocie (docstring : « 0/1 directional loss »). La baseline
   des devises (`random_walk_no_drift`) prédit toujours la classe 2 : un modèle qui ne devine que l'amplitude la bat sans aucune compétence directionnelle.
2. **Les jours plats étaient retirés de l'évaluation** (|rendement| < 0,3 %, seuil absolu quel que soit l'actif et l'horizon, soit environ 60 % des jours
   à 1 jour sur les devises : 120 lignes de holdout sur 325). La sélection des lignes de test dépendait du futur, alors que le live juge tous les jours.
3. **Les régimes CALM/NORMAL/STRESS étaient des terciles du niveau du prix** (héritage du VIX) : pour une action en tendance, presque tout le test tombe en STRESS.
4. **SHAP classait les variables sur les 500 plus anciennes lignes** de l'entraînement : avec une fenêtre croissante, l'importance reflétait 2000-2002.

Mesure préalable sur 45 runs de change (holdouts stockés) : le DM sur la direction rejette plus que le DM sur 4 classes (47 % contre 27 %). L'hypothèse
« le modèle n'a que de l'amplitude » est donc fausse ; la perte directionnelle n'en reste pas moins la bonne, puisque c'est ce qui se négocie.

## Décision

`ValidationConfig.method_version` : **1** = méthode d'origine (valeur de tout run enregistré avant le champ), **2** = méthode courante (`D.CURRENT_METHOD_VERSION`,
donnée à tout run neuf par `run_pipeline`). Le live, l'explication, la reprise et le duel de champions rejouent la version du run.

| | Méthode 1 | Méthode 2 |
|---|---|---|
| Perte du DM | erreur 0/1 sur les 4 classes | erreur 0/1 sur le sens (classes 2-3 contre 0-1), enregistrée dans `dm_result.loss` |
| Jours plats | retirés de la cible, donc de l'évaluation | seuil = 0,25 x volatilité réalisée causale (60 j) x racine(horizon) ; **gardés dans l'évaluation**, retirés de l'entraînement et de l'ajustement des seuils |
| Régimes | terciles du niveau du prix | terciles de la volatilité réalisée sur 60 jours, ajustés sur le train (indices de volatilité : le niveau) |
| SHAP | `shap_sample` plus anciennes lignes | `shap_sample` plus récentes lignes |
| Famille BH | p-values sur 4 classes | une cible qui a une p-value sur la direction n'utilise que celle-là ; sinon l'ancienne, faute de mieux |

Ajout du même lot : **placebo automatique par run** (`run_placebo`, migration 0047) : le modèle final réévalué sur le holdout avec toutes les variables
retardées d'un jour de plus ; verdict `same_day` quand une AUC d'au moins 0,58 perd au moins 0,08. C'est un diagnostic, il ne choisit rien.

## Conséquences

- Le hachage de configuration et la clé du cache de sélection ne bougent que pour la méthode 2 : un run de méthode 1 retrouve ses études Optuna.
- Les 2 249 runs existants ne sont pas réécrits et ne sont pas comparables à un run de méthode 2 : leurs métriques portent sur d'autres lignes de test.
  Comparer deux runs de méthodes différentes est trompeur (jours plats, régimes) ; le champion en titre est rejoué sur les données du challenger par le duel.
- Le golden walk-forward et le golden CPCV de la CI changent (méthode 2 pour tout run neuf) : régénérés par la CI (`golden-regen/`).
- Le jeu de test d'un run de méthode 2 contient environ 2,5 fois plus de lignes à 1 jour : les p-values du DM sont plus resserrées, mais les lignes
  voisines restent corrélées (blocs `n/h`, ADR 0003).
- Limites : les jours plats gardés sont étiquetés par le signe de leur rendement (classe faible), un rendement exactement nul compte « hausse faible » dans
  la cible alors que le live le laisse en attente ; le DM sur un score continu (Brier, log-loss) et les baselines probabilistes ne sont pas faits.
