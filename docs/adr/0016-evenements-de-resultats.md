# ADR 0016 — Événements de résultats : de la newsletter à une bibliothèque d'études, avec des données gratuites seulement

Date : 2026-11-03. Statut : appliquée (page `/resultats`, paquet `patrick/earnings/`, commande `patrick earnings`). Cadrage d'origine : fonctionnalité « Événements de résultats » (9 sections), implémentée d'un bloc à la demande de l'utilisateur, avec la contrainte « que de la donnée gratuite ».

## Contexte

PATRICK est une plateforme d'exploration : toute étude est une brique activable et paramétrable, seules les contraintes techniques dures bloquent. L'utilisateur colle chaque semaine une newsletter de résultats (« Lundi : Palantir, Arm… »). Il faut en tirer des événements datés, mesurer l'historique des réactions de chaque titre, et ranger plusieurs dizaines d'études quantitatives derrière une interface qui dit toujours **N, fiabilité et verdict corrigé des comparaisons multiples**.

## Décisions

1. **Paquet isolé, tables isolées.** `patrick/earnings/` ne touche ni `RunConfig`, ni le pipeline, ni `db.migrate()` (course connue sur `schema_version`). Les tables `earn_*` sont créées par `store.ensure_schema` (`CREATE TABLE IF NOT EXISTS`, modèle de `tracking/cache_tables.py`), sans clé étrangère vers les runs. Elles ne sont **pas** dans la fusion entre PC (`sync_merge`) : à décider avec l'utilisateur si un second PC doit les voir.
2. **Calculé une fois, lu depuis le cache.** Les mesures par événement (`earn_result`) sont clées par un hash des seuls réglages qui changent le calcul (modèle de rendement, fenêtre d'estimation, exclusion) ; les fenêtres de cumul, le test et la winsorisation se relisent des trajectoires stockées (`[-10, +60]` séances) sans recalcul. Chaque carte d'étude est cachée sous (étude, périmètre, paramètres + réglages, version des données) ; la version change dès qu'un événement est recalculé (horodatage à la milliseconde).
3. **J0 = jour de réaction, pas jour d'annonce.** Avant l'ouverture (BMO) : le jour même ; après la clôture (AMC) : la séance suivante ; un jour sans séance (samedi, Berkshire) : le lundi ; heure inconnue ou pendant la séance : le jour même avec fenêtre `[0, +1]` et drapeau « timing incertain ». Priorité des sources du timing : l'utilisateur (jamais écrasé par un rafraîchissement), puis l'heure Yahoo **reconvertie**, puis l'heuristique de la place (Europe = BMO, Japon = AMC, États-Unis = inconnu), toujours marquée incertaine. Un diagnostic de prix (le plus gros mouvement est-il sur l'autre jour ?) est affiché mais **jamais** utilisé pour choisir J0 : ce serait choisir la réaction qui arrange.
4. **Résolution nom → ligne : jamais silencieuse.** Alias persistants (confirmés par l'utilisateur), alias semés pour les cas ambigus connus (Arm, Block→XYZ, Figma, AMC, Leonardo, Diageo, SharkNinja, Novo, Ryanair, Air France-KLM, Interparfums), puis recherche Yahoo, puis **écran de confirmation éditable avant tout calcul**. Ligne locale par défaut ; ADR détecté (place américaine ET pays émetteur étranger) en contrôle. Le nom que Yahoo associe au symbole retenu est comparé au nom collé (`name_matches`, strict : « Block » n'est pas « Blackrock », « Arm » n'est pas « Armstrong »).
5. **Rendements simples, cours ajustés.** Modèle de marché (défaut), ajusté du marché, à facteurs (bibliothèque de Kenneth French : US, Europe, Japon ; publiée avec 1 à 2 mois de retard, repli signalé sur le marché pour les annonces récentes) et sectoriel (ETF SPDR ou panier de pairs). Estimation `[-250, -30]` en excluant ±2 séances autour des autres annonces du titre. La variance d'un CAR sur n'importe quelle fenêtre se recalcule sans refaire l'estimation (`xtx_inv`, `x_path`, `sigma` stockés).
6. **Tests de significativité** (`signif.py`) : BMP (défaut), Patell, Kolari-Pynnönen, Corrado (rangs, étendu aux fenêtres multi-jours), signes généralisé, bootstrap par blocs de semaines ; test « bouge-t-il plus que d'habitude » sans le sens. La carte **placebo** calibre la taille réelle de chaque test sur des dates aléatoires, **sur la fenêtre de ton choix**.
7. **Registre FDR global.** Les p-values de toutes les cartes calculées (toutes variantes de paramètres comprises : explorer plus de réglages augmente le nombre de tests à corriger, il ne le réduit pas) passent par Benjamini-Hochberg (`validation/fdr.py`). C'est ce tableau, pas le p brut d'une carte, qui dit ce qui survit.
8. **54 cartes en 14 thèmes** : cœur (CAAR, BHAR), A anatomie, B volatilité, C liquidité, D surprise/PEAD, E anticipation, F sentiment, G transmission, H régimes, I structure, J calendrier, K stratégies, L probabiliste/petit échantillon, M robustesse, P modèle prédictif et score composite. Le détail est dans `patrick earnings studies`.

## Ce que les données gratuites permettent, et ce qu'elles ne permettent pas

| Besoin | Statut | Traitement |
|---|---|---|
| Prix, volumes, dates et heures d'annonce, EPS estimé/publié/surprise | Yahoo, historique profond | Utilisés. Toutes les heures Yahoo sont en **heure de New York**, y compris Paris, Copenhague ou Tokyo : reconverties dans le fuseau de la place. |
| Consensus, révisions 7/30/60/90 j, recommandations, cibles de cours, vendeurs à découvert | Yahoo, **instantané du jour seulement** | Pris chaque jour (`earn_snapshot`, bouton, `patrick earnings snapshot`, étape de nuit). Affichage tant que moins de 60 annonces passées ont un instantané daté pris avant elles ; jamais d'évaluation avec le consensus d'aujourd'hui sur le passé. |
| Changements de recommandation | Yahoo, **daté** | Utilisés (carte F), avec la réserve que la couverture ancienne est incomplète. |
| Options historiques (implicite contre réalisé, backtest de straddle) | Indisponible | Straddle ATM de la prochaine annonce pris chaque jour puis apparié au réalisé : cartes vides aujourd'hui, utilisables après quelques trimestres. |
| Transcriptions, guidance, chiffre d'affaires publié face à l'estimé | Indisponible | Cartes marquées « indisponible avec des données gratuites ». |
| Historique d'annonces de certains titres (Diageo, LVMH, Interparfums.PA constatés) | Absent chez Yahoo | Saisie manuelle des dates passées (`/resultats/titre/X`, `patrick earnings manual`). |
| Fournisseurs/clients, poids d'indice réels, capitalisation historique | Indisponible | Leader = plus grande capitalisation du secteur ; poids = capitalisation relative dans l'échantillon (dit comme proxy) ; capitalisation, P/B, ROE : instantanés actuels (dit). |
| Calendrier macro | Partiel | FOMC (liste du module `schedule`, à compléter chaque année) et emploi américain approximé au premier vendredi du mois ; pas de CPI. |

## Défauts trouvés en vérifiant sur le vrai Yahoo, et corrigés

Un passage réel (18 titres, 1 147 événements, base et cache jetables) a trouvé ce que les données synthétiques ne montraient pas :

- **Fuite d'information dans le modèle de direction.** Un premier AUC de 0,62 venait de la surprise de BPA *de l'annonce testée*, publiée en même temps que la réaction. Elle sert à EXPLIQUER (carte ERC), jamais à PRÉDIRE : seules les surprises des annonces précédentes entrent dans le modèle (`model.FORBIDDEN_FEATURES`, test qui brouille toutes les colonnes de résultat et exige des variables identiques).
- **Kolari-Pynnönen trop sévère** : la corrélation moyenne n'était calculée que sur les paires dont les fenêtres se chevauchent, puis appliquée à toutes. Les paires sans fenêtre commune comptent maintenant pour 0.
- **Test des signes généralisé absurde sur les fenêtres longues** (p de l'ordre de 10⁻²³⁷ sur `[+2, +60]`) : refusé au-delà de 10 séances.
- **Indice national trop court** (Copenhague) : bascule silencieuse sur un modèle « moyenne constante ». Le benchmark est maintenant choisi selon sa couverture de l'historique du titre (≥ 70 %), sinon le meilleur, et un indice lacunaire écarte les événements non estimables au lieu de les lisser.
- **Heure fantôme 11:00 (New York)** que Yahoo met sur beaucoup de dates à venir (LVMH, Diageo, Interparfums, Air France) : traitée comme heure absente, repli par place, drapeau levé.
- **Sharpe des stratégies gonflé** par des transactions d'une même semaine corrélées : Sharpe, DSR et perte maximale se calculent sur des cohortes d'entrée hebdomadaires.

## Garde-fous méthodologiques

Estimation sans les annonces voisines ; statistiques « historiques » d'un titre sur ses seuls événements passés (`panel._add_history`) ; entrée de stratégie à l'ouverture suivante avec coûts et slippage proportionnel au gap ; DSR avec le nombre de configurations essayées, PBO sur blocs de temps, holdout terminal de 15 mois jamais utilisé pour choisir ; modèle prédictif poolé en walk-forward par date avec purge des événements chevauchants et baselines obligatoires (moyenne du titre, du secteur) ; score composite aux poids appris, toujours décomposé, avec R² hors échantillon.

## Limites assumées

- Biais de survie : les titres délistés manquent des données gratuites.
- Les libellés produits par les cartes sont en français (données du domaine, comme `i18n_server`) ; seule l'interface (titres, boutons, aides) est traduite FR/EN.
- Un résultat « significatif » d'une carte n'est pas un signal. Exemple observé : sur un échantillon de valeurs gagnantes (Palantir, AMD, Apple, Block…), la continuation `[+2, +5]` sort à p < 0,001 avec tous les tests, alors que le placebo de cette fenêtre est calibré (5 à 10 % de rejets) : ce n'est pas un artefact de méthode, mais un échantillon petit, corrélé et soumis au biais de survie ; seul le registre FDR sur un univers plus large peut en dire plus.
- Les tables `earn_*` ne sont pas fusionnées entre PC ; la tâche de nuit prend l'instantané du jour mais ne collecte pas de newsletter.
