"""`patrick sync` -- partage de la base, des modèles et du magasin de données
entre deux PC.

Ce qui est partagé : `patrick.db` (compressée), les fichiers modèles référencés
par `trial.artifact_path`, et les parquet du magasin de données
(`~/.patrick/store`). Un `manifest.json` (sha256, taille, version de schéma)
accompagne les fichiers.

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

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from patrick import settings as settings_mod
from patrick import sync_merge
from patrick.tracking import backup as backup_mod
from patrick.tracking import db as trackdb

GITHUB_TAG = "data-latest"
DB_ASSET = "patrick.db.gz"
MODELS_ASSET = "models.zip"
STORE_ASSET = "store.zip"
MANIFEST = "manifest.json"
_ASSETS = (DB_ASSET, MODELS_ASSET, STORE_ASSET)
FORMAT_VERSION = 1

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


def _gunzip_file(src: Path, dest: Path) -> None:
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


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


def _build_models_bundle(copy: sqlite3.Connection, roots: list[str], dest: Path) -> dict:
    """Zippe les modèles référencés par la copie de la base et y remplace
    `trial.artifact_path` par le nom dans l'archive (aucun chemin local ne
    sort). Retourne le résumé pour le manifeste; `dest` n'est créé que s'il y a
    au moins un modèle."""
    rows = copy.execute("SELECT trial_id, artifact_path FROM trial WHERE artifact_path IS NOT NULL").fetchall()
    index: dict[str, str] = {}
    missing: list[str] = []
    zf: zipfile.ZipFile | None = None
    try:
        for trial_id, art in rows:
            found = _resolve_model(art, roots)
            if found is None:
                missing.append(_anonymise(art))
                continue
            if zf is None:
                zf = zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED)
            arc = f"models/{trial_id}/{found.name}"
            zf.write(found, arc)
            meta = found.with_name(found.stem + "_meta.json")
            if meta.exists():
                zf.write(meta, f"models/{trial_id}/{meta.name}")
            index[str(trial_id)] = arc
            copy.execute("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", (arc, trial_id))
        if zf is not None:
            zf.writestr("index.json", json.dumps(index, indent=1))
    finally:
        if zf is not None:
            zf.close()
    copy.commit()
    return {"included": len(index), "missing": missing}


def _build_store_bundle(store_root: str, dest: Path) -> dict:
    """Zippe les parquet du magasin et un `_index.json` aux chemins relatifs
    (le vrai contient des chemins absolus propres à chaque PC)."""
    root = Path(store_root)
    parquets = sorted(root.glob("snapshot=*/*.parquet")) if root.is_dir() else []
    if not parquets:
        return {"files": 0}
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
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in parquets:
            zf.write(p, f"{p.parent.name}/{p.name}")
        zf.writestr("_index.json", json.dumps(index, indent=1))
        series = root / "_series_observations.json"
        if series.exists():
            zf.write(series, "_series_observations.json")
    return {"files": len(parquets)}


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
    return added


# --------------------------------------------------------------------------
# Destinations
# --------------------------------------------------------------------------

class FolderTransport:
    """Un dossier (Google Drive synchronisé, disque réseau, clé USB...)."""

    def __init__(self, folder: str):
        self.folder = Path(folder)

    def upload(self, files: dict[str, Path]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        # Le manifeste en dernier : un lecteur ne voit jamais un manifeste qui
        # annonce des fichiers pas encore copiés.
        for name in sorted(files, key=lambda n: n == MANIFEST):
            tmp = self.folder / (name + ".part")
            shutil.copyfile(files[name], tmp)
            os.replace(tmp, self.folder / name)

    def download(self, workdir: Path) -> dict[str, Path]:
        if not (self.folder / MANIFEST).exists():
            raise SyncError(f"Aucun partage trouvé dans {self.folder} ({MANIFEST} absent).")
        out = {}
        for name in (MANIFEST, *_ASSETS):
            src = self.folder / name
            if src.exists():
                shutil.copyfile(src, workdir / name)
                out[name] = workdir / name
        return out


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
    return os.environ.get("PATRICK_STORE_ROOT") or os.path.expanduser("~/.patrick/store")


def _default_models_roots() -> list[str]:
    home = os.path.expanduser("~/.patrick")
    return [os.getcwd(), home, os.path.join(home, "runs")]


def push(dest: str, *, db_path: str | None = None, store_root: str | None = None,
         models_roots: list[str] | None = None, include_personal: bool = False,
         repo: str | None = None) -> dict:
    """Publie un état assaini vers `dest` (`"github"` ou un dossier). Retourne le manifeste."""
    transport = resolve_transport(dest, repo)
    if include_personal and not isinstance(transport, FolderTransport):
        raise SyncError("--include-personal (données perso) n'est autorisé que vers un dossier privé, "
                        "jamais vers GitHub.")
    src = db_path or trackdb.default_db_path()
    if not os.path.exists(src):
        raise SyncError(f"Base introuvable : {src}")

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        work = tmp / "work.db"
        source = sqlite3.connect(src)
        copy = sqlite3.connect(work)
        try:
            source.execute("PRAGMA query_only = ON")
            source.backup(copy)
        finally:
            source.close()
        try:
            models_info = _build_models_bundle(
                copy, models_roots if models_roots is not None else _default_models_roots(), tmp / MODELS_ASSET)
            _neutralise_runtime_state(copy)
            excluded: list[str] = []
            if not include_personal:
                excluded = personal_tables(copy)
                for table in excluded:
                    copy.execute(f'DELETE FROM "{table}"')
                if copy.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
                    copy.executemany("DELETE FROM sqlite_sequence WHERE name = ?", [(t,) for t in excluded])
                copy.commit()
                needle = Path.home().name
                leaks = _username_leaks(copy, needle) if len(needle) >= 4 else {}
                if leaks:
                    raise SyncError("La base contient le nom d'utilisateur du PC (" + ", ".join(
                        f"{k}: {v} ligne(s)" for k, v in leaks.items()) + ") : publication refusée.")
            version = copy.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            runs = copy.execute("SELECT COUNT(*) FROM run").fetchone()[0]
            copy.execute("PRAGMA journal_mode = DELETE")
            copy.execute("VACUUM")
        finally:
            copy.close()

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
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema_version": version,
            "runs": runs,
            "personal_included": include_personal,
            "excluded_tables": excluded,
            "models": models_info,
            "store": store_info,
            "files": {name: {"sha256": _sha256(p), "size": p.stat().st_size} for name, p in files.items()},
        }
        manifest_path = tmp / MANIFEST
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        files[MANIFEST] = manifest_path
        transport.upload(files)
    return manifest


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
    if MANIFEST not in files or DB_ASSET not in files:
        raise SyncError("Partage incomplet : manifest ou base manquants.")
    manifest = json.loads(files[MANIFEST].read_text(encoding="utf-8"))
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
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        files, manifest = _download_verified(transport, tmp)

        new_db = tmp / "incoming.db"
        _gunzip_file(files[DB_ASSET], new_db)
        result = _restore_db(new_db, db_path, force=force, backup_dir=backup_dir)
        result["models"] = (_restore_models(files[MODELS_ASSET], models_dir or os.path.expanduser("~/.patrick/models"),
                                            db_path) if MODELS_ASSET in files else 0)
        result["store_files"] = (_restore_store(files[STORE_ASSET], store_root or _default_store_root())
                                 if STORE_ASSET in files else 0)
        result["created_at"] = manifest["created_at"]
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
    data = {**load_state(), **fields, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
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
    return {"sha": manifest["files"][DB_ASSET]["sha256"], "created_at": manifest["created_at"],
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


def merge(source: str, *, db_path: str | None = None, store_root: str | None = None,
          models_dir: str | None = None, backup_dir: str | None = None, dry_run_to: str | None = None,
          adopt_personal: bool = False, repo: str | None = None) -> dict:
    """Importe dans la base locale la recherche du partage `source` (union, voir `sync_merge`).

    Le travail se fait sur une COPIE de la base locale, vérifiée avant de la substituer à l'original
    (qui est sauvegardé d'abord) : un échec ne touche pas la base locale. Le serveur PATRICK doit être
    fermé pour la substitution (Windows). `dry_run_to` : écrit le résultat dans ce fichier et s'arrête
    (la base locale, le magasin et les modèles ne sont pas touchés). `adopt_personal` : remplace aussi le
    patrimoine et les fonds locaux par ceux du partage, s'il en contient (PC qui n'est pas la référence)."""
    transport = resolve_transport(source, repo)
    db_path = db_path or trackdb.default_db_path()
    if dry_run_to is None and _db_in_use(db_path):
        raise SyncError("PATRICK est ouvert (la base est utilisée) : ferme-le, puis relance la synchronisation.")
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        files, manifest = _download_verified(transport, tmp)
        incoming = tmp / "incoming.db"
        _gunzip_file(files[DB_ASSET], incoming)
        trackdb.connect(str(incoming)).close()               # migre le partage jusqu'à la version du code

        work = Path(dry_run_to) if dry_run_to else Path(db_path + ".merging")
        work.parent.mkdir(parents=True, exist_ok=True)
        work.unlink(missing_ok=True)
        if os.path.exists(db_path):
            source_conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
            target_conn = sqlite3.connect(work)
            try:
                source_conn.backup(target_conn)               # copie cohérente même si la base est ouverte
            finally:
                source_conn.close()
                target_conn.close()
        trackdb.connect(str(work)).close()                    # crée/migre la copie de travail
        try:
            runs_before = _count_runs(str(work))
            report = sync_merge.merge_databases(str(work), str(incoming), fast=True)
            personal = (sync_merge.adopt_personal_tables(str(work), str(incoming))
                        if adopt_personal and manifest.get("personal_included") else {})
            models = (_restore_models_merged(files[MODELS_ASSET], models_dir or os.path.expanduser("~/.patrick/models"),
                                             str(work), report["trial_offset"], set(report["new_trial_ids"]))
                      if MODELS_ASSET in files and dry_run_to is None else 0)
            check = _quick_check(str(work))
            if check != "ok":
                raise SyncError(f"Base fusionnée invalide (quick_check : {check}) : base locale inchangée.")
            result = {"runs_before": runs_before, "runs_after": _count_runs(str(work)),
                      "new_runs": report["new_runs"], "local_only_runs": report["local_only_runs"],
                      "models": models, "store_files": 0, "backup": None, "created_at": manifest["created_at"],
                      "remote_sha": manifest["files"][DB_ASSET]["sha256"], "added": report["added"],
                      "personal": personal}
            if dry_run_to is not None:
                return result
            if os.path.exists(db_path):
                result["backup"] = str(backup_mod.backup_database(db_path, backup_dir, pages=-1, sleep_s=0.0))
            for suffix in ("-wal", "-shm"):
                try:
                    os.remove(db_path + suffix)
                except FileNotFoundError:
                    pass
            try:
                os.replace(work, db_path)
            except PermissionError as exc:
                raise SyncError("PATRICK est ouvert (la base est utilisée) : ferme-le, puis relance la "
                                "synchronisation.") from exc
        except BaseException:
            Path(work).unlink(missing_ok=True)               # copie de travail abîmée ou refusée : on la jette
            raise
        if STORE_ASSET in files:
            result["store_files"] = _restore_store(files[STORE_ASSET], store_root or _default_store_root())
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
    return {"folder": folder, "remote": stamp, "last_exchange": state.get("at"), "wealth_reference": reference,
            "local_runs": _count_runs(db_path) if exists else 0,
            "need_pull": need_pull, "local_changed": local_changed,
            "need_push": exists and (stamp is None or local_changed or need_pull)}


def auto(folder: str, *, only: str | None = None, wealth_reference: bool | None = None, db_path: str | None = None,
         store_root: str | None = None, models_dir: str | None = None, models_roots: list[str] | None = None,
         backup_dir: str | None = None) -> dict:
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
            else:
                manifest = push(folder, db_path=db_path, store_root=store_root, models_roots=models_roots,
                                include_personal=reference)
                save_state(remote_sha=manifest["files"][DB_ASSET]["sha256"], local_fp=fp)
                out["actions"].append(f"publication : {manifest['runs']} run(s), "
                                      f"{manifest['models']['included']} modèle(s)"
                                      + (", patrimoine inclus" if reference else ""))
    return out


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
    log = os.path.normpath(os.path.expanduser("~/.patrick/logs/sync.log"))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    command = f'"{pythonw if pythonw.exists() else exe}" -m patrick.cli sync auto --only push --log-file "{log}"'
    proc = subprocess.run(["schtasks", "/Create", "/TN", SYNC_TASK, "/TR", command, "/SC", "MINUTE",
                           "/MO", str(minutes), "/F"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SyncError(f"schtasks : {(proc.stderr or proc.stdout).strip()}")
    return command
