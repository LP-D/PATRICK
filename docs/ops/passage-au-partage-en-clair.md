# Mise en service du partage en clair (format 2) : procédure pas à pas

Contexte : [ADR 0020](../adr/0020-partage-en-clair-et-incremental.md) et [partage-entre-pc.md](partage-entre-pc.md). Cette procédure fait passer les deux PC
de l'ancien partage (archives `.zip` / `.gz`, dossier Google Drive dans un état mélangé depuis le 11/11/2026) au partage en clair.
Compter une demi-journée, dont une à deux heures d'attente de l'envoi vers Google Drive.

**Une fenêtre PowerShell**, c'est la fenêtre où l'on tape des commandes. Pour l'ouvrir : touche Windows, taper `PowerShell`, Entrée.
Toutes les commandes de cette page se collent dans **ta** fenêtre PowerShell, **pas dans l'application Claude** (qui voit un
`AppData` faussé et arrête ses programmes enfants). `git` est l'outil qui télécharge la dernière version du code.

## Les règles à ne pas enfreindre

1. L'autre PC ne doit **ni ouvrir PATRICK ni publier** tant qu'il n'est pas à jour : son ancien code republierait l'ancien format dans le
   même dossier (étape 3).
2. Aucun run en cours pendant les étapes 4 à 8, PATRICK fermé sur le PC qu'on traite.
3. On ne passe à l'étape suivante que si la vérification de l'étape est bonne. En cas de doute : s'arrêter et demander.

## Étape 1 : libérer de la place sur `C:` (ce PC, tout de suite)

Pourquoi : Google Drive en diffusion en continu garde son cache sur `C:`, et le premier envoi fait passer environ 47 Go. Le 12/11, la
réinitialisation de Drive a laissé deux dossiers de cache mis de côté (78 Go et 21 Go) ; tout leur contenu est dans le nuage.

Avant : vérifier que Drive est calme (icône dans la zone de notification : « Synchronisé ») et que `F:` s'ouvre dans l'Explorateur.

```text
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Google\DriveFS.ancien-20261112b"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\Google\DriveFS.ancien-20261112"
"{0:N0} Go libres sur C:" -f ((Get-PSDrive C).Free / 1GB)
```

Vérifier : au moins 100 Go libres sur `C:`. La suppression est définitive (pas de corbeille) ; elle peut prendre quelques minutes.

## Étape 2 : fusionner la pull request et attendre la CI de `main`

1. Sur la page de la pull request (GitHub), bouton **Merge pull request**, puis **Confirm merge**.
2. Ouvrir <https://github.com/LP-D/PATRICK/actions> : la CI de `main` lance quatre tâches (`fast-suite` 3.11, `fast-suite` 3.12,
   `slow-suite`, `promote`). La suite lente dure environ 40 minutes. `promote` avance la branche `stable` que suivent les PC.

Vérifier : les quatre tâches sont vertes, `promote` comprise. **Si une est rouge, ne rien mettre à jour** : le code reste dans `main`
et personne ne le reçoit.

## Étape 3 : préparer l'autre PC (avant toute publication)

Sur l'autre PC, PATRICK fermé :

```text
Disable-ScheduledTask -TaskName PATRICK-Sync
Get-Content "$env:USERPROFILE\.patrick\settings.json"
```

La première commande suspend sa publication horaire (elle se réactive à l'étape 9). La seconde affiche ses réglages : noter la ligne
`sync_folder` (dossier OneDrive ou Google Drive ?) et la ligne `sync_wealth_reference`. Un seul PC doit être la référence du patrimoine :
ce PC-ci l'est aujourd'hui (`true`), donc l'autre doit afficher `false` ou n'avoir aucune ligne `sync_wealth_reference`.

## Étape 4 : mettre à jour ce PC

PATRICK fermé :

```text
cd C:\Users\leonp\PATRICK
git status
git pull --ff-only origin main
git log --oneline -3
```

Vérifier : `git status` ne montre aucun fichier modifié avant le `pull` (sinon s'arrêter), le `pull` annonce `Fast-forward` et
`sync_tree.py` dans la liste, et `git log` affiche le commit « feat(sync): partage en clair et incrémental (format 2) ».

## Étape 5 : vider l'ancien partage dans Google Drive

Dans le navigateur : <https://drive.google.com> > Mon Drive > `Patrick Shared Folder`. **Supprimer** : `manifest.json`, `patrick.db.gz`,
`models.zip`, `store.zip` et les cinq fichiers qui se terminent par `.part` (`patrick.db.gz.part`, `patrick (1).db.gz.part`…).
**Garder** `funds-DESKTOP-AV3KKV0.db.gz` et `funds-DESKTOP-AV3KKV0.json`. Puis menu de gauche > **Corbeille** > **Vider la corbeille**
(sinon Google compte encore ces 33 Go pendant 30 jours).

Pourquoi aussi `manifest.json` : un ancien manifeste dont les archives sont absentes ou différentes ferait refuser la fusion et reporter
la publication (« le partage contient des données pas encore fusionnées ») sans fin.

Vérifier : le dossier ne contient plus que les deux fichiers `funds-…`.

## Étape 6 : première publication en clair (ce PC)

PATRICK fermé, aucun run en cours :

```text
cd C:\Users\leonp\PATRICK\patrick
.venv\Scripts\patrick.exe sync auto --min-push-hours 0 --log-file C:\Users\leonp\.patrick\logs\sync.log
```

`--min-push-hours 0` supprime le délai de 24 h pour cette fois. L'envoi copie environ 47 Go et 31 000 fichiers (la base, le magasin, les
modèles) dans le dossier de Drive, qui les envoie ensuite vers Google : compter de quelques dizaines de minutes à deux heures. **Laisser la
fenêtre ouverte.** Pendant l'envoi, surveiller l'espace de `C:` de temps en temps :

```text
"{0:N0} Go libres sur C:" -f ((Get-PSDrive C).Free / 1GB)
```

La commande s'arrête d'elle-même, sans rien abîmer, si le disque du dossier tombe sous 5 Go libres (message « Disque presque plein ») : attendre
que l'icône de Drive redevienne « Synchronisé », puis **relancer la même commande**, qui reprend où elle s'est arrêtée. Même chose si le PC
s'est mis en veille.

Vérifier : la dernière ligne ressemble à `publication : 4230 run(s), 3374 modèle(s), patrimoine inclus` (les nombres ont changé depuis).

## Étape 7 : vérifier

```text
.venv\Scripts\patrick.exe sync status
```

Attendu : `À faire : rien, tout est à jour`. Dans le navigateur, `Patrick Shared Folder` contient `manifest.json`, `db`, `models`, `store`, et
la page <https://drive.google.com/drive/quota> compte environ 47 Go de plus qu'après l'étape 5. Attendre que l'icône de Drive dise
« Synchronisé » : l'autre PC ne peut rien lire avant.

## Étape 8 : réactiver la publication horaire (ce PC)

```text
Enable-ScheduledTask -TaskName PATRICK-Sync
(Get-ScheduledTask -TaskName PATRICK-Sync).State
```

Attendu : `Ready`. Elle passe toutes les heures, mais ne republie la base qu'au bout de 24 h au moins (journal : « publication reportée :
dernière publication il y a … h »).

## Étape 9 : mettre à jour l'autre PC, puis réactiver sa tâche

1. **Code** : ouvrir PATRICK (la mise à jour se fait au démarrage, si `stable` a avancé à l'étape 2) ou, à la main, dans PowerShell :
   `cd $env:USERPROFILE\PATRICK-stable`, puis `git fetch`, puis `git merge --ff-only origin/stable`, puis `git log --oneline -3` (même commit
   qu'à l'étape 4). Si le lanceur répond « mise à jour ignorée », faire la version à la main.
2. **Google Drive** sur cet ordinateur : même compte Google, dossier `Patrick Shared Folder` visible. S'il manque de place sur son `C:`
   (au moins 100 Go libres pour la diffusion en continu), choisir plutôt le mode « Miroir » vers un autre disque.
3. **Dossier partagé de PATRICK** : si `sync_folder` (étape 3) est l'ancien dossier OneDrive, le changer vers le dossier Google Drive dans
   PATRICK > Réglages. **Ne pas cocher « référence du patrimoine »** si c'est l'autre PC la référence.
4. Fermer PATRICK, puis dans PowerShell : `cd $env:USERPROFILE\PATRICK-stable\patrick`, puis
   `.venv\Scripts\patrick.exe sync auto --log-file $env:USERPROFILE\.patrick\logs\sync.log`. La première fusion lit environ 47 Go : elle
   peut durer longtemps. Attendu : une ligne `fusion : N run(s) importé(s) du partage`.
5. `Enable-ScheduledTask -TaskName PATRICK-Sync`.

## Étape 10 : nettoyage, deux ou trois jours plus tard

Si tout est stable : l'ancien dossier OneDrive de PATRICK (32 Go, `OneDrive - DVHE\Documents\MES FICHIERS\PERSO\PATRICK`) peut être vidé,
**à condition que l'autre PC ne l'utilise plus** (étape 9.3).

## Si quelque chose se passe mal

| Symptôme | Que faire |
|---|---|
| « Disque presque plein » à l'étape 6 | Attendre « Synchronisé » dans Drive, relancer la même commande. |
| `F:` illisible, Drive à 100 % d'un cœur, aucun réseau | Fermer Drive, puis `powershell -File C:\Users\Public\Documents\drive_reset.ps1` (renomme le dossier d'état de Drive en `DriveFS.ancien-20261112b` et le relance) ; se reconnecter à Google ; relancer l'étape 6. Le script refuse s'il existe déjà un dossier de ce nom : le supprimer d'abord (étape 1). |
| L'autre PC affiche « pas entièrement recopié par le dossier partagé » | Drive n'a pas fini de télécharger : attendre « Synchronisé » sur cet ordinateur, relancer `sync auto`. |
| L'autre PC affiche `KeyError` en lisant le manifeste | Son code est resté ancien : étape 9.1. |
| « publication reportée : dernière publication il y a … h » | Normal (délai de 24 h) ; publier tout de suite avec `.venv\Scripts\patrick.exe sync auto --min-push-hours 0`. |
| « publication reportée : le partage contient des données pas encore fusionnées » | L'autre PC a publié : lancer `sync auto` (fusion puis publication). |

Rien dans cette procédure ne touche à la base locale ni à `D:\PATRICK DATA` : les données de recherche restent sur chaque PC, le dossier partagé
n'est qu'une copie d'échange qu'on peut toujours reconstruire par l'étape 6.
