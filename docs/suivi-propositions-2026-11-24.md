# Suivi des 120 propositions du 2026-11-24

Liste demandée par Léon le 24/11 (30 nouvelles fonctionnalités, 30 améliorations, 30 corrections, 30 affichages), puis « implémente tout ».
Mise en œuvre par lots, une branche et une PR par lot, CI verte avant fusion. Ce fichier est la source de vérité de l'avancement.

Statuts : **fait** (fusionné, avec la PR) · **déjà fait** (existait avant la liste) · **en cours** · **à faire** · **à toi** (geste sur le PC de
Léon ou calcul long du worker, commande donnée) · **décision** (irréversible ou change les résultats historiques : à trancher par Léon).

## A. Nouvelles fonctionnalités

| # | Proposition | Statut |
|---|---|---|
| A1 | Prévision du niveau de volatilité (HAR, QLIKE) pour dimensionner les fonds | fait (lot 7 : `fund/vol_forecast.py`, HAR-RV jugé en QLIKE ; pilote `vol_model = har` ; S&P 500 réel : gain QLIKE +29,7 %) |
| A2 | DCC-GARCH dans `tracking/covariance.py` | fait (lot 7b : estimateur `dcc` dans `tracking/covariance.py`, DCC(1,1) sur résidus GARCH, 750 séances) |
| A3 | Variables GJR / APARCH / HAR dans le ML (option hors empreinte) | fait (lot 7b : `features/vol_models_extra.py`, modèles `gjr`, `aparch` et `har` estimés sur le train de chaque pli ; module à part pour ne pas toucher l'empreinte du cache de variables ; proposés dans le formulaire, hors des défauts : aucune empreinte de run ne change) |
| A4 | Variables texte (ton banques centrales / actualités) dans l'entraînement | fait (lot 7b : `features/text_features.py`, drapeau `enable_text_features` : sentiment des nouvelles de la cible et ton des banques centrales, point-in-time ; refusé tant que la porte des 250 séances n'est pas franchie ; hors du hachage et de la clé du cache tant qu'il est faux ; apport à mesurer) |
| A5 | Volatilité intrajournalière (Parkinson, Garman-Klass) | fait (lot 7 : variance de Garman-Klass ramenée à l'échelle clôture à clôture, dans la prévision HAR) |
| A6 | Carry trade | déjà fait (ADR 0015 : carry de change mesuré sur 7 devises 2000-2025, Sharpe 0,17-0,18, Sharpe déflaté 0,64 ; non adopté, à rouvrir sur un fait nouveau) |
| A7 | Cible alpha contre l'indice de référence | déjà fait (`features/alpha_target.py`, cibles `target_kind = alpha` contre un indice de référence) |
| A8 | Valorisation d'entreprise (multiples, puis DCF) | fait (lot 7b : `analysis/valuation.py`, section « Valorisation » de la fiche des actions : multiples, DCF inversé, DCF à hypothèse choisie et table de sensibilité ; taux sans risque de la devise ; données Yahoo du jour, jamais en entraînement) |
| A9 | Dimensionnement par bandit après frais | déjà fait (ADR 0015 : bandit LinUCB et Kelly ridge mesurés après frais sur 459 champions ; moins bons que le seuil fixe, non adoptés) |
| A10 | RL : A2C / SAC / DQN comparés à PPO | à toi (le moteur RL propose déjà PPO, A2C, DQN et SAC sur /rl ; la comparaison demande des runs du worker, puis la vue de comparaison RL) |
| A11 | Brancher `research/phase9.py` sur les fonds | fait en partie (lot 7b : `fund/regime.py`, régime de marché de phase9 (VIX, S&P 500) affiché sur /fonds avec ses déclencheurs ; pas de modulation de l'exposition, non mesurée) |
| A12 | Ordres limite et exécutions partielles | fait (lot 7c : `fund/limit_orders.py`, migration 0059 : ordres limite à validité, exécutés sur les séances suivantes au prix de la limite ou de l'ouverture, tranches d'au plus 10 % du volume ; résolus chaque nuit avant les cycles ; champ « Prix limite » du ticket, liste et annulation dans le panneau) |
| A13 | Ordres manuels sur un fonds | déjà fait (saisie d'un ordre ou d'une position à la main : « Nouvelle position », `/api/fund/strategies/{id}/orders`) ; « 0 ordre manuel » était un constat d'usage |
| A14 | Reprise d'un run au niveau du scan | fait (lot 7c : `pipeline/scan_checkpoint.py`, chaque ajustement du scan est écrit (clé : identité du lancement + contenu exact du pli) et relu par une reprise ; le worker reprend sur la configuration enregistrée du lancement interrompu ; golden local identique ; reprise testée : zéro ajustement refait, classement identique) |
| A15 | Notifications Windows | fait (lot 7 : notification Windows de fin de nuit s'il y a quelque chose à signaler, préférence `notify_night`) |
| A16 | Rapport hebdomadaire PDF | fait (lot 7b : `core/text_pdf.py`, PDF sans dépendance ; lien PDF à côté de chaque rapport sur /sante) |
| A17 | Calendrier économique superposé aux cours | fait (lot 7b : `data/econ_calendar.py`, migration 0058 : dates FRED d'IPC, emploi, PIB, PCE, ventes (passées et à venir) rafraîchies avec les nouvelles ; décisions Fed/BCE/BoE/BoC lues dans les titres des communiqués ; repères sur la courbe de chaque actif, agenda sur /news) |
| A18 | Bai-Perron et ARFIMA exact | fait en partie (lot 7 : Bai-Perron et d de Whittle local dans l'étude « racine unitaire ») ; ARFIMA exact par maximum de vraisemblance non fait |
| A19 | EVT pour la VaR des fonds | fait (lot 7 : VaR et ES à 99 % par loi de Pareto généralisée, panneau d'un fonds) |
| A20 | PBO sur /strategies | fait (lot 7 : PBO de la grille de réglages du laboratoire) |
| A21 | Pipeline complet sur marches aléatoires | déjà fait (`tests/pipeline/test_null_world_validity.py`, `validity.yml` hebdomadaire) |
| A22 | Ablation de Kalman (runs appariés) | à toi (runs du worker ; protocole ADR 0009) |
| A23 | Monte-Carlo sur /placements | déjà fait (`placements/projection.py` : milliers de trajectoires par bootstrap par blocs, quantiles et distribution) |
| A24 | Import de relevés de courtier (CSV) | déjà fait (`wealth/importer.py` : import CSV tolérant des relevés de courtier, glisser-déposer sur /patrimoine et /mouvements) |
| A25 | Export Excel en un clic | fait (lot 7 : `/api/export/patrick.xlsx`, liens sur /predictions et /fonds) |
| A26 | Page vitrine d'un fonds (HTML sans données personnelles) | fait (lot 7 : page vitrine HTML autonome, pourcentages seulement) |
| A27 | Questions en langage naturel sur un run (`llm_guard`) | fait (lot 7b : `analysis/run_qa.py`, carte « Questions sur ce run » : Claude Opus 5.5 répond depuis les seuls chiffres du run, avertissement de fuite par `llm_guard` (part des dates évaluées après sa limite de connaissance) ; extra `llm`, SDK installé dans le .venv ; clé API à fournir par Léon) |
| A28 | Comparaisons limitées à un même profil | fait (lot 7 : l'onglet « Comparer » restreint la liste à la cible ; la comparaison signalait déjà des profils différents) |
| A29 | Test de restauration automatique de la sauvegarde | fait (lot 7 : `patrick storage verify-backup`, étape de nuit ; vraie sauvegarde du 24/11 restaurable, 116 s) |
| A30 | Parité de risque pour les fonds combinés | fait (lot 7 : `fund/risk_parity.py`, pilote `weighting = risk_parity`) |

## B. Améliorations

| # | Proposition | Statut |
|---|---|---|
| B1 | Suite lente partielle sur les PR | fait (PR 97 : job `pr-pinned-golden`, 8 min 44 sur sa propre PR) |
| B2 | Régénération du fichier figé sans poste local | fait (PR 97 : `constraints-regen.yml`) |
| B3 | Supprimer la branche après fusion (réglage GitHub) | fait (réglage du dépôt activé le 24/11 ; vérifié : la branche du lot 1 a disparu seule après fusion) |
| B4 | Tests de mutation : renforcer `dsr` et `diebold_mariano` | fait en partie (lot 3 : `tests/validation/test_dsr_dm_reference.py`, valeurs exactes contre une réimplémentation indépendante) ; taux de mutants tués à remesurer au prochain passage mensuel de `mutation.yml` |
| B5 | Remplacer les `except Exception` larges | fait (lot 2 : les 21 replis silencieux journalisés ; les 113 autres laissaient déjà une trace) |
| B6 | Découper `webapp/app.py` | fait en partie (lot 9 : fragments de la fiche d'un actif sortis vers `webapp/routes/assets.py`, app.py 3 064 -> 2 975 lignes ; le reste à découper par blocs de routes, même méthode) |
| B7 | Découper `pipeline/engine.py` | fait en partie (lot 9 : identité d'un run (`_config_hash`, `_features_payload`) sortie vers `pipeline/identity.py`, réexportée ; golden local identique) |
| B8 | Séparer lecture / écriture dans `tracking/db.py` et `history.py` | fait en partie (lot 9 : lectures groupées des runs sorties vers `tracking/run_queries.py`, lecture seule, réexportées ; db.py 1 687 -> 1 330 lignes) |
| B9 | Découper `patrick.css` | fait (lot 9 : `patrick.css` (socle : jetons, base, coque, composants) et `patrick-pages.css` (styles des pages), chargées dans le même ordre ; rendu vérifié) |
| B10 | Sélection SHAP une fois par (données, pli) | fait (lot 4 : `shap_order`, un seul pilote SHAP pour toute la grille de N, sélections identiques ; méthode shap seulement) |
| B11 | Pools paramétriques par pli en parallèle | déjà fait (`features/parametric_parallel.py`, `PATRICK_PARAMETRIC_JOBS`, réglage de la page « Lancer ») |
| B12 | Cache des plis préparés | écarté : gain direct mesuré faible (NEXT_STEPS, Sprint 2) |
| B13 | Optuna en parallèle | écarté : des essais Optuna en parallèle ne sont plus reproductibles (golden), et le réglage pèse de moins en moins (ADR 0014) |
| B14 | Élagage Optuna plus agressif | à décider : changerait les champions (méthodologique, NEXT_STEPS « ne pas mélanger ») ; 39 essais sur 80 déjà élagués |
| B15 | Moins de sélections CPCV distinctes | à décider : changerait les résultats CPCV (méthodologique) |
| B16 | DM sur la log-loss | fait (lot 3 : `dm_logloss`, migration 0057 `dm_logloss_result`) |
| B17 | Seuils CPCV par combinaison | fait (lot 3, avec C8) |
| B18 | Contrats à terme continus ajustés des sauts d'échéance | écarté : bloqué par les données. Un ajustement des sauts d'échéance exige les contrats individuels, échus compris ; Yahoo n'en sert aucun historique (vérifié le 25/11 : CLZ25, ESZ25, ESH26, GCG26 vides). Prérequis inchangé : `docs/modelisation/chantiers-lointains.md` §3 ; l'avis « contrat continu non ajusté » reste affiché |
| B19 | `ANALYZE` automatique en fin de job | fait (lot 4 : `PRAGMA optimize` borné en fin de job ; `ensure_planner_stats` faisait déjà le premier ANALYZE) |
| B20 | /fonds plus rapide | fait (lot 9 : aperçu de /fonds de 40-48 s à 12,7 s sur une copie des vraies données, dont ~4 s d'import de scipy payé une fois : cotations lues depuis l'ouverture moins 60 jours au lieu de 2000, une lecture par symbole par calcul d'ensemble, dates lues avec leur format, test scalaire dans la boucle de simulation ; résultats identiques vérifiés) |
| B21 | pytest-xdist dans la CI rapide | déjà fait (`-n auto` dans `tests.yml`) |
| B22 | Vérification des types (pyright) | fait (lot 9 : `patrick/pyrightconfig.json`, cliquet sur les 248 fichiers déjà sans erreur en mode standard (sur 474 ; 2 658 erreurs ailleurs), tâche « types » de la CI hors conditions de `stable`, test qui vérifie que les fichiers listés existent) |
| B23 | graphify à jour | en cours (lot 1, local) |
| B24 | Mesurer le cache de téléchargement | fait (lot 4 : mesuré sur 20 journaux de worker, 93 % en cache, 6 % téléchargés, 0,82 h en tout : pas un goulot) |
| B25 | Tests de mutation mensuels | fait (PR 97 : 1er du mois, 06:00 UTC) |
| B26 | Suivi de la calibration en réel | fait (lot 3 calcul, lot 6 bandeau) |
| B27 | Tâche de nuit sans limite de durée | à toi (réinstaller la tâche, ADR 0014) |
| B28 | Éviction du cache de variables pendant la nuit | déjà fait (`daily_predict` évince le cache de variables à chaque exécution et dès que le disque passe sous le seuil) |
| B29 | Supprimer le worktree `PATRICK-wt-fonds` | fait (24/11) |
| B30 | KNOWN_ISSUES à jour | fait (PR 97) |

## C. Corrections

| # | Proposition | Statut |
|---|---|---|
| C1 | Verrou du pilote entre processus | fait (lot 2 : `system/interprocess_lock.py`, verrou de plage d'octets libéré si le processus meurt, `CycleBusy` après 1 h) |
| C2 | La nuit ne dépend plus de la fenêtre PATRICK | fait en partie (lot 2) : cause du 21/11 non établie (code 1 sans trace : arrêt de l'extérieur) ; la nuit journalise désormais fin et plantages (faulthandler), relance une fois la phase des fonds si son marqueur manque, et la fermeture de la fenêtre ne lance plus de publication concurrente |
| C3 | Rendement nul : même traitement à l'entraînement et en réel | fait (lot 3 : `validation.drop_stale_returns`, vrai pour un run neuf, hors empreinte quand faux ; l'évaluation ne compte plus un cours figé que le réel ne juge pas) |
| C4 | Contrôle des champions suspects sur l'AUC | fait (lot 2 : même règle `suspect_reason` des deux côtés, AUC de direction ajoutée) |
| C5 | Biais du gagnant du duel | fait (lot 3 calcul, lot 6 bandeau) |
| C6 | Choix de la meilleure classe de fonds corrigé | déjà fait (ADR 0014 : le Sharpe déflaté d'une stratégie compte au moins les classes comparées par la Synthèse, `fund/kpis.deflation_trials`) |
| C7 | Stratégies de fonds dans `trial_registry` | déjà fait (ADR 0010 : modèles retenus inscrits au registre `fund_selection:<stratégie>` ; stratégies comptées dans la déflation) |
| C8 | Fuite légère des seuils CPCV | fait (lot 3 : `validation.cpcv_thresholds_per_combo`, seuils et régimes ajustés sur l'entraînement de chaque combinaison) |
| C9 | `config_hash` indépendant du dossier de sortie | vérifié, rien à changer : `patrick resume` relit la config enregistrée (même dossier, même empreinte) et le dossier par défaut `runs` est commun à tous les runs ; retirer le dossier de l'empreinte changerait celle de TOUS les runs existants (reprises, golden) |
| C10 | Remplacer les 46 champions de change suspects | à toi (runs du worker) |
| C11 | 6E=F et DXY dans la règle d'alignement | vérifié, rien à changer : l'ADR 0007 dit que 6E=F et le DXY ont un vrai cours de clôture, donc pas concernés par la règle 2 (mauvaise lecture de ma part) |
| C12 | Placebo des champions à F1 > 0,74 inexpliqués | à toi (runs du worker) |
| C13 | Heures des résultats Yahoo | déjà fait (`earnings/exchanges.classify_timing` reconvertit depuis New York, `earnings/schedule.py` repère le 11:00 provisoire) |
| C14 | Anciens runs d'avant la fuite signalés | fait (lot 6 : bandeau « avant le garde anti-fuite » sur la page d'un run, sans exclusion) |
| C15 | `test_webapp_smoke` sous charge | fait (lot 2 : xfail avec la mesure si les processeurs étaient saturés, échec sinon) |
| C16 | Erreur « disk I/O » des tests lents sous charge | non reproduit : aucun nom de test dans la note du 31/10 ; à reprendre à la prochaine occurrence |
| C17 | Audit des formulaires partiels | vérifié, rien à changer : préférences, réglages des placements, correction d'ordre et renommage fusionnent déjà ; seul le pilote avait le défaut (corrigé le 29/10 par `overlay`) |
| C18 | PR 95 (barre du haut à 320 px) | fait (PR 95, autre session, 24/11) |
| C19 | Dossier principal à jour, serve + worker relancés | à toi |
| C20 | Créer les fonds combinés | à toi (`fund combo-setup --create` après relance) |
| C21 | Réactiver PATRICK-Sync | à toi (deux PC) |
| C22 | Python ≥ 3.11 sur l'autre PC | à toi |
| C23 | Tâche NewsRefresh | à toi |
| C24 | Purge de l'ancienne fixture dans l'historique Git public | décision (réécriture d'historique, force-push) |
| C25 | Branche distante `fix/ci-pydantic-floor` | fait (24/11) |
| C26 | Écart holdout / réel sur le change | fait (lot 3 : `patrick audit fx-gap`) ; 24/11 : règle 1 = 72,0 % holdout contre 55,0 % réel (11 runs, déjà marqués suspects) ; règle 2 à relancer quand ses runs auront 20 jugements réels |
| C27 | Seuil de jour plat en multiple de la volatilité | déjà fait (méthode 2, ADR 0008 : jour plat si |r| < 0,25 × volatilité × racine(h)) |
| C28 | `except Exception: pass` de `text/fulltext.py` journalisés | fait (lot 2) |
| C29 | `method_version` par défaut | fait (lot 2) : vrai défaut, tout run neuf était forcé à la méthode 2, la méthode 3 de l'ADR 0011 était inatteignable |
| C30 | Lecture de `dm_result.p_value` (bilatérale) | fait (lot 2) : vrai défaut, la sélection des fonds lisait la p bilatérale (un modèle nettement PIRE passait le niveau `dm`) et acceptait un test du dernier pli ; corrigé aussi dans la liste des modèles proposés |

## D. Affichage

| # | Proposition | Statut |
|---|---|---|
| D1 | Page d'un run en une seule page | en partie : l'onglet Analyse rassemble déjà les 18 sections d'un run sur une page avec sommaire ; fusionner l'onglet Détail (contrôles, journal) reste à décider |
| D2 | Fiabilité à côté de P(hausse) | fait (lot 6 : Brier skill au holdout dans la bulle d'une prédiction) |
| D3 | Annotations (lignes verticales) sur les graphiques | fait (lot 6 : changements de champion et publications de résultats sur la courbe de la page d'un actif) |
| D4 | Curseur synchronisé entre graphiques | fait en partie (lot 6 : courbe d'un fonds et sa perte depuis le plus haut partagent leur réticule) |
| D5 | Petits multiples par classe d'actifs | déjà fait de fait (pages de classes d'actifs : un panneau avec graphique par actif) |
| D6 | Holdout et réel côte à côte | déjà fait (tableau test / holdout / réel côte à côte de l'aperçu d'un run, section holdout_live) |
| D7 | Badge « biais du gagnant » | fait (lot 6 : bandeau du biais du gagnant) |
| D8 | Volatilité séparée des directions | fait (lot 7 : section « Volatilité prévue : une taille de position, pas une direction » à part des signaux) |
| D9 | Diagramme de fiabilité | déjà fait (section « calibration » de l'analyse d'un run) |
| D10 | Carte de chaleur cible × horizon | fait (lot 6 : carte de chaleur cible × horizon de l'AUC regroupée sur la Synthèse) |
| D11 | P&L avant / après frais superposés | déjà fait (graphique d'un fonds : valeur nette et valeur avant frais en pointillés) |
| D12 | Drawdown sous chaque fonds | fait (lot 6) |
| D13 | Navigation réduite | déjà fait (barre latérale en dossiers repliables, 22/11) |
| D14 | Contrastes clair / sombre (WCAG AA) | fait (lot 6 : contraste AA vérifié, pire cas 4,65 et 5,03, test de non-régression) |
| D15 | Tableaux larges en cartes sous 640 px | écarté pour l'instant : les tableaux larges défilent horizontalement dans `.table-scroll` (reflow WCAG respecté à 320 px) ; les transformer en cartes changerait toutes les pages |
| D16 | Colonnes et en-têtes figés | déjà fait (`.table-scroll th` collant) |
| D17 | Blocs de chargement | déjà fait (`lazy_block` affiche des lignes squelettes) |
| D18 | Dates relatives | fait (lot 6 : listes de runs) |
| D19 | Flèches ▲▼ en plus des couleurs | déjà fait (flèches ▲▼ des prédictions et du bandeau, signes des montants) |
| D20 | Accueil : 3 chiffres clés | déjà fait (chiffres clés en tête de la Synthèse) |
| D21 | État de la nuit dans la barre du haut | fait (lot 6 : puce « nuit » visible seulement en cas de problème) ; sur ton vrai journal : nuit du 23/11 partielle, synchronisation en échec |
| D22 | Deux fonds sur un même graphique | fait (lot 6 : « Comparer avec », base 100) |
| D23 | Export PNG / CSV des graphiques | fait (lot 6 : PNG et CSV sur chaque graphique du moteur commun ; l'analyse d'un run avait déjà son PNG) |
| D24 | Panneau des raccourcis clavier | déjà fait (touche « ? ») |
| D25 | Survol des métriques relié au dictionnaire | déjà fait (glossaire au survol, `glossary.js`) |
| D26 | Frise des champions | fait (lot 6) |
| D27 | File d'attente en frise | fait (lot 6) |
| D28 | Page « Nuit » | fait (lot 6 : section « Dernière nuit » de la page Santé) |
| D29 | Écart réel / holdout par champion | fait (lot 6 : section de /reel) |
| D30 | Mise en page pour l'impression | fait (lot 6) |
