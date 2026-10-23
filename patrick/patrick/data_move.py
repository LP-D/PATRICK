"""`patrick data` : état, création et déplacement de la racine de données (spec 2026-10-21-donnees-sur-disque-d-design.md, §6).

La racine de données (`paths.data_root()`) porte `store`, `models`, `feature_cache`, `cache`, `backups`, `archive` et
`reports` ; la base active et les journaux restent dans le dossier maison. Ce module ne fait que lire l'état et déplacer :
tout emplacement se résout par `patrick.paths`.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths, settings, sync
from patrick.desktop import prefs, runtime

COMPONENTS = ("store", "models", "feature_cache", "cache", "backups", "archive", "reports")
JOURNAL_NAME = "data_move_journal.json"           # anciennes valeurs de ce que `switch` réécrit (dans le dossier maison)
STATE_NAME = "data_move_state.json"               # avancement de la copie (dans le dossier maison)
README_NAME = "README.txt"
README_TEXT = ("Données de PATRICK de ce PC. Ne pas partager ni déplacer à la main : voir `patrick data status`.\n")

_COMPONENT_DIRS = {"store": paths.store_dir, "models": paths.models_dir, "feature_cache": paths.feature_cache_dir,
                   "cache": paths.cache_dir, "backups": paths.backups_dir, "archive": paths.archive_dir,
                   "reports": paths.reports_dir}


class MoveError(RuntimeError):
    """Opération refusée ou impossible, expliquée à l'utilisateur."""


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def component_path(name: str) -> Path:
    """Dossier actuel d'un composant ; si le disque de données manque, le dossier attendu (qui n'existe pas)."""
    try:
        return _COMPONENT_DIRS[name]()
    except paths.DataRootUnavailable:
        return paths.configured_data_root() / name


def _unresolved_artifacts(db_path: str) -> int:
    """`trial.artifact_path` absolus qui ne mènent à aucun fichier (les chemins relatifs dépendent du dossier de travail du worker)."""
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute("SELECT artifact_path FROM trial WHERE artifact_path IS NOT NULL AND artifact_path <> ''")
            return sum(1 for (p,) in rows if os.path.isabs(p) and not os.path.exists(p))
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _unresolved_store_entries(store: Path) -> int:
    """Snapshots de `_index.json` dont le fichier parquet est introuvable."""
    index = _read_json(store / "_index.json") or {}
    return sum(1 for value in index.values() for entry in (value or {}).get("snapshots", [])
               if not os.path.exists(entry.get("path", "")))


def status() -> dict:
    """Où sont les données de ce PC, combien de place il reste, et ce qui ne se résout plus (lecture seule)."""
    configured = paths.configured_data_root()
    available = paths.data_root_missing() is None
    home = paths.home_dir()
    volumes = [{"path": str(home), "free_gb": round(sync._free_bytes(home) / 1e9, 1)}]
    if configured is not None and available:
        volumes.append({"path": str(configured), "free_gb": round(sync._free_bytes(configured) / 1e9, 1)})
    components = [{"name": name, "path": str(component_path(name)), "exists": component_path(name).is_dir()}
                  for name in COMPONENTS]
    store = component_path("store")
    overrides = {var: os.environ[var] for var in (paths.ENV_DATA_ROOT, "PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT",
                                                  "PATRICK_FEATURE_CACHE_ROOT") if os.environ.get(var)}
    return {"data_root": str(configured) if configured is not None else None, "home": str(home), "db": paths.db_path(),
            "env_overrides": overrides,
            "available": available, "volumes": volumes, "components": components,
            "unresolved": {"artifact_paths": _unresolved_artifacts(paths.db_path()),
                           "store_index": _unresolved_store_entries(store)},
            "progress": _read_json(home / STATE_NAME)}


def init_root(folder: str) -> Path:
    """Crée la racine de données, ses sept sous-dossiers et un `README.txt`. Le dossier parent doit exister (un lecteur
    absent ne se crée pas). N'écrit pas le réglage : c'est `move` qui le fait."""
    root = Path(folder)
    if not root.is_absolute():
        raise MoveError(f"Indique un chemin complet (par exemple D:\\PATRICK DATA), pas « {folder} ».")
    if not root.parent.is_dir():
        raise MoveError(f"Le dossier {root.parent} n'existe pas : le disque est-il branché ? Rien n'a été créé.")
    root.mkdir(exist_ok=True)
    for name in COMPONENTS:
        (root / name).mkdir(exist_ok=True)
    readme = root / README_NAME
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# Phase 1 : préconditions et copie
# --------------------------------------------------------------------------

_HASHED = ("store", "models")                     # petits (4,8 et 0,4 Go) : vérifiés par somme sha256
_SAME_MTIME_NS = 2_000_000_000                    # deux dates à moins de 2 s : même fichier (précision des systèmes de fichiers)
_TICK_FILES, _TICK_SECONDS = 200, 2.0             # fréquence d'écriture de l'avancement
# Ce que l'application réécrit légitimement sur la NOUVELLE racine après la bascule (rafraîchissement du cache, séries observées,
# nouveaux snapshots dans l'index) : une différence n'y est pas une corruption. Tout le reste est immuable (parquet adressés par
# leur contenu, modèles, sauvegardes horodatées, caches de variables adressés par clé, archives).
_MUTABLE_COMPONENTS = ("cache", "reports")
_MUTABLE_FILES = ("store/_index.json", "store/_series_observations.json")
_INDEX_REL = "store/_index.json"
_PENDING = ("switching", "switched", "finalizing")   # états du journal d'un déplacement qui n'est pas terminé ni annulé


def _is_mutable(rel: str) -> bool:
    return rel in _MUTABLE_FILES or rel.split("/", 1)[0] in _MUTABLE_COMPONENTS


def _index_pairs(index: dict | None) -> set[tuple[str, str]]:
    return {(key, str(entry.get("snapshot_id", ""))) for key, value in (index or {}).items()
            for entry in (value or {}).get("snapshots", [])}


def _merge_index(src_index: Path, dst_index: Path) -> bool:
    """Ajoute à l'index de la copie les snapshots que la source connaît et que la copie ignore (jamais l'inverse : ceux que
    l'application a créés sur la cible survivent à une nouvelle copie). Renvoie True si l'index de la copie a changé."""
    src, dst = _read_json(src_index) or {}, _read_json(dst_index) or {}
    changed = False
    for key, value in src.items():
        value = value or {}
        if key not in dst:
            dst[key], changed = value, True
            continue
        known = {str(e.get("snapshot_id", "")) for e in dst[key].get("snapshots", [])}
        for entry in value.get("snapshots", []):
            if str(entry.get("snapshot_id", "")) not in known:
                dst[key].setdefault("snapshots", []).append(entry)
                changed = True
    if changed:
        _write_json(dst_index, dst)
    return changed


def _pending_journal(other_than: str | None = None) -> dict | None:
    """Journal d'un déplacement ni terminé ni annulé (vers une autre cible que `other_than`, si donnée)."""
    journal = _read_json(paths.home_dir() / JOURNAL_NAME)
    if journal and journal.get("status") in _PENDING and (other_than is None or _norm(journal.get("target", "")) != _norm(other_than)):
        return journal
    return None


def _pending_message(journal: dict) -> str:
    return (f"Un déplacement vers {journal['target']} est en attente (état « {journal['status']} ») : finalise-le "
            "(`patrick data move --finalize`) ou annule-le (`patrick data rollback`) d'abord.")


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(child, parent) -> bool:
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _tree(root: Path):
    """Chaque fichier sous `root` (sans suivre les liens)."""
    stack = [root]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)


def _tree_bytes(root: Path) -> int:
    total = 0
    for file in _tree(root):
        try:
            total += file.stat().st_size
        except OSError:
            continue
    return total


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_preconditions(target: str, *, db_path: str | None = None, port: int | None = None) -> list[str]:
    """Raisons (en français) pour lesquelles `target` ne peut pas devenir la racine de données maintenant ; vide si tout va."""
    db_path = db_path or paths.db_path()
    root, home = Path(target), paths.home_dir()
    if not root.is_absolute():
        return [f"Indique un chemin complet (par exemple D:\\PATRICK DATA), pas « {target} »."]
    if (problem := paths.data_root_problem()):
        return [problem]
    source = paths.data_root()
    problems: list[str] = []
    if (pending := _pending_journal(other_than=target)):
        problems.append(_pending_message(pending))
    configured = paths.configured_data_root()
    if configured is not None and _norm(configured) == _norm(root):
        problems.append(f"{target} est déjà la racine de données de ce PC.")
    if _inside(root, home):
        problems.append(f"{target} est dans le dossier maison de PATRICK ({home}), qui garde la base : choisis un autre dossier.")
    elif _inside(root, source):
        problems.append(f"{target} est dans la source de la copie ({source}) : choisis un autre dossier.")
    if _inside(home, root):
        problems.append(f"{target} contient le dossier maison de PATRICK ({home}) : choisis un dossier plus précis.")
    if _inside(source, root) and _norm(source) != _norm(home):
        problems.append(f"{target} contient la source de la copie ({source}) : choisis un dossier plus précis.")
    share = sync.configured_folder()
    if share and (_inside(root, share) or _inside(share, root)):
        problems.append(f"{target} chevauche le dossier de partage ({share}) : choisis un autre dossier.")
    if not root.parent.is_dir():
        problems.append(f"Le dossier {root.parent} n'existe pas : le disque est-il branché ?")
    if runtime.port_open(port or prefs.get_port()):
        problems.append("PATRICK est ouvert (le serveur écoute) : ferme-le d'abord.")
    try:
        if sync._job_running(db_path):
            problems.append("Un entraînement est en cours ou un worker est vivant : attends sa fin.")
    except sqlite3.Error as exc:
        problems.append(f"La base {db_path} est illisible ({exc}) : impossible de vérifier qu'aucun entraînement ne tourne.")
    needed = sum(_tree_bytes(source / name) for name in COMPONENTS if (source / name).is_dir())
    free = sync._free_bytes(root)
    if free < needed + sync.MIN_FREE_BYTES:
        problems.append(f"Pas assez d'espace libre sur le disque cible : il faut environ {sync._gb(needed + sync.MIN_FREE_BYTES)} Go, "
                        f"il en reste {sync._gb(free)}.")
    return problems


def _copy_file(src: Path, dst: Path) -> None:
    """Copie via un fichier `.part` puis renommage : une copie interrompue ne laisse jamais un fichier tronqué sous son vrai nom."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    shutil.copy2(src, part)
    os.replace(part, dst)


def _same_file(src: Path, dst: Path) -> bool:
    try:
        a, b = src.stat(), dst.stat()
    except OSError:
        return False
    return a.st_size == b.st_size and abs(a.st_mtime_ns - b.st_mtime_ns) < _SAME_MTIME_NS


def _drop_orphan_parts(src_dir: Path, dst_dir: Path) -> None:
    """Supprime les `.part` laissés par une copie interrompue (seulement ceux dont le fichier existe à la source)."""
    for part in dst_dir.rglob("*.part"):
        if (src_dir / part.with_name(part.name[: -len(".part")]).relative_to(dst_dir)).is_file():
            part.unlink(missing_ok=True)


def _verify_copy(src_root: Path, dst_root: Path, names: list[str]) -> None:
    """Chaque fichier de la source existe dans la copie. Les fichiers immuables y sont identiques (taille ; sha256 pour `store`
    et `models`). Les fichiers que l'application réécrit (`_MUTABLE_*`) peuvent différer, mais la copie ne doit pas être plus
    ancienne que la source ; pour l'index du magasin, chaque snapshot de la source doit figurer dans celui de la copie."""
    for name in names:
        for file in _tree(src_root / name):
            rel = file.relative_to(src_root).as_posix()
            copy = dst_root / rel
            if not copy.is_file():
                raise MoveError(f"Copie incomplète : {rel} est absent de {dst_root}.")
            if rel == _INDEX_REL:
                missing = _index_pairs(_read_json(file)) - _index_pairs(_read_json(copy))
                if missing:
                    raise MoveError(f"Copie incomplète : l'index du magasin de la cible ignore {len(missing)} snapshot(s) de la source "
                                    f"(par exemple {min(missing)}).")
                continue
            if _is_mutable(rel):
                if copy.stat().st_mtime_ns + _SAME_MTIME_NS < file.stat().st_mtime_ns:
                    raise MoveError(f"{rel} est plus récente à la source que dans la copie : relance `patrick data move` pour la "
                                    "recopier. Rien n'est supprimé.")
                continue
            if copy.stat().st_size != file.stat().st_size:
                raise MoveError(f"Copie incomplète : {rel} est de taille différente dans {dst_root}.")
            if name in _HASHED and sync._sha256(file) != sync._sha256(copy):
                raise MoveError(f"Copie corrompue (sha256 différent) : {rel}.")


def copy_components(target: str, *, source_root: Path | None = None, progress=None) -> dict:
    """Phase 1 : copie les sept composants de la source vers `target`, sans rien modifier à la source. Reprenable : un fichier
    déjà là, de même taille et de même date, est sauté ; un fichier tronqué est recopié. Renvoie `{"files", "bytes", "skipped"}`
    (fichiers copiés, octets copiés, fichiers sautés). `progress(component, files_done, bytes_done, total_bytes)` est appelé
    régulièrement ; l'avancement est aussi écrit dans `STATE_NAME` (dossier maison)."""
    src_root = Path(source_root) if source_root is not None else paths.data_root()
    dst_root = init_root(target)
    names = [name for name in COMPONENTS if (src_root / name).is_dir()]
    total = sum(_tree_bytes(src_root / name) for name in names)
    state_path = paths.home_dir() / STATE_NAME
    done = {"files": 0, "bytes": 0, "skipped": 0}
    last = [time.monotonic()]

    def record(phase: str, component: str, *, force: bool = False) -> None:
        count = done["files"] + done["skipped"]
        if not force and time.monotonic() - last[0] < _TICK_SECONDS and count % _TICK_FILES:
            return
        last[0] = time.monotonic()
        _write_json(state_path, {"phase": phase, "component": component, "files_done": count, "bytes_done": done["bytes"],
                                 "total_bytes": total, "target": str(dst_root),
                                 "updated_at": datetime.now(UTC).isoformat(timespec="seconds")})
        if progress:
            progress(component, count, done["bytes"], total)

    record("copy", "", force=True)
    for name in names:
        src_dir, dst_dir = src_root / name, dst_root / name
        _drop_orphan_parts(src_dir, dst_dir)
        for file in _tree(src_dir):
            copy = dst_dir / file.relative_to(src_dir)
            rel = file.relative_to(src_root).as_posix()
            if rel == _INDEX_REL and copy.exists():
                done["files" if _merge_index(file, copy) else "skipped"] += 1        # fusion : jamais d'écrasement
            elif _is_mutable(rel) and copy.exists() and copy.stat().st_mtime_ns > file.stat().st_mtime_ns + _SAME_MTIME_NS:
                done["skipped"] += 1                  # l'application l'a réécrit sur la cible depuis : on garde le plus récent
            elif _same_file(file, copy):
                done["skipped"] += 1
            else:
                _copy_file(file, copy)
                done["files"] += 1
                done["bytes"] += file.stat().st_size
            record("copy", name)
    _verify_copy(src_root, dst_root, names)
    record("copied", "", force=True)
    return dict(done)


# --------------------------------------------------------------------------
# Phase 2 : bascule (réécriture des chemins absolus, réglage) avec journal
# --------------------------------------------------------------------------

def rebase_path(value: str, old_root: str, new_root: str) -> str | None:
    """`value` déplacé de `old_root` vers `new_root`, ou None s'il n'est pas sous `old_root`. Séparateurs mixtes
    (`C:\\Users\\x/.patrick/store\\snapshot=…`) et casse Windows tolérés."""
    v, old, new = os.path.normpath(value), os.path.normpath(old_root), os.path.normpath(new_root)
    if os.path.normcase(v) == os.path.normcase(old):
        return new
    prefix = os.path.normcase(old).rstrip("\\/") + os.sep
    if os.path.normcase(v).startswith(prefix):
        return os.path.join(new, v[len(prefix):])
    return None


def _rebased_index(index: dict, old_store: Path, new_store: Path) -> tuple[dict, dict]:
    """`_index.json` réécrit vers `new_store`, et les anciennes valeurs `{"<clé>|<snapshot_id>": chemin}`."""
    rewritten: dict = {}
    old_values: dict = {}
    for key, value in index.items():
        snapshots = []
        for entry in (value or {}).get("snapshots", []):
            current = entry.get("path", "")
            rebased = rebase_path(current, str(old_store), str(new_store))
            if rebased is None and (m := sync._SNAPSHOT_REL_RE.search(current)) and (new_store / m[1] / m[2]).is_file():
                rebased = str(new_store / m[1] / m[2])
            if rebased and rebased != current:
                old_values[f"{key}|{entry.get('snapshot_id', '')}"] = current
                entry = {**entry, "path": rebased}
            snapshots.append(entry)
        rewritten[key] = {**(value or {}), "snapshots": snapshots}
    return rewritten, old_values


def switch(target: str, *, db_path: str | None = None, source_root: Path | None = None) -> dict:
    """Phase 2 : fait de `target` (déjà copié) la racine de données. Dans l'ordre : le journal des anciennes valeurs, les
    `trial.artifact_path` absolus de l'ancien dossier `models` (UNE transaction), l'`_index.json` de la COPIE (celui de la
    source ne bouge pas), puis le réglage `data_root`. Le journal passe par « switching » (écrit AVANT toute modification) puis
    « switched » : un arrêt brutal entre les deux se reprend en relançant `switch`, qui garde les anciennes valeurs d'origine.
    Sans effet si `target` est déjà la racine. Refusé si un déplacement vers une autre cible est en attente. Renvoie le journal."""
    dst_root = Path(target)
    journal_path = paths.home_dir() / JOURNAL_NAME
    if (other := _pending_journal(other_than=target)):
        raise MoveError(_pending_message(other))
    existing = _read_json(journal_path)
    configured = paths.configured_data_root()
    if configured is not None and _norm(configured) == _norm(dst_root) and not (existing and existing.get("status") == "switching"):
        return existing or {}
    resuming = existing if existing and existing.get("status") == "switching" and _norm(existing["target"]) == _norm(dst_root) else None
    src_root = Path(resuming["source_root"]) if resuming else (Path(source_root) if source_root is not None else paths.data_root())
    db_path = db_path or paths.db_path()
    if not (dst_root / "models").is_dir():
        raise MoveError(f"La copie est absente de {dst_root} : lance d'abord `patrick data move`.")
    old_models, new_models = str(src_root / "models"), str(dst_root / "models")
    index_path = dst_root / "store" / "_index.json"
    index = _read_json(index_path)
    new_index, fresh_old_index = _rebased_index(index or {}, src_root / "store", dst_root / "store")

    conn = sqlite3.connect(db_path, timeout=60, isolation_level=None) if os.path.exists(db_path) else None
    try:
        rows = conn.execute("SELECT trial_id, artifact_path FROM trial "
                            "WHERE artifact_path IS NOT NULL AND artifact_path <> ''").fetchall() if conn else []
        changes = [[tid, old, new] for tid, old in rows if (new := rebase_path(old, old_models, new_models)) and new != old]
        originals = {tid: [tid, old, new] for tid, old, new in (resuming or {}).get("artifact_paths", [])}
        for tid, old, new in changes:
            originals.setdefault(tid, [tid, old, new])          # à la reprise, les valeurs d'origine l'emportent
        journal = {"status": "switching", "source_root": str(src_root), "target": str(dst_root),
                   "artifact_paths": [originals[tid] for tid in sorted(originals)],
                   "store_index_old": {**fresh_old_index, **(resuming or {}).get("store_index_old", {})},
                   "previous_data_root": resuming["previous_data_root"] if resuming else (str(configured) if configured is not None else None),
                   "created_at": resuming["created_at"] if resuming else datetime.now(UTC).isoformat(timespec="seconds")}
        _write_json(journal_path, journal)
        if changes:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.executemany("UPDATE trial SET artifact_path = ? WHERE trial_id = ?", [(new, tid) for tid, _old, new in changes])
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                if resuming:
                    _write_json(journal_path, resuming)
                else:
                    journal_path.unlink(missing_ok=True)
                raise MoveError(f"Bascule interrompue, aucune modification faite ({exc}).") from exc
    finally:
        if conn:
            conn.close()
    if index is not None and journal["store_index_old"]:
        _write_json(index_path, new_index)
    settings.save({paths.KEY_DATA_ROOT: str(dst_root)})
    journal = {**journal, "status": "switched"}
    _write_json(journal_path, journal)
    return journal


# --------------------------------------------------------------------------
# Phase 3 : contrôle, retour arrière, finalisation
# --------------------------------------------------------------------------

def _journal() -> dict:
    journal = _read_json(paths.home_dir() / JOURNAL_NAME)
    if not journal:
        raise MoveError("Aucun déplacement en cours : le journal de déplacement est absent.")
    return journal


def verify(db_path: str | None = None) -> dict:
    """Contrôle ce que `switch` a déplacé : chaque modèle qui existait à la source existe à sa nouvelle place, chaque snapshot
    réécrit dans l'index existe. Les chemins déjà introuvables avant le déplacement (modèle élagué) ne comptent pas.
    Renvoie `{"artifact_unresolved", "store_unresolved", "ok"}`."""
    journal = _journal()
    artifacts = sum(1 for _tid, old, new in journal["artifact_paths"] if os.path.exists(old) and not os.path.exists(new))
    index = _read_json(Path(journal["target"]) / "store" / "_index.json") or {}
    moved = journal["store_index_old"]
    store = sum(1 for key, value in index.items() for entry in (value or {}).get("snapshots", [])
                if f"{key}|{entry.get('snapshot_id', '')}" in moved and not os.path.exists(entry.get("path", "")))
    return {"artifact_unresolved": artifacts, "store_unresolved": store, "ok": artifacts == 0 and store == 0}


def _created_since(src_root: Path, dst_root: Path) -> list[str]:
    """Fichiers immuables de `store` et `models` qui existent sur la cible et pas à la source : créés par l'application depuis la
    bascule (un retour arrière les laisserait de côté, sans entrée dans l'index de la source)."""
    extras = []
    for name in _HASHED:
        if (dst_root / name).is_dir():
            for file in _tree(dst_root / name):
                rel = file.relative_to(dst_root).as_posix()
                if not _is_mutable(rel) and not (src_root / rel).exists():
                    extras.append(rel)
    return sorted(extras)


def rollback(db_path: str | None = None, *, force: bool = False) -> dict:
    """Défait `switch` depuis le journal : remet les anciens `artifact_path` (ceux qui n'ont pas changé depuis), retire ou
    rétablit le réglage `data_root`. La source n'a jamais été touchée. Refusé après `finalize` (la source n'existe plus) ou
    pendant une finalisation commencée ; refusé aussi si l'application a créé des fichiers sur la nouvelle racine depuis la
    bascule, sauf `force`."""
    journal = _journal()
    if journal["status"] == "finalized":
        raise MoveError("Retour arrière impossible : la source a été supprimée par `finalize`.")
    if journal["status"] == "finalizing":
        raise MoveError("Retour arrière impossible : la finalisation a commencé et la source est en partie supprimée. "
                        "Relance `patrick data move --finalize` pour la terminer.")
    if journal["status"] == "rolled_back":
        return journal
    extras = [] if force else _created_since(Path(journal["source_root"]), Path(journal["target"]))
    if extras:
        raise MoveError(f"{len(extras)} fichier(s) ont été créés dans la nouvelle racine depuis la bascule (par exemple {extras[0]}) : "
                        "un retour arrière les laisserait de côté. Garde la nouvelle racine, ou force avec `--force` si tu sais ce que tu fais.")
    db_path = db_path or paths.db_path()
    if journal["artifact_paths"] and os.path.exists(db_path):
        conn = sqlite3.connect(db_path, timeout=60, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("UPDATE trial SET artifact_path = ? WHERE trial_id = ? AND artifact_path = ?",
                             [(old, tid, new) for tid, old, new in journal["artifact_paths"]])
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise MoveError(f"Retour arrière interrompu, aucune modification faite ({exc}).") from exc
        finally:
            conn.close()
    settings.save({paths.KEY_DATA_ROOT: journal["previous_data_root"]})
    journal = {**journal, "status": "rolled_back"}
    _write_json(paths.home_dir() / JOURNAL_NAME, journal)
    return journal


def _clear_read_only(func, path, _error) -> None:
    os.chmod(path, stat.S_IWRITE)                     # un fichier en lecture seule bloque la suppression sous Windows
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_read_only)
    else:
        shutil.rmtree(path, onerror=_clear_read_only)


def finalize(*, source_root: Path | None = None) -> dict:
    """Supprime de la source les sept composants déplacés, après un contrôle complet : la racine ACTIVE doit être la cible, `verify`,
    puis chaque fichier de la source revérifié dans la copie (`_verify_copy` : identique pour les fichiers immuables, présent et
    pas plus ancien pour ceux que l'application réécrit, index complet). Un composant dont l'emplacement actif est encore dans la
    source (variable `PATRICK_*_ROOT`) est conservé. Ne touche jamais la base, les réglages, les journaux ni le profil du
    navigateur. Le journal passe par « finalizing » AVANT la première suppression : une suppression interrompue se reprend en
    relançant `finalize` et ne se défait plus. Renvoie `{"removed": [...], "kept": [...]}`."""
    journal = _read_json(paths.home_dir() / JOURNAL_NAME)
    if not journal or journal.get("status") not in ("switched", "finalizing"):
        raise MoveError("Rien à finaliser : aucun déplacement basculé n'est en attente.")
    src_root = Path(source_root) if source_root is not None else Path(journal["source_root"])
    dst_root = Path(journal["target"])
    if _inside(dst_root, src_root) or _inside(src_root, dst_root):
        raise MoveError(f"La source ({src_root}) et la cible ({dst_root}) se chevauchent : rien n'est supprimé.")
    active = paths.configured_data_root()
    if active is None or _norm(active) != _norm(dst_root):
        raise MoveError(f"La racine de données active n'est pas {dst_root} (variable PATRICK_DATA_ROOT ou réglage `data_root`) : "
                        "rien n'est supprimé.")
    check = verify()
    if not check["ok"]:
        raise MoveError(f"Contrôle en échec ({check}) : rien n'est supprimé.")
    names = [name for name in COMPONENTS if (src_root / name).is_dir()]
    _verify_copy(src_root, dst_root, names)
    kept = [name for name in names if _inside(component_path(name), src_root / name)]
    doomed = [name for name in names if name not in kept]
    journal_path = paths.home_dir() / JOURNAL_NAME
    _write_json(journal_path, {**journal, "status": "finalizing", "doomed": doomed, "kept": kept})
    try:
        for name in doomed:
            _rmtree(src_root / name)
    except OSError as exc:
        raise MoveError(f"Suppression interrompue ({exc}) : ferme ce qui utilise ces fichiers, puis relance "
                        "`patrick data move --finalize` pour la terminer.") from exc
    _write_json(journal_path, {**journal, "status": "finalized", "removed": doomed, "kept": kept})
    return {"removed": doomed, "kept": kept}


def use_root(folder: str | None) -> dict:
    """Change ou retire le réglage `data_root` sans rien déplacer (disque mort, dossier déplacé à la main). `None` le retire :
    tout revient dans le dossier maison. Refusé tant qu'un déplacement est en attente. Renvoie `{"data_root", "env_override"}`
    (`env_override` : la variable `PATRICK_DATA_ROOT` est posée et prime sur le réglage)."""
    if (pending := _pending_journal()):
        raise MoveError(_pending_message(pending))
    if folder is not None:
        root = Path(folder)
        if not root.is_absolute():
            raise MoveError(f"Indique un chemin complet (par exemple D:\\PATRICK DATA), pas « {folder} ».")
        if not root.is_dir():
            raise MoveError(f"Le dossier {root} n'existe pas : le disque est-il branché ? Rien n'a été changé.")
        settings.save({paths.KEY_DATA_ROOT: str(root)})
    else:
        settings.save({paths.KEY_DATA_ROOT: None})
    return {"data_root": str(Path(folder)) if folder is not None else None, "env_override": bool(os.environ.get(paths.ENV_DATA_ROOT))}
