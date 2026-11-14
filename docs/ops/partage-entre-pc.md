# Partage de la base, des modèles et des données entre deux PC

> **Au quotidien, tout passe par l'application de bureau** : le dossier partagé se choisit au premier démarrage
> (ou dans Réglages), la fusion se fait au démarrage, la publication à la fermeture et toutes les heures, sans
> commande à taper (une publication complète est faite **au plus toutes les 24 h** par PC : réglage `sync_min_push_hours`,
> `0` = sans délai, ou `patrick sync auto --min-push-hours 0` pour publier tout de suite). Mise en service du PC 2, écrite pour une
> session Claude Code : [mise-en-service-pc2.md](mise-en-service-pc2.md). Voir
> [application-bureau.md](application-bureau.md) ; mise en service du format en clair : [passage-au-partage-en-clair.md](passage-au-partage-en-clair.md).
> Les commandes ci-dessous restent disponibles pour dépanner ou scripter.

## Synchronisation automatique (dossier OneDrive / Drive)

Deux PC qui lancent des runs chacun de leur côté ont des bases **disjointes**. `patrick sync auto` les met à
niveau par **union** : aucun run n'est jamais perdu ni écrasé, quel que soit le PC qui l'a produit.

| Commande | Effet |
|---|---|
| `patrick sync setup --folder <dossier> [--schedule] [--wealth-reference]` | à faire **une fois par PC** : mémorise le dossier partagé (`--schedule` : crée aussi la tâche Windows `PATRICK-Sync`, publication toutes les heures s'il y a du neuf; `--wealth-reference` : ce PC est la référence du patrimoine, voir plus bas) |
| `patrick sync status` | dit ce que `auto` ferait, sans rien modifier |
| `patrick sync auto [--only pull\|push] [--min-push-hours N]` | fusionne ce que l'autre PC a publié, puis publie ce que ce PC a de neuf (au plus toutes les N heures ; défaut : réglage `sync_min_push_hours`, sinon 24 ; `0` = sans délai) |
| `patrick sync merge --from <dossier> [--dry-run-to f.db]` | fusion explicite (à blanc : écrit dans `f.db`, la base locale n'est pas touchée) |

Avec le lanceur `PATRICK.lnk` : la fusion se fait au démarrage (avant le
serveur, écran « Synchronisation... »), la publication en arrière-plan à la fermeture de la fenêtre.
Journal : `~/.patrick/logs/sync.log`.
Les données lourdes (magasin, modèles, caches, sauvegardes) peuvent vivre sur un autre disque : voir
[racine-de-donnees-sur-un-autre-disque.md](racine-de-donnees-sur-un-autre-disque.md) (c'est aussi là que se trouve le correctif des modèles
absents du partage et le dépannage du message « Fichier corrompu (sha256 différent) »).

**Mise en place sur un nouveau PC** : `app\Installer.bat` (installe tout), puis au premier démarrage choisir le
**même** dossier OneDrive que sur le premier PC, sans cocher « référence du patrimoine » (ce PC adopte le
patrimoine de la référence). La première fusion peut durer plusieurs minutes. (À la main, depuis la version
stable, PATRICK fermé : `patrick sync setup --folder "<dossier OneDrive>" --schedule`.)

### Règles de la fusion

- Un run est identifié par son `run_id` : présent des deux côtés, il n'est jamais modifié; absent, il est
  importé avec ses essais, prédictions, métriques, diagnostics et modèles. Les `trial_id` (clés propres à
  chaque base) sont décalés à l'import et les modèles rangés sous le nouvel identifiant.
- Champions : le plus récent (`promoted_at`) gagne pour une même (cible, horizon). Registre des essais (DSR) :
  union dédoublonnée. Caches SHAP/volatilité, snapshots, symboles exclus : union par clé.
- Magasin de données (parquet) : on n'ajoute que les fichiers absents.
- **Patrimoine (`wealth_*`) : un PC de référence.** Les deux PC avaient importé les mêmes comptes sous des
  identifiants différents : une union créerait des doublons. Le PC marqué `--wealth-reference`
  (celui de Léon : `PC_de_LPD`) publie le sien avec la base; **les autres PC le REMPLACENT par celui du
  partage à chaque fusion** (la base locale est sauvegardée avant). Le patrimoine se modifie donc sur le PC de
  référence; une modification faite ailleurs est perdue à la fusion suivante. Un PC non-référence publie sans
  patrimoine (il n'écrase jamais celui de la référence), et ne l'adopte que si le partage en contient.
  Sans PC de référence, chacun garde le sien. `simulation` (ancien simulateur) reste locale dans tous les cas.
- **Fonds (`fund_*`) : fusionnés, jamais remplacés** (depuis le 14/10/2026; avant, un PC non-référence perdait
  ses portefeuilles à la fusion). Chaque PC publie les siens dans `funds-<nom du PC>.db.gz` + `funds-<nom du PC>.json`
  (le nom est celui de l'ordinateur, réglable par `sync_pc_name`) et fusionne ceux des autres, **stratégie par
  stratégie** : une stratégie absente d'ici est importée avec ses ordres, ses règles et les cotations; présente des deux
  côtés, la version modifiée en dernier l'emporte (l'autre est sauvegardée en JSON dans `~/.patrick/backups`);
  supprimée quelque part, elle est supprimée partout, sauf si elle a été modifiée après la suppression. Cet
  échange est **indépendant de la recherche** : il a lieu à chaque `sync auto` (ouverture de PATRICK, tâche horaire),
  même pendant un entraînement. Une version de PATRICK trop ancienne sur l'un des PC l'empêche (message « mets
  PATRICK à jour »).
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

Deux mises en page, choisies par `patrick sync push` selon la destination (ADR 0020) :

- **Format 2, en clair (dossier : Google Drive, OneDrive, disque réseau)** : `manifest.json` (écrit en dernier), `db/patrick.db`
  (la recherche, SQLite lisible telle quelle, sans caches ni données perso, environ 3 Go), `models/index.json` et
  `models/<empreinte>/<modèle>` (un modèle et son `_meta.json`, rangés par empreinte de contenu), `store/snapshot=<date>/*.parquet`
  avec `store/_index.json` et `store/_series_observations.json`. Les modèles et les parquet sont **immuables** : un fichier déjà
  présent avec la même taille n'est jamais recopié, donc une publication ne copie que le neuf, et une copie interrompue reprend
  où elle s'est arrêtée. Aucun fichier temporaire `.part`. La base, elle, est réécrite en entier à chaque publication (d'où le
  délai de 24 h).
- **Format 1, archives (GitHub, anciens dossiers)** : `patrick.db.gz`, `models.zip`, `store.zip`. Toujours lu par `pull` et
  `merge`, publié avec `patrick sync push --to github` (assets limités à 2 Go). Un PC sans le code du format 2 ne sait pas lire
  un dossier en format 2 (erreur `KeyError` à la lecture du manifeste) : **mettre à jour les deux PC avant de publier en clair.**
- `manifest.json` : taille et sha256 de la base et des petits fichiers, taille de chaque modèle et de chaque parquet, version de
  schéma. `pull` refuse un fichier corrompu (« sha256 différent »), un fichier pas encore entièrement recopié (« pas entièrement
  recopié par le dossier partagé » : réessayer plus tard) ou un partage plus récent que le code (faire `git pull` d'abord).
- Après la première publication en format 2 sur un ancien partage, `patrick.db.gz`, `models.zip` et `store.zip` restent dans le
  dossier (une trentaine de Go) : le programme les **signale** mais ne les supprime jamais ; à supprimer à la main.
- Une publication s'arrête (sans rien changer au partage) quand le disque du dossier a moins de 5 Go libres, et reprend à la
  suivante. Attention : avec Google Drive en mode « diffusion en continu » (lecteur `F:`), cet espace libre est celui de `C:`.

## Google Drive pour ordinateur

- **Mode « Miroir » recommandé** (Préférences de Drive, « Mes fichiers » : « Mettre en miroir les fichiers ») avec un dossier sur
  un disque qui a de la place : le dossier partagé devient un vrai dossier NTFS, sans cache caché sur `C:`. En mode « diffusion
  en continu », tout fichier écrit passe par le cache du Drive (`%LOCALAPPDATA%\Google\DriveFS`) qui peut occuper des dizaines de Go
  sur `C:` ; et un fichier lu sur l'autre PC est d'abord téléchargé dans ce cache.
- Le quota Google se lit sur <https://drive.google.com/drive/quota> ; le « libre » du lecteur `F:` ne le reflète pas.
- **Jamais la base vivante** (`~/.patrick/patrick.db`) ni `feature_cache` dans un dossier synchronisé : une base SQLite ouverte
  peut s'y corrompre, et le Drive garde les anciennes versions d'un fichier remplacé.
- Incident du 10-12/11/2026 : l'ancien format reconstruisait `store.zip` (30 Go) dans le dossier temporaire à chaque publication ;
  le cache du Drive a rempli `C:` (16 Go libres), le client Drive s'est figé (100 % d'un cœur, aucun réseau, lecture impossible sur
  `F:`) et des `.part` vides restaient dans le dossier. Réparation : fermer Drive, mettre de côté son dossier `DriveFS`, rouvrir
  Drive et se reconnecter. Les commandes qui modifient `%LOCALAPPDATA%` doivent être lancées dans **ton** PowerShell, pas depuis
  l'application Claude (qui voit un `AppData` virtualisé).

## Cache de variables partagé : la réserve (ADR 0021)

Les deux PC peuvent se partager le cache de variables (`feature_cache`, 250 Go sur le premier PC) : un fichier calculé par l'un évite à l'autre de
le recalculer. Les runs continuent de lire le cache **local** ; une **réserve** dans le Drive ne sert qu'aux défauts de cache, ne reçoit que du neuf
(jamais d'écrasement), est plafonnée à 150 Go et n'est **jamais purgée par le programme** (sauf un fichier cassé). Si le Drive est absent ou figé,
PATRICK continue avec le cache local. Le dossier `cache` (séries téléchargées, 1,4 Go) n'est pas partagé : ses fichiers sont réécrits en place.

Mise en place, sur **chaque PC**, une fois qu'il a le code à jour et que Drive est « Synchronisé » (dans **ta** fenêtre PowerShell, PATRICK fermé ; la
première copie dure des heures, la commande est reprenable) :

```text
cd <dossier du projet>\patrick
.venv\Scripts\patrick.exe storage share-feature-cache --to "<dossier du Drive>\Patrick Shared Folder\feature_cache" --max-gb 150
```

- Avant chaque copie, 20 Go doivent être libres sur le disque de la réserve (avec Drive en diffusion en continu, c'est l'espace libre de `C:`) ; sinon la
  commande attend que Drive ait envoyé, puis s'arrête proprement : relancer la même commande.
- **Mémoire de l'ordinateur** : la commande attend (puis s'arrête proprement) si la mémoire allouable tombe sous 2 Go, et un `MemoryError` en pleine copie la
  fait s'arrêter sans fichier coupé. Le 14/11/2026 l'**interface web de Google Drive** (processus `msedgewebview2` de `GoogleDriveFS.exe`) tenait 21 Go de
  mémoire privée en suivant l'activité de 30 000 fichiers envoyés : la copie a échoué faute de mémoire. **Pendant une grosse copie, n'ouvre pas la fenêtre
  d'activité de Drive** ; si la commande s'arrête sur la mémoire, cherche le processus le plus gourmand (Gestionnaire des tâches), quitte Drive puis rouvre-le.
- `--dry-run` compte sans rien régler ni copier ; `--no-seed` règle seulement le dossier ; `--off` désactive la réserve sur ce PC (le dossier partagé n'est
  pas touché).
- Le deuxième PC peut lancer la même commande : il ne copie que ce qui manque. Pour **réutiliser** les calculs de l'autre PC, les deux doivent avoir la même
  version de PATRICK (le code des variables fait partie de la clé) et les mêmes snapshots du magasin (donc la synchronisation à jour).
- Purge : quand la réserve est pleine elle cesse de grossir. Pour la vider, supprimer des sous-dossiers de `feature_cache` dans le Drive, puis **vider la
  corbeille de Google** (sinon le quota ne baisse pas pendant 30 jours).

## Listes de suivi, carnet et journal de prédictions (2026-11-02)

- **Listes de suivi** (`watchlist`) : fusionnées par nom (insensible à la casse ASCII, comme leur contrainte d'unicité). Une liste déjà présente n'est jamais modifiée :
  si deux PC ont modifié la même liste, chacun garde la sienne.
- **Carnet de recherche** (`research_note`) : union dédoublonnée sur le contenu (date de création, type, titre, texte, étiquettes, cible, horizon, run). Une note retouchée sur un
  PC après avoir été copiée apparaît en double (l'ancienne version et la nouvelle) : le contenu a changé, rien ne dit laquelle garder.
- **Journal de prédictions** (`prediction_journal`) : fusionné depuis la migration 0050 (ADR 0015). Chaque PC garde SA chaîne d'empreintes ; les lignes de l'autre sont recopiées telles quelles
  (empreintes et `trial_id` compris, ils sont dans la charge utile hachée) et marquées `imported_from`. `journal.verify` vérifie la chaîne locale, puis chaque ligne importée contre le
  `prev_hash` qu'elle annonce. Une ligne retirée côté importé est détectée (`imported_prev_missing`), une ligne modifiée aussi (`imported_hash_mismatch`) ; une ligne fausse bien chaînée ne l'est pas.
  Un PC sans la migration 0050 est refusé par la fusion : mettre le code à jour sur les deux PC.

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
