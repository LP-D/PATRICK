"""Import automatique des relevés de courtier déposés dans un dossier (FO20 du 25/11).

Réglages de ce PC : `import_folder` (dossier surveillé) et `import_account` (compte de destination). Chaque passage (`patrick wealth
import-folder`, étape de la nuit) lit les `*.csv` du dossier avec le même lecteur que le glisser-déposer de /patrimoine
(`wealth.importer`), écrit les mouvements NOUVEAUX seulement (les doublons déjà en base sont reconnus et sautés, comme à la main), puis
range le fichier dans `importés/` (ou `refusés/` avec la raison s'il est illisible). Rien n'est supprimé ; un fichier n'est lu qu'une fois.
"""
from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from pathlib import Path

from patrick.core import settings
from patrick.wealth import importer, ledger

KEY_FOLDER, KEY_ACCOUNT = "import_folder", "import_account"


def configured() -> tuple[str | None, str | None]:
    s = settings.load()
    return s.get(KEY_FOLDER), s.get(KEY_ACCOUNT)


def _move(path: Path, sub: str) -> Path:
    dest_dir = path.parent / sub
    dest_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005 -- heure locale lue par l'utilisateur dans le dossier
    dest = dest_dir / f"{path.stem}.{stamp}{path.suffix}"
    shutil.move(str(path), dest)
    return dest


def run(conn: sqlite3.Connection, folder: str, account_id: str, resolve=None, dry_run: bool = False) -> dict:
    """`{files: [{name, written, skipped, status, reason}], written}` pour chaque CSV du dossier."""
    root = Path(folder)
    if not root.is_dir():
        raise ledger.LedgerError(f"dossier d'import introuvable : {folder}")
    if ledger.get_account(conn, account_id) is None:
        raise ledger.LedgerError(f"compte introuvable : {account_id}")
    out: dict = {"files": [], "written": 0}
    for path in sorted(root.glob("*.csv")):
        entry = {"name": path.name, "written": 0, "skipped": 0, "status": "ok", "reason": None}
        try:
            parsed = importer.parse_csv(path.read_bytes(), resolve=resolve)
            plan = importer.plan_import(parsed["rows"], {}, account_id, {account_id: ledger.list_movements(conn, account_id)})
            for row in plan:
                if row["status"] == "":
                    if not dry_run:
                        ledger.add_movement(conn, row["target"], row)
                    entry["written"] += 1
                else:
                    entry["skipped"] += 1
        except (ledger.LedgerError, ValueError, UnicodeDecodeError) as exc:
            entry.update(status="refused", reason=str(exc)[:200])
        if not dry_run:
            dest = _move(path, "importés" if entry["status"] == "ok" else "refusés")
            if entry["status"] != "ok":
                dest.with_suffix(dest.suffix + ".raison.txt").write_text(entry["reason"] or "", encoding="utf-8")
        out["written"] += entry["written"]
        out["files"].append(entry)
    return out
