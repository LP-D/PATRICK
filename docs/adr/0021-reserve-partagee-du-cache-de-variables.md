# ADR 0021 — Réserve partagée du cache de variables entre deux PC

Date : 2026-11-13. Statut : codée et testée sur la branche `feat/cache-partage`, **non fusionnée**. Demande de Léon : « mettre aussi les caches sur `F:` (le Drive) car ce sont des données utilisées par les deux PC ». Complète l'ADR 0020 (partage en clair de la base, du magasin et des modèles).

## Contexte

`feature_cache` (`features/pool_cache.py`) pèse 250 Go sur `D:` (86 844 fichiers `<clé>.parquet`). La clé est une empreinte du **contenu** brut, du code des variables et des paramètres : deux PC qui calculent la même chose produisent le même fichier, donc un cache commun évite à l'un de recalculer ce que l'autre a déjà fait. Ses trois propriétés, relevées dans le code le 13/11 :

1. **Lecture = écriture.** Chaque lecture appelle `os.utime` (la date sert de « récemment utilisé » à l'éviction). Sur un Drive, c'est une modification de métadonnées à chaque lecture.
2. **Éviction qui supprime.** `evict_feature_cache` retire les fichiers les moins récemment lus au-delà de 150 Go. Sur un Drive, un fichier supprimé reste 30 jours dans la corbeille de Google et compte dans le quota ; le cache grossit d'une dizaine de Go par jour (126 Go le 28/10, 250 Go le 13/11).
3. **Chemin unique.** Un seul dossier racine, déjà lu par les runs ; l'outil `patrick data move` déplace les sept dossiers d'un coup et refuse si le disque cible n'a pas la place du tout (339 Go).

Le Drive de Léon a 400 Go de quota, 240 Go libres le 13/11 (160 utilisés, dont ~72 Go de fichiers sans rapport avec PATRICK) ; sous Windows, l'espace libre de `F:` (diffusion en continu) est en réalité celui de `C:`, qui porte le cache du Drive.

## Décision

Un cache **à deux étages**, au lieu de déplacer le dossier racine sur le Drive :

1. **Étage local, inchangé** : `paths.feature_cache_dir()`. Les runs le lisent, l'éviction (plafond 150 Go, `feature_cache_max_gb`) ne vide que lui, `patrick data move` ne connaît que lui.
2. **Réserve partagée** : `paths.feature_cache_shared_dir()` (réglage `feature_cache_shared_root`, un dossier du Drive ; variable d'environnement `PATRICK_FEATURE_CACHE_SHARED_ROOT` pour les tests). Elle n'est consultée que sur un **défaut de cache local** : le fichier est copié en local puis lu. Elle ne reçoit que du **neuf** : à chaque `save`, le fichier est copié sous son nom final s'il n'y est pas déjà (jamais d'écrasement : deux PC dont les versions de pyarrow n'écrivent pas les mêmes octets s'enverraient le fichier indéfiniment), et seulement sous un plafond (`feature_cache_shared_max_gb`, défaut 150 Go, taille balayée au plus une fois par jour).
3. **Jamais de suppression automatique**, sauf d'un fichier qui ne se lit pas (envoi coupé côté Drive) : écarté des deux étages, le prochain calcul de la clé le republie.
4. **Au mieux, jamais bloquant** : réserve absente, Drive figé, `Errno 22`, disque plein : aucune exception ne remonte, la clé est recalculée. Aucun fichier temporaire dans la réserve, aucun `os.utime` sur ses fichiers.
5. **Amorçage** : `patrick storage share-feature-cache --to <dossier du Drive>` règle la réserve de ce PC puis y copie le cache local, les fichiers récents d'abord, jusqu'au plafond. Reprenable (même taille : sauté ; plus court : recopié). Avant chaque copie, il exige 20 Go libres sur le disque de la réserve (`--min-free-gb`) : sinon il attend (par pas de 30 s, une heure au plus) que Google Drive ait fini d'envoyer, puis s'arrête proprement. `--off` désactive la réserve sans rien supprimer. À lancer dans ta propre fenêtre PowerShell : la première copie dure des heures.

Le dossier `cache` (`LocalCache` : séries téléchargées avec une fraîcheur de 7 jours, métadonnées réécrites, 1,4 Go) **n'est pas partagé** : ses fichiers sont modifiés en place, deux PC s'y disputeraient les mêmes noms et Drive créerait des copies en conflit.

## Conséquences

- Un second PC qui configure la même réserve **lit** ce que le premier a calculé (si le code des variables et les données brutes sont les mêmes : même version de PATRICK, mêmes snapshots du magasin partagé) et **y ajoute** ce qu'il calcule ; les deux caches locaux restent indépendants.
- Quota : la réserve est bornée à 150 Go et n'est jamais purgée par le programme. Quand elle est pleine elle cesse de grossir : la purge est un geste de Léon (supprimer des sous-dossiers dans le Drive, puis vider la corbeille de Google). Pas de croissance de la corbeille entre-temps.
- Lecture plus lente seulement sur un défaut de cache local ; tout ce qui est déjà en local se lit à la vitesse du disque. Déplacer le cache **local** de `D:` vers `C:` (plus rapide) est un chantier séparé : `patrick data move` ne le fait que pour les sept dossiers à la fois.
- Limites : le plafond se mesure par un balayage quotidien et un compteur approché (deux PC qui publient en même temps peuvent le dépasser de quelques Go) ; un `parquet` coupé n'est détecté qu'à la lecture ; la réserve ne contient que les fichiers `.parquet` que lit `pool_cache` (pas de journal ni d'index).
- Mémoire (14/11/2026, premier amorçage réel) : la copie s'est arrêtée sur un `MemoryError` après 6 500 fichiers (19,9 Go) alors que `C:` avait 131 Go libres : la mémoire
  allouable de l'ordinateur (RAM 15,9 Go + fichier d'échange) était tombée à 1,9 Go, dont 21 Go de mémoire privée pour l'interface web de Google Drive (processus
  `msedgewebview2` lancé la veille à 23:38, pendant l'envoi de 31 000 fichiers). Ce n'est pas la copie qui fuyait. Désormais `seed` attend (par pas de 30 s, une heure
  au plus) tant que la mémoire allouable est sous 2 Go, retire le fichier coupé et s'arrête proprement sur un `MemoryError`, et `fetch` / `publish` traitent un
  `MemoryError` comme une réserve indisponible (un run ne s'arrête jamais à cause d'elle).
- Tests : `tests/test_feature_cache_share.py` (26).
