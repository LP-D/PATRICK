# Données de PATRICK sur le disque D: (la base active reste sur le SSD)

Date : 2026-10-21. Demande de Léon : « au lieu d'utiliser le cloud pour tout enregistrer, tout sera enregistré sur ce PC, sur le disque
secondaire (HDD) D:, dans le dossier PATRICK DATA ; arborescence propre ; pouvoir faire fonctionner PATRICK depuis un autre PC en partageant
sur OneDrive ou GitHub le nécessaire, avec toutes les fonctionnalités, sans l'énorme enregistrement dans le cloud ». Décision prise après
l'analyse du 21/10 : **la base active (`patrick.db`) reste sur le SSD (C:), tout le reste va sur D:**, le partage entre PC reste **OneDrive**.

## 1. Constat (mesuré le 21/10/2026)

| Élément | Où | Taille | Source |
|---|---|---|---|
| `feature_cache` | `C:\Users\leonp\.patrick` | 87 Go | `du` du 21/10 |
| `backups` (51 fichiers) | idem | 55 Go | idem |
| `patrick.db` | idem | 25 Go | idem |
| `store` (parquet par `snapshot=<date>`) | idem | 4,8 Go | idem |
| `cache` (téléchargements) | idem | 0,8 Go | idem |
| `models` (modèles restaurés par la synchro) | idem | 0,4 Go | idem |
| `app-profile-stable` (profil du navigateur de la fenêtre) | idem | 0,2 Go | idem |
| `patrick/runs` (sortie du moteur, dans le dépôt, ignoré par git) | `C:\Users\leonp\PATRICK\patrick\runs` | 1,1 Go | `du` du 21/10 |
| Partage OneDrive : base 0,8 + modèles 0,4 + magasin 3,1 + fonds 0,02 | dossier `…\PERSO\PATRICK` | ≈ 4,3 Go utiles (+ ≈ 4 Go de `.part` d'envois interrompus) | `ls` du 21/10 |

- **Rien d'énorme n'est dans le cloud** : tout est déjà local. Le cloud ne reçoit qu'une copie allégée (`sync.py::push` n'exporte ni
  `vol_model_cache` ni `shap_selection_cache` ; les tables personnelles `wealth_*`/`fund_*` ne partent que vers un dossier privé, jamais vers GitHub).
- **Le vrai problème est C:** : 99 % plein (7,5 Go libres sur 453), alors que D: a 435 Go libres. L'échec « database or disk is full » du
  10/10 vient de là (mémoire `sync-in-place-and-disk`).
- **D: est un disque dur mécanique SATA (WDC WD5000AAKS)**, C: un SSD NVMe (Crucial CT500P1SSD8) : `Get-PhysicalDisk` du 21/10. Une base
  SQLite de 25 Go fait surtout des lectures/écritures aléatoires, très mal servies par un disque dur : d'où la base sur le SSD.
- Les emplacements sont déjà réglables par variable d'environnement pour la base (`PATRICK_DB_PATH`), le magasin (`PATRICK_STORE_ROOT`),
  le cache (`PATRICK_CACHE_ROOT`) et le `feature_cache` (`PATRICK_FEATURE_CACHE_ROOT`). Les modèles, sauvegardes, rapports et archives
  sont écrits en dur sous `~/.patrick`.
- **Des chemins absolus sont stockés dans les données** (piège principal) :
  - `trial.artifact_path` : 796 lignes renseignées, dont **244 absolues** (`C:\Users\leonp\.patrick\models\<essai>\….joblib`, écrites par
    `sync._restore_models*`) et 552 relatives au dossier de travail du worker (`runs\<run>\….joblib`, écrites par le moteur) ;
  - `store/_index.json` (1,5 Mo) : chaque snapshot porte un `path` absolu (`C:\Users\leonp/.patrick/store\snapshot=…\….parquet`),
    relu tel quel par `DataStore` (`pd.read_parquet(entry["path"])`).

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs**
1. Libérer C: (≈ 148 Go : feature_cache 87 + backups 55 + store 4,8 + cache 0,8 + models 0,4) et supprimer le risque « disque plein ».
2. Une **racine de données unique et réglable** (`D:\PATRICK DATA`), avec une arborescence lisible, branchée à tous les emplacements en dur.
3. Une **migration sûre** de l'existant (copie vérifiée, bascule, réécriture des chemins absolus, suppression de l'ancien seulement après
   accord), sans toucher à la base pendant qu'un run tourne.
4. Un autre PC fonctionne avec **les mêmes fonctionnalités** : code (git) + partage OneDrive existant ; sa racine de données est à son choix.

**Non-objectifs** (décidés)
- Le format et le contenu du partage OneDrive ne changent pas (`patrick.db.gz`, `models.zip`, `store.zip`, `funds-<pc>.db.gz`, `manifest.json`).
- `patrick/runs` (1,1 Go, chemins **relatifs** au dossier de travail du worker) **reste dans le dépôt** : le déplacer change `output.dir`,
  donc potentiellement le hachage de configuration et le golden master, pour un gain de 1 Go. Mon choix.
- Pas de politique de rétention des sauvegardes, pas de synchro incrémentale du magasin, pas de nettoyage des `.part` du dossier OneDrive
  (suites possibles, hors de cette spec ; les `.part` se suppriment à la main quand aucune synchro ne tourne).
- Pas de bouton « Déplacer » dans l'interface : commande en ligne + affichage en lecture seule dans Réglages.
- Aucun changement de schéma SQL : pas de migration, donc pas de collision de numéros avec les autres sessions.

**Anti-objectifs** (un échec même si « ça marche »)
- Retomber **silencieusement** sur `C:\Users\leonp\.patrick` quand D: est absent (disque débranché) : on s'arrête avec un message clair,
  on ne recrée pas un second cache de 87 Go sur C:.
- Changer le hachage de configuration, le golden master ou le comportement d'un run.
- Perdre un modèle, un snapshot du magasin ou une ligne de la base ; toucher au patrimoine et aux fonds (restent dans `patrick.db`).
- Envoyer des données sur GitHub : le dépôt `LP-D/PATRICK` est **public** (API sans connexion = HTTP 200), un asset de release est limité à
  2 Go (`store.zip` en fait 3,1) et `gh` n'est pas installé sur ce PC. GitHub reste pour le code seul. Décision de Léon : OneDrive.

## 3. Arborescence cible

Deux dossiers, deux rôles.

**Dossier maison** (reste `~/.patrick`, SSD) : tout ce qui est chaud, minuscule ou nécessaire pour retrouver D: en cas de panne.

```
C:\Users\leonp\.patrick\
  patrick.db (+ -wal, -shm)     base active
  settings.json                 réglages de la machine, dont `data_root`
  sync_state.json  relaunch.json  last_launch.json  update_state.json
  sync_undo\                    états de champions avant fusion (120 Ko)
  logs\                         journaux (dont celui qui dit « D: introuvable »)
  app-profile-stable\           profil du navigateur de la fenêtre (accès aléatoires)
```

**Racine de données** (réglable, ici `D:\PATRICK DATA`) :

```
D:\PATRICK DATA\
  store\            magasin de données (snapshot=<date>\*.parquet, _index.json, _series_observations.json)
  models\           modèles (<id d'essai>\*.joblib), restaurés par la synchro
  feature_cache\    caches de variables (reconstructibles)
  cache\            cache de téléchargement
  backups\          sauvegardes de la base (autre disque physique que la base : elles survivent à la panne du SSD)
  archive\          archives
  reports\          rapports HTML (aujourd'hui `~/.patrick/reports`)
  README.txt        « Données de PATRICK de ce PC. Ne pas partager ni déplacer à la main : voir `patrick data status`. »
```

Ma décision pour les journaux : ils restent dans le dossier maison, car la tâche planifiée `PATRICK-Sync` les référence en dur
(`--log-file C:\Users\leonp\.patrick\logs\sync.log`) et parce qu'un journal doit rester écrivable quand D: manque.

## 4. Résolution des emplacements

Nouveau module `patrick/paths.py` (nom : mon choix), **seul endroit** où `~/.patrick` est écrit. Fonctions lues **à chaque appel** (comme
`settings.py`, pour qu'un worker déjà lancé voie un changement de réglage) : `home_dir()`, `data_root()`, `store_dir()`, `models_dir()`,
`feature_cache_dir()`, `cache_dir()`, `backups_dir()`, `archive_dir()`, `reports_dir()`, `db_path()`, `logs_dir()`.

Priorité pour chaque emplacement :
1. variable d'environnement **du composant** si elle existe déjà (`PATRICK_DB_PATH`, `PATRICK_STORE_ROOT`, `PATRICK_CACHE_ROOT`,
   `PATRICK_FEATURE_CACHE_ROOT`) : inchangé, c'est ce qui isole les tests et l'aperçu ;
2. `PATRICK_DATA_ROOT` (nouvelle variable), puis la clé `data_root` de `settings.json` (nouveau réglage, **local à chaque PC**, jamais
   partagé) : `<racine>\store`, `<racine>\models`, etc. ;
3. à défaut, `~/.patrick` : **comportement actuel identique** (un PC à un seul disque ne change rien ; les tests existants passent
   sans modification).

La base : `db_path()` = `PATRICK_DB_PATH` sinon `~/.patrick/patrick.db`, jamais sous la racine de données. Pourquoi `settings.json` et pas
seulement une variable : la tâche planifiée `PATRICK-Sync`, le lanceur et les workers détachés n'héritent pas d'un `set` fait dans un terminal.

**Racine configurée mais absente** (lecteur ou dossier manquant) : lever une `DataRootUnavailable` expliquée (« Le disque de données
D:\PATRICK DATA est introuvable. Branche-le ou change le réglage `data_root`. ») ; le lanceur la vérifie avant de démarrer le serveur ; les
pages en lecture seule affichent un bandeau. Les sous-dossiers se créent automatiquement **si la racine existe** ; la racine elle-même
n'est créée que par `patrick data move` / `patrick data init`.

## 5. Ce qui doit passer par `paths.py`

À brancher (liste relevée par recherche de `.patrick` / `expanduser` dans `patrick/patrick`, à compléter par le constructeur avec un test
garde-fou, §8) :

- `tracking/backup.py` : `DEFAULT_BACKUP_DIR` est une **constante calculée à l'import** → fonction `backups_dir()` appelée à l'usage ;
  `scripts/backup_db.py`, `scripts/schtasks_daily_dbbackup.ps1` (non enregistrée comme tâche aujourd'hui), `fund/share.py:160`.
- `tracking/report.py` : `DEFAULT_REPORTS_DIR` (même piège de constante à l'import) ; `cli.py` (`--output`).
- `sync.py` : `_default_store_root`, `_default_models_roots`, les deux `~/.patrick/models` (pull et merge), `~/.patrick/logs/sync.log`,
  messages d'espace disque qui citent `~/.patrick/feature_cache` et `patrick.db.backup*`.
- `data/store.py`, `cache_manager.py`, `features/pool_cache.py` : déjà par variable ; les rattacher à la racine.
- `analysis/diagnostics.py::home()` : aujourd'hui `Path(PATRICK_DB_PATH).parent` ; la liste des dossiers (cache, feature_cache, store,
  models, backups) doit venir de `paths`, car **la base et les données n'ont plus le même parent**.
- `tracking/usage.py::artifact_roots()` : ajouter `models_dir()` aux dossiers de recherche des modèles.
- `desktop/share.py` : refuse un dossier de partage identique au dossier de données ; **ajouter** : refuser un dossier de partage situé
  dans la racine de données (et l'inverse).
- `webapp/i18n_settings.py` (`app_status_disk_low`) : l'espace libre se vérifie sur **les deux volumes** (base et données) et nomme le volume ;
  le texte ne cite plus `~/.patrick/…` en dur.
- Page Réglages : afficher la racine de données, son volume, l'espace libre des deux volumes et la taille par sous-dossier (lecture seule).
- Docs : `ARCHITECTURE.md`, `METHODOLOGY.md`, `README.md`, `NEXT_STEPS.md` citent `~/.patrick/…` ; mise à jour par une phrase renvoyant à `paths`.

## 6. Migration de l'existant : `patrick data`

Commandes (Typer, comme `sync`) : `patrick data status` (racine, volumes, espace, tailles, chemins non résolus), `patrick data init <dossier>`
(crée la racine et son `README.txt`), `patrick data move <dossier>` (en trois phases, ci-dessous), `patrick data rollback`.

**Pré-conditions, vérifiées et bloquantes** : serveur arrêté ; aucun `job` en `queued`/`running` ; pas de `worker_heartbeat` récent ; aucun
processus `patrick` détaché ; tâche planifiée `PATRICK-Sync` (publication horaire) désactivée pendant la migration puis réactivée, et lanceur
fermé (il publie à la fermeture) ; espace libre ≥ taille à copier + marge sur le volume cible ; racine cible hors du dossier maison et hors
du dossier de partage. (Règle de mémoire : jamais de maintenance de la base pendant qu'un worker vit : `no-db-maintenance-during-runs`.)

**Phase 1, copie** (reprenable, idempotente, ne modifie rien à la source) : `store`, `models`, `feature_cache`, `cache`, `backups`,
`archive`, `reports` vers la cible ; un fichier déjà présent à taille et date identiques est sauté ; vérification finale (nombre de
fichiers, octets) ; `models` et `store` vérifiés aussi par somme sha256 (petits : 0,4 et 4,8 Go). Avancement dans un fichier d'état lisible
par la page Réglages. Durée : plusieurs dizaines de minutes à plus d'une heure sur ce disque dur (**estimation** : ≈ 148 Go, disque ancien) ;
le processus se lance **détaché** (jamais dans l'application Claude : mémoire `long-runs-outside-claude-app`).

**Phase 2, bascule** (courte, transactionnelle) :
1. écrire dans `data_move_journal.json` (dossier maison) les anciennes valeurs de tout ce qui va changer ;
2. réécrire les **244 `trial.artifact_path` absolus** de `C:\Users\leonp\.patrick\models\…` vers `<racine>\models\…` en une transaction
   (les 552 relatifs ne bougent pas) ;
3. réécrire les `path` absolus de `store/_index.json` de la **nouvelle** copie (écriture atomique) ;
4. écrire `data_root` dans `settings.json`.
Pas de sauvegarde de 25 Go : le journal des anciennes valeurs suffit à défaire (et la base reste intacte sauf ces lignes).

**Phase 3, contrôle puis nettoyage** : contrôle de bout en bout (chaque `artifact_path` renseigné se résout en fichier existant ; chaque
snapshot de `_index.json` existe ; `DataStore` relit un snapshot ; `predict`/`live_refresh` chargent un modèle déplacé). L'ancien contenu
n'est supprimé que par `patrick data move --finalize` après accord explicite de Léon ; avant, `patrick data rollback` remet l'état d'origine
(réglage retiré, anciennes valeurs de chemins restaurées depuis le journal).

**Mesure de performance avant `--finalize`** (la base reste sur le SSD, mais `feature_cache` et `store` sont lus sur un disque dur) :
un run léger de référence avec `feature_cache` sur C: puis sur D: ; si D: est nettement plus lent (seuil proposé : > 30 %), `feature_cache`
reste sur C: grâce à `PATRICK_FEATURE_CACHE_ROOT` ou à un réglage par composant (le mécanisme existe déjà) ; sinon tout reste sur D:.

## 7. Autre PC

- Il récupère le code (`git pull`) ; aucun changement de schéma.
- Premier lancement : le lanceur fusionne le partage OneDrive comme aujourd'hui ; `_restore_models_merged` et `_restore_store` écrivent
  dans `models_dir()` / `store_dir()` **de cet autre PC** et y écrivent des `artifact_path` absolus locaux (comportement existant).
- Il choisit sa racine de données (`patrick data init <dossier>` puis réglage `data_root`) ou garde `~/.patrick` s'il n'a qu'un disque.
- Les caches (`feature_cache`, `vol_model_cache`) se reconstruisent à l'usage : premiers runs plus lents ; c'est la raison pour laquelle ils
  ne sont pas partagés. Le magasin, lui, **ne se reconstruit pas** (snapshots datés non rejouables) : il reste dans le partage.

## 8. Tests et vérification

**Tests automatiques** (la suite rapide doit rester verte ; la suite lente se lance par tronçons, mémoire `slow-suite-run-method`) :
- `paths` : priorité (variable de composant > `PATRICK_DATA_ROOT` > `data_root` > défaut) ; racine absente → `DataRootUnavailable`, jamais de
  création silencieuse ; constantes relues à chaque appel.
- Garde-fou : un test de dépôt interdit toute occurrence de `.patrick` / `expanduser("~/.patrick` dans `patrick/patrick` hors `paths.py`
  (modèle : `test_repo_hygiene`).
- Isolation : `conftest.py` pose `PATRICK_DATA_ROOT` sur un dossier temporaire pour **tous** les tests (comme il isole déjà le cache),
  de sorte qu'aucun test n'écrive dans la vraie racine ; un test scanne la vraie racine avant/après un échantillon de tests
  (incident du 10/10 : mémoire `preview-writes-real-cache`).
- Migration : sur un arbre temporaire avec une petite base (jamais la vraie) : copie reprenable après interruption ; bascule ; réécriture des
  `artifact_path` absolus et de `_index.json` ; rollback restitue exactement les anciennes valeurs ; pré-conditions (job en cours, worker vivant, espace) bloquent.
- `share.py` : refuse un partage dans la racine de données ; `sync` : `merge` restaure dans la racine locale ; `diagnostics` : liste les
  dossiers de `paths`.

**Vérification finale** (Léon l'attend avant de considérer la tâche finie) : `patrick data status` sans chemin non résolu ; C: avec ≥ 100 Go
libres ; un run léger complet de bout en bout ; une prédiction avec un modèle déplacé ; `sync auto` à blanc contre le dossier OneDrive ;
la tâche `PATRICK-Sync` exécutée une fois ; Réglages affiche les deux volumes. À faire **sur la vraie base** seulement après fermeture de
PATRICK par Léon et dans un worktree pour le code (mémoire `fund-sharing-onedrive` : une migration ou un test ne se fait pas dans le dossier
vivant `C:\Users\leonp\PATRICK`).

## 9. Reste au constructeur

Nom exact des commandes et des clés ; format du fichier d'état et du journal ; outil de copie (Python ou `robocopy`) ; textes FR/EN
(`t('clé')`, règles des « ? » de l'interface) ; emplacement du dossier temporaire de la synchro (laissé sur C: : l'espace sera libéré
par la migration) ; choix éventuel d'un réglage par composant (au lieu des seules variables d'environnement) pour `feature_cache` si la
mesure de performance l'exige.
