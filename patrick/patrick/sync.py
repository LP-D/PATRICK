"""`patrick sync` -- partage de la base, des modèles et du magasin de données
entre deux PC.

Ce qui est partagé : `patrick.db` (la recherche seulement ; les caches de modèles de volatilité, qui font l'essentiel d'une
grosse base, restent sur chaque PC), les fichiers modèles référencés par `trial.artifact_path`, et les parquet du magasin de
données (`~/.patrick/store`). Un `manifest.json` (sha256, taille, version de schéma) accompagne les fichiers.

Deux mises en page (ADR 0020) : **format 2**, pour un dossier -- une arborescence EN CLAIR où seuls les fichiers manquants sont
copiés (voir `sync_tree`) ; **format 1**, pour GitHub (assets limités à 2 Go) -- trois archives (`patrick.db.gz`, `models.zip`,
`store.zip`) reconstruites à chaque publication. `pull` et `merge` lisent les deux.

Ce qui n'est JAMAIS partagé vers GitHub : les tables du patrimoine et des
fonds personnels (`wealth_*`, `fund_*`) et l'ancien simulateur (`simulation`).
Elles sont vidées dans une COPIE de la base (la source n'est pas modifiée) puis
la copie est compactée (`VACUUM`) pour qu'aucune page libérée ne garde la
donnée en clair. Seule la destination « dossier » (ex. un Google Drive
synchronisé, privé) accepte `include_personal=True`.

À la restauration (`pull`), les tables personnelles du PC local sont
conservées : la recherche vient du partage, le patrimoine reste local.

Destinations :
- `github` : release glissante `data-latest` du dépôt (`gh` doit être connecté),
  assets jusqu'à 2 Go, hors de l'historique git;
- un chemin de dossier : copie simple, utilisable avec Google Drive pour
  ordinateur, un disque réseau ou une clé USB.
"""
from __future__ import annotations

import errno
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths, sync_merge, sync_tree
from patrick import settings as settings_mod
from patrick.fund import share as fund_share
from patrick.tracking import backup as backup_mod
from patrick.tracking import db as trackdb

GITHUB_TAG = "data-latest"
DB_ASSET = "patrick.db.gz"
MODELS_ASSET = "models.zip"
STORE_ASSET = "store.zip"
MANIFEST = "manifest.json"
_ASSETS = (DB_ASSET, MODELS_ASSET, STORE_ASSET)
FORMAT_VERSION = 1                       # format 1 : archives (GitHub, anciens dossiers) ; format 2 : arborescence en clair (`sync_tree`)
TREE_ROOT = "."                          # clé du dossier racine dans ce que renvoie `FolderTransport.download` (format 2)
# Disque du dossier partagé : une publication s'arrête (et reprend à la suivante) sous ce seuil. Avec Google Drive « en streaming »
# l'espace libre de `F:` est celui de `C:` (cache du Drive) : le 11/11/2026 il est tombé à 16 Go.
FOLDER_MIN_FREE_BYTES = 5 << 30
KEY_MIN_PUSH_HOURS = "sync_min_push_hours"
DEFAULT_MIN_PUSH_HOURS = 24

PERSONAL_PREFIXES = ("wealth_", "fund_")
PERSONAL_EXACT = ("simulation",)

_SNAPSHOT_REL_RE = re.compile(r"(snapshot=[^/\\]+)[/\\]([^/\\]+)$")


class SyncError(RuntimeError):
    """Échec attendu et expliqué à l'utilisateur (garde-fou, fichier invalide...)."""


# --------------------------------------------------------------------------
# Base de données
# --------------------------------------------------------------------------

def personal_tables(conn: sqlite3.Connection) -> list[str]:
    """Tables qui portent des données personnelles et ne quittent jamais le PC
    vers un dépôt public."""
    names = [n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return sorted(n for n in names if n.startswith(PERSONAL_PREFIXES) or n in PERSONAL_EXACT)


def _latest_code_version() -> int:
    return max(int(p.name.split("_", 1)[0]) for p in trackdb.MIGRATIONS_DIR.glob("*.sql"))


def _text_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = []
    for _cid, name, decl, *_rest in conn.execute(f'PRAGMA table_info("{table}")'):
        decl = (decl or "").upper()
        if decl == "" or "CHAR" in decl or "TEXT" in decl or "CLOB" in decl:
            cols.append(name)
    return cols


def _username_leaks(conn: sqlite3.Connection, needle: str) -> dict[str, int]:
    """`table.colonne -> nombre de lignes` contenant `needle` (nom d'utilisateur
    du PC, p. ex. dans un chemin absolu `C:\\Users\\<nom>\\...`)."""
    leaks: dict[str, int] = {}
    tables = [n for (n,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        for col in _text_columns(conn, table):
            n = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" LIKE ?',
                             (f"%{needle}%",)).fetchone()[0]
            if n:
                leaks[f"{table}.{col}"] = n
    return leaks


# Messages d'erreur libres d'une base : un traceback Windows y porte presque toujours un chemin absolu du dossier personnel.
_ERROR_TEXT_COLUMNS = (("job", "error"), ("job", "log_tail"), ("run", "error"))


def _redact_username_in_errors(conn: sqlite3.Connection, needle: str) -> int:
    """Remplace, dans la COPIE d'export, le dossier personnel du PC par `~` et son nom d'utilisateur par `<utilisateur>` dans les
    messages d'erreur (`job.error`, `job.log_tail`, `run.error`) ; renvoie le nombre de lignes modifiées.

    Le 2026-10-31, deux messages d'erreur du 22/10 (chemin du cache dans une `PermissionError`) bloquaient toute publication : 142
    refus d'affilée, la recherche de ce PC n'atteignait plus le partage. Un message d'erreur n'a aucun intérêt scientifique à porter
    le nom d'un utilisateur, alors que refuser tout l'export à cause de lui coûte des jours de recherche non sauvegardée. Les
    AUTRES colonnes (configuration d'un run, problèmes de données...) ne sont pas touchées : un nom d'utilisateur qui y apparaît
    reste refusé par `_username_leaks`, car il révélerait une fuite de structure, pas un simple message."""
    home = str(Path.home())
    variants = sorted({home, Path(home).as_posix()}, key=len, reverse=True)
    home_patterns = [re.compile(re.escape(v), re.IGNORECASE) for v in variants if v]
    name_pattern = re.compile(re.escape(needle), re.IGNORECASE)

    def redact(text):
        if not isinstance(text, str):
            return text
        for pattern in home_patterns:
            text = pattern.sub("~", text)
        return name_pattern.sub("<utilisateur>", text)

    conn.create_function("_redact_user", 1, redact, deterministic=True)
    conn.execute("PRAGMA secure_delete = ON")       # l'ancien texte est écrasé de zéros, pas seulement détaché : sans VACUUM d'une grosse copie
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    changed = 0
    for table, column in _ERROR_TEXT_COLUMNS:
        if table in tables and column in _text_columns(conn, table):
            changed += conn.execute(
                f'UPDATE "{table}" SET "{column}" = _redact_user("{column}") WHERE "{column}" LIKE ?',
                (f"%{needle}%",)).rowcount
    conn.commit()
    return changed


def _neutralise_runtime_state(conn: sqlite3.Connection) -> None:
    """État d'exécution propre à un PC : un job en attente ou en cours serait
    repris par le worker de l'autre PC, et un battement de worker récent y
    ferait croire qu'un worker tourne."""
    conn.execute("UPDATE job SET status = 'error', worker_pid = NULL, finished_at = datetime('now'), "
                 "error = 'Interrompu : exporté par patrick sync avant la fin du job' "
                 "WHERE status IN ('queued', 'running')")
    conn.execute("DELETE FROM worker_heartbeat")
    conn.commit()


def _anonymise(path: str) -> str:
    """Chemin sans séparateur Windows ni dossier personnel (pour le manifeste)."""
    norm = path.replace("\\", "/")
    home = str(Path.home()).replace("\\", "/")
    return norm.replace(home, "~") if home else norm


def _gzip_file(src: Path, dest: Path) -> None:
    # `filename=""` + `mtime=0` : l'en-tête gzip ne porte ni nom de fichier ni date.
    with open(src, "rb") as fin, open(dest, "wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


MIN_FREE_BYTES = 1 << 30                 # marge laissée libre sur le disque pendant une fusion
_CHUNK = 16 * 1024 * 1024


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",")


def _free_bytes(path: str | Path) -> int:
    """Octets libres sur le disque qui porte `path` (ou son plus proche parent existant)."""
    p = Path(path).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def _folder_hint(folder) -> str:
    """Chemin d'un dossier de données pour un message d'erreur : ne lève jamais (le disque de données peut manquer)."""
    try:
        return str(folder())
    except paths.DataRootUnavailable:
        return "dossier de données absent"


def _disk_full_message(path: str | Path) -> str:
    return (f"Disque presque plein ({_gb(_free_bytes(path))} Go libres) : la synchronisation s'arrête sans rien changer. "
            f"Libère de la place -- les plus gros candidats sont les caches ({_folder_hint(paths.feature_cache_dir)}) et "
            f"les anciennes sauvegardes ({_folder_hint(paths.backups_dir)}) -- puis relance PATRICK.")


def _require_space(path: str | Path, needed: int, what: str) -> None:
    free = _free_bytes(path)
    if free < needed + MIN_FREE_BYTES:
        raise SyncError(f"Espace disque insuffisant pour {what} : il faut environ {_gb(needed + MIN_FREE_BYTES)} Go "
                        f"libres, il en reste {_gb(free)}. " + _disk_full_message(path).split(": ", 1)[1])


def _gunzip_file(src: Path, dest: Path) -> None:
    """Décompresse `src` vers `dest` en vérifiant l'espace libre (un disque plein s'arrête proprement)."""
    written = 0
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        while True:
            chunk = fin.read(_CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            written += len(chunk)
            if (written // _CHUNK) % 16 == 0 and _free_bytes(dest.parent) < MIN_FREE_BYTES // 2:
                raise SyncError(_disk_full_message(dest.parent))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Modèles et magasin de données
# --------------------------------------------------------------------------

def _resolve_model(path: str, roots: list[str]) -> Path | None:
    norm = path.replace("\\", "/")
    if os.path.isabs(norm) and os.path.exists(norm):
        return Path(norm)
    for root in roots:
        candidate = Path(root) / norm
        if candidate.exists():
            return candidate
    return None


def _collect_models(copy: sqlite3.Connection, roots: list[str], arc_for) -> tuple[list[tuple[Path, str]], dict[str, str], list[str]]:
    """Résout les modèles référencés par la copie de la base et y remplace `trial.artifact_path` par leur chemin dans
    l'archive ou l'arborescence publiée (aucun chemin local ne sort). `arc_for(trial_id, fichier)` choisit ce chemin.
    Retourne (fichiers à publier `[(source, chemin)]`, index `{id d'essai: chemin}`, chemins introuvables sur ce PC)."""
    rows = copy.execute("SELECT trial_id, artifact_path FROM trial WHERE artifact_path IS NOT NULL").fetchall()
    files: list[tuple[Path, str]] = []
    index: dict[str, str] = {}
    missing: list[str] = []
    for trial_id, art in rows:
        found = _resolve_model(art, roots)
        if found is None:
            missing.append(_anonymise(art))
            continue
        arc = arc_for(trial_id, found)
        files.append((found, arc))
        meta = found.with_name(found.stem + "_meta.json")
        if meta.exists():
            files.append((meta, f"{arc.rsplit('/', 1)[0]}/{meta.name}"))
        index[str(trial_id)] = arc
        copy.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (arc, trial_id))
    copy.commit()
    return files, index, missing


def _build_models_bundle(copy: sqlite3.Connection, roots: list[str], dest: Path) -> dict:
    """Zippe les modèles référencés par la copie de la base (format 1) et y remplace `trial.artifact_path` par le nom dans
    l'archive. Retourne le résumé pour le manifeste; `dest` n'est créé que s'il y a au moins un modèle."""
    files, index, missing = _collect_models(copy, roots, lambda trial_id, found: f"models/{trial_id}/{found.name}")
    if files:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, arc in files:
                zf.write(src, arc)
            zf.writestr("index.json", json.dumps(index, indent=1))
    return {"included": len(index), "missing": missing}


def _store_selection(store_root: str) -> tuple[list[Path], dict]:
    """Parquet du magasin à publier et `_index.json` aux chemins relatifs (le vrai contient des chemins absolus propres à
    chaque PC)."""
    root = Path(store_root)
    parquets = sorted(root.glob("snapshot=*/*.parquet")) if root.is_dir() else []
    if not parquets:
        return [], {}
    present = {f"{p.parent.name}/{p.name}" for p in parquets}
    index_path = root / "_index.json"
    index: dict = {}
    if index_path.exists():
        for key, value in json.loads(index_path.read_text(encoding="utf-8")).items():
            kept = []
            for entry in value.get("snapshots", []):
                m = _SNAPSHOT_REL_RE.search(entry.get("path", ""))
                if m and f"{m[1]}/{m[2]}" in present:
                    kept.append({**entry, "path": f"{m[1]}/{m[2]}"})
            if kept:
                index[key] = {**value, "snapshots": kept}
    return parquets, index


def _build_store_bundle(store_root: str, dest: Path) -> dict:
    """Zippe les parquet du magasin et un `_index.json` aux chemins relatifs (format 1)."""
    parquets, index = _store_selection(store_root)
    if not parquets:
        return {"files": 0}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in parquets:
            zf.write(p, f"{p.parent.name}/{p.name}")
        zf.writestr("_index.json", json.dumps(index, indent=1))
        series = Path(store_root) / "_series_observations.json"
        if series.exists():
            zf.write(series, "_series_observations.json")
    return {"files": len(parquets)}


def _read_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SyncError(f"Manifeste illisible ({path.name}) : sans doute pas entièrement recopié par le dossier partagé, "
                        "réessaie plus tard.") from exc


def _db_entry(manifest: dict) -> dict:
    """Empreinte (sha256, taille) de la base du partage : `patrick.db.gz` (format 1) ou `db/patrick.db` (format 2)."""
    return manifest["files"][sync_tree.DB_REL if sync_tree.is_tree(manifest) else DB_ASSET]


def _safe_extract(zf: zipfile.ZipFile, member: str, dest_root: Path, target_rel: str) -> Path:
    target = (dest_root / target_rel).resolve()
    if not target.is_relative_to(dest_root.resolve()):
        raise SyncError(f"Archive invalide (chemin hors du dossier cible) : {member}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as fin, open(target, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return target


def _restore_store(archive: Path, store_root: str) -> int:
    root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True)
    added = 0
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.endswith(".parquet") and not (root / name).exists():
                _safe_extract(zf, name, root, name)
                added += 1
        remote_index = json.loads(zf.read("_index.json").decode("utf-8")) if "_index.json" in zf.namelist() else {}
        remote_series = (json.loads(zf.read("_series_observations.json").decode("utf-8"))
                         if "_series_observations.json" in zf.namelist() else {})
    _merge_store_indexes(root, remote_index, remote_series)
    return added


def _merge_store_indexes(root: Path, remote_index: dict, remote_series: dict) -> None:
    """Fusionne l'index et les dates d'observation du partage dans ceux du magasin local (rien de local n'est perdu ; les chemins
    du partage deviennent des chemins locaux)."""
    index_path = root / "_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for key, value in remote_index.items():
        local = index.setdefault(key, {**value, "snapshots": []})
        known = {e["snapshot_id"] for e in local["snapshots"]}
        for entry in value["snapshots"]:
            local_path = root.joinpath(*entry["path"].split("/"))
            if entry["snapshot_id"] not in known and local_path.exists():
                local["snapshots"].append({**entry, "path": str(local_path)})
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")

    series_path = root / "_series_observations.json"
    series = json.loads(series_path.read_text(encoding="utf-8")) if series_path.exists() else {}
    for symbol, obs in remote_series.items():
        if symbol not in series or str(obs.get("date_max", "")) > str(series[symbol].get("date_max", "")):
            series[symbol] = obs
    series_path.write_text(json.dumps(series, indent=1), encoding="utf-8")


# Lecture d'un partage en clair (format 2). Les chemins viennent du manifeste d'un autre PC : `sync_tree.safe_rel` les contrôle.

def _copy_from_share(src: Path, target: Path, size: int | None = None) -> bool:
    """Copie `src` (dans le partage) vers `target` (ce PC) sauf si `target` existe déjà avec la bonne taille ; vrai si copié. Un
    fichier local coupé par une interruption est donc recopié."""
    if target.exists() and (size is None or target.stat().st_size == size):
        return False
    sync_tree.copy_file(src, target, free_bytes=_free_bytes, floor=MIN_FREE_BYTES,
                        low_space=lambda: _disk_full_message(target.parent))
    return True


def _local_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SyncError(f"Partage invalide (chemin hors du dossier cible) : {rel}")
    return target


def _restore_store_tree(share: Path, manifest: dict, store_root: str) -> int:
    root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True)
    added = 0
    for rel, meta in manifest.get("tree", {}).items():
        if rel.startswith("store/") and rel.endswith(".parquet"):
            added += _copy_from_share(share / sync_tree.safe_rel(rel), _local_target(root, rel[len("store/"):]), meta["size"])
    remote_index = (sync_tree.read_json(share, sync_tree.STORE_INDEX_REL)
                    if sync_tree.STORE_INDEX_REL in manifest["files"] else {})
    remote_series = (sync_tree.read_json(share, sync_tree.STORE_SERIES_REL)
                     if sync_tree.STORE_SERIES_REL in manifest["files"] else {})
    _merge_store_indexes(root, remote_index, remote_series)
    return added


def _copy_model_dir(share: Path, manifest: dict, arc: str, root: Path, folder_name: str) -> Path:
    """Copie le modèle `arc` et son `_meta.json` (même dossier du partage) vers `<root>/<folder_name>/` ; retourne le chemin local du modèle."""
    prefix = sync_tree.safe_rel(arc).rsplit("/", 1)[0] + "/"
    main: Path | None = None
    for rel, meta in manifest.get("tree", {}).items():
        if rel.startswith(prefix):
            target = _local_target(root, f"{folder_name}/{rel[len(prefix):]}")
            _copy_from_share(share / sync_tree.safe_rel(rel), target, meta["size"])
            if rel == arc:
                main = target
    if main is None:
        raise SyncError(f"Partage incohérent : modèle annoncé mais absent de la liste des fichiers : {arc}")
    return main


def _restore_models_tree(share: Path, manifest: dict, models_dir: str, db_path: str) -> int:
    """Pull : la base du partage remplace la locale, les essais gardent leur identifiant."""
    index = sync_tree.read_json(share, sync_tree.MODELS_INDEX_REL)
    root = Path(models_dir)
    conn = sqlite3.connect(db_path)
    try:
        for trial_id, arc in index.items():
            main = _copy_model_dir(share, manifest, arc, root, str(int(trial_id)))
            conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(main), int(trial_id)))
        conn.commit()
    finally:
        conn.close()
    return len(index)


def _restore_models_merged_tree(share: Path, manifest: dict, models_dir: str, work_db: str, offset: int,
                                new_src_ids: set[int]) -> int:
    """Fusion : les modèles des essais importés vont sous leur NOUVEL identifiant local (décalé par la fusion)."""
    index = sync_tree.read_json(share, sync_tree.MODELS_INDEX_REL)
    root = Path(models_dir)
    restored = 0
    conn = sqlite3.connect(work_db)
    try:
        for key, arc in index.items():
            src_id = int(key)
            if src_id not in new_src_ids:
                continue
            new_id = src_id + offset
            main = _copy_model_dir(share, manifest, arc, root, str(new_id))
            conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(main), new_id))
            restored += 1
        conn.commit()
    finally:
        conn.close()
    return restored


def _materialise_db(files: dict, manifest: dict, dest: Path) -> None:
    """Met la base du partage dans `dest` (dossier temporaire local) : décompressée (format 1) ou copiée en clair et contrôlée
    par sha256 au passage (format 2)."""
    if sync_tree.is_tree(manifest):
        sync_tree.copy_file(files[TREE_ROOT] / sync_tree.DB_REL, dest, free_bytes=_free_bytes, floor=MIN_FREE_BYTES // 2,
                            low_space=lambda: _disk_full_message(dest.parent), expect_sha=_db_entry(manifest)["sha256"])
    else:
        _gunzip_file(files[DB_ASSET], dest)


def _restore_models_any(files: dict, manifest: dict, models_dir: str, db_path: str) -> int:
    if sync_tree.is_tree(manifest):
        return (_restore_models_tree(files[TREE_ROOT], manifest, models_dir, db_path)
                if sync_tree.MODELS_INDEX_REL in manifest["files"] else 0)
    return _restore_models(files[MODELS_ASSET], models_dir, db_path) if MODELS_ASSET in files else 0


def _restore_store_any(files: dict, manifest: dict, store_root: str) -> int:
    if sync_tree.is_tree(manifest):
        return (_restore_store_tree(files[TREE_ROOT], manifest, store_root)
                if sync_tree.STORE_INDEX_REL in manifest["files"] else 0)
    return _restore_store(files[STORE_ASSET], store_root) if STORE_ASSET in files else 0


def _restore_models_merged_any(files: dict, manifest: dict, models_dir: str, work_db: str, offset: int,
                               new_src_ids: set[int]) -> int:
    if sync_tree.is_tree(manifest):
        return (_restore_models_merged_tree(files[TREE_ROOT], manifest, models_dir, work_db, offset, new_src_ids)
                if sync_tree.MODELS_INDEX_REL in manifest["files"] else 0)
    return (_restore_models_merged(files[MODELS_ASSET], models_dir, work_db, offset, new_src_ids)
            if MODELS_ASSET in files else 0)


# --------------------------------------------------------------------------
# Destinations
# --------------------------------------------------------------------------

class FolderTransport:
    """Un dossier (Google Drive synchronisé, disque réseau, clé USB...)."""

    def __init__(self, folder: str):
        self.folder = Path(folder)

    def upload(self, files: dict[str, Path]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        # Le manifeste en dernier : un lecteur ne voit jamais un manifeste qui annonce des fichiers pas encore copiés.
        # Chaque fichier est écrit SOUS SON NOM FINAL : l'ancien « nom.part puis renommage » laissait des `.part` que le lecteur
        # virtuel de Google Drive refusait ensuite de rouvrir (Errno 22, 10/11/2026) ; le lecteur contrôle de toute façon
        # taille et sha256, donc un fichier coupé ne passe jamais pour complet.
        for name in sorted(files, key=lambda n: n == MANIFEST):
            shutil.copyfile(files[name], self.folder / name)

    def download(self, workdir: Path) -> dict[str, Path]:
        """Chemins des fichiers du partage, LUS SUR PLACE : aucune copie temporaire de 2 Go (ils ne sont jamais écrits)."""
        if not (self.folder / MANIFEST).exists():
            raise SyncError(f"Aucun partage trouvé dans {self.folder} ({MANIFEST} absent).")
        manifest = _read_manifest(self.folder / MANIFEST)
        if sync_tree.is_tree(manifest):             # format 2 : base et petits fichiers listés dans le manifeste ; le reste, `TREE_ROOT`
            try:
                names = [sync_tree.safe_rel(rel) for rel in manifest["files"]]
            except sync_tree.TreeError as exc:
                raise SyncError(str(exc)) from exc
            return {MANIFEST: self.folder / MANIFEST, TREE_ROOT: self.folder, **{n: self.folder / n for n in names}}
        return {name: self.folder / name for name in (MANIFEST, *_ASSETS) if (self.folder / name).exists()}


class GithubTransport:
    """Release glissante `data-latest` du dépôt, via la CLI `gh`."""

    def __init__(self, tag: str = GITHUB_TAG, repo: str | None = None):
        self.tag = tag
        self.repo = repo

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        cmd = ["gh", *args]
        if self.repo:
            cmd += ["--repo", self.repo]
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def _check(self, proc: subprocess.CompletedProcess, what: str) -> None:
        if proc.returncode != 0:
            raise SyncError(f"gh : échec de « {what} » : {(proc.stderr or proc.stdout).strip()}")

    def upload(self, files: dict[str, Path]) -> None:
        if self._gh("release", "view", self.tag).returncode != 0:
            self._check(self._gh("release", "create", self.tag, "--title", "PATRICK : données partagées (dernier état)",
                                 "--notes", "Base assainie, modèles et magasin de données. "
                                            "Généré par `patrick sync push` ; ne pas éditer à la main."),
                        "release create")
        self._check(self._gh("release", "upload", self.tag, *[str(p) for p in files.values()], "--clobber"),
                    "release upload")

    def download(self, workdir: Path) -> dict[str, Path]:
        self._check(self._gh("release", "download", self.tag, "--dir", str(workdir), "--clobber"),
                    "release download")
        return {p.name: p for p in workdir.iterdir() if p.name in (MANIFEST, *_ASSETS)}


def resolve_transport(spec: str, repo: str | None = None):
    return GithubTransport(repo=repo) if spec == "github" else FolderTransport(spec)


# --------------------------------------------------------------------------
# push / pull
# --------------------------------------------------------------------------

def _default_store_root() -> str:
    return str(paths.store_dir())


def _project_dir() -> Path:
    """Dossier du projet (celui qui contient `runs/` et le paquet `patrick/`) : le dossier de travail du worker, auquel se rapportent
    les `trial.artifact_path` relatifs, quel que soit le dossier de travail du processus qui publie (la tâche planifiée Windows
    démarre dans `C:\\Windows\\System32`)."""
    return Path(__file__).resolve().parents[1]


def _default_models_roots() -> list[str]:
    home = str(paths.home_dir())
    roots = [str(_project_dir()), os.getcwd(), home, os.path.join(home, "runs")]
    try:
        roots.append(str(paths.models_dir()))
    except paths.DataRootUnavailable:        # disque de données absent : ses modèles « ne sont pas sur ce PC »
        pass
    return roots


# Caches dérivés (ré-ajustables) : jamais publiés par défaut. Sur la vraie base, `vol_model_cache` fait ~90 % de 27 Go.
_CACHE_TABLES = ("vol_model_cache", "shap_selection_cache")


def _export_research_copy(src: str, work: Path, *, include_personal: bool, include_caches: bool) -> None:
    """Construit `work` (schéma neuf, migré) table par table depuis la base locale, au lieu de copier la base entière
    (27 Go dont 25 de cache) : seuls la recherche (runs, essais, métriques, prédictions...) et, si demandé, les tables
    personnelles sont recopiés. Lecture seule sur `src`."""
    trackdb.connect(str(work)).close()                       # schéma à jour, vide
    conn = sqlite3.connect(Path(work).resolve().as_uri(), uri=True, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")            # ordre de recopie libre
        conn.execute("PRAGMA journal_mode = DELETE")         # fichier jetable : ni WAL (double écriture) ni fsync
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA cache_size = -400000")
        conn.execute("ATTACH DATABASE ? AS src", (Path(src).resolve().as_uri() + "?mode=ro",))
        src_tables = {n for (n,) in conn.execute("SELECT name FROM src.sqlite_master WHERE type = 'table'")}
        conn.execute("BEGIN")
        copied: list[str] = []
        for (name,) in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table' "
                                    "AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall():
            if name not in src_tables or name in ("schema_version", "worker_heartbeat"):
                continue
            if (name.startswith(PERSONAL_PREFIXES) or name in PERSONAL_EXACT) and not include_personal:
                continue
            if name in _CACHE_TABLES and not include_caches:
                continue
            main_cols = [r[1] for r in conn.execute(f'PRAGMA main.table_info("{name}")')]
            src_cols = {r[1] for r in conn.execute(f'PRAGMA src.table_info("{name}")')}
            cols = ", ".join(f'"{c}"' for c in main_cols if c in src_cols)
            conn.execute(f'INSERT OR IGNORE INTO main."{name}" ({cols}) SELECT {cols} FROM src."{name}"')
            copied.append(name)
        if copied and "sqlite_sequence" in src_tables:       # compteurs d'auto-incrément : ne jamais reculer
            for seq_name, seq in conn.execute("SELECT name, seq FROM src.sqlite_sequence").fetchall():
                updated = conn.execute("UPDATE main.sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?",
                                       (seq, seq_name)).rowcount if seq_name in copied else 1
                if updated == 0:
                    conn.execute("INSERT INTO main.sqlite_sequence (name, seq) VALUES (?, ?)", (seq_name, seq))
        conn.execute("COMMIT")
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()


def push(dest: str, *, db_path: str | None = None, store_root: str | None = None,
         models_roots: list[str] | None = None, include_personal: bool = False,
         repo: str | None = None, include_caches: bool = False, layout: str | None = None) -> dict:
    """Publie un état assaini vers `dest` (`"github"` ou un dossier). Retourne le manifeste.

    `layout` : `"tree"` (défaut pour un dossier ; format 2) publie des fichiers en clair en ne copiant que ce qui manque ;
    `"zip"` (défaut pour GitHub, dont les fichiers sont limités à 2 Go ; format 1) reconstruit trois archives à chaque fois."""
    transport = resolve_transport(dest, repo)
    if include_personal and not isinstance(transport, FolderTransport):
        raise SyncError("--include-personal (données perso) n'est autorisé que vers un dossier privé, "
                        "jamais vers GitHub.")
    layout = layout or ("tree" if isinstance(transport, FolderTransport) else "zip")
    if layout not in ("tree", "zip"):
        raise SyncError(f"Mise en page inconnue : {layout!r} (« tree » ou « zip »).")
    if layout == "tree" and not isinstance(transport, FolderTransport):
        raise SyncError("La mise en page en clair n'existe que vers un dossier (GitHub n'accepte que des fichiers de 2 Go).")
    src = db_path or trackdb.default_db_path()
    if not os.path.exists(src):
        raise SyncError(f"Base introuvable : {src}")

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        work = tmp / "work.db"
        _require_space(tmp, 4 << 30, "préparer la publication")
        _export_research_copy(src, work, include_personal=include_personal, include_caches=include_caches)
        copy = sqlite3.connect(work)
        roots = models_roots if models_roots is not None else _default_models_roots()
        models_files: list[tuple[Path, str]] = []
        models_index: dict[str, str] = {}
        try:
            if layout == "zip":
                models_info = _build_models_bundle(copy, roots, tmp / MODELS_ASSET)
            else:
                digests: dict[Path, str] = {}

                def arc_for(_trial_id, found: Path) -> str:      # rangé par empreinte du CONTENU : les id d'essai sont propres à chaque PC
                    digest = digests.setdefault(found, sync_tree.sha256_file(found)[:16])
                    return f"models/{digest}/{found.name}"

                models_files, models_index, missing = _collect_models(copy, roots, arc_for)
                models_info = {"included": len(models_index), "missing": missing}
            _neutralise_runtime_state(copy)
            excluded: list[str] = []
            if not include_personal:
                excluded = personal_tables(copy)            # non copiées dans l'export : on vérifie seulement la fuite
                needle = Path.home().name
                if len(needle) >= 4:
                    _redact_username_in_errors(copy, needle)         # messages d'erreur seulement ; la copie jetable, pas la base locale
                leaks = _username_leaks(copy, needle) if len(needle) >= 4 else {}
                if leaks:
                    raise SyncError("La base contient le nom d'utilisateur du PC (" + ", ".join(
                        f"{k}: {v} ligne(s)" for k, v in leaks.items()) + ") : publication refusée.")
            version = copy.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            runs = copy.execute("SELECT COUNT(*) FROM run").fetchone()[0]
            copy.execute("PRAGMA journal_mode = DELETE")
        finally:
            copy.close()

        common = {
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_version": version,
            "runs": runs,
            "personal_included": include_personal,
            "excluded_tables": excluded,
            "models": models_info,
        }
        if layout == "tree":
            try:
                return _publish_tree(transport.folder, work, models_files, models_index, store_root or _default_store_root(), common)
            except sync_tree.TreeError as exc:
                raise SyncError(str(exc)) from exc

        files: dict[str, Path] = {}
        _gzip_file(work, tmp / DB_ASSET)
        files[DB_ASSET] = tmp / DB_ASSET
        if models_info["included"]:
            files[MODELS_ASSET] = tmp / MODELS_ASSET
        store_info = _build_store_bundle(store_root or _default_store_root(), tmp / STORE_ASSET)
        if store_info["files"]:
            files[STORE_ASSET] = tmp / STORE_ASSET

        manifest = {
            "format": FORMAT_VERSION,
            **common,
            "store": store_info,
            "files": {name: {"sha256": _sha256(p), "size": p.stat().st_size} for name, p in files.items()},
        }
        manifest_path = tmp / MANIFEST
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        files[MANIFEST] = manifest_path
        transport.upload(files)
    return manifest


def _publish_tree(folder: Path, work: Path, models_files: list[tuple[Path, str]], models_index: dict[str, str],
                  store_root: str, common: dict) -> dict:
    """Publie en clair (format 2) : copie les modèles et parquet qui MANQUENT dans `folder`, les index, la base, puis écrit le
    manifeste en dernier. Une copie interrompue (disque presque plein, coupure) ne change rien au partage : la suivante reprend."""
    sync_tree.remove_old_part_files(folder)
    parquets, store_index = _store_selection(store_root)
    immutable = list(models_files) + [(p, f"store/{p.parent.name}/{p.name}") for p in parquets]
    small: dict[str, str] = {}
    if models_index:
        small[sync_tree.MODELS_INDEX_REL] = json.dumps(models_index, indent=1)
    if parquets:
        small[sync_tree.STORE_INDEX_REL] = json.dumps(store_index, indent=1)
        series = Path(store_root) / "_series_observations.json"
        if series.exists():
            small[sync_tree.STORE_SERIES_REL] = series.read_text(encoding="utf-8")
    folder.mkdir(parents=True, exist_ok=True)
    result = sync_tree.publish(folder, db_file=work, immutable=immutable, small=small, free_bytes=_free_bytes,
                               floor=FOLDER_MIN_FREE_BYTES, low_space=lambda: _disk_full_message(folder))
    manifest = {"format": sync_tree.FORMAT, **common, "store": {"files": len(parquets)}, "files": result["files"],
                "tree": result["tree"], "uploaded": result["uploaded"]}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")        # en dernier
    left = [name for name in _ASSETS if (folder / name).exists()]
    return {**manifest, "legacy_assets_left": left} if left else manifest


def _restore_db(new_db: Path, db_path: str, *, force: bool, backup_dir: str | None) -> dict:
    """Remplace la base locale par `new_db` en conservant les tables
    personnelles locales. Sauvegarde d'abord la base locale."""
    conn = trackdb.connect(str(new_db))            # migre le snapshot jusqu'à la version du code
    backup_path = None
    kept: list[str] = []
    try:
        if os.path.exists(db_path):
            old = sqlite3.connect(db_path)
            try:
                local_runs = ({r[0] for r in old.execute("SELECT run_id FROM run")}
                              if old.execute("SELECT 1 FROM sqlite_master WHERE name = 'run'").fetchone() else set())
            finally:
                old.close()
            shared_runs = {r[0] for r in conn.execute("SELECT run_id FROM run")}
            lost = sorted(local_runs - shared_runs)
            if lost and not force:
                raise SyncError(f"{len(lost)} run(s) locaux absents du partage seraient perdus "
                                f"({', '.join(lost[:5])}{'...' if len(lost) > 5 else ''}). "
                                "Pousse d'abord depuis ce PC, ou utilise --force.")
            backup_path = backup_mod.backup_database(db_path, backup_dir, pages=-1, sleep_s=0.0)
            conn.execute("ATTACH DATABASE ? AS old", (db_path,))
            try:
                old_tables = {n for (n,) in conn.execute("SELECT name FROM old.sqlite_master WHERE type = 'table'")}
                for table in personal_tables(conn):
                    if table not in old_tables:
                        continue
                    new_cols = [r[1] for r in conn.execute(f'PRAGMA main.table_info("{table}")')]
                    old_cols = {r[1] for r in conn.execute(f'PRAGMA old.table_info("{table}")')}
                    cols = ", ".join(f'"{c}"' for c in new_cols if c in old_cols)
                    conn.execute(f'INSERT OR REPLACE INTO main."{table}" ({cols}) SELECT {cols} FROM old."{table}"')
                    kept.append(table)
                conn.commit()
            finally:
                conn.execute("DETACH DATABASE old")
        runs = conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
        conn.execute("PRAGMA journal_mode = DELETE")
    finally:
        conn.close()

    incoming = Path(db_path + ".incoming")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(new_db, incoming)
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass
    os.replace(incoming, db_path)
    return {"runs": runs, "backup": str(backup_path) if backup_path else None, "personal_tables_kept": kept}


def _restore_models(archive: Path, models_dir: str, db_path: str) -> int:
    root = Path(models_dir)
    with zipfile.ZipFile(archive) as zf:
        index = json.loads(zf.read("index.json").decode("utf-8"))
        extracted: dict[str, Path] = {}
        for name in zf.namelist():
            if name.startswith("models/"):
                extracted[name] = _safe_extract(zf, name, root, name[len("models/"):])
    conn = sqlite3.connect(db_path)
    try:
        for trial_id, arc in index.items():
            if arc in extracted:
                conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?",
                             (str(extracted[arc]), int(trial_id)))
        conn.commit()
    finally:
        conn.close()
    return len(index)


def _download_verified(transport, workdir: Path) -> tuple[dict[str, Path], dict]:
    """Télécharge le partage, vérifie les sha256 et la version de schéma."""
    files = transport.download(workdir)
    if MANIFEST not in files:
        raise SyncError("Partage incomplet : manifest manquant.")
    manifest = _read_manifest(files[MANIFEST])
    if sync_tree.is_tree(manifest):
        try:
            sync_tree.verify(files[TREE_ROOT], manifest)       # présence, tailles, petits fichiers ; la base l'est à sa copie
        except sync_tree.TreeError as exc:
            raise SyncError(str(exc)) from exc
    else:
        if DB_ASSET not in files:
            raise SyncError("Partage incomplet : manifest ou base manquants.")
        for name, meta in manifest["files"].items():
            if name not in files:
                raise SyncError(f"Fichier annoncé mais absent : {name}")
            if _sha256(files[name]) != meta["sha256"]:
                raise SyncError(f"Fichier corrompu (sha256 différent) : {name}")
    latest = _latest_code_version()
    if manifest["schema_version"] > latest:
        raise SyncError(f"Le partage est en version de schéma {manifest['schema_version']}, ce code ne connaît "
                        f"que jusqu'à {latest} : mets le code à jour (git pull) avant de restaurer.")
    return files, manifest


def pull(source: str, *, db_path: str | None = None, store_root: str | None = None,
         models_dir: str | None = None, backup_dir: str | None = None, force: bool = False,
         repo: str | None = None) -> dict:
    """Restaure le partage `source` (`"github"` ou un dossier) sur ce PC."""
    transport = resolve_transport(source, repo)
    db_path = db_path or trackdb.default_db_path()
    try:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            files, manifest = _download_verified(transport, tmp)

            new_db = tmp / "incoming.db"
            _materialise_db(files, manifest, new_db)
            result = _restore_db(new_db, db_path, force=force, backup_dir=backup_dir)
            result["models"] = _restore_models_any(files, manifest, models_dir or str(paths.models_dir()), db_path)
            result["store_files"] = _restore_store_any(files, manifest, store_root or _default_store_root())
            result["created_at"] = manifest["created_at"]
    except sync_tree.TreeError as exc:
        raise SyncError(str(exc)) from exc
    return result


# --------------------------------------------------------------------------
# Synchronisation automatique entre deux PC (dossier partagé, p. ex. OneDrive)
# --------------------------------------------------------------------------
#
# `merge` importe dans la base locale ce que le partage a en plus (union, voir
# `sync_merge`); `push` publie l'état local. `auto` enchaîne les deux quand il le
# faut, d'après un petit état local (`~/.patrick/sync_state.json`) :
#   remote_sha : empreinte de la base du partage telle que ce PC l'a déjà fusionnée/publiée;
#   local_fp   : empreinte de la recherche locale au dernier échange.
# Partage différent de remote_sha  -> un autre PC a publié : on fusionne.
# Recherche locale différente de local_fp -> ce PC a du neuf : on publie (après fusion).
# Jamais de remplacement de la base locale par le partage : aucun run n'est perdu.

STATE_NAME = "sync_state.json"
KEY_SYNC_FOLDER = "sync_folder"
KEY_WEALTH_REFERENCE = "sync_wealth_reference"
KEY_PC_NAME = "sync_pc_name"
# Tables recopiées/volatiles : un changement n'y compte pas comme « du neuf à publier ».
_VOLATILE_TABLES = ("job", "worker_heartbeat", "vol_model_cache", "shap_selection_cache")


def state_path() -> Path:
    return settings_mod.settings_path().with_name(STATE_NAME)


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(**fields) -> dict:
    data = {**load_state(), **fields, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return data


def configured_folder() -> str | None:
    return settings_mod.load().get(KEY_SYNC_FOLDER) or None


def is_wealth_reference() -> bool:
    """Ce PC est-il la référence du patrimoine ? Seul lui le publie; les autres adoptent celui du partage."""
    return bool(settings_mod.load().get(KEY_WEALTH_REFERENCE))


def fingerprint(db_path: str, *, personal: bool = False) -> str:
    """Empreinte du contenu de recherche d'une base (nombre de lignes et plus grand rowid de chaque table
    hors patrimoine/fonds, caches et état d'exécution). Lecture seule. Un changement fait en place (p. ex.
    un `y_true` rempli après coup) n'est pas vu : il partira avec le prochain run. `personal` : y ajoute le
    contenu du patrimoine et des fonds (PC de référence : une modification doit déclencher une publication)."""
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        parts = []
        if personal:
            for table in sync_merge.ADOPTED_PERSONAL_TABLES:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                parts.append([table, hashlib.sha256(repr(rows).encode()).hexdigest()])
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                    "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            if name.startswith(PERSONAL_PREFIXES) or name in PERSONAL_EXACT or name in _VOLATILE_TABLES:
                continue
            try:
                n, top = conn.execute(f'SELECT COUNT(*), MAX(rowid) FROM "{name}"').fetchone()
            except sqlite3.OperationalError:          # table WITHOUT ROWID
                n, top = conn.execute(f'SELECT COUNT(*), NULL FROM "{name}"').fetchone()
            parts.append([name, n, top])
        return hashlib.sha256(json.dumps(parts).encode()).hexdigest()
    finally:
        conn.close()


def remote_stamp(folder: str) -> dict | None:
    """Empreinte du partage (sha256 de sa base, date de publication), ou None s'il n'y a rien."""
    path = Path(folder) / MANIFEST
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return {"sha": _db_entry(manifest)["sha256"], "created_at": manifest["created_at"],
            "runs": manifest.get("runs")}


def _job_running(db_path: str) -> bool:
    from patrick.tracking import jobs as jobs_db

    if not os.path.exists(db_path):
        return False
    conn = trackdb.connect(db_path)
    try:
        return bool(conn.execute("SELECT COUNT(*) FROM job WHERE status = 'running'").fetchone()[0]
                    or jobs_db.worker_is_alive(conn))
    finally:
        conn.close()


def _db_in_use(db_path: str) -> bool:
    """Windows : un fichier SQLite ouvert par un autre processus ne peut pas être renommé. Sert à savoir si
    PATRICK (serveur) tourne avant de remplacer la base. Ailleurs : jamais bloquant."""
    if os.name != "nt" or not os.path.exists(db_path):
        return False
    probe = db_path + ".probe"
    try:
        os.rename(db_path, probe)
    except PermissionError:
        return True
    os.rename(probe, db_path)
    return False


def _restore_models_merged(archive: Path, models_dir: str, work_db: str, offset: int,
                           new_src_ids: set[int]) -> int:
    """Extrait les modèles des essais importés vers `<models_dir>/<nouvel id>/` (l'identifiant d'essai
    a été décalé par la fusion) et y pointe `trial.artifact_path`."""
    root = Path(models_dir)
    restored = 0
    with zipfile.ZipFile(archive) as zf:
        index = json.loads(zf.read("index.json").decode("utf-8"))
        by_trial: dict[int, list[str]] = {}
        for name in zf.namelist():
            parts = name.split("/")
            if parts[0] == "models" and len(parts) == 3 and parts[1].isdigit():
                by_trial.setdefault(int(parts[1]), []).append(name)
        conn = sqlite3.connect(work_db)
        try:
            for key, arc in index.items():
                src_id = int(key)
                if src_id not in new_src_ids:
                    continue
                new_id = src_id + offset
                for name in by_trial.get(src_id, []):
                    target = _safe_extract(zf, name, root, f"{new_id}/{name.split('/')[2]}")
                    if name == arc:
                        conn.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (str(target), new_id))
                        restored += 1
            conn.commit()
        finally:
            conn.close()
    return restored


def _count_runs(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    finally:
        conn.close()


def _quick_check(path: str) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()


def _backup_affordable(db_path: str, backup_dir: str | None, incoming_bytes: int) -> tuple[bool, str]:
    """Une sauvegarde complète avant fusion n'est faite que si le disque la permet (une base de 27 Go sur un disque presque
    plein : jamais). La fusion reste atomique (une transaction) : sans sauvegarde, une coupure ne laisse pas de demi-fusion."""
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    free = _free_bytes(backup_dir or paths.backups_dir())
    if free >= size * 1.05 + incoming_bytes * 2 + (2 << 30):
        return True, ""
    return False, f"sauvegarde complète ignorée : {_gb(size)} Go à copier pour {_gb(free)} Go libres"


def _save_champion_snapshot(db_path: str) -> str | None:
    """La fusion peut remplacer un champion local par un plus récent du partage : on garde l'ancienne table (quelques Ko),
    seule donnée locale qu'une fusion réécrit."""
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        cur = conn.execute("SELECT * FROM champion")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    dest = Path(db_path).parent / "sync_undo"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"champion-{datetime.now():%Y%m%d_%H%M%S}.json"  # noqa: DTZ005 -- heure locale lue par l'utilisateur
    path.write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return str(path)


def _merge_into_copy(files: dict, manifest: dict, incoming: Path, dry_run_to: str, *, db_path: str,
                     adopt_personal: bool) -> dict:
    """Essai à blanc : fusionne dans une COPIE (`dry_run_to`), sans toucher à la base locale, au magasin ni aux modèles."""
    work = Path(dry_run_to)
    work.parent.mkdir(parents=True, exist_ok=True)
    work.unlink(missing_ok=True)
    if os.path.exists(db_path):
        source_conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
        target_conn = sqlite3.connect(work)
        try:
            source_conn.backup(target_conn)
        finally:
            source_conn.close()
            target_conn.close()
    trackdb.connect(str(work)).close()
    try:
        runs_before = _count_runs(str(work))
        report = sync_merge.merge_databases(str(work), str(incoming), fast=True)
        personal = (sync_merge.adopt_personal_tables(str(work), str(incoming))
                    if adopt_personal and manifest.get("personal_included") else {})
        check = _quick_check(str(work))
        if check != "ok":
            raise SyncError(f"Base fusionnée invalide (quick_check : {check}) : base locale inchangée.")
        return {"runs_before": runs_before, "runs_after": _count_runs(str(work)), "new_runs": report["new_runs"],
                "local_only_runs": report["local_only_runs"], "models": 0, "store_files": 0, "backup": None,
                "created_at": manifest["created_at"], "remote_sha": _db_entry(manifest)["sha256"],
                "added": report["added"], "personal": personal}
    except BaseException:
        work.unlink(missing_ok=True)
        raise


def _merge_in_place(files: dict, manifest: dict, incoming: Path, *, db_path: str, models_dir: str | None,
                    backup_dir: str | None, adopt_personal: bool) -> dict:
    """Fusion DIRECTEMENT dans la base locale (une transaction : tout ou rien), sans copie de travail ni sauvegarde
    systématique -- sur une base de 27 Go, ces deux copies (54 Go, ~14 min) saturaient le disque."""
    incoming_bytes = incoming.stat().st_size
    _require_space(db_path, incoming_bytes, "fusionner le partage")      # le journal d'une fusion ≲ ce qu'elle importe
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    trackdb.connect(db_path).close()                                        # crée/migre la base locale
    backup, backup_skipped = None, None
    ok, why = _backup_affordable(db_path, backup_dir, incoming_bytes)
    if ok:
        backup = str(backup_mod.backup_database(db_path, backup_dir, pages=-1, sleep_s=0.0))
    else:
        backup_skipped = why
    champions = _save_champion_snapshot(db_path)
    runs_before = _count_runs(db_path)
    report = sync_merge.merge_databases(db_path, str(incoming), fast=False)
    personal = (sync_merge.adopt_personal_tables(db_path, str(incoming))
                if adopt_personal and manifest.get("personal_included") else {})
    models = _restore_models_merged_any(files, manifest, models_dir or str(paths.models_dir()),
                                        db_path, report["trial_offset"], set(report["new_trial_ids"]))
    return {"runs_before": runs_before, "runs_after": _count_runs(db_path), "new_runs": report["new_runs"],
            "new_run_ids": report["new_run_ids"], "local_only_runs": report["local_only_runs"], "models": models,
            "store_files": 0, "backup": backup, "backup_skipped": backup_skipped, "champion_snapshot": champions,
            "created_at": manifest["created_at"], "remote_sha": _db_entry(manifest)["sha256"],
            "added": report["added"], "personal": personal}


def merge(source: str, *, db_path: str | None = None, store_root: str | None = None,
          models_dir: str | None = None, backup_dir: str | None = None, dry_run_to: str | None = None,
          adopt_personal: bool = False, repo: str | None = None) -> dict:
    """Importe dans la base locale la recherche du partage `source` (union, voir `sync_merge`).

    La fusion se fait EN PLACE dans la base locale, en une transaction (tout ou rien) : pas de copie de travail, et une
    sauvegarde complète seulement si le disque la permet. Le partage est lu sur place (aucune copie temporaire) et sa base
    n'est décompressée (~15 s pour 5 Go) que dans un dossier temporaire. Le serveur PATRICK doit être fermé.
    `dry_run_to` : écrit le résultat d'une fusion dans ce fichier (copie complète de la base locale) et s'arrête (la base
    locale, le magasin et les modèles ne sont pas touchés). `adopt_personal` : remplace aussi le patrimoine et les fonds
    locaux par ceux du partage, s'il en contient (PC qui n'est pas la référence)."""
    started = time.monotonic()
    transport = resolve_transport(source, repo)
    db_path = db_path or trackdb.default_db_path()
    if dry_run_to is None and _db_in_use(db_path):
        raise SyncError("PATRICK est ouvert (la base est utilisée) : ferme-le, puis relance la synchronisation.")
    try:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            files, manifest = _download_verified(transport, tmp)
            incoming = tmp / "incoming.db"
            _materialise_db(files, manifest, incoming)
            trackdb.connect(str(incoming)).close()               # migre le partage jusqu'à la version du code
            if dry_run_to is not None:
                result = _merge_into_copy(files, manifest, incoming, dry_run_to, db_path=db_path,
                                          adopt_personal=adopt_personal)
            else:
                result = _merge_in_place(files, manifest, incoming, db_path=db_path, models_dir=models_dir,
                                         backup_dir=backup_dir, adopt_personal=adopt_personal)
                result["store_files"] = _restore_store_any(files, manifest, store_root or _default_store_root())
    except sync_tree.TreeError as exc:
        raise SyncError(str(exc)) from exc
    except sqlite3.OperationalError as exc:
        if "disk is full" in str(exc):
            raise SyncError(_disk_full_message(db_path)) from exc
        raise
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise SyncError(_disk_full_message(db_path)) from exc
        raise
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def status(folder: str, *, db_path: str | None = None) -> dict:
    """Ce que `auto` ferait : fusionner le partage (`need_pull`), publier (`need_push`), les deux, ou rien."""
    db_path = db_path or trackdb.default_db_path()
    state, stamp = load_state(), remote_stamp(folder)
    exists = os.path.exists(db_path)
    reference = is_wealth_reference()
    local_fp = fingerprint(db_path, personal=reference) if exists else None
    need_pull = stamp is not None and stamp["sha"] != state.get("remote_sha")
    local_changed = exists and local_fp != state.get("local_fp")
    data_root = paths.configured_data_root()
    data_available = paths.data_root_missing() is None
    return {"folder": folder, "remote": stamp, "last_exchange": state.get("at"), "wealth_reference": reference,
            "local_runs": _count_runs(db_path) if exists else 0,
            "disk_free_gb": round(_free_bytes(db_path) / 1e9, 1), "db_gb": round(os.path.getsize(db_path) / 1e9, 1) if exists else 0.0,
            "data_root": str(data_root) if data_root else None, "data_available": data_available,
            "data_free_gb": round(_free_bytes(data_root) / 1e9, 1) if data_root and data_available else None,
            "need_pull": need_pull, "local_changed": local_changed,
            "need_push": exists and (stamp is None or local_changed or need_pull)}


def _min_push_hours(explicit: float | None) -> float:
    """Délai minimal entre deux publications : paramètre, sinon réglage `sync_min_push_hours`, sinon 24 h."""
    if explicit is not None:
        return float(explicit)
    raw = settings_mod.load().get(KEY_MIN_PUSH_HOURS)
    try:
        return float(raw) if raw is not None else float(DEFAULT_MIN_PUSH_HOURS)
    except (TypeError, ValueError):
        return float(DEFAULT_MIN_PUSH_HOURS)


def _push_too_soon(state: dict, hours: float) -> str | None:
    """Message si la dernière publication de ce PC date de moins de `hours` heures, sinon None. La base (~3 Go) est réécrite
    à chaque publication, et Google Drive garde les anciennes versions d'un fichier remplacé : on ne la republie pas toutes les heures.
    La première publication d'un PC n'est jamais retardée."""
    if hours <= 0 or not state.get("pushed_at"):
        return None
    try:
        last = datetime.fromisoformat(state["pushed_at"])
    except ValueError:
        return None
    elapsed = (datetime.now(UTC) - last).total_seconds() / 3600
    if elapsed >= hours:
        return None
    return (f"publication reportée : dernière publication il y a {elapsed:.1f} h (au moins {hours:g} h entre deux publications, "
            f"réglage « {KEY_MIN_PUSH_HOURS} » ; `patrick sync auto --min-push-hours 0` publie tout de suite)")


def auto(folder: str, *, only: str | None = None, wealth_reference: bool | None = None, db_path: str | None = None,
         store_root: str | None = None, models_dir: str | None = None, models_roots: list[str] | None = None,
         backup_dir: str | None = None, min_push_hours: float | None = None) -> dict:
    """Met ce PC et le partage à niveau : fusionne ce que l'autre PC a publié, puis publie ce que ce PC a de
    neuf. `only="pull"` / `"push"` limite à une moitié. Rien de risqué : pas de fusion tant qu'un entraînement
    tourne ou que PATRICK est ouvert, pas de publication tant qu'un entraînement tourne ni si le partage a
    bougé sans avoir été fusionné. `wealth_reference` (défaut : réglage de ce PC) : ce PC publie son
    patrimoine et ses fonds, sinon il adopte ceux du partage. Renvoie `{"actions": [...], "skipped": [...]}`."""
    if only not in (None, "pull", "push"):
        raise SyncError("only doit être 'pull', 'push' ou omis.")
    db_path = db_path or trackdb.default_db_path()
    reference = is_wealth_reference() if wealth_reference is None else wealth_reference
    out: dict = {"actions": [], "skipped": []}
    problem = paths.data_root_problem()
    if problem:                  # sauvegardes, modèles et magasin vivent sur le disque de données : rien à faire sans lui
        out["skipped"].append(f"synchronisation reportée : {problem}")
        return out
    state, stamp = load_state(), remote_stamp(folder)

    if only in (None, "pull") and stamp is not None and stamp["sha"] != state.get("remote_sha"):
        if _job_running(db_path):
            out["skipped"].append("fusion reportée : un entraînement est en cours")
        else:
            fp_before = fingerprint(db_path, personal=reference) if os.path.exists(db_path) else None
            try:
                res = merge(folder, db_path=db_path, store_root=store_root, models_dir=models_dir,
                            backup_dir=backup_dir, adopt_personal=not reference)
            except SyncError as exc:
                out["skipped"].append(f"fusion reportée : {exc}")
            else:
                # Rien à publier si ce PC n'avait rien de neuf et que le partage contenait déjà tout son contenu.
                clean = state.get("local_fp") == fp_before and res["local_only_runs"] == 0
                save_state(remote_sha=res["remote_sha"],
                           local_fp=fingerprint(db_path, personal=reference) if clean else state.get("local_fp"))
                note = " + patrimoine du PC de référence adopté" if res["personal"] else ""
                out["actions"].append(f"fusion : {res['new_runs']} run(s) importé(s) du partage "
                                      f"({res['runs_before']} -> {res['runs_after']}){note}")
                out["merge"] = res

    if only in (None, "push") and os.path.exists(db_path):
        state, stamp = load_state(), remote_stamp(folder)
        fp = fingerprint(db_path, personal=reference)
        if stamp is None or fp != state.get("local_fp"):
            if stamp is not None and stamp["sha"] != state.get("remote_sha"):
                out["skipped"].append("publication reportée : le partage contient des données pas encore "
                                      "fusionnées (lance la synchronisation avec PATRICK fermé)")
            elif _job_running(db_path):
                out["skipped"].append("publication reportée : un entraînement est en cours")
            elif stamp is not None and (late := _push_too_soon(state, _min_push_hours(min_push_hours))):
                out["skipped"].append(late)
            else:
                manifest = push(folder, db_path=db_path, store_root=store_root, models_roots=models_roots,
                                include_personal=reference)
                save_state(remote_sha=_db_entry(manifest)["sha256"], local_fp=fp,
                           pushed_at=datetime.now(UTC).isoformat(timespec="seconds"))
                out["actions"].append(f"publication : {manifest['runs']} run(s), "
                                      f"{manifest['models']['included']} modèle(s)"
                                      + (", patrimoine inclus" if reference else "")
                                      + (f", anciens fichiers à supprimer du dossier : {', '.join(manifest['legacy_assets_left'])}"
                                         if manifest.get("legacy_assets_left") else ""))
    if os.path.exists(db_path):
        _funds_stage(folder, db_path, backup_dir, out)          # indépendant de la recherche et des entraînements
    return out


# --------------------------------------------------------------------------
# Fonds : un fichier par PC, fusion par union (voir `patrick.fund.share`)
# --------------------------------------------------------------------------
#
# Indépendant de la recherche : il n'attend ni la fin d'un entraînement, ni la fusion du gros partage. Chaque PC
# n'écrit que SON fichier (`funds-<pc>.db.gz` + `funds-<pc>.json` qui porte l'empreinte) : le dossier partagé n'a
# donc jamais deux PC qui écrivent le même fichier. État local : `funds_seen` (empreinte de chaque fichier déjà
# fusionné) et `funds_fp` (empreinte de nos fonds à la dernière publication).

FUNDS_PREFIX = "funds-"


def pc_name() -> str:
    """Nom de ce PC dans les fichiers du partage (réglage `sync_pc_name`, sinon le nom d'hôte)."""
    raw = settings_mod.load().get(KEY_PC_NAME) or socket.gethostname() or "pc"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw)).strip("_")[:40] or "pc"


def _has_funds(db_path: str) -> bool:
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return bool(conn.execute(
            "SELECT (SELECT COUNT(*) FROM fund_strategy) + (SELECT COUNT(*) FROM fund_deleted)").fetchone()[0])
    finally:
        conn.close()


def _funds_merge_others(folder: str, db_path: str, backup_dir: str | None, out: dict) -> None:
    state = load_state()
    seen = dict(state.get("funds_seen") or {})
    own = f"{FUNDS_PREFIX}{pc_name()}.json"
    for meta_path in sorted(Path(folder).glob(f"{FUNDS_PREFIX}*.json")):
        if meta_path.name == own:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            sha, who = meta["sha256"], meta.get("pc") or meta_path.stem[len(FUNDS_PREFIX):]
        except (OSError, ValueError, KeyError, TypeError):
            out["skipped"].append(f"fonds : {meta_path.name} illisible, réessayé au prochain passage")
            continue
        if seen.get(meta_path.name) == sha:
            continue
        gz = meta_path.with_name(meta_path.name[: -len(".json")] + ".db.gz")
        try:
            if not gz.exists() or _sha256(gz) != sha:
                raise SyncError("fichier pas encore entièrement recopié par le dossier partagé")
            with tempfile.TemporaryDirectory() as tmp_s:
                incoming = Path(tmp_s) / "incoming.db"
                _gunzip_file(gz, incoming)
                res = fund_share.merge_funds(db_path, incoming, backup_dir=backup_dir)
        except (SyncError, fund_share.FundShareError, sqlite3.Error, OSError, EOFError) as exc:
            out["skipped"].append(f"fonds de {who} reportés : {exc}")
            continue
        seen[meta_path.name] = sha
        parts = [f"{len(res[key])} stratégie(s) {label}" for key, label in
                 (("imported", "importée(s)"), ("replaced", "remplacée(s) par une version plus récente"),
                  ("deleted", "supprimée(s)")) if res[key]]
        if parts:
            out["actions"].append(f"fonds de {who} : " + ", ".join(parts))
    if seen != (state.get("funds_seen") or {}):
        save_state(funds_seen=seen)


def _funds_publish(folder: str, db_path: str, out: dict) -> None:
    fp = fund_share.fingerprint(db_path)
    name = pc_name()
    gz_name, json_name = f"{FUNDS_PREFIX}{name}.db.gz", f"{FUNDS_PREFIX}{name}.json"
    published = (Path(folder) / json_name).exists()
    if (fp == load_state().get("funds_fp") and published) or (not published and not _has_funds(db_path)):
        if fp != load_state().get("funds_fp"):
            save_state(funds_fp=fp)
        return
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        info = fund_share.export_funds(db_path, tmp / "funds.db")
        _gzip_file(tmp / "funds.db", tmp / gz_name)
        meta = {"format": 1, "pc": name, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "sha256": _sha256(tmp / gz_name), "size": (tmp / gz_name).stat().st_size, **info}
        (tmp / json_name).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        FolderTransport(folder).upload({gz_name: tmp / gz_name, json_name: tmp / json_name})   # le .json en dernier
    save_state(funds_fp=fp)
    out["actions"].append(f"fonds publiés : {info['strategies']} stratégie(s), {info['orders']} ordre(s)")


def _funds_stage(folder: str, db_path: str, backup_dir: str | None, out: dict) -> None:
    """Fusionne les fonds des autres PC puis publie les nôtres s'ils ont changé. Ne lève jamais : un échec (fichier
    pas encore recopié, base occupée...) est noté dans `out["skipped"]` et réessayé au prochain passage."""
    try:
        trackdb.connect(db_path).close()          # migrations en attente (0033) : la tâche horaire peut passer avant PATRICK
        _funds_merge_others(folder, db_path, backup_dir, out)
        _funds_publish(folder, db_path, out)
    except (SyncError, fund_share.FundShareError, sqlite3.Error, OSError) as exc:
        out["skipped"].append(f"fonds : {exc}")


SYNC_TASK = "PATRICK-Sync"


def register_task(minutes: int = 60) -> str:
    """Windows : tâche planifiée (session ouverte, sans fenêtre) qui publie ce PC dès qu'il a du neuf
    (`sync auto --only push`). Elle utilise l'interpréteur qui exécute cette commande : lance donc
    `sync setup --schedule` depuis la version stable pour que la tâche vise la version stable."""
    if os.name != "nt":
        raise SyncError("La tâche planifiée n'est gérée que sous Windows.")
    import sys

    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    log = os.path.normpath(str(paths.logs_dir() / "sync.log"))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    command = f'"{pythonw if pythonw.exists() else exe}" -m patrick.cli sync auto --only push --log-file "{log}"'
    proc = subprocess.run(["schtasks", "/Create", "/TN", SYNC_TASK, "/TR", command, "/SC", "MINUTE",
                           "/MO", str(minutes), "/F"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SyncError(f"schtasks : {(proc.stderr or proc.stdout).strip()}")
    # Par défaut Windows ne lance pas (et arrête) une tâche sur batterie : sur un portable elle n'aurait
    # jamais lieu. On l'autorise, et on rattrape un passage manqué (PC éteint à l'heure prévue).
    settings = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         (f"Set-ScheduledTask -TaskName '{SYNC_TASK}' -Settings (New-ScheduledTaskSettingsSet "
          "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
          "-ExecutionTimeLimit ([TimeSpan]::Zero)) | Out-Null")],      # aucune limite de durée (30/10)
        capture_output=True, text=True, check=False)
    if settings.returncode != 0:
        raise SyncError(f"réglages de la tâche (batterie) : {(settings.stderr or settings.stdout).strip()}")
    return command


def unregister_task() -> bool:
    """Supprime la tâche planifiée `PATRICK-Sync`. Renvoie False si elle n'existait pas."""
    if os.name != "nt":
        raise SyncError("La tâche planifiée n'est gérée que sous Windows.")
    if task_status()["registered"] is False:
        return False
    proc = subprocess.run(["schtasks", "/Delete", "/TN", SYNC_TASK, "/F"], capture_output=True, text=True,
                          check=False)
    if proc.returncode != 0:
        raise SyncError(f"schtasks : {(proc.stderr or proc.stdout).strip()}")
    return True


def task_status() -> dict:
    """État de la tâche planifiée `PATRICK-Sync` : `{"supported", "registered", "next_run"}` (lecture seule)."""
    if os.name != "nt":
        return {"supported": False, "registered": False, "next_run": None}
    proc = subprocess.run(["schtasks", "/Query", "/TN", SYNC_TASK, "/FO", "LIST", "/V"], capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        return {"supported": True, "registered": False, "next_run": None}
    next_run = None
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(":")
        # Le libellé dépend de la langue de Windows (« Prochaine exécution » / « Next Run Time »).
        if key.strip().lower() in ("prochaine exécution", "prochaine execution", "next run time"):
            next_run = value.strip() or None
    return {"supported": True, "registered": True, "next_run": next_run}


def forget_exchange() -> None:
    """Oublie l'état d'échange avec le partage (empreintes de la dernière synchronisation). À appeler quand
    le dossier de partage CHANGE : l'ancien état ne dit rien du nouveau dossier (ni la date de la dernière publication, qui ne
    doit pas retarder la première publication vers ce dossier)."""
    state = load_state()
    for key in ("remote_sha", "local_fp", "at", "pushed_at"):
        state.pop(key, None)
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
