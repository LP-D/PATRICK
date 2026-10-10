# Pages ML / DL / RL, page Exploration, interface à texte minimal

Remplace la seule page « Lancer » (`/launch`, poste de lancement du ML) par trois pages de cadrage (ML, DL, RL) et ajoute une
page d'exploration statistique. Les pages sont livrées en cinq blocs indépendants, chacun testé et commité seul.

## 1. Décisions prises (et pourquoi)

| Sujet | Décision |
|---|---|
| DL et RL | **Vrais moteurs d'entraînement**, pas seulement un formulaire (choix de Léon). PyTorch, Gymnasium et Stable-Baselines3 sont des extras optionnels (`pip install -e .[deep,rl]`) : sans eux les pages s'affichent, le bouton « Lancer » est grisé avec le motif. |
| ML | La page actuelle devient `/ml`. `/launch` redirige (en conservant la requête). Le DL partage le gabarit et le JS du ML (mêmes cibles, horizons, validation, sélection, tuning, file d'attente, résultats). |
| DL | Les réseaux sont des **algos de plus** dans le pipeline existant (`get_classifier`), jamais un second pipeline : walk-forward, purge, embargo, sélection de variables, Optuna, calibration, stacking, classement et duel de champions restent ceux du ML (`docs/ways-of-working.md` : plus d'exclusion a priori du DL). |
| RL | Moteur à part (`patrick/rl/`), même file de jobs (`job.config_json` avec `"kind": "rl"`, résultat dans `job.result_json`), aucune table ni migration nouvelle. Évaluation walk-forward hors échantillon contre « acheter et garder » et « à plat ». |
| Texte | Tout texte explicatif (sous-titres, aides, notes) passe derrière un « ? » (même bouton `.info-icon` que le glossaire). Titres, libellés, valeurs, boutons et messages d'erreur restent visibles. |
| Exploration | Seulement ce qui n'existe pas déjà. Existent déjà et sont seulement liés : rendements/z-score/moyennes mobiles/volatilité par actif (`asset_stats`), covariance et HRP (`/portfolio`), qualité des données, dérive PSI, régime HMM, étude d'événements. |
| Cadrage | Chaque page a une **vue simplifiée** (peu de champs + niveau de budget Rapide/Équilibré/Approfondi) et une **vue experte** (tout modifiable), même bascule `data-mode` que le ML. Les réglages de la vue masquée gardent leur valeur. |

## 2. Navigation

`nav_registry.py` reste la seule source. Nouvelle catégorie **MODÈLES** : `ml` (`/ml`), `dl` (`/dl`), `rl` (`/rl`).
`exploration` (`/exploration`) rejoint PILOTAGE. L'entrée « Lancer » disparaît ; `/launch` devient une redirection
permanente listée dans `NON_PAGE_ROUTES`. Les liens internes (`/launch?target=`, `?run_id=`, `?profile=`, `?suggest=`)
pointent vers `/ml`.

## 3. Bloc 1 — gabarits partagés ML/DL

`index.html` devient `launch_base.html` (structure de la page, blocs surchargeables : modèles, sections propres à la famille).
`ml.html` et `dl.html` l'étendent. Même `app.js`, mêmes identifiants. Un champ caché `family` (`ml`/`dl`) accompagne le POST `/runs`.

## 4. Bloc 2 — texte minimal

`static/help.js` transforme au chargement chaque élément d'aide statique (`.hint`, `.page-subtitle`, notes de pied) en bouton « ? »
placé au bon endroit (fin du libellé, du titre de panneau ou en ligne) ; le texte reste lisible au clavier et par les lecteurs d'écran
(fenêtre `role="tooltip"`, `aria-expanded`, Échap). Un attribut `data-keep` (ou un `aria-live`/`role="status"`) protège les messages
d'état dynamiques. CSS : les éléments d'aide sont cachés par défaut (pas de flash).

## 5. Bloc 3 — Exploration

Page `/exploration` : choix des actifs (groupes de cibles), période, fréquence (jour/semaine/mois) ; études servies en JSON
(`/api/exploration/<étude>`) par `patrick/exploration/` (fonctions pures, testées sur séries synthétiques) :

1. **Corrélations** : Pearson/Spearman/Kendall, ordre par classification hiérarchique, corrélation glissante d'une paire, stabilité.
2. **Distribution** : moyenne, volatilité, asymétrie, kurtosis, Jarque-Bera, VaR/ES historiques, pires/meilleurs jours.
3. **Stationnarité et mémoire** : ADF, KPSS, exposant de Hurst, ACF/PACF, Ljung-Box, ARCH-LM (grappes de volatilité).
4. **Liens entre deux actifs** : corrélation croisée avec décalages, causalité de Granger, cointégration d'Engle-Granger, écart (spread) et z-score.
5. **Structure** : ACP des rendements (variance expliquée, charges), bêta/alpha glissants contre une référence, dépendance de queue.
6. **Saisonnalité** : rendement moyen par jour de semaine et par mois, effet fin de mois.

Chaque résultat indique le nombre d'observations, l'alignement des dates communes et l'avertissement de tests multiples quand
plusieurs paires sont testées (correction de Benjamini-Hochberg déjà dans `validation/fdr`).

## 6. Bloc 4 — Deep learning

`models/deep.py` : classifieurs compatibles scikit-learn (`fit`/`predict_proba`/`classes_`, `sample_weight` accepté) pour
`MLP`, `GRU`, `LSTM`, `CNN1D`, `Transformer`. Réglages communs dans `ModelsConfig.deep` (`DeepConfig`, défauts sûrs) : taille cachée,
couches, dropout, fenêtre (`lookback`), époques, taille de lot, taux d'apprentissage, décroissance de poids, patience
(arrêt anticipé sur la fin de l'échantillon d'entraînement), fraction de validation, coupure de gradient, pondération des classes,
nombre de graines, appareil. Les bornes Optuna des réseaux entrent dans `OPTUNA_PARAM_SPECS`.

Fenêtres : les lignes sont supposées triées par date (vrai pour walk-forward et tuning à découpe temporelle). Le modèle garde les
`lookback − 1` dernières lignes d'entraînement comme contexte ; la prédiction du jour (`predict.py`) fournit les dernières lignes
réelles. Un échantillonneur qui réordonne ou synthétise des lignes (SMOTE…) est incompatible avec les modèles à fenêtre : la page DL
impose `none`. CPCV n'est pas proposé aux modèles à fenêtre (lignes non contiguës).

## 7. Bloc 5 — Reinforcement learning

`patrick/rl/` : `config.py` (`RLRunConfig`, Pydantic), `data.py` (états sans regard vers l'avenir), `env.py` (environnement Gymnasium :
actions discrètes {−1, 0, +1} ou position continue, coûts et glissement en points de base, récompense PnL / log-rendement / Sharpe
différentiel avec pénalité de risque), `agents.py` (PPO, A2C, DQN, SAC via Stable-Baselines3), `walkforward.py` (entraînement sur
le passé, évaluation déterministe sur la période suivante, courbe hors échantillon recollée), `metrics.py` (CAGR, volatilité, Sharpe,
Sortino, perte maximale, rotation, taux de gain, DSR et intervalle de confiance du Sharpe par bootstrap en blocs). Aucune fuite : l'action
prise en *t* ne voit que l'information de *t*, la position est appliquée au rendement de *t + 1*, les coûts sont payés à chaque
changement de position.

Exécution : `worker.py` aiguille selon `kind`. La page `/rl` suit le même fil : formulaire → file → avancement (`phase`,
`progress_done/total`) → résultat (métriques, courbe de capital, comparaison aux références, exports JSON/CSV).

## 8. Hors périmètre

Entraînement distribué, GPU obligatoire, branchement des politiques RL sur les règles du fonds, RL multi-actifs (portefeuille).
Documentés pour un chantier suivant.

## 9. Sécurité du lot en cours

Un lot de runs ML tourne pendant ce chantier : le développement se fait dans une branche/worktree séparée ; tout changement de
schéma ou de registre est **additif** (valeurs par défaut identiques, imports de PyTorch/SB3 paresseux), de sorte qu'un processus
déjà lancé ou un enfant `joblib` qui importerait le nouveau code se comporte comme avant.

## 10. Livré (état au 2026-10-10)

Écarts et précisions par rapport au plan ci-dessus :

- **Gabarits** : `index.html` est renommé `launch_base.html` ; un `index.html` d'une ligne (`extends`) est conservé pour qu'un serveur démarré
  avant la fusion (ancien Python, gabarits relus à chaud) continue de servir `/launch`.
- **Configuration DL** : `ModelsConfig.deep` est ABSENT de la sérialisation d'un run ML (`model_serializer`), donc `config_json` et
  `_config_hash` d'un run de machine learning sont identiques à ceux d'avant (reprise des runs, noms d'études Optuna).
- **Optuna des réseaux** : structure et bornes dans `DL_OPTUNA_PARAM_SPECS` / `DL_DEFAULT_OPTUNA_BOUNDS` (pas dans les dictionnaires ML) ;
  `suggest_params` lit les deux ; le formulaire n'écrit que les bornes des réseaux choisis.
- **RL** : le formulaire est `webapp/forms_rl.py`, les routes `webapp/rl_routes.py` (`/rl`, `/api/rl/runs`) ; l'avancement, la pause, l'arrêt
  et les fichiers passent par les routes génériques des jobs. `/runs/<id>` d'un job RL redirige vers `/rl?open=<id>`. Le Sharpe déflaté compte
  les runs RL terminés sur la cible (le job courant exclu).
- **Exploration** : `exploration_routes.get_panel` construit un panneau par sélection une seule fois même si plusieurs études le demandent
  ensemble ; `LocalCache.save_dataframe` écrit désormais de façon atomique et `load_dataframe` traite un fichier illisible comme absent
  (incident du 2026-10-10 : deux séries du cache réel tronquées par des écritures simultanées, supprimées puis retéléchargées).
- **Texte minimal** : en plus de `.hint` et `.page-subtitle`, `help.js` replie `.profile-desc`, `.headline-sub`, les bandeaux d'information
  (`.banner` sans variante erreur/alerte et sans `role`) et l'explication entre parenthèses d'un libellé (`Libellé (explication)`).
- **Tests** : `test_help_minimal_text`, `test_exploration_studies` / `_routes`, `test_deep_models` / `_pipeline` / `_config` / `test_dl_page`,
  `test_rl_core` / `_walkforward` / `_agents` / `_run` / `_page`, `test_worker_rl`, `test_cache_manager`. Les tests qui exigent PyTorch,
  Gymnasium ou Stable-Baselines3 sont ignorés quand l'extra manque (CI) ; la configuration, la mécanique NumPy et les routes tournent partout.
