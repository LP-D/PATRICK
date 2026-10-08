"""Dossier partagé entre PC (OneDrive, disque réseau…) : détection, contrôle, enregistrement.

Tout ce que fait l'assistant de premier démarrage et la page Réglages passe par ici : une seule règle de
validation, un seul endroit qui écrit les réglages de synchronisation.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from patrick import settings, sync
from patrick.desktop import prefs

MANIFEST = sync.MANIFEST
_ONEDRIVE_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
_SCAN_DEPTH = 5
_SCAN_BUDGET_S = 3.0


class ShareError(ValueError):
    """Dossier de partage refusé (message destiné à l'utilisateur)."""


def data_dir() -> Path:
    """`~/.patrick` : les données de ce PC (jamais un dossier de partage)."""
    return settings.settings_path().parent


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _is_inside(path: str, parent: Path) -> bool:
    child = Path(os.path.normcase(os.path.abspath(path)))
    base = Path(os.path.normcase(os.path.abspath(parent)))
    return child == base or base in child.parents


def _writable(folder: Path) -> bool:
    probe = folder / f".patrick-test-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def _read_manifest(folder: Path) -> dict | None:
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) and "files" in manifest else None


def inspect_folder(path: str) -> dict:
    """Ce qu'on sait d'un dossier candidat, sans rien y écrire (hors fichier-test d'écriture)."""
    folder = Path(os.path.expanduser(path or ""))
    out: dict = {"path": str(folder), "exists": False, "creatable": False, "writable": False, "empty": None,
                 "has_share": False, "runs": None, "created_at": None, "wealth_published": False}
    if not path or not folder.is_absolute():
        return out
    if folder.is_dir():
        out["exists"] = True
        out["writable"] = _writable(folder)
        try:
            out["empty"] = next(folder.iterdir(), None) is None
        except OSError:
            out["empty"] = None
        manifest = _read_manifest(folder)
        if manifest:
            out.update(has_share=True, runs=manifest.get("runs"), created_at=manifest.get("created_at"),
                       wealth_published=bool(manifest.get("personal_included")))
    else:
        parent = folder.parent
        out["creatable"] = parent.is_dir() and _writable(parent)
        out["writable"] = out["creatable"]
    return out


def validate_folder(path: str) -> str:
    """Chemin normalisé d'un dossier utilisable comme partage, ou `ShareError`. Le dossier est créé s'il manque
    (le dossier parent doit exister)."""
    if not path or not path.strip():
        raise ShareError("Indique un dossier.")
    folder = os.path.normpath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.isabs(folder):
        raise ShareError("Le dossier doit être un chemin complet (par exemple C:\\Users\\toi\\OneDrive\\PATRICK).")
    if _is_inside(folder, data_dir()):
        raise ShareError("Choisis un dossier différent des données de PATRICK (le dossier .patrick de ce PC).")
    if os.path.splitdrive(folder)[1] in ("\\", "/", ""):
        raise ShareError("Choisis un sous-dossier (par exemple « PATRICK » dans OneDrive), pas la racine d'un disque.")
    info = inspect_folder(folder)
    if not info["exists"]:
        if not info["creatable"]:
            raise ShareError(f"Le dossier n'existe pas et ne peut pas être créé : {folder}")
        os.makedirs(folder, exist_ok=True)
    elif not info["writable"]:
        raise ShareError(f"PATRICK ne peut pas écrire dans ce dossier : {folder}")
    return folder


def _onedrive_roots() -> list[str]:
    roots: list[str] = []
    candidates = [os.environ.get(v) for v in _ONEDRIVE_VARS]
    candidates += [str(p) for p in sorted(Path.home().glob("OneDrive*"))]
    for root in candidates:
        if root and os.path.isdir(root) and not any(_same(root, r) for r in roots):
            roots.append(root)
    return roots


def find_existing_shares(roots: list[str] | None = None, *, max_depth: int = _SCAN_DEPTH,
                         budget_s: float = _SCAN_BUDGET_S) -> list[dict]:
    """Dossiers contenant déjà un partage PATRICK (`manifest.json`) sous les dossiers OneDrive : sert à
    proposer, sur un 2e PC, le dossier déjà utilisé par le premier. Parcours borné (profondeur et durée)."""
    found: list[dict] = []
    deadline = time.monotonic() + budget_s

    def walk(folder: str, depth: int) -> None:
        if time.monotonic() > deadline:
            return
        manifest = _read_manifest(Path(folder))
        if manifest:
            found.append({"path": folder, "runs": manifest.get("runs"), "created_at": manifest.get("created_at"),
                          "wealth_published": bool(manifest.get("personal_included"))})
            return
        if depth >= max_depth:
            return
        try:
            with os.scandir(folder) as entries:
                children = sorted(e.path for e in entries if e.is_dir(follow_symlinks=False)
                                  and not e.name.startswith("."))
        except OSError:
            return
        for child in children:
            walk(child, depth + 1)

    for root in roots if roots is not None else _onedrive_roots():
        walk(root, 0)
    return found


def suggest_folders() -> list[dict]:
    """Propositions pour l'assistant : le dossier actuel, les partages déjà présents, puis `<OneDrive>\\PATRICK`."""
    out: list[dict] = []

    def add(path: str, kind: str, **extra) -> None:
        if not any(_same(path, o["path"]) for o in out):
            out.append({"path": path, "kind": kind, **extra})

    current = sync.configured_folder()
    if current:
        add(current, "current")
    for share in find_existing_shares():
        add(share["path"], "existing", runs=share["runs"], created_at=share["created_at"])
    for root in _onedrive_roots():
        add(os.path.join(root, "PATRICK"), "onedrive")
    return out


def default_wealth_reference(info: dict) -> bool:
    """Par défaut, ce PC est la référence du patrimoine tant que le partage n'en contient pas déjà un."""
    return not info.get("wealth_published")


def current() -> dict:
    """Réglages de partage de ce PC."""
    folder = sync.configured_folder()
    return {"folder": folder, "wealth_reference": sync.is_wealth_reference(), "setup_done": prefs.setup_done(),
            "task": sync.task_status()}


def apply(folder: str | None, *, wealth_reference: bool | None = None, schedule: bool | None = None) -> dict:
    """Enregistre le partage de ce PC. `folder=None` : pas de dossier partagé (ce PC seul). Ne synchronise pas
    (la fusion demande que PATRICK soit fermé : elle a lieu au prochain démarrage ou via « Synchroniser »).

    `schedule` : crée / supprime la tâche Windows « PATRICK-Sync » (publication horaire); `None` = inchangé.
    Renvoie `{"folder", "inspect", "wealth_reference", "task", "warnings"}`."""
    warnings: list[str] = []
    previous = sync.configured_folder()
    if folder:
        folder = validate_folder(folder)
        updates: dict = {sync.KEY_SYNC_FOLDER: folder}
        if wealth_reference is not None:
            updates[sync.KEY_WEALTH_REFERENCE] = bool(wealth_reference)
        if previous is None or not _same(previous, folder):
            sync.forget_exchange()
        settings.save(updates)
    else:
        settings.save({sync.KEY_SYNC_FOLDER: None})
        if previous:
            sync.forget_exchange()
        schedule = False
    prefs.mark_setup_done()

    if schedule is not None and not (schedule is False and os.name != "nt"):
        try:
            if schedule:
                sync.register_task()
            else:
                sync.unregister_task()
        except sync.SyncError as exc:
            warnings.append(str(exc))
    return {"folder": folder or None, "inspect": inspect_folder(folder) if folder else None,
            "wealth_reference": sync.is_wealth_reference(), "task": sync.task_status(), "warnings": warnings}
