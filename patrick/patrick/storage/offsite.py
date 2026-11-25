"""Copie hors site chiffrée de la base (FO30 du 25/11), et compression zstd quand Python la fournit (AM6).

La sauvegarde de nuit (`tracking/backup.py`) reste sur ce PC : un disque qui lâche ou un vol emporte la base ET ses sauvegardes. Cette copie
part dans un dossier qu'on choisit (le Drive, une clé USB), compressée puis chiffrée : sans la phrase secrète, le fichier ne dit rien de
ses comptes, fonds et ordres, même sur un service tiers.

Format `patrick-AAAAMMJJ-HHMMSS.db.<zst|gz>.enc` :

- en-tête : `PATRICK-OFFSITE1`, l'algorithme de compression (`z` zstd, `g` gzip), le sel de dérivation (16 octets) ;
- puis des blocs `nonce (12) | longueur (4) | données chiffrées + étiquette (16)`, AES-256-GCM, la clé tirée de la phrase par scrypt
  (bibliothèque standard). L'en-tête est authentifié avec chaque bloc : un fichier tronqué ou modifié est refusé à la restauration.

Dépendance facultative : `cryptography` (`pip install -e ".[backup]"`). Sans elle, la commande le dit et ne fait rien. La phrase secrète
vient de la variable d'environnement `PATRICK_BACKUP_PASSPHRASE`, jamais de la ligne de commande (elle resterait dans l'historique) :
sans elle, rien ne se restaure.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import os
import secrets
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path

MAGIC = b"PATRICK-OFFSITE1"
CHUNK = 4 * 1024 * 1024
KEEP = 3
ENV_PASSPHRASE = "PATRICK_BACKUP_PASSPHRASE"


class OffsiteError(RuntimeError):
    """Copie ou restauration impossible : message en français."""


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise OffsiteError("chiffrement indisponible : installer la dépendance facultative (pip install -e \".[backup]\")") from exc
    return AESGCM(key)


def _zstd():
    """Module zstd de la bibliothèque standard (Python 3.14 et plus), sinon None (repli gzip)."""
    try:
        from compression import zstd  # type: ignore[import-not-found]
    except ImportError:
        return None
    return zstd


def _key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase or len(passphrase) < 12:
        raise OffsiteError(f"phrase secrète absente ou trop courte (12 caractères au moins, variable {ENV_PASSPHRASE})")
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=128 * 1024 * 1024, dklen=32)


def _snapshot(db_path: str, dest: Path) -> None:
    """Instantané cohérent même avec un worker vivant (API de sauvegarde en un pas, comme `tracking/backup.py`)."""
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def _compress(src: Path, dest: Path) -> str:
    zstd = _zstd()
    with open(src, "rb") as fin:
        if zstd is not None:
            with zstd.open(dest, "wb", level=6) as fout:
                shutil.copyfileobj(fin, fout, CHUNK)
            return "z"
        with gzip.open(dest, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout, CHUNK)
        return "g"


def encrypt_file(src: Path, dest: Path, passphrase: str, algo: str) -> None:
    salt = secrets.token_bytes(16)
    aes = _aesgcm(_key(passphrase, salt))
    header = MAGIC + algo.encode("ascii") + salt
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        fout.write(header)
        index = 0
        while True:
            block = fin.read(CHUNK)
            if not block and index > 0:
                break
            nonce = secrets.token_bytes(12)
            # données associées : l'en-tête, le rang du bloc et « dernier bloc ou non » (un fichier tronqué est refusé)
            last = len(block) < CHUNK
            aad = header + struct.pack(">Q?", index, last)
            sealed = aes.encrypt(nonce, block, aad)
            fout.write(nonce + struct.pack(">I", len(sealed)) + sealed)
            index += 1
            if last:
                break
    os.replace(tmp, dest)


def decrypt_file(src: Path, dest: Path, passphrase: str) -> str:
    with open(src, "rb") as fin:
        header = fin.read(len(MAGIC) + 1 + 16)
        if not header.startswith(MAGIC):
            raise OffsiteError(f"{src.name} n'est pas une copie hors site de PATRICK")
        algo, salt = header[len(MAGIC):len(MAGIC) + 1].decode("ascii"), header[len(MAGIC) + 1:]
        aes = _aesgcm(_key(passphrase, salt))
        from cryptography.exceptions import InvalidTag
        index, finished = 0, False
        with open(dest, "wb") as fout:
            while True:
                head = fin.read(16)
                if not head:
                    break
                nonce, size = head[:12], struct.unpack(">I", head[12:])[0]
                sealed = fin.read(size)
                block = None
                for last in (False, True):
                    try:
                        block = aes.decrypt(nonce, sealed, header + struct.pack(">Q?", index, last))
                        finished = last
                        break
                    except InvalidTag:                # on essaie l'autre marque de fin avant de refuser
                        continue
                if block is None:
                    raise OffsiteError("phrase secrète fausse ou fichier modifié : restauration refusée")
                fout.write(block)
                index += 1
        if not finished:
            raise OffsiteError("copie tronquée (dernier bloc absent) : restauration refusée")
    return algo


def make_offsite_copy(db_path: str, dest_folder: str, passphrase: str | None = None, keep: int = KEEP) -> dict:
    """Instantané + compression + chiffrement dans `dest_folder` ; garde les `keep` dernières copies. Retourne le chemin et les tailles."""
    passphrase = passphrase if passphrase is not None else os.environ.get(ENV_PASSPHRASE, "")
    _key(passphrase, b"\0" * 16)                       # refus immédiat d'une phrase absente, avant de copier des gigaoctets
    _aesgcm(b"\0" * 32)
    folder = Path(dest_folder)
    if not folder.is_dir():
        raise OffsiteError(f"dossier de destination introuvable : {folder}")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005 -- heure locale lue par l'utilisateur, comme les sauvegardes
    with tempfile.TemporaryDirectory(prefix="patrick-offsite-") as tmp:
        snap, packed = Path(tmp) / "patrick.db", Path(tmp) / "patrick.db.pack"
        _snapshot(db_path, snap)
        algo = _compress(snap, packed)
        name = f"patrick-{stamp}.db.{'zst' if algo == 'z' else 'gz'}.enc"
        encrypt_file(packed, folder / name, passphrase, algo)
        sizes = {"db": snap.stat().st_size, "packed": packed.stat().st_size}
    copies = sorted(folder.glob("patrick-*.db.*.enc"))
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return {"path": str(folder / name), "compression": "zstd" if algo == "z" else "gzip", **sizes,
            "encrypted": (folder / name).stat().st_size, "kept": min(len(copies), keep)}


def restore_offsite_copy(src: str, out_db: str, passphrase: str | None = None) -> dict:
    """Déchiffre et décompresse `src` vers `out_db` (un fichier neuf, jamais la base en service), puis vérifie son intégrité."""
    passphrase = passphrase if passphrase is not None else os.environ.get(ENV_PASSPHRASE, "")
    out = Path(out_db)
    if out.exists():
        raise OffsiteError(f"{out} existe déjà : la restauration n'écrase jamais un fichier")
    with tempfile.TemporaryDirectory(prefix="patrick-restore-") as tmp:
        packed = Path(tmp) / "pack"
        algo = decrypt_file(Path(src), packed, passphrase)
        opener = _zstd().open if algo == "z" and _zstd() is not None else (gzip.open if algo == "g" else None)
        if opener is None:
            raise OffsiteError("copie compressée en zstd : la restaurer avec Python 3.14 ou plus")
        with opener(packed, "rb") as fin, open(out, "wb") as fout:
            shutil.copyfileobj(fin, fout, CHUNK)
    conn = sqlite3.connect(str(out))
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if check != "ok":
        raise OffsiteError(f"base restaurée abîmée : {check}")
    return {"path": str(out), "size": out.stat().st_size, "integrity": check}


__all__ = ["OffsiteError", "decrypt_file", "encrypt_file", "make_offsite_copy", "restore_offsite_copy"]
