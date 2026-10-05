# Partage de la base, des modèles et des données entre deux PC

`patrick sync` copie un état **assaini** de `~/.patrick` vers un partage, et le restaure sur l'autre PC.

| Commande | Effet |
|---|---|
| `patrick sync push` | publie vers la release GitHub glissante `data-latest` (assets jusqu'à 2 Go, hors historique git) |
| `patrick sync pull` | restaure depuis GitHub; la base locale est sauvegardée avant remplacement |
| `patrick sync push --to <dossier>` / `pull --from <dossier>` | même chose via un dossier (Google Drive pour ordinateur, disque réseau, clé USB) |
| `patrick sync push --to <dossier> --include-personal` | dossier **privé** uniquement : inclut aussi le patrimoine et les fonds; refusé vers GitHub |

## Ce qui est partagé

- `patrick.db` compressée (~110 Mo), modèles référencés par `trial.artifact_path`, parquet du magasin de données.
- `manifest.json` : sha256 et taille de chaque fichier, version de schéma. `pull` refuse un fichier corrompu ou un
  partage plus récent que le code (faire `git pull` d'abord).

## Ce qui ne l'est jamais vers GitHub

- Tables `wealth_*`, `fund_*` et `simulation` : vidées dans une **copie** de la base (la source n'est pas modifiée),
  puis `VACUUM` pour qu'aucune page libérée ne garde la donnée.
- Nom d'utilisateur du PC : si une table assainie le contient (chemin absolu), la publication est refusée.
- Jobs en attente/en cours (mis en erreur dans l'export) et battement de worker : propres à un PC.

## À la restauration

- Les tables patrimoine/fonds **locales sont conservées** (fusion : le local gagne sur une même clé).
- Refusé si des runs locaux n'existent pas dans le partage (`--force` pour les abandonner) ou si un run tourne.
- Les chemins des modèles et du magasin sont réécrits vers ce PC (`~/.patrick/models`, `~/.patrick/store`).

Le dépôt est public : une release `data-latest` l'est aussi. Pour un partage strictement privé, utiliser un dossier.
