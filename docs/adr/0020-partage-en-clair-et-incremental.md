# ADR 0020 — Partage entre PC en clair et incrémental (format 2)

Date : 2026-11-12. Statut : codée et testée sur la branche `feat/sync-en-clair`, **non fusionnée** (le second PC doit recevoir le code en même temps). Demande de Léon : « on peut se permettre de tout mettre directement sur le Drive, sans zip ». Complète l'ADR 0009 (stockage) et la doc `docs/ops/partage-entre-pc.md`.

## Contexte

Depuis le 10/11/2026 le dossier partagé est un Google Drive (`F:\Mon Drive\Patrick Shared Folder`, lecteur virtuel en mode « diffusion en continu »). Le format 1 reconstruisait à **chaque** publication `store.zip` (~30 Go, des parquet déjà compressés : le zip ne gagnait que 25 %) dans le dossier temporaire de `C:`, puis le recopiait en entier vers le Drive en passant par un fichier `.part` renommé. Résultat les 10-12/11 :

- jusqu'à 13 publications par jour, chacune réécrivant 30 Go ; le contrôle d'espace n'en réservait que 4 ;
- le cache du Drive vit sur `C:` (79 Go le 11/11) et l'espace libre que `F:` annonce est celui de `C:` (16 Go) : la copie a fini par se figer et le client Drive est resté à 100 % d'un cœur, sans réseau, sans lecture possible ;
- des `.part` de 0 octet (`patrick (1).db.gz.part`…) sont restés dans le dossier, et `funds-….db.gz.part` a fait répondre `Errno 22` à deux publications des fonds ;
- l'autre PC aurait refusé la fusion (manifeste du 10/11, base du 12/11).

Le quota Google (400 Go, 71 utilisés) n'était pas en cause.

## Décisions

1. **Format 2 : une arborescence en clair** dans le dossier (`manifest.json`, `db/patrick.db`, `models/index.json`, `models/<empreinte>/…`, `store/snapshot=…/*.parquet`, `store/_index.json`, `store/_series_observations.json`). Choisi par défaut pour une destination « dossier » (`push(layout="tree")`) ; GitHub reste en archives (assets limités à 2 Go), `layout="zip"` donne l'ancien format.
2. **Immuable = jamais recopié.** Un parquet ou un modèle déjà présent (même chemin, même taille) est sauté : une publication ne copie que le neuf, et une copie interrompue reprend où elle s'est arrêtée. Les modèles sont rangés par **empreinte de leur contenu** (16 premiers caractères du sha256), pas par `trial_id` : les identifiants d'essai sont propres à chaque base, deux PC ont chacun un essai n° 1 et un `m.joblib` différent, et un rangement par identifiant aurait servi le modèle de l'un à l'autre.
3. **Plus de fichier temporaire `.part`.** Les fichiers sont écrits sous leur nom final, le manifeste en dernier ; le lecteur contrôle la taille de chaque fichier annoncé et le sha256 de la base et des petits fichiers (pas des parquet : lire 40 Go deux fois depuis un Drive coûterait deux téléchargements). Un fichier coupé donne « pas entièrement recopié », jamais une donnée fausse. Les `.part` de l'ancien mécanisme sont supprimés au début d'une publication. `FolderTransport.upload` (fonds, format 1) fait de même.
4. **Garde d'espace sur le disque du dossier** : sous 5 Go libres la publication s'arrête proprement (vérifié avant chaque fichier puis tous les 256 Mo) sans toucher au manifeste ; la suivante reprend.
5. **Délai minimal entre deux publications complètes : 24 h** par PC (`sync_min_push_hours`, `--min-push-hours`, `0` = sans délai ; la première publication d'un PC n'est jamais retardée ; `patrick sync auto --min-push-hours 0` publie tout de suite, avec le patrimoine si ce PC en est la référence, ce que `patrick sync push` sans `--include-personal` ne fait pas). La base (3 Go) est réécrite en entier à chaque fois et Google Drive garde les anciennes versions d'un fichier remplacé. Les fonds (`funds-<pc>.db.gz`, petits) restent hors de ce délai.
6. **Les deux formats se lisent** (`pull`, `merge`, `remote_stamp`). Un code sans le format 2 ne lit pas un dossier en format 2 : les deux PC doivent être mis à jour avant la première publication en clair.
7. **Rien n'est supprimé automatiquement** dans le dossier partagé : après la première publication en clair, les anciens `patrick.db.gz`, `models.zip` et `store.zip` sont seulement signalés (`legacy_assets_left`, message de `auto` et de `sync push`).
8. **Journal** : `patrick sync auto` écrit aussi dans le journal une erreur d'accès disque (`OSError`), jusque-là perdue dans une tâche planifiée sans console.

## Conséquences

- Taille du dossier : ~47 Go en clair (base 3 + magasin 39 + modèles 4,6 + fonds), contre 32,7 Go zippés ; premier envoi complet, puis quelques fichiers par jour au lieu de 30 Go. Plus aucun fichier temporaire de 30 Go dans `C:`.
- Le Drive doit pouvoir recevoir ces 47 Go : le mode **Miroir sur un disque avec de la place** est recommandé (en diffusion en continu, l'espace libre de `F:` est celui de `C:`).
- Mesuré le 2026-11-12 sur 30 000 fichiers synthétiques (25 000 parquet et 5 000 modèles de quelques Ko, disque local, machine chargée par la suite de tests) : première publication 886 s (30 003 fichiers écrits), **seconde publication sans changement 63 s (3 fichiers écrits : la base et les deux index)**, première lecture 632 s, **seconde lecture 43 s (0 fichier recopié)** ; manifeste de 2,4 Mo. Le coût d'une publication sans nouveauté est donc surtout la lecture des métadonnées (un `stat` par fichier) et l'export de la base ; sur Google Drive le premier envoi complet sera plus long qu'en local (un fichier à la fois).
- Limites : les modèles ou parquet qui ne sont plus référencés restent dans le dossier (pas de nettoyage) ; un `_meta.json` modifié sans changer de taille n'est pas recopié ; le manifeste liste chaque fichier (environ 2,5 Mo pour 30 000 fichiers) ; la base est réécrite en entier.
- Tests : `tests/test_sync_tree.py` (16), `tests/test_sync_cli.py` (+3) ; les tests de `test_sync.py` publient explicitement en `zip` (le format 1 reste couvert) ; l'assistant `PC` de `test_sync_auto.py` règle `sync_min_push_hours` à 0.
