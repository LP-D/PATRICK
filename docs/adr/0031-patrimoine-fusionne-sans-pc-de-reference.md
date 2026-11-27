# ADR 0031 — Patrimoine fusionné entre PC ligne par ligne, sans PC de référence

Date : 2026-11-27. Statut : codée et testée sur la branche `feat/obligataire`. Demande de Léon : « au lieu d'avoir un PC maître, je veux
que les données se recoupent à chaque fois et mettent à jour la base, un peu comme sur le modèle de GitHub mais tout en automatique ».

## Contexte

- Depuis le 07/10/2026, le patrimoine (`wealth_account`, `wealth_movement`) avait un PC de RÉFÉRENCE (`sync_wealth_reference`,
  aujourd'hui `DESKTOP-AV3KKV0`) : il l'ajoutait à la base de recherche publiée, les autres PC le remplaçaient par le sien à chaque
  fusion. Raison : les deux PC avaient importé les mêmes comptes sous des identifiants différents, une union aurait créé des doublons.
- Conséquences : un relevé importé sur l'autre PC était perdu à la fusion suivante ; une modification faite sur la référence
  n'arrivait qu'avec la publication de la base de recherche (au plus une par 24 h, PATRICK fermé pour fusionner).
- Les fonds (`fund_*`) se fusionnent déjà sans référence depuis le 14/10, stratégie par stratégie (`fund/share.py`).
- Un mouvement n'avait pas d'identité commune aux PC : `movement_id` est un entier auto-incrémenté propre à chaque base. Aucune date
  de modification, aucune trace des suppressions : impossible de savoir, à la fusion, qui a ajouté, modifié ou supprimé quoi.

## Décisions

1. **Identité et historique minimal** (migration 0062) : `wealth_movement.uid` (unique, le même sur tous les PC ; `mv_<hex>` aléatoire
   pour un nouveau mouvement), `updated_at` sur les comptes et les mouvements (UTC au millième, posé par chaque écriture de
   `wealth/ledger.py`), table `wealth_deleted (kind, uid, deleted_at)` remplie à chaque suppression. Les mouvements existants dérivent
   leur `uid` du compte, du numéro et de la date de saisie : deux PC qui ont la même copie (celle que la référence publiait) obtiennent
   les mêmes identifiants, sans échange préalable.
2. **Échange par fichier, comme les fonds** : chaque PC publie `wealth-<pc>.db.gz` + `wealth-<pc>.json` (empreinte, `merged`,
   `reference`) dans le dossier partagé, et fusionne ceux des autres à chaque `sync auto` (démarrage, tâche horaire, fermeture), même
   PATRICK ouvert ou pendant un entraînement. Un PC n'écrit jamais le fichier d'un autre. La base de recherche ne porte plus le
   patrimoine une fois le passage fait.
3. **Fusion ligne par ligne** (`wealth/share.py::merge_wealth`, une transaction) : une ligne absente est importée ; présente des deux
   côtés et différente, la plus récente (`updated_at`) gagne, à date égale l'empreinte du contenu décide (le même choix sur tous les PC,
   donc convergence) ; une suppression l'emporte sauf modification postérieure (pour un compte, ses mouvements comptent : il revient
   avec eux) ; un mouvement saisi des deux côtés avant l'échange (même compte, date, type, titre, quantité, prix, montant, frais,
   taux, échéance) est rangé sous un seul `uid`, le plus petit, au lieu d'être compté deux fois. Les versions locales écartées sont
   sauvegardées en JSON (`patrimoine_fusion_*.json`).
4. **Passage automatique** (`sync/core.py::_wealth_switch`) : l'ancienne référence et un PC sans patrimoine passent tout de suite ; un
   PC qui adoptait la référence attend qu'elle publie son fichier (marqué `reference` et `merged`), en reprend une DERNIÈRE fois la copie
   (`adopt_wealth`), puis fusionne ; s'il voit un autre PC publier sans être la référence, il n'y a pas de référence et il fusionne. En
   attendant, il publie son fichier marqué `merged: false`, qu'aucun PC ne fusionne (sa copie n'a pas trace des suppressions faites sur
   la référence depuis sa dernière adoption : la fusionner les ressusciterait).
5. **Interface** : la case « Ce PC est la référence du patrimoine » disparaît de l'assistant de premier démarrage et de Réglages ;
   l'état de la synchronisation dit « fusionné avec les autres PC » ou « passage à la fusion au prochain échange ».
   `sync setup --wealth-reference` reste pour le passage.

## Conséquences

- On saisit et on importe sur n'importe quel PC ; la modification arrive sur l'autre au prochain passage (au plus une heure avec la
  tâche `PATRICK-Sync`).
- L'arbitre est l'horloge des PC : deux modifications de la même ligne à quelques secondes d'écart sur deux PC mal réglés peuvent être
  départagées à l'envers ; la version écartée reste dans la sauvegarde. Il n'y a pas de fusion champ par champ : la ligne entière gagne.
- Deux comptes créés séparément sur deux PC pour le même compte réel restent deux comptes (identifiants différents) : à supprimer à
  la main. La reconnaissance des doublons ne vaut que pour les mouvements d'un même compte.
- Une saisie faite sur un ancien PC « suiveur » avant son passage est perdue (comme avant) : importer après le message « passage à la
  fusion entre PC ».
- Les fonds gardent leur fusion stratégie par stratégie : leurs ordres sont produits par le pilote automatique, une union ligne par
  ligne des ordres de deux PC qui font tourner le même pilote les doublerait.
