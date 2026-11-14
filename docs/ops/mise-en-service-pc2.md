# Mise en service du PC 2 : instructions pour Claude Code

**Ce fichier est écrit pour une session Claude Code lancée sur le PC 2** (le deuxième ordinateur de Léon, celui qui n'est pas la référence du patrimoine).
Lis-le en entier, puis exécute les étapes dans l'ordre, sans en sauter. Léon est **débutant** : explique chaque commande la première fois qu'elle apparaît,
réponds en français, reste concis. Aucune étape ne supprime de donnée de recherche : si une commande te semble en supprimer, arrête-toi et demande.

Contexte détaillé (pour comprendre, pas pour agir) : [partage-entre-pc.md](partage-entre-pc.md), [passage-au-partage-en-clair.md](passage-au-partage-en-clair.md),
ADR [0020](../adr/0020-partage-en-clair-et-incremental.md) et [0021](../adr/0021-reserve-partagee-du-cache-de-variables.md).

## 1. Où on en est (écrit le 14/11/2026 par la session du PC 1)

| Élément | État |
|---|---|
| Partage entre PC | Depuis le 13/11, le PC 1 publie dans le dossier Google Drive `Patrick Shared Folder` au format « en clair » (ADR 0020) : `manifest.json`, `db/`, `models/`, `store/`. Le PC 2 doit avoir le code qui sait le lire (commit `75fe360` ou plus récent). |
| Cache de variables partagé | Code fusionné dans `main` au commit `55357d3` (ADR 0021). Le PC 1 doit d'abord amorcer la réserve (dossier `Patrick Shared Folder\feature_cache` dans le Drive) ; cela dure des heures. |
| Branche `stable` (celle que suit le lanceur du PC 2) | Le 14/11 au matin elle était à `cdd257c` : elle contient le partage en clair mais **pas encore** le cache partagé. Elle passe à `55357d3` quand la CI de `main` est verte. Vérifier : `git ls-remote origin stable`. |
| Ancien partage | Les anciens `patrick.db.gz`, `models.zip`, `store.zip` peuvent encore traîner dans le dossier ; Léon les supprime. Ne les touche pas. |

## 2. Règles

- **PATRICK reste fermé** (pas de fenêtre, pas de `patrick serve`) et **aucun entraînement ne tourne** pendant les étapes 2 à 7. Vérifie les processus `python` / `pythonw`.
- Ne supprime rien : ni l'ancien dossier OneDrive, ni la base `~/.patrick/patrick.db`, ni les données (`data_root`). Ne touche à la base que par `patrick sync`.
- Ce PC **n'est pas** la référence du patrimoine (le PC 1 l'est) : n'écris jamais `--wealth-reference`. Si `sync_wealth_reference` vaut `true` ici, demande à Léon avant de le changer.
- **Ce qui dure plus de 2 minutes** (première fusion, étape 6) : donne la commande à Léon pour **sa** fenêtre PowerShell (menu Démarrer, taper `PowerShell`, Entrée), pas depuis l'application Claude : l'application arrête ses programmes enfants et voit un `AppData` virtualisé.
  Même raison : ne modifie rien sous `%LOCALAPPDATA%` depuis l'application Claude.
- Ne saisis jamais d'identifiant Google : la connexion à Google Drive est faite par Léon.
- N'abîme pas le dossier suivi par le lanceur : **ne modifie aucun fichier** du dossier du projet (`%USERPROFILE%\PATRICK-stable` en général). Une modification locale fait ignorer les mises à jour automatiques.

## 3. Communiquer avec la session du PC 1 : le journal

Le canal est un fichier du dossier partagé Google Drive : **`JOURNAL-PC2.md`**, dans `Patrick Shared Folder` (créé par la session du PC 1 ; crée-le avec un titre si
tu ne le trouves pas). Les deux sessions le lisent et **peuvent le modifier** : c'est le seul endroit où écrire pour parler à l'autre session.

- **Ajoute une entrée à la fin** (n'efface ni ne réécris les entrées des autres), de la forme :
  `### AAAA-MM-JJ HH:MM — PC 2 — étape N — OK | BLOQUÉ | QUESTION`, puis quelques lignes : ce que tu as fait (commandes et résultats utiles), ce qui bloque, ce que tu demandes.
- Écris une entrée **au début** (diagnostic de l'étape 0), **à la fin de chaque étape**, et **dès qu'une étape échoue ou qu'une décision dépend de Léon ou de la session du PC 1**.
  La session du PC 1 répond par une entrée `### ... — PC 1 — réponse`.
- Pas de secret dans le journal : ni mot de passe, ni jeton, ni clé d'API (le dossier du Drive peut être partagé).
- Si ce fichier d'instructions contient une erreur, **dis-le dans le journal**. Tu peux proposer une correction : copie le fichier hors du dossier suivi (par exemple dans
  `%USERPROFILE%\Documents\PATRICK-instructions`), modifie la copie et mentionne-la dans le journal ; la session du PC 1 la reportera dans le dépôt.

## 4. Étapes

Remplace `<projet>` par le dossier du projet (normalement `%USERPROFILE%\PATRICK-stable`), et `<partage>` par le chemin complet de `Patrick Shared Folder` tel que ce PC le voit.

### Étape 0 : diagnostic en lecture seule

```text
Get-Content "$env:USERPROFILE\.patrick\settings.json"
git -C "<projet>" fetch origin
git -C "<projet>" log --oneline -3
git -C "<projet>" status --short
git -C "<projet>" ls-remote origin stable
Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='LibreGo';e={[math]::Round($_.Free/1GB)}}
Get-ScheduledTask -TaskName PATRICK-Sync
Get-Process python, pythonw -ErrorAction SilentlyContinue
```

Relève : `sync_folder` (OneDrive ? Google Drive ? absent ?), `sync_wealth_reference`, `data_root`, le commit installé, les modifications locales (il ne doit pas y en avoir), la place libre de chaque
disque, si la tâche `PATRICK-Sync` existe, si Google Drive pour ordinateur est installé (processus `GoogleDriveFS`, lecteur virtuel éventuel) et si `<partage>` est visible avec `manifest.json` (environ 3 Mo)
et les dossiers `db`, `models`, `store`. **Écris l'entrée 0 du journal** et résume à Léon avant de continuer.

### Étape 1 : suspendre la publication horaire

```text
Disable-ScheduledTask -TaskName PATRICK-Sync
```

(Si la tâche n'existe pas, passe : elle sera créée à l'étape 8.) Pourquoi : l'ancien code publierait l'ancien format dans le dossier partagé.

### Étape 2 : mettre le code à jour

```text
cd "<projet>\patrick"
.venv\Scripts\python.exe -m patrick.desktop update --check
.venv\Scripts\python.exe -m patrick.desktop update
git log --oneline -3
git merge-base --is-ancestor 75fe360 HEAD; if ($?) { "partage en clair : OK" } else { "code trop ancien" }
git merge-base --is-ancestor 55357d3 HEAD; if ($?) { "cache partagé : OK" } else { "cache partagé : pas encore" }
```

Attendu : « partage en clair : OK ». « cache partagé : pas encore » est normal tant que `stable` n'a pas avancé : continue jusqu'à l'étape 6, puis revois l'étape 7. Si la mise à jour répond « ignorée », ou si des
modifications locales existent : arrête-toi, explique et écris dans le journal. Si `75fe360` n'est toujours pas atteint : **arrête-toi** (le reste dépend de ce code).

### Étape 3 : Google Drive

- Google Drive pour ordinateur doit être installé et connecté au **même compte Google** que le PC 1 (Léon le fait, tu ne saisis rien). `<partage>` doit contenir `manifest.json`, `db`, `models`, `store`.
- Deux modes : **diffusion en continu** (un lecteur virtuel, par exemple `F:` ; les fichiers sont dans le nuage et copiés à la demande dans un cache sur `C:`) ou **Miroir** (un vrai dossier sur un de tes disques, tous les
  fichiers du Drive y sont copiés). En diffusion en continu, **l'espace libre du lecteur virtuel est celui de `C:`** : il faut au moins **100 Go libres sur `C:`**. Sinon propose à Léon le mode Miroir vers un disque qui a la place
  (Préférences de Drive, à régler par Léon) et écris-le dans le journal.
- Attends que l'icône de Drive dise « Synchronisé » (Léon regarde) : tant que le PC 1 n'a pas fini d'envoyer, la lecture échoue avec « pas entièrement recopié » (sans danger : on réessaie).

### Étape 4 : dire à PATRICK où est le partage

```text
cd "<projet>\patrick"
.venv\Scripts\patrick.exe sync setup --folder "<partage>" --no-wealth-reference
.venv\Scripts\python.exe -c "from patrick import sync; sync.forget_exchange()"
Get-Content "$env:USERPROFILE\.patrick\settings.json"
```

Attendu : `sync_folder` = `<partage>`, `sync_wealth_reference` absent ou `false`. (`forget_exchange` oublie l'état d'échange avec l'ancien dossier ; il ne touche pas aux données.)

### Étape 5 : place pour la première fusion

La première fusion copie jusqu'à environ 47 Go (modèles et magasin du PC 1) sur le disque de données de ce PC (`data_root` ; à défaut `%USERPROFILE%\.patrick`). Exige **au moins 60 Go libres** là, plus la place d'une sauvegarde
de la base si l'étape 2 en a fait une. Sinon : arrête-toi et dis-le (journal + Léon).

### Étape 6 : première fusion (à lancer par Léon)

Dans la fenêtre PowerShell de Léon, PATRICK fermé :

```text
cd "<projet>\patrick"
.venv\Scripts\patrick.exe sync auto --log-file "$env:USERPROFILE\.patrick\logs\sync.log"
```

Attendu : une ligne `fusion : N run(s) importé(s) du partage (a -> b)`, puis éventuellement `publication : …` et `fonds publiés : …`. Peut durer longtemps (lecture d'environ 47 Go) ; si elle est coupée, relancer la même commande.
Messages et réponses : « pas entièrement recopié » = Drive n'a pas fini, attendre « Synchronisé » et relancer ; « Disque presque plein » = libérer de la place avant de relancer ; `KeyError` = code trop ancien (étape 2).
Écris l'entrée 6 du journal avec la ligne de résultat.

### Étape 7 : cache de variables partagé (seulement si l'étape 2 a dit « cache partagé : OK »)

Condition préalable : **le PC 1 a fini d'amorcer la réserve** (demande à Léon ou lis le journal) et le dossier `<partage>\feature_cache` existe avec de nombreux sous-dossiers (`00` à `ff`). Sinon, attends : écris « en attente du PC 1 » dans le journal.

```text
cd "<projet>\patrick"
.venv\Scripts\patrick.exe storage share-feature-cache --to "<partage>\feature_cache" --max-gb 150 --no-seed
Get-Content "$env:USERPROFILE\.patrick\settings.json"
```

`--no-seed` règle seulement le dossier (le PC 2 lira la réserve du PC 1 sur ses défauts de cache et y ajoutera ce qu'il calcule, sous le plafond de 150 Go) sans copier son propre cache : la réserve est déjà presque pleine. Vérifie que
`settings.json` contient `feature_cache_shared_root`. Pour désactiver : `.venv\Scripts\patrick.exe storage share-feature-cache --off` (rien n'est supprimé). Pour **réutiliser** les calculs du PC 1, les deux PC doivent avoir la **même version** de PATRICK.

### Étape 8 : réactiver la publication horaire

```text
Enable-ScheduledTask -TaskName PATRICK-Sync
(Get-ScheduledTask -TaskName PATRICK-Sync).State
.venv\Scripts\patrick.exe sync status
```

Attendu : `Ready` et « À faire : rien, tout est à jour ». Si la tâche n'existait pas : `.venv\Scripts\patrick.exe sync setup --folder "<partage>" --no-wealth-reference --schedule` la crée (à lancer depuis le dossier du projet, avec le venv du projet).
La publication complète ne se fait qu'**au plus toutes les 24 h** ; pour publier tout de suite : `.venv\Scripts\patrick.exe sync auto --min-push-hours 0`.

### Étape 9 : rapport

Écris dans le journal une entrée finale `étape 9 — OK` : commit installé (`git log --oneline -1`), `sync_folder`, résultat de la fusion (runs importés), état de la tâche, cache partagé réglé ou en attente, et tout ce qui reste à faire. Dis à Léon qu'il pourra vider l'ancien dossier OneDrive de PATRICK dans quelques jours,
**seulement s'il n'est plus utilisé** : toi, tu n'y touches pas.

## 5. Dépannage

| Symptôme | Que faire |
|---|---|
| `KeyError` en lisant le manifeste | Le code est resté ancien : étape 2. |
| « pas entièrement recopié par le dossier partagé » | Drive n'a pas fini : attendre « Synchronisé », relancer. |
| « Disque presque plein » | Libérer de la place (`C:` avec Drive en diffusion en continu ; sinon le disque de données), relancer la même commande : elle reprend. |
| « publication reportée : dernière publication il y a … h » | Normal (délai de 24 h) ; `sync auto --min-push-hours 0` pour publier tout de suite. |
| « publication reportée : le partage contient des données pas encore fusionnées » | Lancer `sync auto` (fusion puis publication). |
| Le lecteur Drive est illisible, Drive à 100 % d'un cœur et aucun réseau | Léon ferme Drive et le rouvre ; en dernier recours, voir « Si quelque chose se passe mal » dans [passage-au-partage-en-clair.md](passage-au-partage-en-clair.md). |
| La mise à jour répond « ignorée » | Modifications locales dans le dossier du projet, ou dossier pas sur `main` : écrire dans le journal, ne rien forcer. |
| Quelque chose qui ressemble à une suppression de données | Arrêt immédiat, journal, Léon. |

## 6. Côté PC 1 (pour mémoire ; fait par Léon et la session du PC 1, pas par toi)

1. Dans la fenêtre PowerShell de Léon, amorcer la réserve en **deux temps**, pour laisser de la place aux fichiers neufs des deux PC :
   `patrick storage share-feature-cache --to "<partage>\feature_cache" --max-gb 100` (copie les 100 Go les plus récents, des heures, reprenable), puis `patrick storage share-feature-cache --to "<partage>\feature_cache" --max-gb 150 --no-seed`.
2. Quand Drive est « Synchronisé », écrire une entrée `PC 1 — réserve prête` dans le journal.
3. Plus tard (décision de Léon, pas automatique) : `patrick storage evict` ramène le cache **local** sous son plafond de 150 Go (les fichiers retirés se recalculent ; faire après l'amorçage).
