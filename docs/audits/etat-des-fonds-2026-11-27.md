# État des fonds — mise en place, incohérences, pistes (2026-11-27)

Demande de Léon : « beaucoup de fonds en double, ou des noms identiques qui portent à confusion : vérifie et fais un rapport sur l'état des
fonds (pas leur performance, la mise en place, les incohérences et les pistes d'amélioration) ».

**Périmètre.** Base de PC_de_LPD, lue en lecture seule (`mode=ro`), code `main` f52b38f, page `/fonds` du serveur local. Le dossier partagé
(Google Drive, `G:`) n'est plus monté depuis le 25/11 : les fonds de DESKTOP-AV3KKV0 ne sont pas lisibles d'ici. Ce qui les concerne vient du
code (`fund/asset_classes.py`, `fund/real_funds.py`, `fund/combo.py`), des ADR 0026, 0028 et 0030 et du journal `~/.patrick/logs/sync.log`.
Les montants cités ne servent qu'à mesurer une incohérence, pas à juger une performance.

## En bref

1. **247 positions orphelines, jamais refermées.** Sur les 534 positions ouvertes des 13 fonds, 247 appartiennent à des règles retirées dont
   le modèle n'a plus de signal live : la règle ne peut plus calculer sa fermeture, la position reste ouverte depuis fin octobre. Elles pèsent
   160 % du capital de « Systematic Diebold-Mariano », 177 % de « Benjamini-Hochberg », 92 % de « Volatilité », 80 % d'« Actions US ».
   C'est la cause principale des leviers de 2 à 3,4× affichés alors que tous les fonds sont réglés à `gross = 1`.
2. **Pas de fonds en double sur ce PC, mais des règles et des expositions en double.** Les 13 noms sont uniques. En revanche :
   - **74 règles du pilote existent en deux exemplaires** (même cellule, même modèle), créées à quelques secondes d'écart dans la nuit du
     16/11 par deux passes du pilote simultanées. Le pilote n'en voit qu'une, les deux tradent : 112 positions ouvertes en dépendent, et c'est
     ce qui pousse au-delà de 100 % l'exposition des règles actives (ETF, Actions Europe, Indices, Taux…) ;
   - 17 modèles actifs sont tradés par 2 ou 3 fonds à la fois (`^VIX` et `XLY` dans trois fonds) : les fonds « par preuve »
     (Diebold-Mariano, Benjamini-Hochberg) puisent dans le même univers que les fonds « par classe ».
3. **Les noms se répètent d'une gamme à l'autre.** Sur DESKTOP-AV3KKV0, le code et les ADR donnent 36 stratégies où 13 thèmes reviennent
   2 ou 3 fois (« Actions France » : Systematic, CTO, PEA ; « Diebold-Mariano » : Systematic, CTO, PEA…). La gamme « Systematic » est
   elle-même en enveloppe CTO, et deux « Actions Europe » n'ont pas le même univers. C'est très probablement l'impression de doublons.
4. **Deux PC pilotent les mêmes fonds.** Les 13 fonds Systematic ont été créés sur DESKTOP-AV3KKV0 le 24/10 et importés ici le 14/11 ; depuis,
   chaque PC lance le pilote chaque nuit sur les mêmes identifiants. La fusion garde la stratégie modifiée en dernier, ordres compris : le
   travail d'un PC efface celui de l'autre (13 remplacements le 15/11). Et les 23 fonds créés ensuite sur DESKTOP-AV3KKV0 (CTO, PEA, Tous
   signaux, Combinés) ne sont jamais arrivés ici : les deux PC n'affichent pas les mêmes fonds.
5. **Les fonds par classe tradent sans preuve.** Les 11 fonds par classe sont au niveau `large` (tout signal non suspect), alors que le
   défaut documenté est `strict` depuis la critique du 28/10. La page ne propose plus `large`, mais les fonds existants n'ont jamais été repassés.

## Inventaire (base de ce PC)

| Fonds | Niveau | Règles non retirées (dont en double) / retirées | Positions ouvertes (orphelines) | Exposition affichée | Ordres | Frais + financement |
|---|---|---|---|---|---|---|
| Systematic Future | large | 22 / 33 | 28 (9) | 93 % | 234 | 97 807 € |
| Systematic Actions US | large | 25 / 262 | 140 (120) | 158 % | 1 588 | 127 291 € |
| Systematic Actions France | large | 53 / 89 | 63 (18) | 110 % | 607 | 75 423 € |
| Systematic Actions Europe | large | 89 (20) / 58 | 74 (3) | 107 % | 794 | 72 335 € |
| Systematic Actions Asie | large | 18 (6) / 27 | 24 (1) | 189 % | 210 | 121 821 € |
| Systematic Indices | large | 23 (11) / 31 | 27 (15) | 163 % | 345 | 48 050 € |
| Systematic ETF | large | 49 (21) / 49 | 63 (24) | 233 % | 621 | 209 852 € |
| Systematic Devises | large | 18 (2) / 10 | 27 (9) | 214 % | 111 | 35 757 € |
| Systematic Crypto | large | 4 (1) / 2 | 3 (0) | 127 % | 23 | 833 081 € |
| Systematic Volatilité | large | 3 / 12 | 9 (7) | 197 % | 79 | 33 895 € |
| Systematic Taux | large | 6 (3) / 2 | 9 (1) | 296 % | 71 | 69 859 € |
| Systematic Diebold-Mariano | dm | 17 (5) / 67 | 48 (32) | 282 % | 374 | 168 956 € |
| Systematic Benjamini-Hochberg | bh | 12 (5) / 23 | 19 (8) | 335 % | 173 | 198 531 € |

Réglages communs : CTO, 10 M€ virtuels, catégorie `quant`, horizon 1 jour, vente à découvert, `gross = 1`, aucun plafond de modèles, signal
frais de moins de 7 jours. Aucune stratégie archivée, 4 suppressions anciennes (14/10 et 07/11) gardées comme pierres tombales pour la fusion.
Tables inutilisées : `fund_limit_order` (0 ligne), `fund_settings_log` (0 ligne : les réglages n'ont pas changé depuis l'arrivée du journal).

**Ce que DESKTOP-AV3KKV0 devrait avoir en plus** (d'après le code et l'ADR 0030) : 13 « CTO … » (11 classes + Diebold-Mariano +
Benjamini-Hochberg), 4 « PEA … » (Actions France, Actions Europe, Diebold-Mariano, Benjamini-Hochberg), « CTO Tous signaux » et « PEA Tous
signaux », 4 « Combiné … » : 36 stratégies au total. À vérifier sur ce PC-là : `patrick fund list` ou la page `/fonds`.

## Incohérences

### A. Positions orphelines (le plus grave)

Quand le pilote abandonne une cellule (cible, horizon) que plus aucun modèle sélectionné ne couvre, il **retire** la règle au lieu de la
supprimer : « une retirée finit de fermer » (`autopilot.managed_rules`, `systematic.apply` chaque nuit). Mais quand le champion de cette cellule
perd ensuite un duel, son run est élagué (`champions.prune_run`) et ses prédictions avec. `systematic.plan` lève alors « aucun signal du segment
'live' pour l'essai … » : la fermeture n'est jamais planifiée et la position reste ouverte indéfiniment, avec son risque et son P&L.

Mesuré : 247 positions orphelines, ouvertes depuis le 26/10 pour les plus anciennes. Chaque nuit ces règles échouent et gonflent le compteur
`failed` du compte rendu du pilote (257 « échecs » pour Actions US le 27/11, presque tous des règles retirées), ce qui noie les vrais échecs.

Le remplacement d'un modèle par un autre sur la même cellule ne pose pas ce problème : `_purge_previous_models` supprime l'ancienne règle et ses
ordres (décision du 13/11).

### B. Règles du pilote en double

74 cellules (cible, horizon) ont **deux règles actives identiques** : même essai, même date de départ, créées à 3 à 30 secondes d'écart le
16/11 entre 4 h et 7 h (Actions Europe 20, ETF 21, Indices 11, Actions Asie 6, Diebold-Mariano 5, Benjamini-Hochberg 5, Taux 3, Devises 2,
Crypto 1). Cette nuit-là suivait la fusion du 15/11 et les 418 remplacements des 15 et 16/11 : deux passes du pilote ont tourné en même temps
(l'application et la tâche de nuit ; la PR 88 a depuis empêché la double passe de prédictions, pas nettoyé ce qu'elle avait créé).

Pourquoi elles ne disparaissent pas : le pilote range les règles actives par cellule (`active[(cible, horizon)] = règle` dans
`autopilot.run`), donc n'en voit qu'une ; mais il applique chaque nuit **toutes** les règles du pilote (`managed_rules`). Les deux exemplaires
ouvrent chacun leur position : 112 positions ouvertes dépendent de ces cellules doublées. C'est la cause la plus probable des expositions des
règles actives au-delà du budget (Taux 250 %, ETF 165 %, Actions Asie 129 %, Devises 128 % du capital) ; les autres causes possibles (taille
figée à la création, `_stable_sizing`) n'ont pas été mesurées.

Côté code, rien n'empêche deux passes concurrentes de créer la même règle : pas de verrou par fonds autour de `autopilot.run`, pas de
contrainte d'unicité (fonds, cible, horizon, essai) sur les règles actives.

### C. Le P&L affiché ignore les pertes des modèles remplacés

Le journal `fund_replacement` compte 491 remplacements (302 le 15/11, 116 le 16/11 : la règle du 13/11 appliquée à l'historique), 2 836
ordres supprimés. P&L net retiré : **−768 421 €** (somme des valeurs absolues : 5,46 M€). Les modèles remplacés perdaient plus qu'ils ne
gagnaient : les retirer embellit le P&L des fonds d'environ 0,6 % du capital total. C'est la décision prise le 13/11 (« on supprime le P&L du
seul modèle précédent »), mais la page ne montre nulle part ce qui a été retiré : le P&L se lit comme un historique réel alors qu'il est
réécrit à chaque remplacement.

### D. Frais du fonds Crypto

833 081 € de frais pour 23 ordres (8,3 % du capital) : 3 modèles seulement, donc 3 positions d'un tiers du capital chacune, levier CFD 2:1,
horizon 1 jour. Le spread médian d'un CFD crypto (30 points de base) est multiplié jusqu'à 3 pour un notionnel de plus de 2 M€
(`fees.DERIV_SIZE_CAP`), puis tiré au sort (loi log-normale) : un aller-retour quotidien coûte 1 à 2,5 %. Le dimensionnement « capital /
nombre de modèles » produit des positions énormes quand peu de modèles passent.

### E. Noms et gammes qui se recouvrent

- Le préfixe « Systematic » désigne la gamme quant, mais son enveloppe est CTO : dans le tableau, « Systematic Actions US · CTO » et
  « CTO Actions US · CTO » se lisent pareil. Le mot « CTO » sert à la fois de gamme et d'enveloppe.
- Les fonds par preuve portent le même nom dans trois gammes (« Systematic / CTO / PEA Diebold-Mariano ») et recouvrent les fonds par classe
  de leur gamme : sur la gamme PEA, 5 fonds de 5 000 € (Actions France, Actions Europe, Diebold-Mariano, Benjamini-Hochberg, Tous signaux)
  puisent dans les mêmes 112 actions et, plafonnés à 25 positions de 200 €, retiendront largement les mêmes meilleurs signaux.
- « Actions Europe » n'a pas le même univers selon la gamme : Allemagne + Royaume-Uni + autres pays en Systematic, actions de l'UE/EEE en euro
  hors France en PEA.
- « Combiné Référence » (niveau `auc`, horizon 1, tout l'univers, vente à découvert) est presque un « Tous signaux » quant : la seule
  différence avec les autres combinés est l'ingrédient testé, ce qui est voulu, mais rien sur la page ne le relie à son témoin.
- Dans le tableau « Règles du pilote » d'un fonds, les règles retirées restent listées (262 sur 287 pour Actions US) : la même cellule apparaît
  deux ou trois fois, une active et les autres retirées.

### F. Synchronisation des fonds entre PC

- **Deux pilotes sur les mêmes stratégies.** La fusion des fonds (`fund/share.py`) remplace une stratégie entière par la version la plus
  récente. Comme les deux PC font tourner le pilote, chaque nuit l'un écrase les ordres et les règles de l'autre. Le patrimoine a un PC de
  référence (`sync_wealth_reference`) ; les fonds n'en ont pas.
- **DESKTOP-AV3KKV0 ne publie plus ses fonds depuis le 15/11** (dernière importation dans le journal ; « PATRICK-Sync désactivée » relevé le
  13/11), et ce PC ne voit plus le dossier partagé depuis le 25/11 (« le client Google Drive est-il lancé ? »). Les fonds créés sur
  DESKTOP-AV3KKV0 depuis le 20/11 n'existent pas ici.

### G. Niveau de sélection des fonds par classe

Les 11 fonds par classe sont en `large` : tout modèle non suspect, sans correction pour tests multiples ni test de Diebold-Mariano.
`asset_classes.DEFAULTS["tier"]` vaut `strict` depuis le 28/10, parce qu'on « tradait sans preuve puis classait les classes sur leur P&L
fictif ». Les fonds créés le 24/10 n'ont pas été repassés : leurs P&L comparés entre classes restent une sélection non corrigée.

## Pistes d'amélioration (par ordre d'urgence)

1. **Refermer les orphelines, et empêcher qu'il y en ait d'autres.** Une règle retirée dont le modèle n'a plus de signal ferme ses positions
   au prochain cours disponible (motif « modèle élagué ») ; ou bien l'élagage d'un run épargne un essai encore référencé par une règle qui a une
   position ouverte. Puis une commande de nettoyage avec aperçu (`--dry-run`) pour les 247 positions existantes.
2. **Dédoublonner les règles et verrouiller le pilote.** Supprimer le second exemplaire de chacune des 74 règles (et ses ordres, comme un
   remplacement) ; un verrou par fonds autour de `autopilot.run` (le fichier `patrick.db.autopilot.lock` existe déjà pour la passe globale) et
   un contrôle « une seule règle active par cellule » qui retire les surnuméraires au lieu de les ignorer.
3. **Un seul PC pilote les fonds.** Un réglage `sync_funds_reference` sur le modèle du patrimoine : seul ce PC lance `run_autopilots`, l'autre
   importe. Relancer Google Drive ici et réactiver PATRICK-Sync sur DESKTOP-AV3KKV0 pour que les deux PC voient les mêmes 36 fonds.
4. **Des noms qui disent la gamme, l'enveloppe et le découpage.** Par exemple « Quant · Actions US (CTO, 10 M€) », « Particulier CTO · Actions
   US (5 000 €) », « Particulier PEA · Actions France », « Quant · preuve Diebold-Mariano » ; une colonne « Gamme » et un regroupement gamme →
   découpage sur `/fonds` ; « Actions Europe (PEA) » pour l'univers PEA. Renommer est sans risque pour la fusion (identifiants inchangés).
5. **Choisir un découpage par gamme, ou montrer le recouvrement.** Soit une gamme se découpe par classe OU par preuve, soit chaque fonds affiche
   le nombre de cellules qu'il partage avec un autre fonds de la même catégorie (aujourd'hui 17 cellules actives sur ce PC).
6. **Repasser les fonds par classe en `strict`** (ou décider explicitement de garder `large` et l'écrire dans le nom).
7. **Montrer le P&L retiré.** Sous le P&L d'un fonds, « dont modèles remplacés : −… » à partir de `fund_replacement.pnl_removed`, pour que
   l'historique affiché ne se lise pas comme un historique réel.
8. **Fonds quant à peu de modèles** : plafonner le notionnel d'une position (par exemple 20 % du capital) et appliquer aux fonds quant le filtre
   de coût des fonds combinés (gain attendu ≥ coût d'un aller-retour), au moins pour la crypto.
9. **Compte rendu du pilote** : séparer les échecs des règles actives de ceux des règles retirées sans signal ; masquer par défaut les règles
   retirées dans « Règles du pilote » (un compteur et un bouton pour les montrer).
10. **Remesurer l'exposition des règles actives après le dédoublonnage** (point B) avant de toucher au dimensionnement.

## Corrections du 2026-11-27 (pistes 1 et 2)

**Code** (branche `feat/modeles-valeur-profils`) :
- `systematic.orphan_closes` / `apply` : une règle retirée dont le plan ne se calcule plus ferme quand même ses positions ouvertes, à
  l'échéance qu'aurait donnée le dernier signal avant le retrait (retrait + 1 jour + horizon). Plus d'« échec » quotidien pour ces règles.
  Une règle encore active sans signal reste une erreur (le pilote la retire, puis la ferme).
- `autopilot.drop_duplicate_rules`, appelé à chaque cycle : une seule règle active par cellule, la plus ancienne ; chaque exemplaire en trop
  est supprimé avec ses ordres. Le verrou entre processus (24/11) empêchait déjà deux cycles simultanés ; ce contrôle nettoie l'existant et
  rattrape tout doublon futur. Compte rendu du cycle : `deduplicated`, `orphans_closed`.
- `patrick fund repair --all [--apply]` : aperçu par défaut, sous le verrou du cycle.

**Aperçu sur la vraie base de ce PC** (avant écriture) : 74 règles en double portant 582 ordres, dont le P&L compté deux fois faisait
**−1 033 325 €** au total (ETF −168 716 €, Crypto −306 082 €, Benjamini-Hochberg −152 771 €, Actions Asie −123 975 €, Taux −119 726 €…) ;
247 positions orphelines. Sauvegarde des fonds avant écriture : `~/.patrick/backups/fonds-avant-reparation-2026-11-27.db` (13 stratégies,
5 230 ordres, export `fund/share.export_funds`).

**Appliqué le 27/11 au soir** (`patrick fund repair --all --apply`, code du worktree) : 74 règles en double supprimées avec leurs 582
ordres ; 244 positions orphelines fermées, 3 en attente (Devises, échéance après le 27/11 : elles se fermeront au premier cycle qui tourne
avec ce code, ou par une nouvelle `fund repair --apply`). Relu ensuite : plus aucune cellule doublée ; exposition des règles actives
revenue sous 100 % sauf Devises (117 %) et Taux (125 %).

**Point B expliqué ensuite (pas de défaut de dimensionnement)** : Devises = 92 % de règles actives + 34 % des 3 orphelines en attente.
Taux : la règle `^TNX h1` tient une position longue et une courte en même temps. Pendant Thanksgiving (pas de cours le 26/11), les ordres
s'exécutent au dernier cours connu (25/11, « provisoire ») et les signaux arrivent en retard ; la fermeture de la longue, refusée le 27/11 à
14 h 20, est acceptée depuis que le cours du 27/11 existe (aperçu `service.quote`) et partira au prochain cycle. Effet de bord connu : quand
un signal tardif change le plan, la fermeture déjà passée garde son ancienne note et le plan en redemande une autre, refusée chaque jour.

**Pistes 6 et 8 faites** : le panneau d'un fonds affiche le total du P&L retiré avec les modèles remplacés (`insight.replacement_totals`, tout
le journal, pas seulement ses 50 dernières lignes) ; dans « Règles du pilote », les règles retirées sont repliées sous un compteur.
Restent à décider : un seul PC qui pilote les fonds, des noms plus clairs, le niveau `strict` pour les fonds par classe.

## Méthode

Requêtes en lecture seule sur `fund_strategy`, `fund_rule`, `fund_order`, `fund_replacement`, `fund_deleted` ; `systematic.plan` rejoué sur une
connexion en lecture seule pour classer chaque position ouverte (règle active, retirée lisible, retirée sans signal) ; exposition = quantité ×
cours d'ouverture × change, rapportée aux 10 M€ du fonds ; colonne « Exposition affichée » lue sur `/fonds`. Journal de synchronisation :
`~/.patrick/logs/sync.log` (lignes « fonds »). Scripts d'audit gardés hors dépôt.
