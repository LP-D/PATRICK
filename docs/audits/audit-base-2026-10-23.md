# Audit de la base du 2026-10-23 (avant purge des caches) et chantier d'empilement

Base lue en `mode=ro` (`~/.patrick/patrick.db`, 49 Go) : **2 121 runs** (2 052 terminés, 68 échoués, 1 en cours), 1 086 jobs, 518 cibles
entraînées, 1 954 essais gagnants dont 1 920 avec un holdout. Rien n'a été modifié dans la base ni supprimé sur disque.

## 1. Ce que dit la base

| Constat | Chiffres | Suite donnée |
|---|---|---|
| Les runs sont presque tous des runs « rapides » | 83 % : 3 folds, réglage Optuna coupé, 2 algorithmes, grille de 5 variables (profil Rapide) ; 1 912 runs sur 2 052 sont à l'univers par défaut (8 à 24 tickers) | l'univers étendu devient le défaut (§3) |
| Le signal est dans deux classes seulement | AUC holdout médiane : devises 0,624 (79 % des runs > 0,55), volatilité US 0,589 (88 %) ; actions Europe 0,516 (844 runs, 33 % sous 0,5), actions US 0,523, futures 0,518, Asie-Pacifique 0,536 | la carte « par classe d'actifs » (§4) permet de relancer une classe entière avec de meilleurs réglages |
| Plus de rigueur n'améliore pas l'AUC holdout | même cible et même horizon : réglage + 5 folds contre rapide, −0,004 (erreur-type 0,006, 25 paires) ; 4 algos contre 2, +0,002 (0,006, 20 paires) ; grille ≥ 6 contre 5, +0,006 (0,007, 13 paires) | pas de durcissement général des réglages |
| **Les probabilités des runs rapides sont sur-confiantes** | Brier de P(hausse) sur le holdout : 0,265 en moyenne (79 % des runs au-dessus de 0,25 = « pièce à pile ou face ») ; 0,269 pour les runs rapides contre 0,246 pour les runs réglés ; même cible et même horizon (15 paires) : le réglage Optuna avec 4 algos et 5 folds baisse le Brier de 0,006 (0,003) et l'ECE de 0,019 (0,010) sans bouger l'AUC | nouvelle règle `overconfident` du conseiller (§5) ; le mode systématique du fonds trade sur ces probabilités |
| L'univers étendu n'est pas pénalisant | 9 paires : +0,010 d'AUC holdout (0,011), Brier +0,001 ; durée médiane 23,5 min contre 16,9 (+39 %) | décision de l'utilisateur : étendu partout |
| Le « stacking » du formulaire ne faisait rien | 11 runs l'avaient coché ; `models.stacking` n'était lu nulle part dans le moteur (`train_stacking_category` n'est appelée par personne) | empilement réel (§2) |
| Erreurs | 14 `XGBoostError: inf` du 2026-10-07 (univers étendu, **avant** le correctif du 10-09 : plus aucune depuis) ; 1 `IndexError` du 10-02 (classe manquante, corrigée le 10-16) ; 46 arrêts utilisateur ; 22 runs « orphelins » (processus disparu) | rien à corriger |
| Trous | 98 runs terminés sans essai gagnant (80 en août, 18 en octobre ; cause non établie) ; 26 sans holdout | informatif |
| Calibration | seulement 9 runs calibrés : trop peu pour trancher (AUC 0,50, Brier 0,267) | pas de changement de défaut |

Piste non traitée : les actions européennes ont l'AUC la plus basse alors que les marchés US (clôture 22 h CET) précèdent leur ouverture
du lendemain. Le décalage de séance (`data/session_calendar.py`, `objective.disable_session_lag`) mérite un contrôle dédié.

## 2. Empilement (stacking)

`models/stacking.py` : `StackingEnsemble`, classifieur scikit-learn ajouté à la grille du scan sous le nom « Stacking » quand la case est
cochée (`models.stacking`). Le **nombre de modèles de base est saisi à la main** (`models.stacking_n_models`, 3 à 60, défaut 12).

- Rigueur d'entraînement **allégée sur les modèles de base**, voulue : hyperparamètres tirés au hasard dans de larges plages
  (profondeur 1 comprise), sous-ensemble aléatoire de variables (40-100 %) et de lignes (60-100 %), graine propre, algorithmes du run en
  tournée. Pas d'Optuna (`engine._without_stack` écarte « Stacking » du réglage), pas de sélection, pas de règle de parcimonie : il faut des
  bons et des mauvais modèles pour que le méta-modèle ait quelque chose à apprendre.
- Rigueur **conservée là où la fuite se produit** : le méta-modèle (régression logistique régularisée) n'est appris que sur des
  probabilités hors-échantillon. Entraînement coupé par le temps (70 % | 30 %), trou d'un horizon entre les deux, bases ajustées sur
  l'ancien, prédiction du récent, puis bases réajustées sur tout l'entraînement pour le test. Le rééchantillonnage (SMOTE) ne touche que
  les lignes d'ajustement, jamais celles du méta-modèle (`engine._fit_eval_full` ne rééchantillonne pas en amont pour « Stacking »).
- Coût : 2 N ajustements par candidat de la grille (le conseiller le chiffre : `retrain_advisor._units`). Walk-forward uniquement
  (refusé en CPCV) ; il faut au moins un algorithme à arbres (la case a disparu de la page Deep learning, où elle ne servait à rien).
- Export et duel : le panel (N, algorithmes) est consigné dans `best_params["stack"]` du fichier meta, un champion rejoué depuis un autre
  run retrouve le sien. Profil « Empilement » : 20 modèles, 3 algorithmes, sans Optuna, grille 8/12/16.

## 3. Univers de variables étendu par défaut

Le menu « Univers candidat » est retiré : le formulaire utilise toujours l'univers étendu (`forms.universe_excluding`, défaut
`scope="extended"`). Une ligne d'information le dit. Le regroupement par corrélation (`reduction_corr_threshold`) reste optionnel et vide
par défaut (« jamais un filtre silencieux »). Profil « Univers étendu » supprimé (devenu le défaut). Les YAML et le CLI gardent l'univers
par défaut du schéma (golden master inchangé).

## 4. Lots : une carte par classe d'actifs

La carte « Cibles jamais lancées » (vide : toutes les cibles ont été faites) est remplacée par **une carte par classe d'actifs**
(`launch_batches.by_asset_class`) : un clic sélectionne toutes les cibles de la classe dans le formulaire ; le compte dit combien n'ont encore
aucun run. Valable pour ML, DL et RL. « Horizons jamais lancés » et « Runs conseillés » sont inchangés.

## 5. Conseiller de réentraînement

Règle `overconfident` : run sans réglage Optuna dont le Brier holdout dépasse 0,265 → relancer avec Optuna, 4 algorithmes, 5 folds
(score 36-58, coût chiffré). Le coût d'un empilement dépend maintenant de N. Seuils d'AUC inchangés : la médiane de test de la base est 0,524
(0,530 au 16/10) et les runs ajoutés depuis sont des runs rapides, pas de nouveaux réglages à mesurer.

## 6. Avant de supprimer les caches

Dossiers de `~/.patrick` (tailles du 23/10) : `feature_cache` 126 Go (cache pur, reconstruit), `cache` 739 Mo (cours Yahoo et millésimes
ALFRED, retéléchargés), `store` 7,3 Go (**pas un cache** : instantanés de données que les runs référencent, nécessaires à `resume` et au
rejeu), `models` 79 Mo (modèles champions pour la prédiction en direct), `backups` 250 Go (sauvegardes de la base), `patrick.db` 49 Go
(contient aussi deux tables de cache : `vol_model_cache`, `shap_selection_cache`). Un worker tournait (BZ=F) avec 15 jobs en file : l'arrêter
avant de purger.
