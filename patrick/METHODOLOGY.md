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

### Convention de timing (rapport de correction, C6)

Le plan de phase 4 prescrivait une convention `open_next` (exécution à
l'ouverture du jour suivant) — **non implémentable ici** : le simulateur ne
modélise qu'une seule série de clôtures par actif (close-to-close), pas
d'open/high/low. Le seul paramètre de timing est `execution_lag_bars`, et
c'est exactement ce qu'il fait (aucune mention d'`open_next` ne subsiste dans
le code, l'UI, les YAMLs ou le glossaire).

Convention réelle (`simulate/engine.py::_build_exposure`) : le signal est
connu à la clôture du jour `t` ; l'exposition démarre à la ligne
`t + execution_lag_bars` de la grille quotidienne. Comme
`underlying_ret[i] = close[i]/close[i-1] - 1` (le rendement qui SE TERMINE au
jour `i`, pas celui qui en part), le premier rendement capté par cette entrée
est celui de `t+lag-1` à `t+lag`. Avec le minimum imposé
`execution_lag_bars=1` (anti-pattern #5, section 10), ce premier rendement
capté est donc exactement celui de `t` à `t+1` — le mouvement qui suit
immédiatement la clôture du signal, sans latence réelle ajoutée au-delà de
cette clôture. `execution_lag_bars=0` capterait le rendement de `t-1` à `t`,
déjà connu au moment où le signal est calculé — du look-ahead pur,
structurellement interdit par `SimParams.__post_init__`.

**Revisite du finding F.2 de l'audit** ("lag=0 donne un Sharpe plus bas que
lag=1", non résolu) : un signal oracle (prédiction parfaite, par
construction, du mouvement `t`→`t+1`) injecté dans `_build_exposure` réel
(lag=0 testé en contournant la validation, diagnostic seul) confirme que ce
n'est **pas un bug d'alignement** — sur série synthétique (20000 jours,
signaux isolés espacés de 5 jours, horizon=1), lag=1 capte exactement ce que
l'oracle prédit (Sharpe ≈ 6, quasi parfait), tandis que lag=0/2/3 captent un
rendement sans rapport avec la prédiction (Sharpe proche de 0 : 0.07/0.20/0.10,
jamais négatif ni anormal). `_build_exposure` fonctionne comme attendu ; le
finding F.2 s'explique entièrement par cette convention une fois comprise.

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
8. Exclure une série de l'univers sans motif explicite persisté (Phase 6.5 --
   `data/quality.py` : chaque exclusion porte un `reason`, jamais un simple
   `[WARN]` de log).

## 11. Phase 6 — rigueur d'échantillonnage

Contrainte transversale à toute la phase 6 : aucune des briques ci-dessous ne
doit devenir un défaut silencieux. Chacune est explicitement activable/
désactivable dans le YAML (`RunConfig`) et le formulaire web, et le rapport
HTML de run indique lesquelles étaient actives (section "Corrections phase 6",
`tracking/report.py`).

### 11.1 P6.5 — Portes de qualité de données à l'ingestion

`patrick/data/quality.py`, câblé dans `data/ingest.py` (toggle
`data_quality.enabled`, défaut `true`). Chaque série candidate (yfinance ou
FRED) passe six contrôles avant d'entrer dans l'univers de features :

1. **Prix figés** : `n` clôtures consécutives identiques (défaut 4).
2. **Trous de cotation** : plus de `n` jours ouvrés sans observation (défaut 10).
3. **Rendements aberrants** : au-delà de `n` écarts-types **robustes** (MAD ×
   1.4826, résistant aux queues épaisses — pas un écart-type classique, qui
   serait lui-même gonflé par l'aberration qu'on cherche à détecter). Défaut 40.
4. **Fin de série précoce** : dernière observation trop antérieure à la date de
   fin demandée (probable délistage) — même seuil que 2.
5. **Série FRED absente ou discontinuée** : aucune observation renvoyée.
6. **Couverture insuffisante** : réutilise `universe.yf_coverage` (Phase 0,
   0.85 par défaut), pas un nouveau seuil inventé.

**Seuils mesurés, pas choisis par convention** (cf. docstring de module et
`tests/test_data_quality.py::test_thresholds_measured_not_arbitrary_*`) :
simulation de centaines de séries synthétiques à queues épaisses réalistes
(Student-t, df=5) — le seuil de prix figés (4) et le seuil de rendement
aberrant (40 écarts-types robustes) ne se déclenchent JAMAIS sur ces séries
propres, mais se déclenchent nettement sur une corruption injectée réaliste
(split boursier non ajusté, erreur de décimale). Le seuil de trou de cotation
(10 jours ouvrés) est calé sur le plus long cluster de jours fériés de marché
connu (~5 jours), doublé par marge de sécurité.

Comportement : une série qui échoue un contrôle est EXCLUE avec un motif
explicite (`reason` + `detail`), persisté en base (table `data_quality_issue`,
liée au `snapshot_id`) — jamais un `[WARN]` perdu dans les logs (même classe de
défaut que le repli FRED silencieux, déjà corrigé, cf. section "Accès aux
données" du README). Si plus de `max_universe_exclusion_frac` (défaut 30%) de
l'univers demandé est exclu, l'ingestion **échoue** plutôt que de continuer sur
un univers décimé silencieusement.

Limite assumée : `download_universe` (yfinance) ffille déjà en interne avant
de renvoyer les colonnes retenues (couverture) — les trous de cotation y sont
donc déjà comblés au moment où `data/quality.py` les voit. Une interruption
prolongée y apparaît comme une clôture figée (valeur ffillée répétée), déjà
couverte par le contrôle 1 — convergence assumée, documentée dans
`data/ingest.py::_run_extra_quality_checks`, pas un trou dans la garantie. Les
contrôles 2 et 4 (trous/fin précoce) s'appliquent tels quels aux séries FRED
(non pré-remplies à ce stade).

### 11.2 P6.3 — Stabilité de la sélection de features

`patrick/selection/stability.py`, câblé dans `pipeline/engine.py` après le
scan (toggle `selection.track_stability`, défaut `true`). Pour la
configuration (régime, N) localement gagnante de CHAQUE horizon (moyenne
F1_dir sur ses folds — indépendant du choix global `final_best`, qui ne
retient qu'un seul horizon pour le modèle exporté), calcule :

- l'indice de **Jaccard** des ensembles de features retenues entre chaque
  paire de folds walk-forward (chemins CPCV demain, P6.1) — moyenné en
  `mean_jaccard` ;
- la **fréquence de sélection** de chaque feature sur l'ensemble des folds.

Persisté dans `feature_stability(run_id, feature, selection_freq)` +
`run_feature_stability(run_id, mean_jaccard, n_folds)` (migration 0006).
Affiché dans le rapport HTML de run : Jaccard moyen, classement des features
par fréquence de sélection, et un avertissement explicite si le Jaccard moyen
tombe sous `MIN_MEAN_JACCARD_WARNING = 0.40`.

**Seuil mesuré, pas choisi par convention** (cf.
`tests/test_feature_stability.py::test_warning_threshold_is_measured_not_arbitrary`) :
sur des données synthétiques SANS lien réel entre X et y (cible pur bruit),
avec des features corrélées entre elles comme le sont les familles
technical/interactions du pipeline réel, la sélection SHAP RÉELLE (pas une
formule combinatoire naïve) produit déjà un Jaccard moyen jusqu'à ~0.40 entre
folds par la seule structure de corrélation — une formule combinatoire naïve
(deux sous-ensembles aléatoires indépendants) donnerait un seuil de hasard
~100x plus bas (~0.01), largement sous-estimé car elle ignore que des
features corrélées sont choisies ENSEMBLE par un sélecteur basé sur
l'importance, pas indépendamment. En dessous de 0.40, la stabilité observée
est indiscernable de cet artefact — pas la preuve d'un signal reproductible.

### 11.3 P6.2 — Poids d'unicité et bootstrap séquentiel

`patrick/models/uniqueness.py` + `patrick/models/sequential_forest.py`
(López de Prado, "Advances in Financial Machine Learning", ch. 4). Avec un
horizon `h > 1` et une prédiction par barre, les fenêtres de label se
chevauchent : l'observation à la barre `t` prédit `[t, t+h]`, donc deux
observations à moins de `h` barres l'une de l'autre partagent une partie du
même mouvement de marché sous-jacent — les observations d'entraînement ne
sont PAS indépendantes.

- **Concurrence par barre** : nombre de spans d'observation qui la recouvrent.
- **Unicité moyenne par observation** : moyenne de `1/concurrence` sur les
  barres qu'elle couvre.
- **Taille d'échantillon effective** (`n_eff`) : somme des unicités —
  toujours calculée et rapportée à côté de `n_train` (`fold_metric`, métriques
  `n_train`/`effective_n_train`), quel que soit le sampler.
- **Poids d'unicité en `sample_weight`** + **bootstrap séquentiel pour
  RandomForest** (`SequentialBootstrapRandomForestClassifier`, tirage
  favorisant dynamiquement les observations les moins concurrentes avec le
  tirage en cours) : ne s'appliquent concrètement QUE si `sampler_name=
  "none"` — SMOTE et les autres suréchantillonneurs synthétisent des
  observations sans date/span réels, auxquelles un poids d'unicité ne peut
  pas être rattaché proprement. Limite assumée, documentée dans
  `SamplingConfig`/`pipeline/engine.py::_fit_eval`.

Toggle `sampling.uniqueness_weights` (défaut `true`, jamais un défaut
silencieux).

**Mesure sur cible synthétique** (déliverable P6.2, observations
consécutives, une par barre — cf. `tests/test_uniqueness.py::
test_effective_sample_size_matches_1_over_horizon_plus_1`) : `n_eff/n`
converge vers `1/(horizon+1)` (résultat analytique, confirmé numériquement) :

| horizon (jours) | n_eff / n | Exemple (n=1000) |
|---|---|---|
| 1  | 0.500 | 500 |
| 3  | 0.251 | 251 |
| 5  | 0.167 | 167 |
| 10 | 0.092 | 92 |
| 20 | 0.049 | 49 |

Le chiffre est délibérément surprenant : à l'horizon par défaut du pipeline
VIX (5 jours), un run avec `n_train=1000` a l'incertitude statistique d'un
échantillon d'environ **170 lignes**, pas 1000 — cf. justification du seuil
`min_test_rows`/`MIN_BLOCKS` (rapports de correction D3/C5), qui raisonnaient
déjà en observations réellement indépendantes sans le formaliser aussi
explicitement.

**Coût de calcul assumé** : le bootstrap séquentiel coûte O(n_obs x n_bars)
PAR ARBRE (contre O(n_obs) pour un bootstrap uniforme) — `n_estimators`
réduit à 100 par défaut pour la variante séquentielle (200 pour la forêt
standard, `models/registry.py`), compromis documenté dans
`models/sequential_forest.py`. Mesuré sur `tests/test_uniqueness.py` (config
minuscule, walk-forward à 2 folds) : ~70s pour un run complet avec
`sampler="none"`+RandomForest+bootstrap séquentiel, contre quelques secondes
en configuration standard (SMOTE, bootstrap uniforme) — l'écart grandit avec
la taille du train, à anticiper sur un run réel (n_train de plusieurs
centaines à quelques milliers de lignes par fold).
