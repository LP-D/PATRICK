# Méthodologie

Ce document explique **pourquoi** `patrick` est construit comme il l'est —
les garanties qu'il apporte contre le sur-ajustement et la fuite
d'information, et où elles s'arrêtent. Pour *comment* l'utiliser, voir
`README.md`.

## 1. Walk-forward strict

Chaque config (cible × horizon × régime) est évaluée sur plusieurs folds
walk-forward chronologiques : le train ne contient jamais de données
postérieures au test qui le suit. Aucun k-fold aléatoire n'est utilisé nulle
part dans le pipeline — un k-fold aléatoire sur une série temporelle laisse
le train "voir" des dates futures par rapport à certaines lignes de test,
ce qui gonfle artificiellement les métriques.

### Purge

Une ligne de train dont la fenêtre de label (`horizon` jours ouvrés en
avant) chevauche la coupure de fold est retirée du train : sans ça, cette
ligne contient une information sur la période de test (`patrick/validation/
purge.py`). Impact mesuré sur ce projet : marginal (delta F1_dir ≈ -0.002)
mais le mécanisme reste actif par défaut plutôt que supposé négligeable.

### Embargo

Distinct de la purge : les features à fenêtre glissante (moyennes
mobiles, EWMA, volatilité réalisée...) calculées juste après la coupure
incluent encore des observations du train dans leur fenêtre, même une fois
le *label* purgé. L'embargo retire du **test** les `embargo_bars` premières
lignes suivant la coupure (défaut : dérivé de l'horizon courant, cf.
`patrick/validation/embargo.py`).

### Alignement temporel (as-of join par classe d'actif)

Une jointure "même date calendaire" traite implicitement comme simultanées
des clôtures de marché qui ne le sont pas (ex. une clôture US utilisée "du
jour" pour une cible qui a déjà clôturé plus tôt dans la même journée UTC).
`patrick/data/session_calendar.py` décale d'une barre les colonnes dont la
classe d'actif clôture après celle de la cible, avant toute construction de
feature — cf. `data/ingest.py::_apply_session_lag`.

## 2. Données macro : vintages point-in-time (ALFRED)

Les séries FRED sont révisées après publication (PIB, chômage...) — les
requêter "telles qu'elles sont aujourd'hui" pour une date d'entraînement
passée introduit une fuite invisible (le modèle voit une révision qui
n'existait pas encore à cette date). `patrick/data/sources/fred_source.py`
peut basculer sur les vintages ALFRED (`realtime_date=...`), qui renvoient
la série telle qu'elle était connue à cette date précise plutôt que la
version révisée actuelle.

## 3. Sélection, tuning, leaderboard : jamais sur le holdout

Le holdout terminal (12-18 derniers mois, `validation.holdout_months`) est
réservé dès le début du run (`_walk_forward_span`, `patrick/pipeline/
engine.py`) et n'est *jamais* utilisé pour sélectionner des features, tuner
des hyperparamètres, ou trier le leaderboard — seul le walk-forward (folds
antérieurs) sert à ça. La config déjà choisie par ce processus est
réévaluée **une seule fois** sur le holdout, à titre de contrôle final
(`_evaluate_holdout`) — jamais pour comparer plusieurs configs entre elles
(cf. anti-pattern #1 ci-dessous).

## 4. Correction multi-tests (validité statistique)

Chercher la meilleure config parmi *N* essais gonfle mécaniquement le
meilleur score observé, même si aucune config n'a de vrai pouvoir
prédictif (le problème classique du "multiple testing"). `patrick`
persiste **tous** les essais (table `trial`, pas seulement le vainqueur) et
en tient compte :

- **Compteur d'essais cumulé** (`tracking/stats.py::count_cumulative_trials`) :
  tout l'historique de runs sur cette cible/horizon, pas seulement le run
  courant — chercher la meilleure config sur 50 runs successifs revient à
  en avoir essayé bien plus qu'un run isolé ne le suggère.
- **Sharpe déflaté (DSR)** (Bailey & López de Prado 2014,
  `validation/dsr.py`) : corrige le Sharpe observé du nombre d'essais.
  Affiché systématiquement à côté du Sharpe brut, jamais seul (anti-pattern
  #6).
- **PBO** (probabilité de sur-ajustement du backtest, CSCV par blocs,
  `validation/pbo.py`) : estime la probabilité que la config choisie
  in-sample soit en réalité médiocre out-of-sample.
- **Diebold-Mariano** (`validation/diebold_mariano.py`) : test de
  significativité de la différence de perte entre le meilleur modèle et la
  meilleure baseline systématique — une config peut battre une baseline
  "en moyenne" sans que l'écart soit statistiquement significatif.

Ces quatre éléments apparaissent ensemble dans le leaderboard et dans
`patrick report` : métrique de test, métrique de holdout, p-value DM vs
baseline, compteur d'essais cumulé.

## 5. Baselines systématiques

Trois baselines "sans intelligence" sont calculées à chaque run
(`validation/baselines.py`) : classe majoritaire, persistance (la classe
réalisée sur la fenêtre la plus récente), et HAR-RV (Corsi) pour les cibles
de volatilité. Un modèle qui ne bat pas ces baselines n'apporte rien, même
si ses métriques absolues semblent correctes.

## 6. Le simulateur d'investissement ne ré-exécute jamais un modèle

Le module de simulation (`patrick/simulate/`, Phase 4) lit exclusivement la
table `prediction` (splits `test`/`holdout`/`live`, déjà écrite par un run
antérieur) et le snapshot Parquet immuable associé, pour calculer le
rendement réalisé de l'actif sous-jacent. Il ne charge, ne réentraîne, ni
ne resélectionne jamais de modèle — la seule chose qu'il ajoute au run
existant est une politique de position et un jeu de frictions.

## 7. SMOTE vs `class_weight` + seuil calibré

Trois des cinq algos (RandomForest, LightGBM, CatBoost) appliquent déjà
`class_weight="balanced"`/`auto_class_weights="Balanced"` en dur
(`models/registry.py`), indépendamment du sampler choisi. `models/
calibration.py` (calibration isotonique + recherche de seuil causal,
méthodologie `VIX_CALIBRATED_THRESHOLD`) existait déjà mais n'était branché
nulle part dans le pipeline. Phase 5.3 :

- `sampler.candidates` accepte désormais `"none"` (pas de rééchantillonnage,
  `models/samplers.py`) — s'ajoute comme une config de plus dans le scan/
  leaderboard existant, comparable aux configs SMOTE via les mêmes
  métriques et le même test Diebold-Mariano.
- `config.calibration: bool` (déjà dans le schéma, ignoré jusqu'ici) est
  maintenant branché dans `_fit_eval` (`pipeline/engine.py`) : calibration
  isotonique + seuil recherché sur les 15% les plus récents du train
  (jamais le test).

**Comparaison réelle sur 5 cibles : pas faite dans cette session** (pas
d'accès réseau en environnement sandbox — cf. `README.md`, "État de la
vérification"). Le résultat déjà documenté dans `models/calibration.py`
(sur le seul projet VIX d'origine, pas 5 cibles) est mitigé : gain hors
régime STRESS, perte en régime STRESS — pas de victoire nette qui
justifierait de changer le défaut. **Le défaut reste `sampler.candidates:
["SMOTE"]`, `calibration: false`.** À revalider sur 5 cibles avec accès
réseau avant de changer le défaut, conformément au plan.

## 8. Limites connues

- **Biais de survivance** : l'univers de tickers (`configs/examples/*.yaml`,
  `webapp/forms.py::TARGET_GROUPS`) est une liste fixe reflétant la
  composition *actuelle* des indices/secteurs — un backtest sur plusieurs
  années ne retire pas correctement les entreprises qui ont été retirées
  des indices (rachat, faillite, radiation) pendant la période. Limite
  structurelle de tout backtest basé sur des données gratuites (yfinance) ;
  non corrigée ici.
- **`Adj Close` rétro-ajusté** : l'ingestion utilise `auto_adjust=True`
  (`data/sources/yfinance_source.py`), qui replie dividendes/splits dans le
  prix de clôture. Les rendements (base de la cible et de la plupart des
  features) sont peu affectés, mais les indicateurs sensibles au *niveau*
  de prix (supports/résistances, moyennes mobiles sur longue fenêtre)
  peuvent légèrement varier a posteriori d'un ré-ingestion à l'autre après
  un nouveau split — accepté comme prix de l'accès gratuit aux données.
- **`patrick predict --live`** : `y_true` des prédictions live est un
  binaire simplifié (rendement réalisé positif/négatif) plutôt qu'une
  reclassification dans les 4 classes du modèle — les seuils par
  quantile/régime de `features/target.py` sont fittés par run et non
  persistés séparément pour l'inférence (cf. `patrick/predict.py`, hors
  scope Phase 4 de les persister).
- **Kelly fractionnaire** (simulateur) : approximé avec un ratio de gain
  b=1 (pari à cote égale) plutôt qu'un modèle de gain/perte calibré par
  trade — gaté sur un score de Brier (`simulate/engine.py::
  check_kelly_available`) pour éviter de l'activer sans signal
  correctement calibré, mais reste une simplification du Kelly complet.

## 9. Logo

Le monogramme "P" dans l'anneau doré (`webapp/static/style.css::.brand-mark`,
`webapp/templates/base.html`) est un **placeholder CSS**, pas un logo — à
remplacer par une vraie image/SVG de marque si/quand elle est fournie.

## 10. Anti-patterns explicitement refusés

Ces pratiques cassent une ou plusieurs des garanties ci-dessus — le code
les évite structurellement plutôt que par convention :

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
