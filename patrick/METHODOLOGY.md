# Méthodologie

Ce document explique **pourquoi** `patrick` est construit comme il l'est —
les garanties qu'il apporte contre le sur-ajustement et la fuite
d'information, où elles s'arrêtent, et ses limites connues. Il complète le
code (les modules cités contiennent des docstrings détaillées) sans le
dupliquer. Pour *comment* l'utiliser, voir `README.md`.

## 1. Walk-forward strict

Aucune validation croisée aléatoire (`KFold`, `train_test_split` mélangé)
nulle part dans le pipeline : l'historique est découpé en folds
chronologiques successifs (`patrick/validation/walkforward.py`,
`build_fold_cuts`) — le train d'un fold ne contient jamais de données
postérieures au test qui le suit. Nombre de folds et fraction minimale de
train paramétrables (`ValidationConfig`).

### Purge et embargo (López de Prado)

Deux fuites distinctes, deux mécanismes distincts :

- **Purge** (`patrick/validation/purge.py`) : une ligne de train dont la
  fenêtre de label (`horizon` jours ouvrés en avant) chevauche la coupure de
  fold est retirée du train — sinon son label contient de l'information sur
  la période de test. Impact mesuré sur ce projet : marginal (delta
  F1_dir ≈ -0.002) mais le mécanisme reste actif par défaut plutôt que
  supposé négligeable.
- **Embargo** (`patrick/validation/embargo.py`) : au-delà de la purge, les
  `embargo_bars` premières barres du **test** (par défaut dérivées de
  l'horizon, `ValidationConfig.embargo_bars=None`) sont retirées — des
  features à fenêtre glissante (moyennes mobiles, EWMA, volatilité
  réalisée...) calculées juste après la coupure incluent encore des
  observations du train, donc restent corrélées avec lui même une fois le
  label "propre" (déjà géré par la purge).

Vérifié par un test de corruption du futur bout-en-bout
(`tests/test_leakage.py::test_corrupting_the_future_does_not_change_train_features_or_model`)
qui modifie délibérément les données post-coupure et vérifie que les
features/le modèle du train n'en sont pas affectés, et par un test de
décalage de cible
(`test_shifting_target_by_one_bar_collapses_performance_to_baseline`) qui
vérifie qu'un label décalé d'une barre fait s'effondrer la performance au
niveau des baselines — preuve empirique qu'il n'y a pas de fuite résiduelle
qui compenserait artificiellement un mauvais alignement temporel.

### Alignement temporel par classe d'actif (as-of join)

Les données sont indexées par date calendaire (barres quotidiennes), sans
horodatage de clôture intrajournalier. Une jointure "même date" traiterait
implicitement une clôture Tokyo (~08:00 UTC) et une clôture New York
(~20-21:00 UTC) du même jour comme simultanées — faux dans le sens où une
feature dont la clôture arrive *après* celle de la cible contiendrait de
l'information non encore disponible au moment de la décision.
`patrick/data/session_calendar.py` décale d'une barre toute feature dont la
classe d'actif clôture après celle de la cible (heure de clôture UTC
approximative par classe : crypto 24/7, FX ~22:00, actions US ~21:00,
actions Europe ~16:30, etc.) — cf. `data/ingest.py::_apply_session_lag`.
Approximation documentée, pas un vrai as-of join intrajournalier (qui
demanderait de migrer toute l'ingestion sur des données horaires, hors
périmètre).

## 2. Données macro : vintages point-in-time (ALFRED)

Par défaut, l'API FRED renvoie chaque série *telle que révisée aujourd'hui*
— pas telle qu'elle était connue à la date de décision historique (les
révisions de PIB, chômage, etc. peuvent être significatives). Les jointures
macro peuvent utiliser les vintages ALFRED
(`patrick/data/sources/fred_source.py::download_series(realtime_date=...)`),
qui renvoient la série telle que publiée à `realtime_date`, évitant que le
modèle "apprenne" sur des révisions qui n'existaient pas encore à l'époque.

## 3. Sélection, tuning, leaderboard : jamais sur le holdout

Les `holdout_months` derniers mois d'historique (`ValidationConfig`,
désactivable à 0) sont réservés avant même le découpage walk-forward
(`pipeline/engine.py::_walk_forward_span`) — ni la sélection de features, ni
le tuning Optuna, ni le tri du leaderboard ne les voient jamais.
`_evaluate_holdout` réévalue **une seule fois** la config déjà choisie sur ce
holdout, jamais pour choisir entre plusieurs configs (anti-pattern #1
ci-dessous).

## 4. Correction multi-tests (validité statistique)

Chercher la meilleure config parmi *N* essais gonfle mécaniquement le
meilleur score observé, même si aucune config n'a de vrai pouvoir prédictif
(le problème classique du "multiple testing"). `patrick` persiste **tous**
les essais (table `trial`, pas seulement le vainqueur) et en tient compte,
via quatre garde-fous dans `patrick/validation/` :

- **Compteur d'essais cumulé** (`tracking/stats.py::count_cumulative_trials`) :
  tout l'historique de runs sur cette cible/horizon, pas seulement le run
  courant — chercher la meilleure config sur 50 runs successifs revient à
  en avoir essayé bien plus qu'un run isolé ne le suggère.
- **Sharpe déflaté** (`dsr.py::deflated_sharpe_ratio`, Bailey & López de
  Prado 2014) : corrige le Sharpe observé du nombre d'essais dont le
  gagnant a été sélectionné. Affiché systématiquement à côté du Sharpe
  brut, jamais seul (anti-pattern #6).
- **PBO** (`pbo.py::compute_pbo`, CSCV par blocs) : probabilité que la
  config gagnante en échantillon (IS) soit perdante hors échantillon (OOS),
  estimée en partitionnant les blocs temporels en toutes les combinaisons
  IS/OOS possibles.
- **Diebold-Mariano** (`diebold_mariano.py`) : p-value du test de
  différence de perte entre le meilleur modèle et la meilleure baseline
  systématique — un modèle non significativement meilleur qu'une baseline
  est signalé comme tel, pas caché.

Ces éléments apparaissent ensemble dans le leaderboard et dans
`patrick report` : métrique de test, métrique de holdout, p-value DM vs
baseline, compteur d'essais cumulé. Le même principe s'applique au
simulateur d'investissement (Phase 4, section 6) : chaque configuration de
simulation testée sur une cible est journalisée (`simulation` table), et le
compteur + Sharpe déflaté correspondant sont affichés en permanence dans
`/simulate`.

## 5. Baselines systématiques

Trois baselines "sans intelligence" (`patrick/validation/baselines.py`)
calculées pour chaque (horizon, fold, régime) et ajoutées au leaderboard à
côté des modèles réels : classe majoritaire, persistance (la classe
réalisée sur la fenêtre la plus récente), et HAR-RV (Corsi — direction par
persistance de signe, amplitude reclassée via les mêmes seuils causaux que
la cible réelle) pour les cibles de volatilité. Un modèle (ou un F1_dir de
0.55) qui ne bat pas ces baselines n'apporte rien, même si ses métriques
absolues semblent correctes.

## 6. Le simulateur d'investissement ne ré-exécute jamais un modèle

Le module de simulation (`patrick/simulate/`, Phase 4) lit exclusivement la
table `prediction` (splits `test`/`holdout`/`live`, déjà écrite par un run
antérieur) et le snapshot Parquet immuable associé, pour calculer le
rendement réalisé de l'actif sous-jacent. Il ne charge, ne réentraîne, ni ne
resélectionne jamais de modèle — la seule chose qu'il ajoute au run existant
est une politique de position et un jeu de frictions.

## 7. SMOTE vs `class_weight` + seuil calibré

Défaut actuel : SMOTE (suréchantillonnage, `sampler.candidates: ["SMOTE"]`).
`class_weight="balanced"`/`auto_class_weights="Balanced"` est déjà appliqué
par défaut sur les classifieurs qui le supportent nativement (LightGBM,
RandomForest, CatBoost — `models/registry.py`), en plus de SMOTE ; XGBoost
et GradientBoosting n'ont pas d'équivalent sklearn natif. `models/
calibration.py` (calibration isotonique + recherche de seuil causal,
méthodologie `VIX_CALIBRATED_THRESHOLD`) existait déjà mais n'était branché
nulle part dans le pipeline. Phase 5.3 :

- Le pseudo-sampler `"none"` (`models/samplers.py::_NoResample`) permet de
  tester `class_weight` SEUL (sans suréchantillonnage) via la grille
  `sampler.candidates` existante — ex. `sampler.candidates: ["SMOTE",
  "none"]` dans une config de run, comparable via les mêmes métriques et le
  même test Diebold-Mariano, sans script d'A/B test séparé.
- `config.models.calibration: bool` (déjà dans le schéma, ignoré jusqu'ici)
  est maintenant branché dans `_fit_eval` (`pipeline/engine.py`) :
  calibration isotonique + seuil recherché sur les 15% les plus récents du
  train (jamais le test).

**L'A/B test empirique sur 5 cibles (demandé par le plan) n'a pas pu être
exécuté dans cette session** : le sandbox n'a pas d'accès réseau à
yfinance/FRED (vérifié directement — toute requête sortante échoue avec une
erreur de proxy). Marche à suivre en environnement avec accès réseau :

```bash
for target in "^VIX" "^GSPC" "SPY" "TLT" "GLD"; do
  patrick run --config configs/ab_test_${target}.yaml  # sampler.candidates: ["SMOTE", "none"]
done
```

puis comparer, par cible, les lignes `SMOTE` vs `none` du leaderboard (même
horizon/régime/N/algo) sur F1_dir/balanced accuracy — changer le défaut vers
`class_weight` seul (`sampler.candidates: ["none"]`) si `none` gagne sur la
majorité des 5 cibles. Le résultat déjà documenté dans `models/
calibration.py` (sur le seul projet VIX d'origine, pas 5 cibles) est mitigé
— gain hors régime STRESS, perte en régime STRESS — pas de victoire nette
qui justifierait de changer le défaut sans revalidation. **Le défaut reste
`sampler.candidates: ["SMOTE"]`, `calibration: false`.**

## 8. Limites connues

- **Biais de survivance** : l'univers de tickers (`configs/examples/*.yaml`,
  `webapp/forms.py::TARGET_GROUPS`) est une liste fixe reflétant la
  composition *actuelle* des indices/secteurs — les actifs retirés d'un
  indice, délistés ou en faillite depuis n'y figurent pas, ce qui gonfle
  mécaniquement la performance historique apparente de tout ce qui touche à
  des paniers larges. Limite structurelle de tout backtest basé sur des
  données gratuites (yfinance) ; non corrigée ici (un univers point-in-time
  demanderait une source de données dédiée).
- **`Adj Close` rétro-ajusté** : l'ingestion utilise `auto_adjust=True`
  (`data/sources/yfinance_source.py`), qui replie dividendes/splits dans le
  prix de clôture *rétroactivement à la date d'ingestion*, pas tels qu'ils
  étaient affichés au moment de la décision historique — une forme de fuite
  d'information mineure mais réelle (l'ampleur d'un ajustement futur n'était
  pas connue à l'époque). Les rendements (base de la cible et de la plupart
  des features) sont peu affectés ; les indicateurs sensibles au *niveau* de
  prix (supports/résistances, moyennes mobiles longues) le sont davantage.
  Écart assumé, pas un risque au niveau purge/embargo (l'ajustement ne
  dépend pas de la fenêtre walk-forward) — prix de l'accès gratuit aux
  données.
- **`patrick predict --live`** : `y_true` des prédictions live est stocké en
  binaire (hausse/baisse réalisée) plutôt que reclassifié dans les 4 classes
  du modèle — les seuils par quantile/régime de `features/target.py` sont
  fittés par run et non persistés séparément pour l'inférence
  (`patrick/predict.py`, hors scope Phase 4). Sert uniquement à l'affichage
  de suivi, jamais à réentraîner ou sélectionner un modèle.
- **Kelly fractionnaire** (simulateur) : approximé avec un ratio de gain
  b=1 (pari à cote égale) plutôt qu'un modèle de gain/perte calibré par
  trade — gaté sur un score de Brier (`simulate/engine.py::
  check_kelly_available`) pour éviter de l'activer sans signal correctement
  calibré, mais reste une simplification du Kelly complet.

## 9. Logo

Le monogramme "P" dans l'anneau doré (`webapp/static/style.css::.brand-mark`,
`webapp/templates/base.html`) est un **placeholder CSS**, pas un logo — à
remplacer par une vraie image/SVG de marque si/quand elle est fournie.

## 10. Anti-patterns explicitement refusés

Ces pratiques cassent une ou plusieurs des garanties ci-dessus — le code les
évite structurellement plutôt que par convention :

1. Trier/sélectionner quoi que ce soit sur le holdout.
2. Exécuter un modèle depuis le simulateur au lieu de lire `prediction`.
3. Appliquer un sampler (SMOTE) hors du fold d'entraînement.
4. Joindre une série macro sur sa date de référence plutôt que sa date de
   publication.
5. Exécuter un signal sur la bougie qui l'a produit (le simulateur impose
   `execution_lag_bars >= 1`).
6. Afficher un Sharpe sans le nombre d'essais qui l'ont produit.
7. Écraser un snapshot de données existant au lieu d'en créer un nouveau
   (`data/store.py` — dédupliqué par hash de contenu, jamais réécrit).
