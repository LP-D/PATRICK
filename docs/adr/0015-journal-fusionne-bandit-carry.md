# ADR 0015 — Journal de prédictions fusionné entre PC, dimensionnement appris mesuré, carry de change mesuré

Date : 2026-11-02. Statut : le journal fusionné est appliqué ; le dimensionnement appris et le carry sont des MESURES, pas des fonctions du fonds. Suite de l'ADR 0014 (« Non fait »).

## Contexte

Trois chantiers que l'ADR 0014 laissait ouverts, repris à la demande de l'utilisateur (« si tu as une solution, fais-le »). Deux avaient une solution de conception ; le troisième s'est révélé mal posé
dans l'ADR 0014 : le carry de CHANGE n'a pas besoin d'une courbe de futures, seul le carry de matières premières en a besoin.

## Décisions

1. **Journal de prédictions fusionné** (migration 0050, `tracking/journal.py`, `sync_merge.py`). Chaque PC garde SA chaîne d'empreintes. Les lignes de l'autre PC sont recopiées TELLES QUELLES
   (`prev_hash`, `entry_hash` et `trial_id` compris : ils sont dans la charge utile hachée, on ne peut pas les décaler comme dans `sync_merge`) et marquées `imported_from`. Conséquences de
   conception :
   - un `trial_id` importé désigne un essai de l'AUTRE base : toutes les lectures par `trial_id` (`record_signals`, `record_outcome`, `seal_existing`, la dernière empreinte de la chaîne) filtrent
     sur les lignes locales ; sinon un signal importé masquerait un signal local de même essai et même jour, ou la chaîne locale se prolongerait sur une ligne étrangère ;
   - `verify` rejoue la chaîne locale comme avant, puis vérifie chaque ligne importée contre le `prev_hash` qu'elle annonce (`imported_hash_mismatch`) et que ce `prev_hash` est `GENESIS` ou une ligne
     présente (`imported_prev_missing` : une ligne a été retirée avant elle). `n_imported` les compte, `forks` compte les lignes qui prolongent une empreinte déjà prolongée (deux PC partis d'une même
     copie : informatif) ;
   - la fusion est idempotente (`entry_hash` est unique) et un aller-retour A→B→A ne crée aucun doublon ;
   - la vue (`analysis/journal_view.py`) distingue les lignes importées (clé `(origine, trial_id, jour)`, comparaison à la table `prediction` locale limitée aux lignes locales) et l'export CSV
     porte la colonne `imported_from`.
   Limite : insérer une ligne FAUSSE bien chaînée reste indétectable (il faudrait un ancrage externe de la dernière empreinte). Un PC dont le code n'a pas la migration 0050 est refusé par la
   fusion (« mets le code à jour sur les deux PC »), comme pour toute autre table.
2. **Dimensionnement appris : mesuré, pas adopté** (`simulate/sizing_bandit.py`, `scripts/bandit_sizing_bench.py`, `tests/test_sizing_bandit.py`). Deux politiques, une configuration chacune, fixées avant
   la mesure : un bandit LinUCB (taille ∈ {0 ; 0,25 ; 0,5 ; 1}, retour de bandit) et un Kelly fractionnaire appris par ridge en ligne (information complète : dans un rejeu l'action ne change pas les
   prix). Contexte : force du signal, rapport de volatilités 20 j / 250 j. Préchauffage sur le segment `test` (antérieur au holdout), évaluation sur le holdout, mêmes frais (5 pb par unité de rotation)
   que les trois heuristiques de `/simulate` (seuil 0,55, proportionnel, levier moitié). **Résultat sur 459 champions à 1 jour de la vraie base** : Sharpe net moyen bandit 0,045, Kelly ridge 0,095,
   seuil 0,163, proportionnel 0,176. Écart bandit − seuil −0,119 (IC à 97,5 % [−0,209 ; −0,031], test des signes p = 0,025) ; Kelly ridge − seuil −0,068 ([−0,148 ; +0,010]) ; Kelly ridge − proportionnel
   −0,080 ([−0,152 ; −0,010]). **Le critère d'entrée du cadrage (battre le dimensionnement heuristique après coûts sur le holdout) n'est pas atteint.** Dans un monde synthétique construit pour
   que la conviction compte, les deux apprentis retrouvent l'avantage mais ne battent pas le dimensionnement proportionnel : le rapport signal/bruit quotidien (~0,05) est trop faible pour qu'un
   apprentissage de 1 000 observations fasse mieux qu'une règle fixe. Les champions étant choisis sur le holdout (ADR 0005), le biais joue pour toutes les politiques à la fois. Rien n'est branché au fonds.
3. **Carry de change : mesuré, pas adopté** (`features/fx_carry.py`, `scripts/fx_carry_study.py`, `tests/test_fx_carry.py`). Sept devises contre le dollar, taux interbancaires à 3 mois de l'OCDE (FRED,
   `IR3TIB01<pays>M156N`), valeur d'un mois utilisée seulement deux mois plus tard, rebalancement mensuel, 2 pb de frais, avril 2000 à novembre 2025 (la série de la zone euro s'arrête fin 2025).
   Deux stratégies : séries chronologiques et coupe transversale (3 longues, 3 courtes). **Sharpe 0,17 et 0,18, t de la moyenne +0,87 et +0,92, Sharpe déflaté (2 essais) 0,64 et 0,65** (seuil
   habituel 0,95) ; 2013-2025 : 0,00 et 0,07. Le change seul (sans le portage) rend −0,15 et −0,22 : tout le gain vient du portage et le change le reprend presque en entier. Ce n'est pas une preuve
   d'absence de prime (305 mois, Sharpe attendu ~0,3-0,5 avant 2008, écart-type d'un Sharpe ~0,2), c'est l'absence de preuve d'une prime exploitable avec ces sept devises, ces taux et ces frais. Pas d'intégration
   au fonds : une règle de carry n'a pas de modèle, or toute règle du fonds est rattachée à un essai (`trial_id`) dans `create_rule`, la validation, `plan` et l'interface.

## Non fait

Carry de matières premières (pas de courbe d'échéances) ; règle du fonds sans modèle (nécessaire pour déployer un signal de carry, à ouvrir si une preuve le justifie) ; ancrage externe de la dernière
empreinte du journal ; interface du journal (colonne d'origine dans la page) au-delà de l'export CSV.

## Conséquences

- La page du journal et `journal.verify` renvoient deux champs de plus (`n_imported`, `forks`) ; les lignes importées n'y sont pas comptées dans `n`.
- Après la mise à jour des deux PC, une synchronisation fusionne les deux journaux ; chaque PC garde la preuve de ses propres signaux et voit celle de l'autre.
- Les chantiers « bandit contextuel » (cadrage §1) et « carry » (§3 pour les futures, ici pour le change) sont clos par une mesure négative ; les rouvrir demande un fait nouveau (plus de signal, une courbe
  de futures, d'autres devises).
