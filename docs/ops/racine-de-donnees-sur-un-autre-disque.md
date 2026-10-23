# Racine de données sur un autre disque : mémo pour les autres PC

Chantier du 21 au 23/10/2026, mené sur le PC de Léon (celui qui n'est pas la référence du patrimoine). **À lire sur chaque autre PC avant de mettre à jour.**
Spec : [`docs/superpowers/specs/2026-10-21-donnees-sur-disque-d-design.md`](../superpowers/specs/2026-10-21-donnees-sur-disque-d-design.md) ;
plan : [`docs/superpowers/plans/2026-10-21-donnees-sur-disque-d.md`](../superpowers/plans/2026-10-21-donnees-sur-disque-d.md).

## En bref

- Le disque système (C:, SSD) était plein à 99 % : `patrick.db` (28 Go) et surtout ~163 Go de données et de caches vivaient dans
  `~/.patrick`. Un « disk is full » avait déjà fait échouer des runs et la synchronisation.
- Les données lourdes peuvent maintenant vivre dans une **racine de données** sur un autre disque (ici `D:\PATRICK DATA`). **La base
  active, les journaux et les réglages restent dans `~/.patrick` (le disque rapide).**
- **Un PC à un seul disque n'a rien à faire** : sans réglage, tout reste dans `~/.patrick`, comme avant.
- Le partage OneDrive n'a pas changé de format. Rien n'est envoyé sur GitHub (le dépôt est public).

## Ce que le code fait maintenant

- `patrick/paths.py` est le seul module qui connaît `~/.patrick`. La racine se règle par `data_root` dans `settings.json` (réglage
  **propre à chaque PC, jamais partagé**) ou par la variable `PATRICK_DATA_ROOT` (elle prime). Les variables par composant
  (`PATRICK_STORE_ROOT`, `PATRICK_CACHE_ROOT`, `PATRICK_FEATURE_CACHE_ROOT`, `PATRICK_DB_PATH`) priment sur tout.
- Dossiers de la racine : `store`, `models`, `feature_cache`, `cache`, `backups`, `archive`, `reports`.
- **Racine configurée mais absente** (disque débranché) : le serveur, le worker et le lanceur refusent de démarrer avec un message clair ; les
  pages répondent 503 et affichent un bandeau ; la synchronisation se reporte. Jamais de repli silencieux sur C:.
- Commande `patrick data` : `status` (où sont les données, espace libre, chemins cassés), `init <dossier>`, `move <dossier>`,
  `move --finalize`, `rollback [--force]`, `use <dossier>` / `use --none` (change la racine sans rien déplacer).
- Un test de dépôt interdit d'écrire `~/.patrick` en dur ailleurs que dans `paths.py` : tout nouveau chemin passe par `paths`.

## Sur un autre PC

1. **Mettre à jour le code.** Le lanceur met à jour depuis la branche `stable` (alimentée après la CI) ; à la main : `git pull` sur
   `main`. Faire la mise à jour sur **tous** les PC (voir « Correctif du partage des modèles » : un PC resté sur l'ancien code publie
   un `models.zip` réduit).
2. **Si le PC n'a qu'un disque** : c'est fini. `patrick data status` doit afficher « Racine de données : aucune réglée ».
3. **Si C: manque de place, déplacer les données sur un autre disque** (dans **ton propre** PowerShell, pas depuis l'application Claude :
   la copie dure plus d'une heure et serait interrompue) :
   - fermer PATRICK, vérifier qu'aucun entraînement ne tourne, **désactiver la tâche planifiée** : `Disable-ScheduledTask -TaskName "PATRICK-Sync"` ;
   - `cd <dossier du projet>\patrick`, puis `.\.venv\Scripts\patrick.exe data status` (état de départ : 0 chemin cassé attendu) ;
   - `.\.venv\Scripts\patrick.exe data move "<disque>:\PATRICK DATA"` : refuse (« Refusé : … ») si PATRICK est ouvert, si un entraînement
     tourne, si la place manque ou si la cible est mal choisie ; sinon copie vérifiée (somme sha256 des modèles et du magasin),
     puis bascule du réglage et des chemins. **Reprenable** : si elle s'interrompt (veille, coupure), relancer la même commande ;
   - vérifier (un run rapide, une prédiction), puis `.\.venv\Scripts\patrick.exe data move --finalize` : revérifie toute la copie
     avant de supprimer l'ancien emplacement (irréversible, confirmation `o`). **C: ne se libère qu'à ce moment** ;
   - réactiver la tâche : `Enable-ScheduledTask -TaskName "PATRICK-Sync"`.
4. **Place temporaire.** La publication prépare ses fichiers dans le dossier temporaire de Windows (variable `TEMP`) et exige
   environ 5,4 Go libres : sur un disque système presque plein, elle est refusée (« Espace disque insuffisant »).

Ordre de grandeur sur le PC de Léon : ~163 Go copiés en une heure environ, puis suppression en quelques minutes.

## Correctif du partage des modèles (mis à jour avec le même chantier)

- **Symptôme** : le partage ne contenait que 34 modèles (`models.zip` de 27 Mo, contre 425 Mo auparavant).
- **Cause** : les modèles entraînés sur un PC ont un chemin **relatif au dossier du projet** (`runs/<run>/<modèle>.joblib`). La publication les
  cherchait depuis le dossier de travail de son processus. Le lanceur démarre dans le dossier du projet (il les trouve) ; la tâche planifiée
  `PATRICK-Sync` n'a pas de « Démarrer dans » et Windows la lance dans `C:\Windows\System32` : elle ne trouvait aucun modèle relatif. Sur le PC de
  Léon : 1 310 modèles trouvés sur 1 978 depuis la tâche, 1 928 depuis le lanceur.
- **Correctif** : `sync._project_dir()` ajoute le dossier du projet aux dossiers de recherche, quel que soit le dossier de travail.
- **Conséquences** : après la mise à jour, la première publication d'un PC embarque tous ses modèles (`models.zip` de l'ordre de 3 Go sur le PC de
  Léon) et sera longue à synchroniser par OneDrive. Un PC qui publie encore avec l'ancien code remet un `models.zip` réduit dans le partage.

## Dépannage

- **« Le disque de données … est introuvable »** : brancher le disque, ou `patrick data use <dossier>` / `patrick data use --none` (retire le
  réglage : tout revient dans `~/.patrick`). Refusé tant qu'un déplacement est en attente.
- **`patrick data move` refuse** : lire les raisons, elles sont explicites. Un déplacement vers une autre cible est refusé tant que le précédent
  n'est ni finalisé (`move --finalize`) ni annulé (`rollback`).
- **`rollback`** : possible tant que `--finalize` n'a pas démarré. Refusé si l'application a créé des fichiers sur la nouvelle racine depuis la bascule
  (ils resteraient orphelins) ; `--force` seulement en connaissance de cause. Impossible après `--finalize`.
- **`--finalize` interrompu** (fichier verrouillé par l'antivirus ou l'Explorateur) : fermer ce qui l'utilise et **relancer** la même commande ; la
  suppression reprend, elle ne se défait plus.
- **« Fichier corrompu (sha256 différent) : patrick.db.gz »** au moment de la fusion : le partage est incomplet parce que OneDrive n'a pas fini de
  rapatrier les gros fichiers publiés par l'autre PC. Attendre la fin de la synchronisation OneDrive ; la protection fait son travail. Tant que
  c'est le cas, les publications sont reportées (« le partage contient des données pas encore fusionnées »).
- **Tests** : `hypothesis` manque parfois dans le venv (un fichier de tests ne se collecte pas) ; `test_settings_parametric_jobs` peut échouer quand
  PATRICK tourne (plafond de ressources) ; `test_kill_process_tree…` échoue sous Windows indépendamment de ce chantier.

## Mesures (PC de Léon)

| | avant | après |
|---|---|---|
| Espace libre sur C: | 1,2 Go | ~155-164 Go |
| Lecture d'un fichier du `feature_cache` | 18 ms (SSD) | 107 ms (disque dur) |
| Lecture d'un fichier du `store` | 9 ms | 31 ms |

Le disque dur lit ~5 fois moins vite par fichier ; un run en lit quelques dizaines, face à plusieurs minutes de calcul : négligeable (seuil de 30 % non approché).
Un run rapide complet a tourné sur la nouvelle racine sans erreur ; rien n'a été recréé sur C:.

## Limites connues

- Les préconditions de `patrick data move` ne sont pas revérifiées entre la copie et la bascule ; pas de `fsync` avant le renommage des copies ;
  `status` n'affiche pas la taille de chaque dossier ; les jonctions Windows ne sont pas résolues avant suppression.
- `DataRootUnavailable` n'est attrapée proprement que par `serve`, `worker`, le lanceur, la synchronisation et les pages web ; les autres commandes
  de `patrick` affichent une trace.
- Les aperçus (`.claude/launch.json`) qui ne posent que `PATRICK_DB_PATH` lisent la vraie racine de données : poser aussi `PATRICK_DATA_ROOT` (et
  `PATRICK_SETTINGS_PATH`) pour un aperçu isolé.
