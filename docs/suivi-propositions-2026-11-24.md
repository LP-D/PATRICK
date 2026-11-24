# Suivi des 120 propositions du 2026-11-24

Liste demandée par Léon le 24/11 (30 nouvelles fonctionnalités, 30 améliorations, 30 corrections, 30 affichages), puis « implémente tout ».
Mise en œuvre par lots, une branche et une PR par lot, CI verte avant fusion. Ce fichier est la source de vérité de l'avancement.

Statuts : **fait** (fusionné, avec la PR) · **déjà fait** (existait avant la liste) · **en cours** · **à faire** · **à toi** (geste sur le PC de
Léon ou calcul long du worker, commande donnée) · **décision** (irréversible ou change les résultats historiques : à trancher par Léon).

## A. Nouvelles fonctionnalités

| # | Proposition | Statut |
|---|---|---|
| A1 | Prévision du niveau de volatilité (HAR, QLIKE) pour dimensionner les fonds | à faire |
| A2 | DCC-GARCH dans `tracking/covariance.py` | à faire |
| A3 | Variables GJR / APARCH / HAR dans le ML (option hors empreinte) | à faire |
| A4 | Variables texte (ton banques centrales / actualités) dans l'entraînement | à faire |
| A5 | Volatilité intrajournalière (Parkinson, Garman-Klass) | à faire |
| A6 | Carry trade | à faire |
| A7 | Cible alpha contre l'indice de référence | à faire |
| A8 | Valorisation d'entreprise (multiples, puis DCF) | à faire |
| A9 | Dimensionnement par bandit après frais | à faire |
| A10 | RL : A2C / SAC / DQN comparés à PPO | à faire |
| A11 | Brancher `research/phase9.py` sur les fonds | à faire |
| A12 | Ordres limite et exécutions partielles | à faire |
| A13 | Ordres manuels sur un fonds | à faire |
| A14 | Reprise d'un run au niveau du scan | à faire |
| A15 | Notifications Windows | à faire |
| A16 | Rapport hebdomadaire PDF | à faire |
| A17 | Calendrier économique superposé aux cours | à faire |
| A18 | Bai-Perron et ARFIMA exact | à faire |
| A19 | EVT pour la VaR des fonds | à faire |
| A20 | PBO sur /strategies | à faire |
| A21 | Pipeline complet sur marches aléatoires | déjà fait (`tests/pipeline/test_null_world_validity.py`, `validity.yml` hebdomadaire) |
| A22 | Ablation de Kalman (runs appariés) | à toi (runs du worker ; protocole ADR 0009) |
| A23 | Monte-Carlo sur /placements | à faire |
| A24 | Import de relevés de courtier (CSV) | à faire |
| A25 | Export Excel en un clic | à faire |
| A26 | Page vitrine d'un fonds (HTML sans données personnelles) | à faire |
| A27 | Questions en langage naturel sur un run (`llm_guard`) | à faire |
| A28 | Comparaisons limitées à un même profil | à faire |
| A29 | Test de restauration automatique de la sauvegarde | à faire |
| A30 | Parité de risque pour les fonds combinés | à faire |

## B. Améliorations

| # | Proposition | Statut |
|---|---|---|
| B1 | Suite lente partielle sur les PR | en cours (lot 1 : job `pr-pinned-golden`) |
| B2 | Régénération du fichier figé sans poste local | en cours (lot 1 : `constraints-regen.yml`) |
| B3 | Supprimer la branche après fusion (réglage GitHub) | en cours (lot 1) |
| B4 | Tests de mutation : renforcer `dsr` et `diebold_mariano` | à faire |
| B5 | Remplacer les `except Exception` larges | à faire |
| B6 | Découper `webapp/app.py` | à faire |
| B7 | Découper `pipeline/engine.py` | à faire |
| B8 | Séparer lecture / écriture dans `tracking/db.py` et `history.py` | à faire |
| B9 | Découper `patrick.css` | à faire |
| B10 | Sélection SHAP une fois par (données, pli) | à faire |
| B11 | Pools paramétriques par pli en parallèle | à faire |
| B12 | Cache des plis préparés | à faire |
| B13 | Optuna en parallèle | à faire |
| B14 | Élagage Optuna plus agressif | à faire |
| B15 | Moins de sélections CPCV distinctes | à faire |
| B16 | DM sur la log-loss | à faire |
| B17 | Seuils CPCV par combinaison | à faire |
| B18 | Contrats à terme continus ajustés des sauts d'échéance | à faire |
| B19 | `ANALYZE` automatique en fin de job | à faire |
| B20 | /fonds plus rapide | à faire |
| B21 | pytest-xdist dans la CI rapide | déjà fait (`-n auto` dans `tests.yml`) |
| B22 | Vérification des types (pyright) | à faire |
| B23 | graphify à jour | en cours (lot 1, local) |
| B24 | Mesurer le cache de téléchargement | à faire |
| B25 | Tests de mutation mensuels | en cours (lot 1 : `schedule` dans `mutation.yml`) |
| B26 | Suivi de la calibration en réel | à faire |
| B27 | Tâche de nuit sans limite de durée | à toi (réinstaller la tâche, ADR 0014) |
| B28 | Éviction du cache de variables pendant la nuit | à faire |
| B29 | Supprimer le worktree `PATRICK-wt-fonds` | en cours (lot 1, local) |
| B30 | KNOWN_ISSUES à jour | en cours (lot 1) |

## C. Corrections

| # | Proposition | Statut |
|---|---|---|
| C1 | Verrou du pilote entre processus | à faire |
| C2 | La nuit ne dépend plus de la fenêtre PATRICK | à faire |
| C3 | Rendement nul : même traitement à l'entraînement et en réel | à faire |
| C4 | Contrôle des champions suspects sur l'AUC | à faire |
| C5 | Biais du gagnant du duel | à faire |
| C6 | Choix de la meilleure classe de fonds corrigé | à faire |
| C7 | Stratégies de fonds dans `trial_registry` | à faire |
| C8 | Fuite légère des seuils CPCV | à faire |
| C9 | `config_hash` indépendant du dossier de sortie | à faire |
| C10 | Remplacer les 46 champions de change suspects | à toi (runs du worker) |
| C11 | 6E=F et DXY dans la règle d'alignement | à faire |
| C12 | Placebo des champions à F1 > 0,74 inexpliqués | à toi (runs du worker) |
| C13 | Heures des résultats Yahoo | à faire |
| C14 | Anciens runs d'avant la fuite signalés | à faire |
| C15 | `test_webapp_smoke` sous charge | à faire |
| C16 | Erreur « disk I/O » des tests lents sous charge | à faire |
| C17 | Audit des formulaires partiels | à faire |
| C18 | PR 95 (barre du haut à 320 px) | fait (PR 95, autre session, 24/11) |
| C19 | Dossier principal à jour, serve + worker relancés | à toi |
| C20 | Créer les fonds combinés | à toi (`fund combo-setup --create` après relance) |
| C21 | Réactiver PATRICK-Sync | à toi (deux PC) |
| C22 | Python ≥ 3.11 sur l'autre PC | à toi |
| C23 | Tâche NewsRefresh | à toi |
| C24 | Purge de l'ancienne fixture dans l'historique Git public | décision (réécriture d'historique, force-push) |
| C25 | Branche distante `fix/ci-pydantic-floor` | en cours (lot 1) |
| C26 | Écart holdout / réel sur le change | à faire |
| C27 | Seuil de jour plat en multiple de la volatilité | à faire |
| C28 | `except Exception: pass` de `text/fulltext.py` journalisés | à faire |
| C29 | `method_version` par défaut | à faire |
| C30 | Lecture de `dm_result.p_value` (bilatérale) | à faire |

## D. Affichage

| # | Proposition | Statut |
|---|---|---|
| D1 | Page d'un run en une seule page | à faire |
| D2 | Fiabilité à côté de P(hausse) | à faire |
| D3 | Annotations (lignes verticales) sur les graphiques | à faire |
| D4 | Curseur synchronisé entre graphiques | à faire |
| D5 | Petits multiples par classe d'actifs | à faire |
| D6 | Holdout et réel côte à côte | à faire |
| D7 | Badge « biais du gagnant » | à faire |
| D8 | Volatilité séparée des directions | à faire |
| D9 | Diagramme de fiabilité | à faire |
| D10 | Carte de chaleur cible × horizon | à faire |
| D11 | P&L avant / après frais superposés | à faire |
| D12 | Drawdown sous chaque fonds | à faire |
| D13 | Navigation réduite | à faire |
| D14 | Contrastes clair / sombre (WCAG AA) | à faire |
| D15 | Tableaux larges en cartes sous 640 px | à faire |
| D16 | Colonnes et en-têtes figés | à faire |
| D17 | Blocs de chargement | à faire |
| D18 | Dates relatives | à faire |
| D19 | Flèches ▲▼ en plus des couleurs | à faire |
| D20 | Accueil : 3 chiffres clés | à faire |
| D21 | État de la nuit dans la barre du haut | à faire |
| D22 | Deux fonds sur un même graphique | à faire |
| D23 | Export PNG / CSV des graphiques | à faire |
| D24 | Panneau des raccourcis clavier | à faire |
| D25 | Survol des métriques relié au dictionnaire | à faire |
| D26 | Frise des champions | à faire |
| D27 | File d'attente en frise | à faire |
| D28 | Page « Nuit » | à faire |
| D29 | Écart réel / holdout par champion | à faire |
| D30 | Mise en page pour l'impression | à faire |
