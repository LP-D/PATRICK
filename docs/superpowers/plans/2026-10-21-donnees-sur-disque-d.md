# Données de PATRICK sur le disque D: — plan d'implémentation

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE REQUISE : `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans`. Les étapes sont des cases à cocher (`- [ ]`).

**Objectif :** une racine de données réglable (`D:\PATRICK DATA`) pour tout sauf la base active (`patrick.db`, SSD), et une commande `patrick data` qui déplace l'existant sans perdre un modèle ni un snapshot.

**Architecture :** un module `patrick/paths.py` devient le seul endroit qui connaît `~/.patrick` et la racine de données ; tous les emplacements en dur passent par lui. Un module `patrick/data_move.py` porte la migration en trois phases (copie reprenable, bascule avec journal, contrôle puis nettoyage). Le format du partage OneDrive ne change pas ; aucune migration SQL.

**Stack :** Python 3, Typer (CLI), SQLite (`sqlite3`), FastAPI/Jinja (Réglages), pytest. Dossier du projet Python : `C:\Users\leonp\PATRICK\patrick` (paquet `patrick/patrick`, tests `patrick/tests`).

**Spec :** `docs/superpowers/specs/2026-10-21-donnees-sur-disque-d-design.md` (lire d'abord ; ce plan renvoie à ses sections par §).

**Environnement d'exécution :** travailler dans un worktree (`git worktree add C:\Users\leonp\PATRICK-wt-data -b feat/donnees-disque-d`), jamais dans le dossier vivant (la tâche `PATRICK-Sync` et le lanceur y tournent). Lancer `python -m pytest` depuis `<worktree>\patrick` avec l'interpréteur de `C:\Users\leonp\PATRICK\patrick\.venv`, et vérifier d'abord que `python -c "import patrick; print(patrick.__file__)"` pointe dans le worktree. Ne jamais lire ni écrire le vrai `~/.patrick` dans une tâche de code (sauf T13, avec Léon).

## Contraintes globales (valeurs de la spec)

- Racine de données de Léon : `D:\PATRICK DATA` ; sous-dossiers exactement `store, models, feature_cache, cache, backups, archive, reports` (+ `README.txt`).
- Réglage `data_root` dans `settings.json` (local à chaque PC, jamais partagé) ; variable `PATRICK_DATA_ROOT`. Priorité : variable de composant (`PATRICK_DB_PATH`, `PATRICK_STORE_ROOT`, `PATRICK_CACHE_ROOT`, `PATRICK_FEATURE_CACHE_ROOT`) > `PATRICK_DATA_ROOT` > `data_root` > `~/.patrick` (comportement actuel identique).
- La base, `settings.json`, `sync_state.json`, `relaunch.json`, `last_launch.json`, `update_state.json`, `sync_undo/`, `logs/`, `app-profile-stable/` restent dans le dossier maison. `patrick/runs` reste dans le dépôt.
- Racine configurée mais absente : `DataRootUnavailable`, jamais de création silencieuse ni de repli sur C: ; la racine n'est créée que par `patrick data init` / `move`.
- Aucun changement de schéma SQL, de hachage de configuration, de golden master ni du format du partage OneDrive. Rien sur GitHub.
- Migration : copie reprenable ; `models` et `store` vérifiés par sha256 ; journal des anciennes valeurs (pas de sauvegarde de 25 Go) ; suppression de l'ancien seulement par `patrick data move --finalize` après accord explicite ; jamais pendant un run ni serveur ouvert.
- Seuil de la mesure de performance avant finalisation : `feature_cache` reste sur C: si D: est plus lent de plus de 30 %.
- Le `conftest.py` pose `PATRICK_DATA_ROOT` (dossier temporaire existant) pour tous les tests (T1) : tout test qui veut un PC « sans réglage » commence par `monkeypatch.delenv("PATRICK_DATA_ROOT", raising=False)`.
- Textes visibles : `t('clé')` FR/EN, phrases courtes (règles des « ? » de `help.js`). Tests rapides lancés en trois blocs (mémoire `fast-suite-split-run`).

## Points de vigilance (non couverts par la spec, chacun a son test)

1. **Chemins à séparateurs mixtes et casse Windows** : `_index.json` contient `C:\Users\leonp/.patrick/store\snapshot=…` ; la réécriture doit les reconnaître (T10).
2. **Copie interrompue** : un fichier partiel ne doit jamais passer pour une copie valide à la reprise (T9).
3. **Cible mal choisie** : racine déjà active, dans le dossier maison, dans la source ou dans le dossier de partage → refus clair (T9).
4. **Migration relancée** après succès, ou `rollback` après `--finalize` : sans effet / refusé, journal jamais écrasé (T10, T11).
5. **PC à un seul disque ou lettre de lecteur différente** : sans réglage, rien ne change ; l'autre PC restaure dans sa propre racine avec des `artifact_path` locaux (T1, T4).

---

### Tâche 1 : `patrick/paths.py` et isolation des tests

**Fichiers :** créer `patrick/patrick/paths.py` ; modifier `patrick/tests/conftest.py` ; test `patrick/tests/test_paths.py`.

**Interfaces — produit (utilisé par T2 à T12) :**
```python
ENV_DATA_ROOT = "PATRICK_DATA_ROOT"; KEY_DATA_ROOT = "data_root"
class DataRootUnavailable(RuntimeError): ...
def home_dir() -> Path                    # dossier de PATRICK_DB_PATH s'il est posé, sinon ~/.patrick
def db_path() -> str                      # PATRICK_DB_PATH sinon home_dir()/"patrick.db" ; jamais sous la racine de données
def logs_dir() -> Path                    # home_dir()/"logs"
def configured_data_root() -> Path | None # env puis réglage, sans aucune vérification
def data_root() -> Path                   # configurée (doit exister, sinon DataRootUnavailable) ou home_dir()
def data_root_missing() -> str | None     # chemin configuré mais absent, sinon None
def data_root_problem() -> str | None     # message français expliqué, sinon None
def store_dir() -> Path; def cache_dir() -> Path; def feature_cache_dir() -> Path          # variable de composant d'abord
def models_dir() -> Path; def backups_dir() -> Path; def archive_dir() -> Path; def reports_dir() -> Path
```
Toutes relisent l'environnement et `settings.load()` à chaque appel (jamais figées à l'import).

- [ ] **Étape 1 : tests `test_paths.py`** (chacun commence par `monkeypatch.delenv("PATRICK_DATA_ROOT", raising=False)`, car T1 pose cette variable pour tous les tests) :
  - `test_default_is_the_home_folder` : `PATRICK_DB_PATH=tmp/patrick.db` → `data_root() == tmp`, `models_dir() == tmp/"models"`, `db_path() == str(tmp/"patrick.db")`.
  - `test_priority_component_env_over_env_over_setting` : `settings.save({"data_root": a})` → `store_dir() == a/"store"` ; `PATRICK_DATA_ROOT=b` → `b/"store"` ; `PATRICK_STORE_ROOT=c` → `c`. Idem `cache_dir` / `feature_cache_dir` avec leurs variables.
  - `test_missing_root_raises_and_creates_nothing` : racine `tmp/"PATRICK DATA"` absente, par variable puis par réglage → `models_dir()` lève `DataRootUnavailable` (message contient `PATRICK DATA`), le dossier n'existe toujours pas, `data_root_missing() == str(racine)`, `"PATRICK DATA" in data_root_problem()`.
  - `test_db_and_logs_stay_in_home_with_a_data_root` : racine existante → `db_path()` et `logs_dir()` restent sous `home_dir()`.
  - `test_setting_is_reread_on_every_call` : changer `data_root` entre deux appels change `backups_dir()`.
  - `test_no_problem_when_unconfigured` : `data_root_problem() is None`, `data_root_missing() is None`.
- [ ] **Étape 2 : lancer `python -m pytest tests/test_paths.py -q` ; attendu : échec (module absent).**
- [ ] **Étape 3 : créer `paths.py`** avec les signatures ci-dessus (importe seulement `patrick.settings`). Message de `DataRootUnavailable` : « Le disque de données {racine} est introuvable. Branche-le ou change le réglage `data_root`. »
- [ ] **Étape 4 : `conftest.py`** : ajouter une fixture autouse `_isolated_data_root(tmp_path, monkeypatch)` qui crée `tmp_path/"data_root"` et pose `PATRICK_DATA_ROOT` dessus (même style que `_isolated_local_cache`).
- [ ] **Étape 5 : `python -m pytest tests/test_paths.py -q` passe ; commit** `feat(paths): racine de données réglable, base active dans le dossier maison`.

### Tâche 2 : composants de données lus par `paths`

**Fichiers :** modifier `data/store.py:35` (`_default_store_dir`), `cache_manager.py:17`, `features/pool_cache.py:56-57`, `tracking/db.py:48` (`default_db_path`), `tracking/usage.py:51` (`artifact_roots`) ; test `patrick/tests/test_data_paths_wiring.py` (créé ici, complété par T3 et T4).

**Interfaces — consomme :** `paths.store_dir/cache_dir/feature_cache_dir/models_dir/db_path` (T1). **Produit :** les mêmes fonctions publiques qu'avant, même type de retour (`str` pour `_default_store_dir`).

- [ ] **Étape 1 : tests** : `PATRICK_DATA_ROOT=R` (existant) et variables de composant retirées → `DataStore().root == str(R/"store")` ; `cache_manager` renvoie `R/"cache"` ; `pool_cache` renvoie `R/"feature_cache"` ; `trackdb.default_db_path()` n'est PAS sous `R` ; `usage.artifact_roots()` contient `R/"models"` ; une variable de composant posée l'emporte encore.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : remplacer chaque `os.path.expanduser("~/.patrick/…")` / `Path.home() / ".patrick"` par l'appel `paths` correspondant** (`str(...)` là où l'appelant attendait un `str`) ; ajouter `models_dir()` aux dossiers de `artifact_roots()`.
- [ ] **Étape 4 : tests T2 + `tests/test_data_store*.py tests/test_cache_manager*.py tests/test_pool_cache*.py` verts ; commit** `refactor(paths): magasin, caches, base et modèles lus via paths`.

### Tâche 3 : sauvegardes, rapports, scripts

**Fichiers :** modifier `tracking/backup.py:46,129` (supprimer la constante `DEFAULT_BACKUP_DIR`), `tracking/report.py:28,477-478`, `fund/share.py:160`, `scripts/backup_db.py:33,49`, `scripts/schtasks_daily_dbbackup.ps1` ; adapter `tests/test_sync_cli.py:91` ; compléter `test_data_paths_wiring.py`.

**Interfaces — produit :** `report.default_reports_dir() -> str` (remplace `DEFAULT_REPORTS_DIR`). `backup_database(..., backup_dir=None)` écrit dans `paths.backups_dir()`.

- [ ] **Étape 1 : tests** : `backup_database(src)` sans `backup_dir` crée le fichier dans `R/"backups"` ; `report.default_reports_dir() == str(R/"reports")` ; `merge_funds(..., backup_dir=None)` utilise `R/"backups"` (test existant de `test_fund_share.py` à étendre d'une assertion).
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter** : `backup.py` et `fund/share.py` appellent `paths.backups_dir()` à l'usage ; `report.py` définit `default_reports_dir()` ; `scripts/backup_db.py` n'importe plus la constante (aide : « défaut : dossier backups de la racine de données ») ; le `.ps1` écrit son journal dans `%USERPROFILE%\.patrick\logs\backup.log` (non enregistré comme tâche aujourd'hui). `test_sync_cli.py::_pc_env` : remplacer `monkeypatch.setattr(backup, "DEFAULT_BACKUP_DIR", …)` par `PATRICK_DATA_ROOT` sur `tmp_path/f"{name}_data"` (créé).
- [ ] **Étape 4 : `tests/test_backup_db.py tests/test_sync_cli.py tests/test_fund_share.py tests/test_data_paths_wiring.py` verts ; commit** `refactor(paths): sauvegardes et rapports via paths`.

### Tâche 4 : `sync.py` — emplacements, messages, statut

**Fichiers :** modifier `sync.py` (`_default_store_root` l.369, `_default_models_roots` l.373, `models_dir or expanduser` l.589 et l.839, `_backup_affordable` l.763, `_disk_full_message` l.148-151, `register_task` l.1072, `status` l.892-905) ; compléter `test_data_paths_wiring.py`.

**Interfaces — consomme :** T1. **Produit :** `sync.status()` ajoute `data_root: str | None`, `data_free_gb: float | None`, `data_available: bool` (utilisés par T5).

- [ ] **Étape 1 : tests** : `_default_store_root() == str(R/"store")` ; `R/"models"` figure dans `_default_models_roots()` ; `_disk_full_message(p)` cite `str(R/"feature_cache")` et `str(R/"backups")` et ne contient plus `~/.patrick` ; `status()` renvoie `data_root == str(R)`, `data_available is True` ; **autre PC** : `sync.merge(partage, db_path=…)` sans `models_dir` explicite restaure dans `R/"models"` et écrit des `trial.artifact_path` absolus sous `R/"models"` (réutiliser le scénario de `test_sync_inplace.py`) ; racine absente → `status()["data_available"] is False` sans lever.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter** ; le journal de `register_task` reste `paths.logs_dir()/"sync.log"` (même emplacement qu'aujourd'hui, tâche existante inchangée).
- [ ] **Étape 4 : `tests/test_sync*.py tests/test_data_paths_wiring.py` verts ; commit** `refactor(sync): emplacements via paths, statut de la racine de données`.

### Tâche 5 : diagnostics et page Réglages

**Fichiers :** modifier `analysis/diagnostics.py` (`home()` l.30, `logs_dir()` l.35, `system()` l.53, `storage()` l.141-146), `webapp/static/reglages.js:119-121`, `webapp/i18n_settings.py:73-75,150` ; tests `tests/test_analysis_diagnostics.py`, `tests/test_settings_routes.py`.

**Interfaces — consomme :** `paths.home_dir/logs_dir/*_dir`, `sync.status()` (T4).

- [ ] **Étape 1 : tests** : `dg.home() == paths.home_dir()` ; `storage()` : les dossiers `models`, `backups`, `archive` viennent de `paths` (sous `R`), `logs` du dossier maison ; `system()` : `holds_data` est vrai pour le volume du dossier maison ET celui de la racine de données ; la route de statut de `settings_routes.py` expose `data_root`, `data_free_gb`, `data_available` ; une clé `app_status_data_disk` et une clé `app_status_data_missing` existent en FR et EN (le test garde-fou `test_i18n_js_keys.py` doit rester vert).
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter.** `diagnostics.home()` = `paths.home_dir()`. Chaînes : `app_status_disk_low` sans `~/.patrick` (« … libère de la place (caches de variables, anciennes sauvegardes). ») ; `app_status_data_disk` : « Données : {path}, {free} Go libres. » ; `app_status_data_missing` : « Disque de données introuvable : {path}. » ; `reglages.js` affiche la ligne de données sous la ligne du disque de la base, et le seuil « presque plein » s'applique à chaque volume séparément. Ajouter les deux clés à `SETTINGS_JS_KEYS`.
- [ ] **Étape 4 : `tests/test_analysis_diagnostics.py tests/test_settings_routes.py tests/test_i18n_*.py` verts ; commit** `feat(reglages): racine de données et espace libre des deux volumes`.

### Tâche 6 : dossier de partage vs racine de données

**Fichiers :** modifier `desktop/share.py` (`validate_folder` l.84-103) ; test `tests/test_desktop_share.py`.

- [ ] **Étape 1 : tests** : `validate_folder(R/"partage")` lève `ShareError` ; `validate_folder(parent_de_R)` lève `ShareError` ; un dossier sans lien avec `R` reste accepté ; sans racine configurée, comportement inchangé.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter** avec `_is_inside` dans les deux sens contre `paths.configured_data_root()` (message : « Choisis un dossier différent de la racine de données de PATRICK ({racine}). »).
- [ ] **Étape 4 : `tests/test_desktop_share.py` vert ; commit** `fix(share): le partage ne peut pas chevaucher la racine de données`.

### Tâche 7 : disque de données absent (lanceur, serve, worker, pages)

**Fichiers :** modifier `desktop/launcher.py:262` (avant `start_and_wait_for_server`), `cli.py` (`serve` l.266, `worker` l.251), `webapp/app.py` (gestionnaire d'exception + `templates.env.globals`), `webapp/templates/base_v2.html` (bandeau), chaînes serveur (clé `data_root_banner`, motif des clés `app_*`) ; tests `tests/test_desktop_launcher.py`, nouveau `tests/test_data_root_unavailable.py`.

**Interfaces — consomme :** `paths.data_root_problem()`, `paths.data_root_missing()`, `paths.DataRootUnavailable`.

- [ ] **Étape 1 : tests** (racine configurée absente) : `launcher.run(rep)` renvoie 1, appelle `rep.error` avec le chemin, et ne démarre pas le serveur (monkeypatcher `start_and_wait_for_server` pour échouer s'il est appelé) ; `CliRunner().invoke(app, ["serve"])` et `["worker"]` sortent en code 1 avec le message sur `stderr` ; `TestClient` : une route `/api/…` qui lit le magasin renvoie 503 et `{"error": <message>}` ; une page HTML renvoie 503 avec le message ; `GET /reglages` renvoie 200 et contient `data-root-banner` ; avec la racine présente, aucun bandeau.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter** : lanceur et commandes `serve`/`worker` vérifient `data_root_problem()` en tête ; `app.add_exception_handler(paths.DataRootUnavailable, …)` (JSON pour `/api/`, HTML court sinon, statut 503) ; global Jinja `data_root_missing` et bloc `<div class="data-root-banner" role="alert">{{ t('data_root_banner', path=…) }}</div>` en haut de `base_v2.html` quand il renvoie un chemin.
- [ ] **Étape 4 : `tests/test_data_root_unavailable.py tests/test_desktop_launcher.py tests/test_i18n_templates.py` verts ; commit** `feat(app): arrêt clair et bandeau quand le disque de données est absent`.

### Tâche 8 : `patrick data status` et `init`

**Fichiers :** créer `patrick/patrick/data_move.py` ; modifier `cli.py` (nouveau `data_app = typer.Typer(...)`, `app.add_typer(data_app, name="data")`, à côté de `sync_app` l.35) ; test `tests/test_data_move.py`.

**Interfaces — produit (utilisé par T9 à T11) :**
```python
COMPONENTS = ("store", "models", "feature_cache", "cache", "backups", "archive", "reports")
JOURNAL_NAME = "data_move_journal.json"; STATE_NAME = "data_move_state.json"   # dans paths.home_dir()
class MoveError(RuntimeError): ...
def status() -> dict   # {"data_root": str|None, "home", "db", "available": bool, "volumes": [{"path","free_gb"}],
                       #  "components": [{"name","path","exists"}], "unresolved": {"artifact_paths": int, "store_index": int},
                       #  "progress": dict|None}
def init_root(folder: str) -> Path   # crée la racine, ses 7 sous-dossiers et README.txt ; MoveError si le lecteur n'existe pas
```

- [ ] **Étape 1 : tests** : `init_root(tmp/"PATRICK DATA")` crée les 7 sous-dossiers et un `README.txt` contenant `patrick data status` ; `init_root` sur un lecteur inexistant (chemin sous un dossier parent absent) lève `MoveError` et ne crée rien ; `status()` sans réglage renvoie `data_root is None`, `available is True` ; avec racine configurée absente `available is False` ; `status()["unresolved"]` compte les `artifact_path` absolus qui ne résolvent pas en fichier (petite base temporaire) ; `CliRunner` : `data status` et `data init <dossier>` sortent en 0.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter.** `unresolved` : absolus de `trial.artifact_path` sans fichier ; entrées de `store/_index.json` sans fichier. Lecture seule de la base (`mode=ro`). `init` n'écrit pas le réglage (c'est `move` qui le fait).
- [ ] **Étape 4 : tests verts ; commit** `feat(data): commandes status et init`.

### Tâche 9 : `move` — préconditions et phase 1 (copie)

**Fichiers :** modifier `data_move.py`, `cli.py` (`data move <dossier>`) ; test `tests/test_data_move.py`.

**Interfaces — produit :**
```python
def check_preconditions(target: str, *, db_path: str | None = None, port: int | None = None) -> list[str]  # messages bloquants, [] si rien
def copy_components(target: str, *, source_root: Path | None = None, progress=None) -> dict               # {"files","bytes","skipped"}
```
`source_root` : `paths.data_root()` actuel. Avancement écrit dans `STATE_NAME`.

- [ ] **Étape 1 : tests** (arbre temporaire, jamais la vraie base) : préconditions bloquantes pour un job `running` ou un worker vivant (`sync._job_running`), un serveur qui écoute (`desktop.runtime.port_open`, monkeypatché), un espace libre insuffisant (monkeypatcher `shutil.disk_usage`) ; **point de vigilance 3** : cible égale à la racine active, dans le dossier maison, dans la source, ou dans/contenant `sync.configured_folder()` → message précis ; `copy_components` copie les 7 composants vers `tmp/"PATRICK DATA"` (**espace dans le nom**) et renvoie les totaux ; **point 2** : relancé après une interruption simulée (un fichier cible tronqué de taille différente, un `.part` orphelin) il recopie le fichier tronqué, supprime le `.part`, et saute les fichiers identiques (`skipped > 0`) ; aucune écriture dans la source ; `models` et `store` vérifiés par sha256 (un octet altéré dans la copie → `MoveError`).
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter.** Copie fichier par fichier : écriture dans `<nom>.part` puis `os.replace`, préservation de la date (`shutil.copy2`), saut si taille et date identiques ; vérification finale (nombre de fichiers, octets par composant, sha256 pour `store` et `models`). `move` affiche un rappel non bloquant : « Vérifie que la tâche PATRICK-Sync est désactivée ». Pas de détachement automatique : la commande est lancée dans le PowerShell de Léon (mémoire `long-runs-outside-claude-app`).
- [ ] **Étape 4 : tests verts ; commit** `feat(data): préconditions et copie reprenable vers la racine de données`.

### Tâche 10 : `move` — phase 2 (bascule et journal)

**Fichiers :** modifier `data_move.py` ; test `tests/test_data_move.py`.

**Interfaces — produit :**
```python
def rebase_path(value: str, old_root: str, new_root: str) -> str | None   # None si `value` n'est pas sous old_root ; séparateurs et casse normalisés
def switch(target: str, *, db_path: str | None = None, source_root: Path | None = None) -> dict   # écrit le journal, renvoie son contenu
```
Journal (`JOURNAL_NAME`) : `{"source_root","target","artifact_paths": [[trial_id, old, new], …], "store_index_old": {chemin: ancienne valeur}, "created_at"}`.

- [ ] **Étape 1 : tests** : **point 1** `rebase_path(r"C:\Users\leonp/.patrick/store\snapshot=2026-07-28\raw_IDX_VIX__02b2bd20a711.parquet", r"C:\Users\leonp\.patrick\store", r"D:\PATRICK DATA\store")` renvoie le chemin sous `D:\PATRICK DATA\store\snapshot=2026-07-28\…` ; casse différente (`c:\users\LEONP\.PATRICK\…`) reconnue ; chemin hors racine → `None` ; sur une petite base temporaire : `switch` réécrit seulement les `trial.artifact_path` absolus de l'ancien `models` (les relatifs `runs\GSPC_34\…`, `NULL` et vides restent identiques), réécrit les `path` de la copie de `_index.json` (jamais ceux de la source), écrit `data_root` dans `settings.json`, et le journal contient toutes les anciennes valeurs ; **point 4** un second `switch` après succès ne change rien et ne réécrit pas le journal ; échec au milieu de la transaction SQL → aucune ligne modifiée, réglage non écrit.
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter.** Ordre : journal (écriture atomique) → UPDATE des `artifact_path` en UNE transaction → `_index.json` de la cible (écriture atomique, par `rebase_path` sur le préfixe, repli sur la queue `snapshot=…\fichier` comme `sync._SNAPSHOT_REL_RE`) → réglage `data_root` en dernier.
- [ ] **Étape 4 : tests verts ; commit** `feat(data): bascule avec journal des anciennes valeurs`.

### Tâche 11 : `move` — phase 3 (contrôle, rollback, finalisation)

**Fichiers :** modifier `data_move.py`, `cli.py` (`data move <dossier> [--finalize]`, `data rollback`) ; test `tests/test_data_move.py`.

**Interfaces — produit :**
```python
def verify(db_path: str | None = None) -> dict          # {"artifact_unresolved": int, "store_unresolved": int, "ok": bool}
def rollback(db_path: str | None = None) -> dict        # restaure depuis le journal ; MoveError après finalize
def finalize(*, source_root: Path | None = None) -> dict  # supprime les 7 composants de la source ; exige verify()["ok"]
```

- [ ] **Étape 1 : tests** : `verify` : `ok` vrai après `switch` valide, faux si un fichier de la cible manque ; `rollback` remet exactement les anciennes valeurs de la base, retire `data_root` du réglage, et laisse la source intacte ; **point 4** `rollback` après `finalize` lève `MoveError` ; `finalize` refuse si `verify` n'est pas ok, supprime uniquement les 7 composants de la source (jamais `patrick.db`, `settings.json`, `logs`, `app-profile-stable`, `sync_undo`), et ne s'exécute que si l'utilisateur répond oui à la confirmation (`CliRunner(input="o\n")` accepte, `"n\n"` refuse sans rien supprimer).
- [ ] **Étape 2 : lancer, attendu : échec.**
- [ ] **Étape 3 : implémenter.** `data move <dossier>` enchaîne préconditions → copie → bascule → `verify`, et n'affiche « lance `patrick data move --finalize` après ta mesure de vitesse » qu'en cas de succès. `--finalize` n'accepte aucun dossier.
- [ ] **Étape 4 : tests verts ; commit** `feat(data): contrôle, retour arrière et finalisation`.

### Tâche 12 : garde-fou, docs, isolation des vrais dossiers

**Fichiers :** créer `tests/test_no_hardcoded_home.py` ; modifier `ARCHITECTURE.md`, `METHODOLOGY.md`, `README.md`, `NEXT_STEPS.md` (phrases citant `~/.patrick/…`).

- [ ] **Étape 1 : test** : parcourir `patrick/patrick/**/*.py` et `patrick/scripts/**/*.py` ; échec si `.patrick` apparaît dans un chemin construit (`expanduser("~/.patrick`, `/ ".patrick"`, `\.patrick\`) hors de `paths.py`, des commentaires/docstrings et d'une liste blanche explicite de deux entrées : `settings.py` (emplacement de `settings.json`) et `data_move.py` (messages). Modèle : `test_repo_hygiene.py`.
- [ ] **Étape 2 : lancer ; corriger les oublis révélés** (candidats : `explain.py`, `desktop/runtime.py`, `desktop/prefs.py`, `webapp/*`) en les passant par `paths` ; relancer jusqu'au vert.
- [ ] **Étape 3 : docs** : une phrase par fichier renvoyant à `paths` et `patrick data status`.
- [ ] **Étape 4 : suite rapide en trois blocs** (`ls tests/test_*.py | sort`, coupures à `test_dl_page.py` et `test_run_controls.py`, `timeout 570`, `-p no:cacheprovider`, deselect de `test_kill_process_tree_spares_the_caller_even_when_it_is_a_descendant`) ; attendu : tout vert. Avant/après, relever la liste et les dates des fichiers de `~/.patrick/models`, `backups`, `reports`, `archive` : **aucune différence** (incident du 10/10).
- [ ] **Étape 5 : commit** `test(paths): garde-fou contre les chemins en dur, docs`.

### Tâche 13 : exécution réelle avec Léon (aucun code)

À faire **après fusion de la branche**, PATRICK fermé par Léon, dans son propre PowerShell (mémoires `long-runs-outside-claude-app`, `no-db-maintenance-during-runs`). Aucune étape n'est lancée depuis l'application Claude.

- [ ] **1.** Léon désactive la tâche : `Disable-ScheduledTask -TaskName PATRICK-Sync`. Vérifier qu'aucun processus `patrick` ne tourne et qu'aucun job n'est `running`.
- [ ] **2.** `patrick data status` : noter les chemins non résolus de départ.
- [ ] **3.** `patrick data init "D:\PATRICK DATA"`, puis `patrick data move "D:\PATRICK DATA"` (copie ≈ 148 Go : plusieurs dizaines de minutes à plus d'une heure, estimation). Attendu : `verify` ok, aucun chemin non résolu.
- [ ] **4.** Mesure de vitesse : un run léger de référence avec `PATRICK_FEATURE_CACHE_ROOT` sur C: puis sur D: ; si D: est plus lent de plus de 30 %, laisser `feature_cache` sur C: (variable ou ancien dossier conservé) avant la finalisation.
- [ ] **5.** Vérifications de la spec §8 : un run léger complet ; une prédiction avec un modèle déplacé ; `patrick sync auto` à blanc contre le dossier OneDrive ; Réglages affiche les deux volumes ; `patrick data status` sans chemin non résolu.
- [ ] **6.** `patrick data move --finalize` (confirmation de Léon) ; contrôler que C: a au moins 100 Go libres ; réactiver `Enable-ScheduledTask -TaskName PATRICK-Sync` et l'exécuter une fois (`Start-ScheduledTask`), journal `~/.patrick/logs/sync.log` sans erreur.
- [ ] **7.** Vérifier le schéma de la vraie base (`schema_version`) après tout `git pull` (mémoire `fund-sharing-onedrive`). Autre PC : `git pull`, `patrick data init`/réglage `data_root` à son choix, première fusion OneDrive ; les modèles apparaissent sous sa racine.
