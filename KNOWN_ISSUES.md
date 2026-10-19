# KNOWN_ISSUES.md — Problèmes connus, hors scope des sessions en cours

Suivi des échecs pré-existants identifiés mais volontairement **non corrigés**
dans les sessions de traduction (D1-D6) et d'infrastructure (CI, commit
fréquent, nettoyage de branches) — hors mandat de ces sessions
(« aucune modification de logique fonctionnelle »). Traités dans une session
de correction dédiée (voir « Résolus » ci-dessous).

---

## Résolus

### 1. `test_data_quality.py::test_ingest_excludes_series_with_explicit_reason_and_persists` — résolu 2026-08-08

Cause confirmée : fixture à date absolue `2018-01-01`. Corrigé en remplaçant
par `_OLD_ENOUGH_START`, une date calculée relativement à l'exécution
(`pd.Timestamp.today() - 30 ans`, marge de 10 ans au-delà du seuil de 20 ans
testé) — `patrick/tests/test_data_quality.py`. Voir l'historique git de ce
fichier / le commit associé sur la PR #41 pour le diff exact.

### 2. `test_data_quality.py::test_data_quality_disabled_restores_pre_p6_5_behavior` — résolu 2026-08-08

Même cause, même correctif que le point 1 (fixture partageant la même
constante `_OLD_ENOUGH_START`).

### 4. `test_audit_degradation.py::test_audit_degradation_runs_all_four_configurations_and_exports` — résolu 2026-08-11

Même cause, même famille que les points 1-2 (fixture à date absolue,
`START = "2015-01-01"`) : passée sous le seuil des 20 ans d'historique
minimum requis par `data/ingest.py`. Pas détectée avant cette session car
le test est marqué `slow` (exclu de la suite rapide par défaut,
`pyproject.toml::addopts`) et n'était donc pas visible tant que
`pytest -m slow` n'avait pas été relancé après que la fixture ait
franchi le seuil. `_OLD_ENOUGH_START` (point 1) déplacée de
`test_data_quality.py` vers `tests/conftest.py::OLD_ENOUGH_START`
(helper partagé plutôt que dupliqué une deuxième fois, cf. règle du
projet) ; les deux fichiers l'importent désormais.

### 3. `test_history_webapp_smoke.py::test_universe_page_renders` — résolu 2026-08-08

**Ce n'était pas un problème de date** : investigation menée avant toute
correction (voir règle du projet : ne jamais deviner la cause). Cause réelle,
confirmée par exécution directe : `patrick/webapp/app.py::universe_page`
contenait une confusion de type — `DEFAULT_TARGET_GROUPS.values()` donne des
listes de tuples `(symbole, label)`, mais la route les itérait comme si
c'étaient des symboles bruts (`for s in targets`), puis testait
`target in symbol_info` avec `target` = tuple entier contre un dict à clés
string. Résultat : `target in symbol_info` était **toujours `False`**, donc
la liste `groups` restait vide dans 100% des cas, indépendamment du contenu
de la base — un bug de production, pas un artefact de test.

`tracking/history.py::universe_overview` faisait déjà cette jointure
correctement (`for symbol, label in items:`) mais n'était pas appelée par la
route — une deuxième implémentation parallèle, divergente, avait été écrite
directement dans `app.py`. Corrigé en supprimant cette duplication : la route
appelle désormais `universe_overview()` pour le regroupement, et ne conserve
que la logique propre à la route (traduction i18n du nom de groupe, qui a
besoin de `request` et n'a donc pas sa place dans la couche lecture seule
`tracking/history.py`).

### 5. `test_run_pipeline_golden.py` (walkforward et cpcv) — résolu 2026-09-28

Échec local (Python 3.14, Windows) et slow-suite CI rouge/verte en
alternance sur `main` (rouge 4cdeba3, 6e495a6, 2e5bcea ; verte a8636d8,
7247fff, e1f4e92). **Pas une régression** : la sortie du pipeline est
identique au bit près sur tous les commits de 3dc8753 (dernière
régénération du golden) à 2e5bcea — aucun bisect possible. Cause :
l'environnement numérique. (1) Versions : le venv local 3.14 (numpy 2.5,
xgboost 3.4, shap 0.52) ne retient pas les mêmes features que la CI 3.11
(numpy 2.4, xgboost 3.2, shap 0.51). (2) CPU : même avec les versions
exactes de la CI, 7-8 valeurs diffèrent encore ; forcer le noyau OpenBLAS
Sandybridge au lieu de Haswell sur la même machine en change 23 (seules les
prédictions LightGBM bougent : écarts au dernier bit des features Kalman,
amplifiés par le binning). Le golden n'était donc reproductible que sur un
runner du même type de CPU que la machine qui l'avait généré -- cause
probable de l'alternance CI (non confirmée : logs CI illisibles sans
connexion GitHub).

Corrigé : chaque golden enregistre l'environnement qui l'a produit et la
comparaison est refusée ailleurs (skip en local, échec en CI) ; la
slow-suite tourne dans un environnement figé (`.github/constraints-py311.txt`,
`OPENBLAS_CORETYPE=Haswell`, `NPY_ENABLE_CPU_FEATURES=X86_V3`) où le golden
est régénéré par `.github/workflows/golden-regen.yml` (branche
`golden-regen/<nom>`) ; en local, un golden de sa propre machine via
`PATRICK_GOLDEN_DIR` (docstring du test).

### 6. `test_backup_db.py::test_backup_database_creates_timestamped_file_in_dest_dir` -- résolu 2026-10-06

Même famille que les points 1-2-4 (date figée dans un test), mais côté rétention : le test sauvegardait avec
l'horodatage fixe `20260905_161500`, et `backup_database` purge juste après toute sauvegarde dont l'horodatage
(lu dans le NOM du fichier) dépasse `retention_days` (30 jours par défaut). Le 2026-10-05, ce fichier est devenu
« trop vieux » : il était créé puis supprimé par la purge, d'où `dest_path.exists()` faux. Confirmé par exécution :
rouge avant, vert avec `retention_days=0`. Le test porte sur le nommage, pas sur la rétention (testée ailleurs dans le
fichier avec des dates relatives) : correctif = `retention_days=0` dans cet appel, sans toucher au code de production.

---

## Contexte de découverte

Ces trois échecs sont apparus de façon répétée et cohérente tout au long
des sessions D1-D6 (traduction) et de mise en place de la CI — toujours
les mêmes trois, jamais de régression supplémentaire causée par les
changements de ces sessions (vérifié systématiquement via exécution
isolée et comparaison `git stash`/HEAD non modifié). Confirmés une
dernière fois par la CI elle-même (`.github/workflows/tests.yml`,
premiers runs sur PR #41) : `3 failed, 221 passed, 42 deselected`.

Après correction : suite complète rapide vérifiée verte —
`224 passed, 42 deselected, 0 failed`.

---

## Instable, cause identifiée -- pas corrigé (charge machine, pas un bug)

### `test_webapp_smoke.py` (tests slow lançant un vrai pipeline) — `deadline_s=240` insuffisant sous charge externe, identifié 2026-08-11

`pytest -m slow` complet (session C1-C4) : 2 échecs sur 16 tests slow,
`test_audit_degradation...` (point 4 ci-dessus, résolu) et
`test_relaunch_reuses_config_with_fresh_name`
(`test_webapp_smoke.py`) — timeout dans `_wait_for_status(...,
deadline_s=240)`.

**Investigation avant correctif** (règle du projet) : `test_relaunch_reuses_
config_with_fresh_name` passe seul en isolation (29,5s, marge large sur
240s). Reproduit de façon fiable en relançant les 6 tests slow de
`test_webapp_smoke.py` ensemble (~5 min) -- mais avec `-x` (arrêt au premier
échec), c'est le PREMIER test du fichier
(`test_run_via_web_form_end_to_end`), pas le test du rapport initial, qui
échoue le premier : `elapsed_s=235.6`, `phase='features'`,
`progress={'done': 0, 'total': 16}` -- le pipeline réel n'avait même pas
commencé les essais de modèles après 235s, alors qu'il termine
normalement en quelques secondes à quelques dizaines de secondes. Au
moment de cette relance, `uptime` mesurait une charge machine de
**19,3 sur 4 cœurs** (`nproc`) sans aucun processus pytest concurrent de
cette session -- charge externe au conteneur, pas une contention entre
tests de cette suite.

**Conclusion** : pas la même famille que les points 1-2-4 (aucune fixture
en cause) et pas un bug de code -- le budget de 240s de
`_wait_for_status` n'a simplement aucune marge quand la machine hôte est
fortement chargée par autre chose que cette session, et LEQUEL des 6
tests du fichier échoue en premier dépend du moment exact où la charge
frappe, pas d'un test spécifique ni d'un ordre d'exécution particulier.
**Non corrigé délibérément** : augmenter `deadline_s` à une valeur
arbitraire (600? 900?) serait deviner un correctif sans savoir si la
marge serait suffisante à la prochaine charge externe -- exactement ce
que la règle du projet interdit. Nécessite une décision produit (budget
de timeout acceptable pour la CI/le sandbox, ou marquer ces tests comme
non fiables sous charge partagée) plutôt qu'un ajustement de constante
à la volée.

---

## Code mort — traité (audit phase9.py, D1-D4)

### 1. `patrick/patrick/features/vol_models.py::build_vol_model_features` — identifié 2026-08-09, supprimé 2026-08-11

Fonction combinée (paramétrique + non-paramétrique) **jamais appelée en
production** — confirmé par recherche exhaustive des appelants : seule
`build_vol_model_features_parametric` (et séparément
`build_vol_model_features_base`) est utilisée, depuis
`pipeline/engine.py::build_parametric_pool`/`build_base_feature_pool`.
Lue en détail (D4) : duplication exacte des deux fonctions séparées
concaténées, en plus ancien -- sans le cache (`conn`/`snapshot_id`,
migration 0015) ni l'instrumentation de profilage (P1) ajoutés depuis aux
deux fonctions séparées. Supprimée, ainsi que `_VOL_MODEL_BUILDERS` (dict
de fusion qui n'existait que pour l'alimenter). Les 3 tests de
`tests/test_features_robustness.py` qui l'utilisaient (régression zero-
crossing/infini, cf. en-tête du fichier) ont été portés sur un helper de
test local qui appelle les deux fonctions séparées et concatène -- la
couverture réelle (le bug historique testé) est préservée, seul le point
d'entrée mort a disparu.

### 2. `patrick/patrick/phase9.py::signal_strength` — identifié et supprimé 2026-08-11

Orpheline totale (même pas exportée dans `__init__.py`, contrairement au
reste de `phase9.py`). Enveloppe triviale `{signal: score} -> DataFrame`
à 2 colonnes ; son rôle (poser une colonne `signal` en entrée
d'`aggregate_signals`) est déjà rempli en production par la sortie
(bien plus riche : `dm_stat`/`p_value`/`testable`/`significant`...) de
`signal_dm_summary`, qui alimente réellement `aggregate_signals`.
Supprimée sans réécriture de test (aucun test n'y faisait référence).

### 3. `patrick/patrick/phase9.py::reconstruct_state` — identifié et supprimé 2026-08-11

Fonction libre, strictement orpheline : aucun appelant, y compris depuis
`StrategyEngine` (qui n'a jamais utilisé `take_snapshot`/`reconstruct_state`
comme une paire symétrique malgré les noms). Supprimée.

### 4. `patrick/patrick/phase9.py::DecisionJournal`/`DecisionJournalEntry`/`take_snapshot` — **conservées**, décision révisée 2026-08-11

Identifiées dans l'audit comme redondantes avec la vraie persistance
(`tracking/db.py::save_phase9_journal_entry`/`save_phase9_snapshot`,
branchée sur `/api/phase9/journal` et `/phase9`) -- la décision initiale de
l'audit était de les supprimer avec le reste du "journal en double" (D3).
Lecture du code avant suppression (règle du projet : jamais deviner) a
révélé une dépendance structurelle non anticipée : `StrategyEngine`
(conservée, cf. bloc 5-7 ci-dessous) journalise en interne via
`self.journal` (une `DecisionJournal`) sur CHAQUE méthode, et
`StrategyEngine.snapshot_state` appelle directement `take_snapshot`.
Supprimer ces trois symboles aurait cassé `StrategyEngine`, ce que D1
(même audit) demande explicitement de ne pas toucher. Rôle clarifié en
commentaire de module (`phase9.py`, juste avant `StrategyRule`) : ce ne
sont pas des concurrentes de `tracking/db.py` mais l'audit trail interne,
en mémoire, du futur moteur de stratégie -- gardées pour cette seule
raison, pas pour un usage autonome.

---

## Plomberie future volontaire (non retirée)

### `StrategyRule`/`StrategyVersion`/`StrategyEngine`/`enforce_risk_constraints`/`ExecutionOrder`/`simulate_execution`/`parameter_grid_summary` — audit D1, 2026-08-11

Jamais appelées hors de leurs propres tests -- blocs 5-7 du plan PATRICK
original en 9 blocs (stratégie, backtest, exécution), jamais commencés en
pratique puisque l'univers reste limité à `^VIX`. Pas du code mort par
accident : plomberie préparée pour cette phase future, documentée en
commentaire de module dans `phase9.py` plutôt que supprimée et à
réécrire plus tard.

---

## Nettoyage du dépôt — 2026-10-12

Parcours complet du dépôt (références cherchées dans le code, les tests, les gabarits, le JavaScript et les documents) :

- **Supprimé** : 23 constantes/fonctions Python sans aucune référence (liste dans le commit `chore: 23 définitions Python jamais utilisées`),
  138 clés de texte i18n jamais utilisées (restes de l'ancien simulateur `sim_*`, de l'ancien panneau `record_*`, d'anciens gabarits),
  le module `tracking/black_litterman.py` (version « intérimaire » jamais branchée) avec son test et son terme de glossaire,
  3 scripts de profilage/A-B ponctuels, des copies de notebooks identiques, un `requirements.txt` d'outils sans rapport avec PATRICK,
  deux plans d'implémentation exécutés (les spécifications restent dans `docs/superpowers/specs/`).
- **Fusionné** (`docs/historique/`) : les trois audits de septembre 2026, l'ancien système de design « Desk Amber » avec son rapport
  d'extraction, trois rapports de chantier terminés ; deux vérifications de tickers en un seul fichier (`docs/audits/`).
- **Corrigé** : une section obsolète de ce fichier (« mode clair non implémenté » : il l'est depuis `base_v2.html`), une regex de test
  vide (caractères backspace au lieu de `\b`), l'idiome NaN `v == v`.
- **Conservé volontairement** (voir aussi « Plomberie future volontaire » ci-dessus) :
  - `phase9.py` (`StrategyEngine`…) : plomberie documentée pour la phase stratégie/exécution ;
  - `pipeline/model_categories_training.py` et `tracking/model_categories.py` : catégories de modèles (global / par régime / stacking),
    décrites dans `docs/ways-of-working.md`, non branchées sur le moteur à ce jour — à décider (brancher ou retirer) ;
  - `features/event_features.py` : garde d'horodatage de publication pour les données textuelles (`docs/research/README.md`) ;
  - `wealth/signal_replay.py` : rejeu des signaux sur un patrimoine, dont `_winning_trial` sert encore à des tests ;
  - les fonctions d'accès aux données de `tracking/db.py` sans appelant (`exclude_symbol`, `list_drift_psi_history`,
    `list_phase9_snapshots`) : elles forment avec leurs tables des fonctionnalités à moitié branchées ;
  - les 33 termes de glossaire non rattachés à une icône d'aide : ils restent trouvables par la recherche du glossaire.

---

## Pages ML / DL / RL / Exploration — limites assumées (2026-10-10)

- **Deep learning, modèles à fenêtre** (GRU, LSTM, CNN1D, Transformer) : les lignes sont supposées triées par date. En walk-forward, les
  `lookback − 1` premières lignes de chaque appel de prédiction utilisent comme contexte les dernières lignes d'ENTRAÎNEMENT (écart de
  quelques barres si purge/embargo), approximation documentée dans `models/deep.py`. La prédiction du jour fournit la vraie fenêtre ;
  les barres de rattrapage (reconstitution « à la date t ») sont sautées pour ces modèles, jamais approximées (`predict.py`).
  SMOTE et CPCV sont refusés avec ces modèles (`RunConfig._check_deep_models`). L'explication d'un réseau
  (`explain._deep_contributions`) est en unités de probabilité (valeurs de Shapley estimées), pas dans l'espace brut des arbres.
- **Deep learning, coût** : un réseau coûte nettement plus qu'un arbre sur processeur seul ; les profils de `/dl` le tiennent compte,
  pas la recherche exhaustive (grille de variables × réseaux × Optuna).
- **Reinforcement learning** : une cible cotée à la fois (pas de portefeuille), positions au rendement de clôture à clôture (pas
  d'exécution intra-journalière), coûts proportionnels (frais + glissement en points de base, pas de spread dépendant de la liquidité).
  Les variables sont causales (fenêtres glissantes) : EGARCH, HMM et interactions sont exclus faute de réajustement pli par pli. Le Sharpe
  déflaté compte les runs RL déjà lancés sur la cible comme autant d'essais, pas ceux qui ont été supprimés de la file. Un indice non
  investissable (`^VIX`) donne un rendement théorique.
- **Exploration** : les séries sont rechargées via le cache local de 7 jours de `yfinance_source.download_one` (et l'API FRED pour les séries
  FRED) ; sans cache et sans réseau, un actif est exclu et signalé plutôt que remplacé. Une série FRED hebdomadaire, mensuelle ou trimestrielle
  fait passer tout le panneau à sa fréquence (avertissement affiché ; les séries rapides sont ramenées à leur dernier niveau de la
  période, jamais de valeur recopiée). Les p-values corrigées (Benjamini-Hochberg) couvrent un tableau de tests à la fois, pas l'ensemble des
  analyses lancées pendant une session.
- **Extras optionnels** : sans `pip install -e ".[deep]"` / `".[rl]"`, les pages `/dl` et `/rl` s'affichent mais le lancement est
  désactivé avec le motif ; la CI n'installe pas PyTorch (les tests qui l'exigent sont ignorés, ceux de configuration et de mécanique
  NumPy tournent partout).

---

## Analyse textuelle des news et Black-Litterman — limites assumées (2026-10-18)

- **News** (`patrick/text/`, page `/news`) : aucune variable textuelle n'entre dans un entraînement ; l'historique commence à la
  première collecte. Les flux relus après coup (publiés plus de 72 h avant d'être vus) sont stockés mais écartés des agrégats. Le
  lexique intégré est réduit (anglais, français) ; la polarité d'un mot ne dépend pas de l'actif. Le rattachement privilégie la
  précision (un lien manqué vaut mieux qu'un faux lien). GDELT n'a pas pu être vérifié en réel (HTTP 429 depuis ce poste) ; la BCE
  (certificat refusé par Python ici), l'USDA et l'OPEP (403) ne sont pas dans les flux par défaut (réglage `news_extra_feeds`).
- **P(hausse) du jour** : avant le 2026-10-18, le modèle exporté n'était pas calibré, la `p_up` des prédictions live était un score
  brut. Seuls les exports faits depuis (calibrateur dans le bundle, `prediction.p_up_calibrated = 1`) donnent une probabilité calibrée ;
  les 11 runs avec calibration déjà en base doivent être relancés pour l'obtenir. La classe prédite et sa confiance restent celles
  du modèle refit sur tout l'historique ; seul `p_up` passe par le calibrateur : son modèle sous-jacent est ajusté sur les ~85 % les plus anciens
  de l'historique et sa carte isotonique/Platt sur les ~7,5 % suivants (même découpage que dans le walk-forward, un trou d'une longueur
  d'horizon entre les deux) ; les lignes les plus récentes ne servent donc pas à cette probabilité.
- **Black-Litterman** : conversion P(hausse) -> rendement attendu par une hypothèse gaussienne (tailles de hausse et de baisse égales) ;
  prior = portefeuille HRP faute de capitalisations ; aucune comparaison hors échantillon avec la pondération de référence.
- `tests/test_desktop_runtime.py::test_kill_process_tree_spares_the_caller_even_when_it_is_a_descendant` échoue sur ce poste, lancé
  depuis un shell de l'application Claude (cause probable : processus placés dans un objet de tâche Windows, non confirmée) ; le
  code concerné (`desktop/`) n'est pas modifié par ces chantiers.
