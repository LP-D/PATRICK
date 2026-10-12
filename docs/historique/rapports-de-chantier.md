# Rapports de chantier (historique)

Rapports intermédiaires et constats de faisabilité de chantiers terminés. Chaque partie garde son contenu d'origine.


---

## Partie 1 — Synthèse `/` — branchement aux données réelles (B1-B2)

*Source d'origine : `patrick/DASHBOARD_B1-B2.md`.*

Livrable intermédiaire du chantier de remplacement de `/` par une nouvelle page de synthèse, réutilisant la structure de `/phase9` branchée aux vraies données. Arrêt avant B3-B6 (états vides, pas de cache, tests, devenir de `/phase9`), conformément à la consigne. Aucun fichier de production modifié à ce stade — investigation et plan uniquement.

---

### B1 — Structure de la page

Ordre proposé confirmé (aucun doute réel, structure alignée sur ce qui existe déjà) :

1. **Bandeau de couverture** : `n_targets` entraînées / 550 (univers théorique, `config/defaults.py::DEFAULT_TARGET_GROUPS`) + `MAX(prediction.ts)` tous splits confondus, toutes cibles.
2. **Qualité par cible** : `trackstats.fdr_across_targets()` — voir B2, c'est la vraie source, pas `phase9.signal_dm_summary`.
3. **Dernière prédiction par cible** : table `prediction` (réelle, déjà peuplée par le pipeline — `y_true`/`y_pred`/`y_proba`/`ts`), dernière ligne par cible (`split='live'` si présente, sinon dernier `test`/`holdout`).
4. **Métriques du modèle gagnant, ventilées par direction** : **gap réel identifié**, voir B2.
5. **Historique récent** : `tracking.history.list_runs()` (déjà utilisée par `/runs`), tronquée — aucune nouvelle requête.

---

### B2 — Branchement aux données réelles

#### `regime_summary` / `classify_regime_daily`

Confirmé par recherche exhaustive (`grep` sur tout `patrick/patrick/`) : **jamais appelée en dehors de `phase9.py` et de ses propres tests**. Aucune ligne de code de production (`pipeline/engine.py`, `worker.py`, `predict.py`, `cli.py`) ne l'invoque, aucune table de la base ne stocke de classification de régime.

Ce n'est pas une donnée qui existe et que j'aurais dû aller chercher ailleurs : **elle n'a jamais tourné en production, point final**. Conformément à l'anti-pattern explicite de la consigne, je ne la branche pas — section en état vide explicite (B3) :

> « Classification de régime jamais exécutée en production — fonctionnalité disponible (`patrick.phase9.classify_regime_daily`) mais non intégrée au pipeline. »

#### `determine_signal_quality_status` / `signal_dm_summary`

Écart à signaler avant de continuer : ces deux fonctions `phase9.py` ne sont **pas** le chemin réel de production. Le vrai chemin, déjà câblé et déjà utilisé par `/runs/{id}` et `/targets/{ticker}`, est :

- `dm_result` (table réelle, peuplée par `pipeline/engine.py` via le vrai `diebold_mariano()`, **pas** la copie de `phase9.py`) ;
- `tracking/stats.py::fdr_across_targets()` — MIN(p-value) par cible × `benjamini_hochberg()` (même fonction de correction que `signal_dm_summary` appelle en interne) → `{target: {p_value, adjusted_p_value, rank, significant}}`.

Utiliser `phase9.signal_dm_summary` littéralement obligerait à recharger les tableaux de prédictions bruts et à recalculer le DM — redondant, et risque réel d'obtenir une p-value différente de celle déjà affichée sur `/runs/{id}`/`/targets/{ticker}` (incohérence au clic, contraire à B4).

**Proposition** : `fdr_across_targets()` comme source réelle pour le point 2 du bandeau, pas `signal_dm_summary`. `determine_signal_quality_status` reste utilisable tel quel pour le verdict agrégé, alimenté par les p-values réelles de `fdr_across_targets()` au lieu du dict codé en dur — ou, alternative plus proche de l'existant : `history.station_verdict()` fait déjà exactement ce rôle de verdict agrégé et sert déjà le bandeau actuel.

**À trancher** : réutiliser `station_verdict()` (zéro nouveau code) ou brancher `determine_signal_quality_status` sur les p-values réelles (répond plus littéralement à la consigne initiale) ?

#### Gap réel trouvé pour B1.4 (métriques par direction)

Aucune métrique par direction (hausse/baisse séparées) n'est actuellement stockée — `fold_metric` ne contient que des agrégats macro (`F1_dir`, `Acc_dir`, `AUC_ovr_4cls`, calculés sur DOWN/UP fusionnés). Ce qui existe par « force » (`F1_UP_FORT`/`F1_DOWN_FORT`) est un axe différent (amplitude dans une direction, pas performance par direction).

Solution sans toucher au pipeline : la table `prediction` (réelle, `y_true`/`y_pred`/`y_proba` par ligne, `split='test'`/`'holdout'`) permet de **recalculer en lecture seule**, au chargement de la page, le F1/accuracy/AUC par classe DOWN vs UP — même philosophie que `tracking/stats.py`/`holdout_diagnostic.py` (« recomputed on the fly on request, no cache »), aucune nouvelle colonne, aucun changement de pipeline.

---

### Points à trancher avant B3-B6

1. Verdict agrégé section 2 : `station_verdict()` (déjà existant) ou `determine_signal_quality_status` rebranché sur les p-values réelles ?
2. Confirmation de l'état vide pour la classification de régime (jamais exécutée en production), plutôt que d'ouvrir un chantier séparé pour l'intégrer ?

Aucun fichier de production modifié par ce rapport.


---

## Partie 2 — Phase 4 — audit de dégradation en UI : constat de blocage

*Source d'origine : `patrick/PHASE4_AUDIT_FINDING.md`.*

Branche : `feature/degradation-badge` (HEAD au moment de l'audit :
`fbd354b32de01f9cad4d424ee96a7330d78b827f`, = HEAD de `main`).

### 1. Ce que fait reellement `patrick audit degradation`

Source : `patrick/patrick/audit.py` (module docstring, lignes 1-22) et
`patrick/patrick/cli.py::audit_degradation_cmd` (lignes 198-213).

- **Nature** : un rapport de correction ponctuel ("Correction report, C7"),
  pas un moniteur continu. Il mesure l'impact reel des correctifs de fuite
  de donnees de la Phase 0 (purge/embargo, alignement as-of par classe
  d'actif, vintages FRED/ALFRED) en comparant **4 configurations empilees
  et cumulatives** (`CONFIGURATIONS = ("baseline_avant", "+purge",
  "+vintages", "complet")`, `audit.py` ligne 45) sur le **meme** univers de
  cibles et le **meme** seed :
  > "The 4 configurations are CUMULATIVE (each adds one fix on top of the
  > previous one), not independent -- this isolates the marginal
  > contribution of each fix" (`audit.py`, lignes 11-13).
- **Univers fixe et restreint** : `DEFAULT_TARGETS` (`audit.py`, lignes
  52-68) contient exactement **5 cibles**, une par classe d'actif
  (`indice_us` = ^GSPC, `action_europe` = MC.PA, `paire_fx` = EURUSD=X,
  `matiere_premiere` = GC=F, `crypto` = BTC-USD) -- commentaire a la ligne
  49-51 : "One asset per class (Phase 0 concerns the whole yfinance/FRED
  surface, not a single market)". Ce n'est pas un echantillon de la
  production (68 tickers), c'est un jeu de test dedie a la validation de la
  correction.
- **Reseau reel obligatoire** : `run_degradation_audit()` appelle
  `run_pipeline(cfg, store=store, force_ingest=True, db_path=db_path)`
  (`audit.py` ligne 205) avec `force_ingest=True` explicitement pour
  eviter tout cache -- chaque config de chaque cible re-ingere en reseau
  (yfinance + FRED). Le docstring de `cli.py` (lignes 211-212) est
  explicite : "Runs the real pipeline (yfinance/FRED network access
  required)".
- **`FRED_API_KEY` obligatoire, echec explicite sinon** : `audit.py` lignes
  176-185 -- `run_degradation_audit` leve un `RuntimeError` immediat si la
  variable d'environnement `FRED_API_KEY_ENV` est absente, car sans elle la
  configuration `+vintages` n'a aucun sens (le fallback de scraping ne peut
  retourner que la revision courante d'une serie FRED, jamais une vraie
  vintage ALFRED point-in-time -- voir `_vintage_date_for_audit()`, lignes
  71-77, et `data/sources/fred_source.py`).
- **Sortie** : un CSV + un markdown (`_export`, lignes 153-170) avec une
  ligne par (cible, configuration) -- 5 cibles x 4 configs = 20 lignes --
  portant les colonnes `BalAcc_4cls`, `MCC_4cls`, `F1_dir` (`METRIC_COLUMNS`,
  ligne 47), plus `fred_source` et `n_evaluations`. Ce n'est PAS un score de
  "degradation" par (ticker, horizon) : c'est une comparaison de 3 metriques
  de performance entre 4 variantes de pipeline, pour les memes 5 cibles,
  a horizon fixe (`horizons=[5]`, `_config_for`, ligne 92).

### 2. Verdict : mismatch confirme entre la premisse de la Phase 4 et le code

Confirmation explicite, apres lecture complete de `audit.py` (211 lignes) et
de la commande CLI associee :

`patrick audit degradation` est un **outil de validation ponctuelle d'une
correction de fuite de donnees** (Phase 0), execute a la demande par un
humain qui dispose d'un acces reseau complet (yfinance + FRED) et d'une cle
`FRED_API_KEY`, sur un univers FIXE de 5 cibles choisies pour couvrir les
classes d'actifs -- **pas** un moniteur de derive de performance par
(ticker, horizon) exploitable en continu sur les 68 tickers de production.
Consequences concretes qui rendent un badge "degradation" par
ticker/horizon denue de sens produit ici :

1. **Pas de couverture de l'univers** : seulement 5 cibles sur 68 ont un
   resultat -- un badge sur les 63 autres ticker/horizon n'aurait aucune
   donnee source.
2. **Cout reseau a la demande** : `force_ingest=True` force une
   re-ingestion complete (yfinance + FRED) a chaque invocation, pour
   chacune des 4 configurations -- executer ceci pour alimenter une page
   web a chaque chargement (ou meme en tache de fond reguliere) serait
   couteux et lent, et echouerait purement et simplement sans
   `FRED_API_KEY`.
3. **Semantique differente** : le signal produit compare des variantes de
   pipeline (avec/sans purge, avec/sans vintages) sur les MEMES donnees et
   le MEME horizon, pas une evolution de la performance d'un modele de
   production dans le temps. Il n'y a pas de notion de "seuil ok/warning"
   par ticker/horizon a en tirer -- juste un delta baseline vs corrige,
   pour un usage de validation technique, pas de suivi produit continu.

**En consequence, conformement a la consigne, je m'arrete ici : pas de
badge "degradation" par ticker/horizon ajoute, pas de route web modifiee,
pas de nouveau composant `status_badge` pour cette notion.**

### 3. Piste alternative (signalee, non implementee)

Si un signal de "sante"/derive par (ticker, horizon) doit exister, les
candidats reels deja presents dans le code (lecture seule, deja peu
couteux, pas de reseau) sont, par ordre de pertinence :

- `patrick/patrick/tracking/holdout_diagnostic.py::spearman_test_vs_holdout`
  (lignes 44 et suivantes) : correlation de rang entre le classement des
  trials sur `test` et sur `holdout` pour un run donne -- un diagnostic de
  generalisation deja calcule et affiche en lecture seule sur
  `/runs/{run_id}` (via `tracking/history.py::run_detail`, ligne 261).
  Explicitement documente comme jamais utilise pour la selection de
  modele (isolation garantie par
  `tests/test_holdout_diagnostic_isolation.py`), donc un candidat "propre"
  pour un badge de risque de surapprentissage par run/cible.
- `patrick/patrick/tracking/history.py::target_detail` (lignes 295-337) :
  calcule deja `pbo_by_horizon` (probability of backtest overfitting, par
  horizon, walkforward ET cpcv) pour une cible donnee, a partir de l'
  historique de runs deja en base -- aucun appel reseau, deja utilise par
  `/targets/{ticker}`. Un vrai candidat "par (ticker, horizon)" a cout nul.
- `patrick/patrick/tracking/history.py::direction_metrics_by_target` /
  `latest_predictions_by_target` (lignes 450-637) : F1/precision/recall par
  direction pour le dernier run termine de chaque cible -- deja agrege pour
  `/` (synthesis) sans requete N+1, purement lecture de base.

Ces trois sources meriteraient une comparaison EXPLICITE dans le temps
(ex. `pbo_by_horizon` ou le F1 test/holdout du run le plus recent vs celui
d'il y a N runs pour la meme cible/horizon) pour constituer un vrai signal
de "derive" -- ce calcul n'existe pas encore tel quel dans le code. Piste
seulement, non implementee dans cette branche.

### 4. Statut final

- Etape 1 (audit) : **effectuee**, mismatch confirme, documente ci-dessus.
- Etape 2 (badge par ticker/horizon) : **non realisee**, bloquee par le
  constat de l'etape 1 (conformement a la consigne de la tache).
- Etape 3 (TDD + verification navigateur) : **non applicable**, aucune
  route/fonction d'exposition nouvelle n'a ete creee.
- Aucun fichier de code modifie. Seul ce document est ajoute.
- Branche : `feature/degradation-badge`, prete a review (commit de
  documentation du blocage uniquement).


---

## Partie 3 — Phase 7 — faisabilité SHAP par prédiction

*Source d'origine : `patrick/PHASE7_SHAP_FEASIBILITY.md`.*

Constat de faisabilité (feature/shap-waterfall) : **implémenté**, coût jugé
acceptable pour un affichage à la demande. Ce document consigne les chiffres
réels mesurés, référencés depuis `patrick/explain.py` et `tests/test_explain.py`.

### Où les valeurs SHAP existaient déjà — et pourquoi elles ne sont pas réutilisées

`selection/shap_select.py` calcule déjà des valeurs SHAP, mais sur un modèle
**pilote jetable** (XGBoost `n_estimators=80, max_depth=4`, entraîné
uniquement pour classer/sélectionner les features, jamais exporté). La
migration `tracking/migrations/0014_shap_selection_cache.sql` ne persiste
que `selected_columns` — jamais les valeurs SHAP elles-mêmes. Le modèle
réellement **exporté** (`tracking/export.py::export_best_model`) peut être
n'importe lequel des 5 algos de `models/registry.py`, avec hyperparamètres
tunés et données rééchantillonnées — un objet entraîné complètement
différent. Expliquer une vraie prédiction exige donc de calculer SHAP sur
CE modèle, pas de réutiliser le cache de sélection.

### Coût mesuré (chiffres réels, pas une estimation)

Mesuré sur un modèle réellement exporté en production
(`~/.patrick/runs/mon_run/BTC_USD_1_best_model_h1.joblib`, LightGBM, 15
features sélectionnées) :

| Étape | Coût mesuré |
|---|---|
| `shap.TreeExplainer(model)` + `shap_values()` sur 1 ligne, à froid | ~0,73s (joblib.load + explainer + shap_values) |
| Même appel, explainer réutilisé (à chaud) | ~5ms |
| Reconstruction du pool de features (`build_base_feature_pool` + `build_parametric_pool`, EGARCH/Kalman/HMM/particle-filter sur tout l'univers, `fit_end_idx=None`) pour retrouver la ligne exacte à expliquer | **~33,6s** (mesuré sur l'export réel BTC-USD/h1, données brutes déjà en cache, aucun appel réseau) |

**Conclusion** : le calcul SHAP proprement dit est négligeable (<1s, "rounding error" face au reste). Le coût réel visible par l'utilisateur vient de la reconstruction du pool de features nécessaire pour retrouver la ligne exacte de la date expliquée — un coût **préexistant**, payé de la même façon par `predict.py` lors de chaque inférence live, pas quelque chose que ce module ajoute.

### Décision produit

- Calcul **à la demande** (bouton "Générer l'explication" sur `/targets/{ticker}`), jamais au chargement de page — le bouton se désactive et affiche un message d'attente pendant le calcul (~30s en pratique), sans prétendre que c'est instantané.
- Pas de cache inter-requêtes de l'`explainer` : le trafic visé (outil local, un seul utilisateur) ne justifie pas la complexité de garder une référence au modèle chargé + données de fond entre deux requêtes HTTP.
- Valeurs SHAP affichées dans l'**espace brut du modèle** (`TreeExplainer(model_output="raw")`, unités type marge/log-odds) — PAS une décomposition de probabilité : pour un ensemble d'arbres multiclasse, la garantie d'additivité de SHAP tient dans cet espace brut, pas après passage par softmax. Le front-end (`shap_waterfall.js`) affiche explicitement cet avertissement sous le graphique.

### Limite honnête trouvée en testant contre une vraie base

`trial.artifact_path` est un chemin **relatif**, résolu par `joblib.load()`
contre le `cwd` du process serveur au moment de l'appel — pas contre
l'emplacement du code. Si `patrick serve`/`patrick worker` tourne depuis un
répertoire différent de celui où le run a été exporté à l'origine, la
résolution échoue (`FileNotFoundError` remontée proprement en `ok: false`
côté JSON, jamais une page cassée). C'est exactement le même piège déjà
documenté par `feature/scheduled-inference` (`daily_predict.py`, option
`--base-dir`) — cette route API n'a pas d'équivalent `--base-dir` (elle
tourne dans le process web déjà démarré au bon endroit en production), mais
le constat mérite d'être connu si le mode de déploiement change un jour.
