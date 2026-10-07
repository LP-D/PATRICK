# Partage de la base, des modèles et des données entre deux PC

## Synchronisation automatique (dossier OneDrive / Drive)

Deux PC qui lancent des runs chacun de leur côté ont des bases **disjointes**. `patrick sync auto` les met à
niveau par **union** : aucun run n'est jamais perdu ni écrasé, quel que soit le PC qui l'a produit.

| Commande | Effet |
|---|---|
| `patrick sync setup --folder <dossier> [--schedule] [--wealth-reference]` | à faire **une fois par PC** : mémorise le dossier partagé (`--schedule` : crée aussi la tâche Windows `PATRICK-Sync`, publication toutes les heures s'il y a du neuf; `--wealth-reference` : ce PC est la référence du patrimoine, voir plus bas) |
| `patrick sync status` | dit ce que `auto` ferait, sans rien modifier |
| `patrick sync auto [--only pull\|push]` | fusionne ce que l'autre PC a publié, puis publie ce que ce PC a de neuf |
| `patrick sync merge --from <dossier> [--dry-run-to f.db]` | fusion explicite (à blanc : écrit dans `f.db`, la base locale n'est pas touchée) |

Avec le lanceur `PATRICK.lnk` : la fusion se fait au démarrage (avant le serveur, écran « Synchronisation... »),
la publication en arrière-plan à la fermeture de la fenêtre. Journal : `~/.patrick/logs/sync.log`.

**Mise en place sur un nouveau PC** : mettre le code à jour (le lanceur le fait), copier le dossier
`PATRICK-app` (lanceur mis à jour), puis `patrick sync setup --folder "<dossier OneDrive>" --schedule` depuis
la version stable, PATRICK fermé (sans `--wealth-reference` : ce PC adopte le patrimoine de la référence).
La première fusion peut durer plusieurs minutes.

### Règles de la fusion

- Un run est identifié par son `run_id` : présent des deux côtés, il n'est jamais modifié; absent, il est
  importé avec ses essais, prédictions, métriques, diagnostics et modèles. Les `trial_id` (clés propres à
  chaque base) sont décalés à l'import et les modèles rangés sous le nouvel identifiant.
- Champions : le plus récent (`promoted_at`) gagne pour une même (cible, horizon). Registre des essais (DSR) :
  union dédoublonnée. Caches SHAP/volatilité, snapshots, symboles exclus : union par clé.
- Magasin de données (parquet) : on n'ajoute que les fichiers absents.
- **Patrimoine et fonds (`wealth_*`, `fund_*`) : un PC de référence.** Les deux PC avaient importé les mêmes
  comptes sous des identifiants différents : une union créerait des doublons. Le PC marqué `--wealth-reference`
  (celui de Léon : `PC_de_LPD`) publie les siens avec la base; **les autres PC les REMPLACENT par ceux du
  partage à chaque fusion** (la base locale est sauvegardée avant). Le patrimoine se modifie donc sur le PC de
  référence; une modification faite ailleurs est perdue à la fusion suivante. Un PC non-référence publie sans
  patrimoine (il n'écrase jamais celui de la référence), et ne l'adopte que si le partage en contient.
  Sans PC de référence, chacun garde le sien. `simulation` (ancien simulateur) reste locale dans tous les cas.
- Limite connue : un run reste « figé » à l'import; les prédictions *live* qu'un PC ajoute ensuite à un run
  déjà synchronisé restent sur ce PC.
- Garde-fous : rien n'est fusionné ni publié tant qu'un entraînement tourne; la fusion demande que PATRICK
  soit fermé (la base est remplacée par une copie vérifiée, l'ancienne est sauvegardée dans
  `~/.patrick/backups`); la publication est refusée si le partage contient des données pas encore fusionnées;
  `patrick sync push --to <dossier>` manuel est refusé dans ce cas (`--force` pour écraser).

## Partage manuel (GitHub ou dossier)

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
