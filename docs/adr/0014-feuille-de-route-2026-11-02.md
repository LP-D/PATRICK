# ADR 0014 — Feuille de route du 2026-11-02 : duel sur l'AUC, placebo toutes classes, déflation par classes, dimensionnement proportionnel, retraits, sauvegardes

Date : 2026-11-02. Statut : appliqué aux nouveaux runs et aux nouvelles règles ; rien n'est réécrit.

## Contexte

Douze chantiers proposés après lecture des ADR 0007 à 0013, du triage du 28/10 et de l'état du dépôt. Cet ADR dit ce qui est fait, ce qui a été mesuré avant de décider de ne pas faire,
et pourquoi. Mesures sur la base locale (64,8 Gio, 3 173 runs terminés, lecture seule).

## Décisions

1. **Le duel champion/challenger suit le critère du run** (`pipeline/champion_duel.py`). `AUC_dir` quand le run le classe ainsi (défaut des runs neufs, ADR 0013) et que les deux côtés
   l'ont ; `F1_dir` pour un run enregistré avant le champ ou quand un côté n'a pas d'AUC. Le duel enregistre le critère et les deux scores. Le duel reste une sélection sur le holdout
   (ADR 0005) : seul le critère est aligné, pas la rigueur.
2. **Placebo sur toutes les classes d'actifs** (`audit_placebo.py`). Mesure : 113 runs sur 3 173 ont un placebo, aucun pour les indices de volatilité, aucun à horizon court (<= 3 j) pour
   l'Asie, les futures, les Amériques hors États-Unis et la crypto, un seul pour le change. Nouveaux panels (`fx`, `futures`, `us`, `europe`, `americas`, `crypto`, `volatility`,
   `every_class`), `patrick audit placebo-report --coverage`. 37 runs légers mis en file (sans worker : ils attendent le prochain passage de nuit).
3. **Cible de volatilité : non branchée, mesurée** (`docs/modelisation/cible-volatilite-faisabilite-2026-11-02.md`). AUC de la direction de σ : 0,77 (h = 5) et 0,73 (h = 20), contre 0,51 pour
   la direction du prix, mais le simple retour à la moyenne en donne 0,771 et 0,731 : le modèle HAR n'ajoute que +0,007 et +0,003. Une telle cible mettrait des AUC de 0,75 dans des tableaux
   qui lisent 0,52 comme un signal. Si l'objectif est le dimensionnement, la bonne cible est le NIVEAU de σ (HAR-RV, QLIKE), à brancher sur la taille à volatilité inverse du fonds.
4. **Tests de validité du DM et du DSR.** Monde à pertes égales par construction (`tests/test_dm_equal_loss_world.py`) : le DM bilatéral rejette 4,3 à 5,8 % du temps à h <= 5, ~8 % à
   15 blocs (h = 30), ce que dit déjà le seuil de 15 blocs. Le « 3 mondes sur 12 à p < 5 % » de l'audit du 20/10 (toujours du côté « le modèle fait pire ») ne vient donc pas d'un test mal
   dimensionné à h = 5 : un modèle choisi sur du bruit coûte de la variance face à sa baseline (lecture (a) de `KNOWN_ISSUES.md`). Valeurs exactes ajoutées pour `diebold_mariano`
   (poids de Bartlett, signe, arrondis, frontières 9/10 lignes, écart constant) et `dsr` (formule du papier recalculée, annualisation, un essai, 19/20 observations, erreur-type, maximum espéré).
   Les tests de mutation tournent sur GitHub (Linux) : le nouveau taux de mutants tués n'est pas mesuré ici.
5. **Plancher de déflation par classes comparées** (`fund/kpis.py::deflation_trials`). Le Sharpe déflaté d'une stratégie compte au moins autant d'essais que de classes d'actifs classées par la Synthèse
   (signal regroupé) : choisir la meilleure classe est un essai par classe comparée, même si une seule a donné une stratégie. Un plancher (`max`), pas un produit : les modèles retenus sont déjà
   comptés dans `trial_registry`.
6. **Fonds : dimensionnement proportionnel au score** (`fund/systematic.py`, `scale_by_score`). La taille configurée devient un maximum, atteint à `saturation` (0,75 par défaut) ; en dessous,
   fraction `|P − 0,5| / (saturation − 0,5)`, jamais moins que `floor` (0,25). Réservé aux règles à seuils tenues au signal (les seules dont chaque ouverture porte son score). Pas dans le
   formulaire : configuration de règle (API). `apply` quotidien : déjà fait (`live_refresh.run_autopilots`, après les prédictions). **Carry trade : non fait**, il exige une courbe de futures et une
   règle de roll explicite qui n'existent pas (`docs/modelisation/chantiers-lointains.md` §3).
7. **RL : 3 graines par défaut** (au lieu d'une), x3 de coût par pli. L'avertissement « indice non négociable » existait déjà (`rl/data.py::untradable_warning`). Le bandit contextuel sur `p_up`
   (`chantiers-lointains.md` §1) n'est pas fait : il demande un banc de rejeu sur les prédictions de holdout et un critère d'entrée (battre Kelly/seuil après coûts).
8. **Synchronisation entre PC** : listes de suivi (par nom) et carnet de recherche (union dédoublonnée) fusionnés (`sync_merge`). Le journal de prédictions n'est pas fusionné : une chaîne
   unique d'empreintes ne survit pas à l'union de deux chaînes (conception dans `docs/ops/partage-entre-pc.md`).
9. **Retrait des catégories de modèles** (`pipeline/model_categories_training.py`, `tracking/model_categories.py`, 2 fichiers de tests, 3 termes de glossaire) : jamais branchées, remplacées par
   l'algorithme Stacking et l'axe des régimes. `features/triple_barrier.py` est conservée non branchée (même coût d'intégration que la cible de volatilité).
10. **Reprise au niveau du scan : non faite, mesurée.** 22 runs « orphelins » et 56 arrêtés par l'utilisateur sur 3 251 (2,4 %), aucun job repris à ce jour : au plus quelques heures de scan
    perdues sur ~410 h de calcul. Un cache de résultats de fit par (données, réglages, graine) ne se justifie pas à ce niveau.
11. **Optuna en parallèle : non fait, mesuré.** Parts du temps de calcul : scan 39 %, diagnostic holdout 23 %, construction des variables 16 %, réglage 13 %. Le réglage est en voie d'extinction :
    513 runs réglés avant le 28/10, 6 depuis. Le scan (142 s en moyenne depuis le 28/10 contre 202 s avant) est le seul poste où un gain pèse ; le mesurer proprement demande une machine au repos.
12. **Sauvegardes** (`tracking/backup.py`). Incident du 02/11 : la tâche `PATRICK-SauvegardeBase` a une limite d'exécution d'une heure (`PT1H`) ; la copie de la base (64,8 Gio) a été tuée à 89,4 %
    (09:19:09, une heure après 08:19:10), laissant 62 Gio de `.part` (et 32 Gio la veille), des restes qui ne partaient qu'à la fin d'une copie réussie, et un journal de 10 millions de lignes (766 Mo).
    Corrigé : restes périmés supprimés AVANT chaque copie, refus d'une copie qui ne tiendrait pas sur le disque (marge 1 Gio), progression journalisée par paliers de 5 %, installateur avec
    `-ExecutionTimeLimit` sans limite. **À faire sur le PC** : la tâche déjà installée garde sa limite (voir « Conséquences »). Cause de fond : `vol_model_cache` pèse ~61 Gio sur 64,8 (1,02 M de lignes
    d'environ 60 Ko d'après un échantillon de 20 000 lignes ; la mesure par table sur toute la base n'a pas abouti dans le délai) : c'est un cache reconstructible qui multiplie par 15 le poids de chaque sauvegarde.

## Non fait

Carry trade (pas de courbe de futures) ; bandit contextuel du RL ; fusion du journal de prédictions ; cible de volatilité (décision de concevoir le niveau de σ à part) ; reprise du scan ; Optuna parallèle ;
mesure des mutants après les nouveaux tests ; sauvegarde sans le cache de la base.

## Conséquences

- Les runs neufs jugent leur duel sur l'AUC : un champion de F1 peut céder son titre à un meilleur AUC. `dm_result`, `holdout_diagnostic` et `champion.holdout_f1_dir` gardent le F1.
- Les 37 runs placebo apparaîtront dans la file ; `patrick audit placebo-report --coverage` dit ensuite quelles classes restent à auditer.
- La tâche Windows installée doit être corrigée une fois : `Set-ScheduledTask -TaskName PATRICK-SauvegardeBase -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero))`
  (ou relancer `app\Installer.ps1`). Tant qu'elle ne l'est pas, la copie de 65 Gio est tuée à l'heure.
- Pour alléger la base : `patrick storage evict --db-days N --dry-run` compte, sans rien supprimer, les entrées de cache de la base plus vieilles que N jours ; à lancer worker arrêté, puis `patrick storage vacuum` (demande ~65 Gio libres).
