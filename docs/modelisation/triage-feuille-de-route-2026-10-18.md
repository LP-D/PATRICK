# Tri de la feuille de route — 2026-10-18

La note de chantiers datait de fin septembre 2026. Chaque ligne a été recoupée avec le code, les tests et l'historique git au
2026-10-18. Statuts : **Fait** (déjà dans le dépôt, avec la preuve), **Obsolète** (remplacé ou sans objet), **Livré 18/10** (fait
dans ce chantier), **Bloqué** (dépend d'une donnée ou d'une licence absente), **Reporté** (décision argumentée, critère d'entrée).

## Préalables

| Item | Statut | Preuve / raison |
|---|---|---|
| Rebase de `feature/replay-cache-universe` | Obsolète | Branche fusionnée et supprimée : cache SHAP (`ad5ff07`) et réduction d'univers par pli (`1c2b49a`) sont sur `main`. |
| Preuve TDD rétroactive du cache (phase 2) | Fait | `ad5ff07` : « ported with mutation proof » ; `tests/test_selection_cache.py`, `tests/test_vol_model_cache.py`. |
| Qualification de `repro_gspc_isinf.py` | Obsolète | Script absent de l'historique. Le défaut ±inf est couvert par `tests/test_inf_features.py`, `tests/test_inf_export_predict.py` et `METHODOLOGY.md` §13. |

## Intégrité statistique

| Item | Statut | Preuve / raison |
|---|---|---|
| F01 lag de publication FRED (point-in-time) | Fait | `data/publication_lag.py`, ALFRED par défaut (`74e3ffe`), `tests/test_fred_point_in_time.py`. |
| F09/F10 et violations DTZ | Fait (partiel) | `ruff check` passe, DTZ explicite (`52713b6`). Les identifiants F09/F10 n'existent pas dans le dépôt : rien à traiter sans l'audit d'origine. |
| F02 purge/embargo dans la CV d'Optuna | Fait | `tests/test_optuna_inner_cv_purge.py`. |
| F03 registre d'essais persistant (DSR) | Fait | `trial_registry`, `tests/test_trial_registry.py`. |
| F04 correction HLN de Diebold-Mariano | Fait | `validation/diebold_mariano.py`, `docs/ways-of-working.md`. |
| Diebold-Mariano aux horizons longs (audit externe, 19/10) | **Livré 19/10** | Mesuré par simulation : le test à 5 % rejetait H0 ~22 % du temps à h=120 et plus de 80 % à h=504 (holdout de 15 mois), HLN compris. Sous 15 blocs indépendants (n/h) le DM est non testable ; `validation/diebold_mariano.py`, `METHODOLOGY.md` §4, `tests/test_diebold_mariano.py`. |
| Fuite CPCV des interactions (audit externe, 19/10) | **Livré 19/10** | Les formules étaient découvertes une fois sur le groupe 0 (groupe de test de 6 combinaisons sur 21). Une découverte par combinaison, sur ses barres d'entraînement purgées ; le modèle exporté a la sienne (tout l'historique). `pipeline/engine.py::_cpcv_interaction_formulas`, `tests/test_cpcv_interaction_leak.py`. Golden CPCV à régénérer (`golden-regen/…`). Reste approximé : seuils de classes et régimes fixés sur le groupe 0. |
| Registre d'accès au holdout (audit externe, 19/10) | **Livré 19/10** | Table `holdout_access` (migration 0038) écrite par `_evaluate_holdout`, seule fonction qui lit le holdout : évaluation finale, diagnostic, duel champion / challenger. Compte par cible / horizon (`trackstats.holdout_reads`), affiché sur la page d'un run, fusionné entre PC. Démarre à sa création ; le simulateur (relecture des prédictions holdout stockées) n'y est pas encore compté. |
| Garde-fous git (audit externe, 19/10) | **Livré 20/10** | `.gitignore` (`.env`, bases SQLite, `runs/`, `.claude/` sauf `settings.json`), hook `.githooks/pre-push` (ni suppression, ni push forcé hors `wip/`, `tmp/`, `golden-regen/`), `scripts/git_facts.sh` (faits bruts), fixture `test_wealth_importer` rendue synthétique. L'historique public garde l'ancienne fixture : sa purge demande de réécrire l'historique, non fait. |
| Test de validité sur marche aléatoire (audit externe, 19/10) | **Livré 20/10** | `tests/test_null_world_validity.py` : 12 mondes nuls + 3 mondes à signal. BH 0 rejet, PBO moyen 0,59, DSR bas ; mais DM bilatéral à surveiller (3/12 côté « pire ») et DM peu puissant : `KNOWN_ISSUES.md`. |
| F05 famille BH avec cibles CPCV | Fait | `tests/test_fdr_family.py::test_cpcv_only_targets_count_in_the_bh_family`. |
| F06 test / holdout / live séparés dans `/simulate` | Fait | `tests/test_simulate_segments.py`. |
| Reproductibilité de la sélection entre OS | Fait | `tests/test_selection_determinism.py` (tri stable, graine). |
| Bug de snapshot dans `explain.py` | Fait | `tests/test_explain_snapshot.py`. |
| Réduction d'univers dans chaque pli | Fait | `selection/universe_reduction.py`, `METHODOLOGY.md` §3. |
| Relance des runs de référence (GSPC) | Fait | 12 champions refaits les 9-10/10 après la fuite ; `docs/research/fuite-f1-parfait-2026-10-09.md`. |

## Infrastructure et dette

| Item | Statut | Preuve / raison |
|---|---|---|
| Réduction d'univers propagée à `explain` et `predict` | Fait | `explain.py`, `predict.py` (`restrict_to_required_series`). |
| Vérification réseau des 39 tickers Yahoo | Fait | `data/ticker_check.py`, `patrick audit tickers`, `docs/audits/verification-tickers.md`. |
| ruff local et 159 violations | Fait | `ruff check patrick tests` : All checks passed. |
| Fraîcheur sur tous les tickers | Fait | `b458d5a` ; page `/data-freshness`. |
| Cache « calculer une fois » par (vintage, fold) | Fait | `features/pool_cache.py` (clé = hash du contenu × coupe du pli × code). |
| Refactor de `run_pipeline` par golden master | Fait | Étapes `_scan_*`, `_tune`, `_export_tables` ; `tests/test_run_pipeline_golden.py` (lié à l'environnement). |
| Audit de vitesse | Fait | `docs/audits/audit-vitesse-2026-09-25.md`, `patrick/audit_speed.py`. |
| `n_jobs` borné | Fait | `MODEL_N_JOBS = 1`, `resource_budget.py`. |
| Enquête sur la tâche planifiée autonome | Fait | `docs/ops/taches-planifiees-agents.md` (origine non localisée, garde-fou posé). |
| `ways-of-working` et `MASTER.md` (levée DL / stacking) | Fait / Obsolète | `docs/ways-of-working.md` à jour ; `MASTER.md` est le système de design, sans rapport avec la levée. |

## Modélisation

| Item | Statut | Preuve / raison |
|---|---|---|
| Calibration isotonic / Platt | Fait + **Livré 18/10** | Walk-forward : `models/calibration.py`. **Nouveau** : le modèle exporté n'était pas calibré, donc la `p_up` du jour était un score brut. L'export ajoute un calibrateur (`tracking/export.py`), `predict_live` l'applique et marque `prediction.p_up_calibrated` (migration 0037). |
| Black-Litterman v2 sur sorties calibrées | **Livré 18/10** | `tracking/black_litterman.py`, section de `/portfolio` (fragment `/fragments/portfolio-bl`), terme de glossaire. Ne lit que les `p_up` calibrées. |
| Meta-labeling | Fait | `validation/meta_labeling.py`. |
| Prédiction conforme | Fait | `validation/conformal.py`. |
| Badge de dérive par ticker et horizon | Fait | `validation/drift.py`, `tests/test_drift_badge*.py`. |
| Évaluation du protocole anti-overfitting du DL | Fait | `docs/modelisation/cadrage-dl.md` ; DL branché (`models/deep.py`, page `/dl`). |
| Features de cycle long (252/504/756 j) | Fait | `features/long_cycle.py` ; 504/756 j sont descriptifs par décision du 2026-09-26. |
| Taux zone euro | Fait (partiel) | Jambe euro du carry EUR/USD (`ECBDFR`), taux 10 ans DE/UK/JP. Reste le carry des autres paires (GBP, JPY…) : faute de taux directeurs publiés sur FRED pour ces banques, à ajouter source par source. |
| Cible alpha vs benchmark | Fait | `features/alpha_target.py`, page Lancer, simulation couverte. |
| Module d'event study | Fait | `research/event_study.py` ; Apple keynotes et Netflix. |
| RL pour l'allocation | Fait | `patrick/rl/`, page `/rl`. |
| Stratégie keynotes Apple | Obsolète | Étude faite : le « sell the news » n'est pas établi (`docs/research/event-study-apple-keynotes.md`). Pas d'avantage directionnel à exploiter. |
| Stratégie streaming musical | Bloqué | Même outil (`patrick research event-study --ticker SPOT --earnings`), mais la variable utile (abonnés, prévisions) n'a pas de source horodatée. |
| Source d'open interest et de basis momentum | Bloqué | Aucune source (Yahoo n'a que des séries continues). Cadrage : `chantiers-lointains.md` §3. |
| Fondamentaux point-in-time des actions | Bloqué | yfinance ne donne que l'état actuel ; garde explicite dans `features/equity_fundamentals.py`. |
| Extension futures | Bloqué | Même cause que l'open interest : pas de courbe de contrats. |
| Modèles de diffusion | Reporté | Entrent seulement s'ils battent la prédiction conforme au CRPS en walk-forward (`cadrage-dl.md` §2) ; les bases probabilistes (régression quantile, CRPS/PIT) qui les précèdent n'existent pas encore. |

## Analyse textuelle des news

Livré le 2026-10-18 : paquet `patrick/text/`, migration 0036, page `/news`, commande `patrick news refresh|summary`. Tout est
point-in-time (`max(publication, première observation)`, après la clôture = séance suivante, date seule = fin de journée) et une
nouvelle vue plus de 72 h après sa publication (flux relu après coup) est écartée des agrégats.

| Item | Statut | Où |
|---|---|---|
| Ingestion point-in-time (GDELT, RSS, presse) | **Livré 18/10** | `text/sources.py` : 9 flux RSS vérifiés en réel le 18/10 (244 nouvelles collectées, 29 actifs rattachés), Yahoo (`--yahoo`). GDELT (`--gdelt`) : analyseur testé sur la forme documentée de l'API, **non vérifié en réel** (HTTP 429 persistant depuis ce poste le 18/10). |
| Discours et communiqués de banques centrales | **Livré 18/10, étendu 27/10** | Fed, BoE, puis BCE, Banque du Canada, BRI (27/10). Les pages complètes sont lues (`text/fulltext.py`, migration 0045), y compris le procès-verbal du FOMC. SNB : certificat non reconnu par Windows ici. |
| Rapports matières premières | **Livré 18/10** (partiel) | EIA. Revérifiés le 27/10 : OPEP (403), AIE (aucun flux RSS officiel), USDA (`usda.gov` 403 ; `ams.usda.gov` ne publie que des événements). Rien d'ajoutable sans URL valide. |
| Transcripts d'earnings calls | Bloqué | Sources payantes ou sous licence. |
| Réseaux sociaux (X, Reddit, StockTwits) | Bloqué | API à clé et conditions d'usage ; pas de collecte sans accord explicite. |
| Indices textuels existants (EPU, GPR) | Reporté, instruit le 27/10 | FRED publie `USEPUINDXD` (jour), `USEPUINDXM` et `GEPUCURRENT` (mois) ; l'indice est révisé (ALFRED ne garde les versions que depuis 2014). Les brancher comme séries macro change les variables de tous les nouveaux runs (tables `MACRO_ONLY_FRED_SERIES`, fraîcheur, délais de publication) : décision à prendre, pas un ajout silencieux. GPR : pas d'identifiant FRED trouvé. |
| Sentiment par dictionnaire (Loughran-McDonald) | **Livré 18/10, lexique v2 le 27/10** | `text/lexicon.py` : lexique réduit intégré (FR/EN), 38 % des nouvelles notées (contre 33 %) ; `patrick news lexicon fichier.csv` branche le fichier LM complet (à télécharger par Léon, non redistribué). |
| Sentiment FinBERT et ajustement matières premières | Bloqué | Demande PyTorch + modèle téléchargé + données étiquetées. Interface prévue dans `topics.py` / `service.py`. |
| Ton hawkish / dovish des banques centrales | **Livré 18/10, refondu le 27/10** | `text/central_bank.py` : calculé sur la page complète, vocabulaire Fed/BoE, filtre de pertinence monétaire (17 documents sur 152 ont un ton, contre 0 sur 79). |
| Classification directionnelle zero-shot par LLM | Bloqué | Demande une clé d'API ; le garde-fou, lui, est livré (`text/llm_guard.py`). |
| Plongements de news | **Livré 18/10** (LSA) | `text/topics.py::fit_embedder` : TF-IDF + SVD, pas un transformeur. |
| Thèmes (LDA, BERTopic) | **Livré 18/10** (LDA) | `text/topics.py::fit_topics`. BERTopic non installé. |
| Extraction d'événements | **Livré 18/10** | `text/events.py` : choc d'offre, sanction, grève, météo (FR/EN). |
| Score de nouveauté | **Livré 18/10** | `text/novelty.py` (haché, strictement antérieur). |
| Attention médiatique | **Livré 18/10** (volume) | z-score du nombre de nouvelles (`text/aggregate.py`). Google Trends : bloqué (non officiel). |
| Rattachement news → ticker | **Livré 18/10, élargi le 27/10** | `text/entities.py` : cashtag, ticker de place de cotation, nom et orthographe de presse (casse respectée), thèmes (indices, devises, taux, matières premières). 75 nouvelles rattachées sur 431 (17 %) : les flux contiennent beaucoup d'articles sans actif de l'univers. |
| Agrégation par actif et par horizon | **Livré 18/10** | `text/aggregate.py::sentiment_features`, `features_for_symbol`. **Pas encore une variable d'entraînement** : `training_features_for_symbol` refuse tant que `text/readiness.py` mesure moins de 250 séances et 60 jours avec nouvelles (`patrick news readiness`). Branchement dans `RunConfig` volontairement non fait (changerait la clé du cache de variables et l'identité des runs). |
| Garde-fou contre la fuite temporelle des LLM | **Livré 18/10** | `text/llm_guard.py`. |
| Event study textuel | **Livré 18/10** | `aggregate.textual_event_study`, à la demande sur `/news`. |

**Limites assumées** : l'historique commence à la première collecte (GDELT ne remonte que de quelques mois par cette API), donc aucune
variable textuelle n'entre dans les entraînements tant que quelques centaines de séances ne sont pas accumulées ; la polarité d'un
mot ne dépend pas de l'actif ; le lexique intégré est réduit.

## Patrimoine et produit

| Item | Statut | Preuve / raison |
|---|---|---|
| Pages PATRIMOINE, comptes multiples PEA/CTO | Fait | `wealth/`, `/patrimoine`, `/mouvements`, `fund/rules.py`. |
| Glisser-déposer des mouvements entre comptes | Fait | `static/wealth.js`. |
| Gestion réelle et fictive | Fait | `wealth/` + `fund/` (page `/fonds`). |
| `/simulate` étendu au patrimoine | Obsolète | Remplacé par la refonte Simulation/Fonds (`docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md`). |
| Covariance Ledoit-Wolf, IPO sans historique (D.A.T.E) | Fait | `tracking/covariance.py`, `wealth/performance.py` (proxy `history_proxies`). |
| Benchmark en colonne | Fait | `tests/test_benchmark_column.py`. |
| Univers massivement élargi | Fait | `config/universe_extension.py`. |
| Prétraitement par corrélations avant entraînement | Fait | `selection/universe_reduction.py`. |
| Infobulles régime, HRP, BL, sentiment | Fait + **Livré 18/10** | Régime et HRP existaient ; BL et sentiment ajoutés (`webapp/glossary_text.py`). |
| Page de flux de news et de sentiment par actif | **Livré 18/10** | `/news`. |
