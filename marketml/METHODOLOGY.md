# Méthodologie

Ce document décrit comment `patrick` évite les pièges classiques du backtesting
ML sur séries temporelles financières, et documente honnêtement ses limites
connues. Il complète le code (les modules cités contiennent les docstrings
détaillées) sans le dupliquer.

## Walk-forward strict

Aucune validation croisée aléatoire (`KFold`, `train_test_split` mélangé) :
l'historique est découpé en folds chronologiques successifs
(`patrick/validation/walkforward.py`, `build_fold_cuts`) — le train d'un fold
ne contient jamais de données postérieures à son test. Le nombre de folds et
la fraction minimale de train sont paramétrables (`ValidationConfig`).

## Purge et embargo (López de Prado)

Deux fuites distinctes, deux mécanismes distincts :

- **Purge** (`patrick/validation/purge.py`) : une ligne de train dont la
  fenêtre de label (`horizon` jours ouvrés en avant) chevauche la coupure de
  fold est retirée du train — sinon son label contient de l'information sur
  la période de test.
- **Embargo** (`patrick/validation/embargo.py`) : au-delà de la purge, les
  `embargo_bars` premières barres du test (par défaut dérivées de l'horizon,
  `ValidationConfig.embargo_bars=None`) sont retirées — des features à
  fenêtre glissante calculées juste après la coupure incluent encore des
  observations du train, donc restent corrélées avec lui même une fois le
  label "propre".

Vérifié par un test de corruption du futur bout-en-bout
(`tests/test_leakage.py::test_corrupting_the_future_does_not_change_train_features_or_model`)
qui modifie délibérément les données post-coupure et vérifie que les
features/le modèle du train n'en sont pas affectés, et par un test de
décalage de cible (`test_shifting_target_by_one_bar_collapses_performance_to_baseline`)
qui vérifie qu'un label décalé d'une barre fait s'effondrer la performance au
niveau des baselines — la preuve empirique qu'il n'y a pas de fuite résiduelle
qui compenserait artificiellement un mauvais alignement temporel.

## Alignement temporel par classe d'actif (as-of join)

Les données sont indexées par date calendaire (barres quotidiennes), sans
horodatage de clôture intrajournalier. Une jointure "même date" traiterait
implicitement une clôture Tokyo (~08:00 UTC) et une clôture New York
(~20-21:00 UTC) du même jour comme simultanées — faux dans le sens où une
feature dont la clôture arrive *après* celle de la cible contiendrait de
l'information non encore disponible au moment de la décision.

`patrick/data/session_calendar.py` décale d'une barre toute feature dont la
classe d'actif clôture après celle de la cible (heure de clôture UTC
approximative par classe : crypto 24/7, FX ~22:00, actions US ~21:00,
actions Europe ~16:30, etc.). Approximation documentée — pas un vrai as-of
join intrajournalier, qui demanderait de migrer toute l'ingestion sur des
données horaires (hors périmètre).

## Vintages point-in-time (macro FRED)

Par défaut, l'API FRED renvoie chaque série *telle que révisée aujourd'hui*
— pas telle qu'elle était connue à la date de décision historique (les
révisions de PIB, chômage, etc. peuvent être significatives). Les jointures
macro utilisent en priorité les vintages ALFRED
(`patrick/data/sources/fred_source.py::download_series(realtime_date=...)`),
qui renvoient la série telle que publiée à `realtime_date`, évitant que le
modèle "apprenne" sur des révisions qui n'existaient pas encore à l'époque.

## Correction multi-tests (validité statistique)

Chercher la meilleure config parmi *N* essais gonfle mécaniquement le Sharpe
apparent du gagnant, même si aucun n'a de vrai edge — quatre garde-fous,
tous dans `patrick/validation/` :

- **Sharpe déflaté** (`dsr.py::deflated_sharpe_ratio`, Bailey & López de
  Prado 2014) : corrige le Sharpe du nombre d'essais dont le gagnant a été
  sélectionné (`tracking.stats.count_cumulative_trials` — tout l'historique
  de runs sur la cible, pas seulement le run courant).
- **PBO** (`pbo.py::compute_pbo`, CSCV) : probabilité que la config gagnante
  en échantillon (IS) soit perdante hors échantillon (OOS), estimée en
  partitionnant les blocs temporels en toutes les combinaisons IS/OOS
  possibles.
- **Diebold-Mariano** (`diebold_mariano.py`) : p-value du test de différence
  de perte entre le meilleur modèle et la meilleure baseline systématique —
  un modèle non significativement meilleur qu'une baseline est signalé
  comme tel dans le leaderboard, pas caché.
- **Compteur d'essais cumulé** : affiché en permanence à côté de chaque
  Sharpe/PBO (dashboard web et `patrick report`) — jamais de métrique de
  performance sans le nombre d'essais qui l'a produite (anti-pattern #6 du
  plan de développement).

Le même principe s'applique au simulateur d'investissement (Phase 4) : chaque
configuration de simulation testée sur une cible est journalisée
(`simulation` table), et le compteur + Sharpe déflaté correspondant sont
affichés en permanence dans `/simulate`.

## Holdout terminal jamais touché

Les `holdout_months` derniers mois d'historique (`ValidationConfig`,
désactivable à 0) sont réservés avant même le découpage walk-forward
(`pipeline/engine.py::_walk_forward_span`) — ni la sélection de features, ni
le tuning Optuna, ni le tri du leaderboard ne les voient jamais.
`_evaluate_holdout` réévalue *une seule fois* la config déjà choisie sur ce
holdout, jamais pour choisir entre plusieurs configs (anti-pattern #1 du plan
de développement : « trier/sélectionner sur le holdout »).

## Baselines systématiques

Trois baselines (`patrick/validation/baselines.py`) calculées pour chaque
(horizon, fold, régime) et ajoutées au leaderboard à côté des modèles réels :
classe majoritaire, persistance (« rien ne change »), et HAR-RV (Corsi —
direction par persistance de signe, amplitude reclassée via les mêmes seuils
causaux que la cible réelle). Un F1_dir de 0.55 n'a de sens que rapporté à
ces baselines, pas dans l'absolu.

## Rééquilibrage des classes : SMOTE vs `class_weight`

Défaut actuel : SMOTE (suréchantillonnage, `sampler.candidates: ["SMOTE"]`).
`class_weight="balanced"` est déjà appliqué par défaut sur les classifieurs
qui le supportent nativement (LightGBM, RandomForest, CatBoost —
`models/registry.py`), en plus de SMOTE ; XGBoost et GradientBoosting n'ont
pas d'équivalent sklearn natif. Le pseudo-sampler `"none"`
(`models/samplers.py`) permet de tester `class_weight` SEUL (sans
suréchantillonnage) via la même grille `sampler.candidates` existante — ex.
`sampler.candidates: ["SMOTE", "none"]` dans une config de run.

**L'A/B test empirique sur 5 cibles (demandé par le plan) n'a pas pu être
exécuté dans cette session** : le sandbox n'a pas d'accès réseau à
yfinance/FRED (vérifié directement — toute requête sortante vers ces domaines
échoue avec une erreur de proxy). Marche à suivre pour l'exécuter dans un
environnement avec accès réseau :

```bash
for target in "^VIX" "^GSPC" "SPY" "TLT" "GLD"; do
  patrick run --config configs/ab_test_${target}.yaml  # sampler.candidates: ["SMOTE", "none"]
done
```

puis comparer, par cible, les lignes `SMOTE` vs `none` du leaderboard (même
horizon/régime/N/algo) sur F1_dir/balanced accuracy — changer le défaut vers
`class_weight` seul (`sampler.candidates: ["none"]`) si `none` gagne sur la
majorité des 5 cibles. Non fait faute de données réelles disponibles ici.

## Limites connues

- **Biais de survivance** : l'univers de tickers (actions, ETFs) est la
  liste *actuelle* de composants — les actifs retirés d'un indice, délistés
  ou en faillite depuis n'y figurent pas, ce qui gonfle mécaniquement la
  performance historique apparente de tout ce qui touche à des paniers
  larges (ex. features dérivées d'un indice sectoriel). Pas corrigé ici (un
  univers point-in-time demanderait une source de données dédiée, hors
  périmètre de cet outil local).
- **`Adj Close` rétro-ajusté** : les prix ingérés via yfinance sont ajustés
  dividendes/splits *rétroactivement à la date d'ingestion*, pas tels qu'ils
  étaient affichés au moment de la décision historique — une forme de fuite
  d'information mineure mais réelle (l'ampleur d'un ajustement futur n'était
  pas connue à l'époque). Écart assumé, pas un risque au niveau
  purge/embargo (l'ajustement ne dépend pas de la fenêtre walk-forward).
- **`y_true` simplifié pour `patrick predict --live`** : les résultats
  réalisés des prédictions live sont stockés en binaire (hausse/baisse),
  pas reclassifiés dans les 4 classes du modèle (les seuils par régime,
  fittés au moment de l'entraînement, ne sont pas persistés) — sert
  uniquement à l'affichage de suivi, jamais à réentraîner ou sélectionner un
  modèle.
