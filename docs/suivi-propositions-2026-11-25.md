# Suivi des 120 propositions du 2026-11-25

Deuxième liste demandée par Léon le 25/11 (30 améliorations « AM », 30 corrections « CO », 30 fonctionnalités « FO », 30 idées visuelles
« VI »), sans doublon avec celle du 24/11 (`docs/suivi-propositions-2026-11-24.md`), puis « fais tout d'un coup ». Mise en œuvre par lots,
une branche et une PR par lot, CI verte avant fusion. Ce fichier est la source de vérité de l'avancement.

Statuts : **fait** (avec le lot) · **déjà fait** · **rien à changer** (vérifié : le constat ne tenait pas) · **à faire** · **à toi** (geste sur
le PC de Léon ou calcul long du worker) · **décision** (change des résultats historiques ou irréversible : à trancher par Léon).

Règles tenues dans tous les lots : aucun fichier de `features/pool_cache._FEATURE_SOURCES` n'est modifié (empreinte du cache de variables,
plus de 100 Go) ; aucune empreinte de run ni golden ne change sans le dire ; aucune maintenance de la vraie base pendant qu'un worker tourne.

## Améliorations (AM)

| # | Proposition | Statut |
|---|---|---|
| AM1 | Journaux au lieu de `print()` | rien à changer : les `print()` du pipeline, du worker et de l'ingestion sont le protocole de progression que le worker capture et lit (étiquettes `[SCAN]`, `[CACHE]`…, `system/worker.py`) ; les passer par `logging` casserait le suivi des jobs |
| AM2 | Un seul module de métriques de performance | fait (lot 1 : `core/perf.py` : 252/365 jours, écart à la baisse ; simulateur, laboratoire, placements, risque et `stats_core` s'y rattachent) |
| AM3 | Préchauffage au démarrage de serve | déjà fait : `cached_views.warm_async()` calcule les vues lourdes (dont /fonds et l'import de scipy) 20 s après le démarrage du serveur |
| AM4 | Cache des blocs lourds par version de base | déjà fait : `webapp/cached_views.py` garde chaque vue lourde et la recalcule en tâche de fond quand la base bouge (`memo.fingerprint`) |
| AM5 | Table `prediction` dans une base séparée | décision : une seconde base attachée exige un ATTACH sur chaque connexion, et en mode WAL une transaction qui touche les deux fichiers n'est plus atomique entre eux ; sauvegarde, partage et fusion devraient suivre deux fichiers. À trancher (l'archivage Parquet des prédictions du scan, ADR 0009, a déjà retiré l'essentiel du volume) |
| AM6 | Compression zstd | fait en partie (lots 4-5 : copies hors site compressées en zstd sous Python 3.14, gzip sinon) ; décision pour `vol_model_cache` : un format zstd serait illisible par l'autre PC tant qu'il n'est pas à jour |
| AM7 | Éviction du cache de variables selon le coût | fait (lots 4-5 : durée du calcul écrite à côté de chaque pool (`.cost`), l'éviction rajeunit un pool cher : 1 min de calcul = 4 h, plafond 40 h ; jamais un fichier lu depuis moins d'une heure) |
| AM8 | Worker en tâche planifiée Windows | fait, installation à toi (lots 4-5 : `patrick worker --if-no-worker` et `scripts/schtasks_worker.ps1 -Install`, toutes les 15 min : relance un worker mort s'il y a des jobs, jamais un second) |
| AM9 | File triée par le conseiller de ré-entraînement | fait (lots 4-5 : bouton « Trier par urgence » de la file : paires sans champion, puis champions les plus anciens ; ordre modifiable ensuite) |
| AM10 | Bande de non-transaction sur les fonds | déjà fait : le pilote ne change une taille que si le budget a bougé de plus de 10 % (`autopilot.SIZING_TOLERANCE`) |
| AM11 | Spreads calibrés sur les vrais bid/ask | fait en partie (lot 7 : `patrick fund spreads` mesure l'écart achat-vente affiché par Yahoo par classe et le compare aux médianes du modèle) ; remplacer les médianes = décision (change les frais et le P&L passé des fonds) |
| AM12 | Intervalles de confiance sur AUC et F1 | déjà fait : AUC avec intervalle de bootstrap par blocs dans l'analyse d'un run (sections « prédiction » et « robustesse », `analysis/sec_predict.py`, `sec_robust.py`) |
| AM13 | Recherche Ctrl K élargie | à faire (lot 9) |
| AM14 | Cliquet pyright sur les modules d'argent | fait (lots 2-3 : `fund/selection.py`, `core/perf.py`, `tracking/run_queries.py` ajoutés au cliquet pyright ; le reste des modules d'argent compte 316 erreurs, surtout des annotations de pandas) |
| AM15 | Liste blanche testée des requêtes SQL assemblées | fait (lots 2-3 : les constructeurs relus filtrent déjà leurs noms ; liste fermée ajoutée aux ordres limite ; `tests/repo/test_sql_builders.py` refuse tout nouveau constructeur non relu) |
| AM16 | Tests de propriété sur la fiscalité et les frais | fait (lots 2-3 : `tests/placements/test_tax_fee_properties.py`, hypothesis : impôt jamais négatif, jamais au-delà du gain hors PER, couple et durée jamais pénalisants, frais positifs et croissants, forfait exclusif) |
| AM17 | Non-régression visuelle en CI | fait (lots 2-3 : tâche de CI `pages-screenshots`, 12 pages à 1280 et 375 px sur la base de démonstration, artefact + rapport console / défilement horizontal ; informative) |
| AM18 | Audit d'accessibilité automatique | fait (lots 2-3 : `tests/repo/test_pages_quality.py` sur toutes les pages de la navigation ; 5 manques corrigés : recherche Ctrl K, bouton de confirmation vide, bouton de la file, recherche du vocabulaire) |
| AM19 | Budget de temps par page en CI | fait (lots 2-3 : même test, 12 s par page cadre + blocs ; /sante = 3,4 s en local) |
| AM20 | CI plus rapide avec uv | fait (lots 2-3 : suite rapide et vérification des types installées par uv ; les tâches à environnement figé gardent pip) |
| AM21 | Dependabot sur les versions figées | déjà fait : `.github/dependabot.yml` (pip et actions, chaque semaine) ; le fichier figé se régénère par `constraints-regen.yml` (B2) |
| AM22 | Fusionner `feat/sync-en-clair` (ADR 0020) | déjà fait : ADR 0020 fusionnée le 13/11 (PR 72) ; la branche distante restante est un reste |
| AM23 | Rotation des journaux | fait (lots 4-5 : la nuit compresse `nightly.log` au-delà de 300 Mo et garde 4 archives ; testé sur un faux journal) |
| AM24 | Couverture anglaise mesurée | à faire (lot 9) |
| AM25 | Erreurs de formulaire sur le champ concerné | à faire (lot 9) |
| AM26 | Phases de nuit indépendantes en parallèle | rien à changer : mesuré sur le journal réel, la nuit est dominée par les prédictions (étapes de 59 000 à 63 000 s) ; les autres étapes durent quelques minutes, les paralléliser ne gagnerait rien et chargerait les processeurs pendant les prédictions |
| AM27 | Route `/healthz` | fait (lots 4-5 : `/healthz` : version du schéma de la base et du code, `server_too_old`, `migrations_pending`, worker vivant) |
| AM28 | graphify à jour automatiquement | fait (lots 2-3 : crochet `.githooks/post-merge`, `graphify update .` en arrière-plan après un `git pull`) |
| AM29 | Index des ADR généré et vérifié en CI | fait (lots 2-3 : `tests/repo/test_adr_index.py` : numéros uniques et continus, chaque ADR une fois dans l'index ; 8 statuts « à fusionner » périmés corrigés) |
| AM30 | Durée de chaque étape d'un run | déjà fait : section « Durées » de la page Détail d'un run (`run_phase_timing`, migration 0016) |

## Corrections (CO)

| # | Proposition | Statut |
|---|---|---|
| CO1 | Nom de run inséré sans échappement | rien à changer : `tracking/history._run_name` échappe déjà le nom à la source (constat du 25/11 erroné) |
| CO2 | « Significatif » en vert pour un modèle pire que la référence (page d'un run) | fait (lot 1 : `run_queries.dm_reading`, p unilatérale « le modèle fait mieux » partout où une page lit `dm_result` ; mention « moins bon que la référence ») |
| CO3 | Même lecture sur /predictions et la fiche d'un actif | fait (lot 1 : même lecture ; pastille « moins bon ») |
| CO4 | Sortino faux dans le simulateur | fait (lot 1 : écart à la baisse sur toutes les séances) |
| CO5 | Annualisation sur 252 jours des séries 7 j/7 | fait (lot 1 : 365 jours quand plus de 20 % des dates tombent un week-end ; les fonds passaient déjà par les jours ouvrés) |
| CO6 | Comparaison journal / table faite sur une ligne au hasard | fait (lot 1 : première prédiction du jour, intervalle de dates indexable) |
| CO7 | Total des divergences plafonné à 30 | fait (lot 1) |
| CO8 | Fuseau horaire figé au démarrage | fait (lot 1 : heure d'été appliquée date par date) |
| CO9 | Configuration YAML lue dans l'encodage Windows | fait (lot 1 : UTF-8, repli cp1252 ; 4 autres `open()` en UTF-8) |
| CO10 | Bloc en 404 : « Réessayer » inutile | fait (lot 1 : « serveur à relancer » ; le message d'erreur était en fait le libellé de chargement) |
| CO11 | Chargement différé sans délai maximal | fait (lot 1 : 90 s puis message et Réessayer) |
| CO12 | Interrogation toutes les 10 s sans fin, même onglet caché | fait (lot 1 : en pause onglet caché, abandon après 10 min) |
| CO13 | Accès disque bloquant dans une route asynchrone | fait (lot 1) |
| CO14 | « Tout relancer » sans confirmation | fait (lot 1 : confirmation, bouton secondaire) |
| CO15 | Nombre de runs ayant lu le holdout ignoré | fait (lot 1 : colonne « Lectures » des garde-fous) |
| CO16 | 56 `zip()` sans `strict=` | fait (lot 1 : `strict=True` pour l'alignement de données, `strict=False` explicite pour les lignes de base et l'affichage) |
| CO17 | Causes d'erreur perdues | fait (lot 1 : `from None` sur les sorties de la CLI ; `logger.exception` pour l'échec de sauvegarde ; l'autre message est sans trace voulue) |
| CO18 | 25 variables de boucle réaffectées | rien à changer : les 25 réaffectations relues sont des normalisations voulues (`token = token.strip()`…) |
| CO19 | Nettoyage (variables inutilisées, `noqa` obsolètes) | fait (lots 2-3 : 4 variables de boucle inutilisées renommées ; les `noqa` signalés en mode isolé documentent des règles volontairement non activées) |
| CO20 | Option fantôme `enable_fundamentals_features` | rien à changer : `features/equity_fundamentals.py` fait partie de l'empreinte du cache de variables et retirer le champ changerait l'empreinte des runs |
| CO21 | Copies de travail orphelines | fait (25/11 : `PATRICK-wt-lot9` et `PATRICK-wt-topbar` supprimées, branches fusionnées effacées) |
| CO22 | 9 tests sautés ou en échec attendu | rien à changer : tous les sauts dépendent de l'environnement (Windows, Node, gymnasium, git) ; le test au tirage fixe du simulateur tourne bien |
| CO23 | Synchronisation en échec la nuit du 23/11 | fait (lots 4-5 : cause = lecteur F:\ du Google Drive absent ; `sync auto` le note « Reporté » au lieu d'échouer) |
| CO24 | Protection automatique de l'aperçu | déjà fait : depuis l'incident du 10/10, le cache local écrit par fichier temporaire puis remplacement (`storage/cache_manager.save_dataframe`) : deux écritures simultanées ne laissent plus de fichier tronqué |
| CO25 | Décisions des banques centrales lues dans les titres | à faire (lot 8) |
| CO26 | Jours de changement d'échéance des contrats à terme | fait en partie (lot 6 : `patrick audit futures-rolls` repère les sauts au-delà de 5 écarts robustes près d'une échéance) ; retirer ces jours des étiquettes = décision (change tous les runs de contrats à terme) |
| CO27 | Erreurs pyright « valeur peut-être absente » | fait en partie (lots 2-3 : accès à None gardés dans les ordres limite, le transfert de mouvements et la sélection des fonds ; reste du bruit d'annotations pandas) |
| CO28 | Lecture DM de la sélection des fonds | déjà fait (`fund/selection._dm_evidence` lit la p unilatérale ; `test_a_model_significantly_worse_than_its_baseline_is_not_dm_evidence`) |
| CO29 | Verdict RL sans correction du nombre d'essais | fait (lot 1 : seuil de Šidák sur `stats.n_trials`) |
| CO30 | Dates brutes sur la fiche d'un actif | fait (lot 1 : dates relatives, date exacte au survol) |

## Fonctionnalités (FO)

| # | Proposition | Statut |
|---|---|---|
| FO1 | Ensemble de confiance de modèles (MCS) | fait (lot 6 : `validation/model_set.py`, MCS de Hansen-Lunde-Nason sur le Brier au holdout de tous les runs de la paire ; section de la fiche d'un actif, champion dans l'ensemble ou non) |
| FO2 | Test SPA / Reality Check | fait (lot 6 : SPA de Hansen contre le pile ou face, même section, p consistante) |
| FO3 | Prévision conforme | déjà fait : section « Prévision conforme » de la page d'un run (couverture par découpage et adaptative, taux d'abstention) |
| FO4 | Combinaison des modèles (stacking) | déjà fait : empilement disponible en option (`DEFAULT_STACKING_ENABLED`, ADR 0001), désactivé par défaut après mesure |
| FO5 | Méta-étiquetage | déjà fait : `validation/meta_labeling.py`, sur la page d'un run |
| FO6 | Cible à barrières triples | décision : le module `features/triple_barrier.py` existe ; en faire une cible change l'étiquette lue par une vingtaine de consommateurs (même blocage que la cible de volatilité, ADR 0011) |
| FO7 | Régime HMM comme variable | déjà fait : variable `hmm_filtered_stress_prob` (régime filtré par HMM, sans regard vers le futur) dans `features/vol_models.py` |
| FO8 | Score de robustesse d'un champion | fait (lot 6 : `validation/robustness.py`, note sur 100 en tête de la page d'un run, avec ce qui manque) |
| FO9 | Ré-entraînement automatique en cas de dérive | fait, réglage à toi (lots 4-5 : `patrick retrain auto`, dernière étape de la nuit, met en file les premiers runs conseillés dans le budget `auto_retrain_per_week` ; 0 par défaut) |
| FO10 | Rejouer la règle de sélection des fonds | déjà fait en partie : écart holdout / réel par champion sur /reel (D29) ; rejouer la sélection dans le passé contredit la règle à sens unique du pilote (une règle ne rejoue jamais le passé avec une sélection d'aujourd'hui) |
| FO11 | Mode « et si » d'un fonds | déjà fait en partie : « Aperçu » du pilote (réglages essayés sans être appliqués) ; une courbe rejouée irait contre la même règle à sens unique |
| FO12 | Historique daté des réglages d'un fonds | fait (lot 7 : migration 0060 `fund_settings_log`, chaque activation, changement et désactivation daté avec les réglages changés ; « Historique des réglages » dans le panneau) |
| FO13 | Attribution de performance | déjà fait : `fund/insight.attribution` (P&L par modèle, par classe d'actifs, par sens), panneau d'un fonds |
| FO14 | Rapport mensuel en PDF par fonds | fait (lot 7 : `fund/monthly_report.py`, « Rapport du mois (PDF) » dans le panneau : performance, attribution, ordres, positions, stress tests) |
| FO15 | Stress tests historiques | fait (lot 7 : positions ouvertes rejouées sur six crises (2000, 2008, 2011, 2018, 2020, 2022), sens et notionnel des dérivés compris ; dans le rapport et `/api/fund/strategies/{id}/stress`) |
| FO16 | Alertes de prix et de signal | à faire (lot 8) |
| FO17 | Explication en clair de chaque prédiction | à faire (lot 8) |
| FO18 | Comparaison de deux ré-entraînements | à faire (lot 8) |
| FO19 | Comparaison fonds / vraies opérations | à faire (lot 8) |
| FO20 | Import automatique des relevés | à faire (lot 8) |
| FO21 | Objectifs patrimoniaux | à faire (lot 8) |
| FO22 | Exposition aux devises du patrimoine | à faire (lot 8) |
| FO23 | Dividendes et détachements | à faire (lot 8) |
| FO24 | Volatilité implicite | à faire (lot 8) |
| FO25 | Détecteur de paires cointégrées | à faire (lot 8) |
| FO26 | Planification des lots par créneau | à faire (lot 9) |
| FO27 | Assistant de lancement par objectif | à faire (lot 9) |
| FO28 | Résumé du matin lisible sur téléphone | à faire (lot 9) |
| FO29 | Mode démo sur base synthétique | à faire (lot 9) |
| FO30 | Sauvegarde hors site chiffrée | fait, mise en place à toi (lots 4-5 : `patrick storage offsite --to <dossier>` et `offsite-restore` : instantané, zstd ou gzip, AES-256-GCM, phrase dans `PATRICK_BACKUP_PASSPHRASE`, 3 copies gardées ; dépendance facultative `[backup]`) |

## Visuel (VI)

| # | Proposition | Statut |
|---|---|---|
| VI1 | Cône de prévision | à faire (lot 10) |
| VI2 | Treemap d'un fonds | à faire (lot 10) |
| VI3 | Cascade du rendement | à faire (lot 10) |
| VI4 | Carte de corrélation des positions | à faire (lot 10) |
| VI5 | Calendrier en carte de chaleur | à faire (lot 10) |
| VI6 | Nuage risque / rendement des fonds | à faire (lot 10) |
| VI7 | Courbe ROC avec curseur de seuil | à faire (lot 10) |
| VI8 | Entonnoir de sélection des variables | à faire (lot 10) |
| VI9 | Importance des familles de variables au fil des plis | à faire (lot 10) |
| VI10 | Frise de la nuit | à faire (lot 10) |
| VI11 | Jauge du disque et des caches | à faire (lot 10) |
| VI12 | Étapes d'un run en frise | à faire (lot 10) |
| VI13 | Mur de signaux | à faire (lot 10) |
| VI14 | Carte du monde des marchés | à faire (lot 10) |
| VI15 | Mini-courbes dans les tableaux | à faire (lot 10) |
| VI16 | Pastille de fraîcheur sur chaque chiffre | à faire (lot 10) |
| VI17 | Distribution des rendements d'un actif | à faire (lot 10) |
| VI18 | Week-ends et fériés grisés | à faire (lot 10) |
| VI19 | Échelle logarithmique | à faire (lot 10) |
| VI20 | Zoom par sélection et mini-carte | à faire (lot 10) |
| VI21 | Couleur fixe par famille de modèle | à faire (lot 10) |
| VI22 | Icône de classe d'actifs | à faire (lot 10) |
| VI23 | Comparateur de runs en « diff » | à faire (lot 10) |
| VI24 | Notes libres datées sur les courbes | à faire (lot 10) |
| VI25 | Plein écran d'un graphique | à faire (lot 10) |
| VI26 | Synthèse personnalisable | à faire (lot 10) |
| VI27 | Mode dense des tableaux | à faire (lot 10) |
| VI28 | Thème haute lisibilité | à faire (lot 10) |
| VI29 | Onglet du navigateur vivant | à faire (lot 10) |
| VI30 | Écran de démarrage du lanceur | à faire (lot 10) |
