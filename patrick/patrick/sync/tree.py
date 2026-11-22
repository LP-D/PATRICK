"""Format 2 du partage entre PC : une arborescence EN CLAIR dans le dossier partagé (Google Drive, OneDrive, disque réseau).

    manifest.json                       écrit EN DERNIER ; liste les fichiers annoncés (taille, sha256 des petits fichiers et de la base)
    db/patrick.db                       la recherche (sans caches ni données perso), SQLite lisible telle quelle
    models/index.json                   {id d'essai: chemin du modèle}
    models/<empreinte>/<fichier>        un modèle et son `_meta.json`, rangés par empreinte de CONTENU
    store/snapshot=<date>/<fichier>     les parquet du magasin de données (le nom porte déjà l'empreinte du contenu)
    store/_index.json, store/_series_observations.json

Pourquoi : le format 1 reconstruisait `store.zip` (~30 Go) dans le dossier temporaire à CHAQUE publication, puis le recopiait en
entier. Sur Google Drive « en streaming » ces 30 Go passent par le cache du Drive (sur `C:`) : les 10 et 11/11/2026 `C:` est tombé à
16 Go libres et le client Drive s'est figé. Ici les modèles et les parquet sont IMMUABLES : un fichier déjà publié (même chemin, même
taille) n'est jamais recopié, une publication ne copie que le neuf, et une copie interrompue reprend où elle s'est arrêtée.

Aucun fichier temporaire `.part` : sur le lecteur virtuel de Google Drive un `.part` oublié rendait son nom inutilisable
(`Errno 22`). Les fichiers sont écrits sous leur nom final ; le manifeste, écrit en dernier, n'annonce que des fichiers complets, et
le lecteur contrôle taille et sha256 (un fichier coupé en deux donne « pas entièrement recopié », jamais une donnée fausse).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

FORMAT = 2
DB_REL = "db/patrick.db"
MODELS_INDEX_REL = "models/index.json"
STORE_INDEX_REL = "store/_index.json"
STORE_SERIES_REL = "store/_series_observations.json"

_CHUNK = 16 * 1024 * 1024
_SPACE_CHECK_EVERY = 16 * _CHUNK            # on revérifie l'espace libre tous les 256 Mo copiés
# Fichiers `.part` de l'ancien mécanisme (le nôtre : « patrick.db.gz.part », « patrick (1).db.gz.part » créé par Drive...).
_OLD_PART_RE = re.compile(r"^(patrick|models|store|funds-|manifest)[^/\\]*\.part$")


class TreeError(RuntimeError):
    """Échec attendu d'une publication ou d'une lecture en clair (espace, fichier incomplet ou corrompu)."""


def is_tree(manifest: dict) -> bool:
    return manifest.get("format") == FORMAT


def safe_rel(rel: str) -> str:
    """Chemin relatif d'un manifeste (donnée venue d'un autre PC) : jamais absolu, jamais de `..`."""
    parts = rel.replace("\\", "/").split("/")
    if not rel or rel.startswith(("/", "\\")) or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
        raise TreeError(f"Manifeste invalide (chemin hors du dossier partagé) : {rel}")
    return "/".join(parts)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def remove_old_part_files(folder: Path) -> list[str]:
    """Supprime les `.part` laissés par l'ancien mécanisme de publication (vides ou coupés : jamais lus par personne)."""
    removed = []
    if not folder.is_dir():
        return removed
    for p in sorted(folder.iterdir()):
        if p.is_file() and _OLD_PART_RE.match(p.name):
            try:
                p.unlink()
                removed.append(p.name)
            except OSError:
                pass                                   # verrouillé par le client Drive : on réessaiera à la prochaine publication
    return removed


def copy_file(src: Path, dest: Path, *, free_bytes: Callable[[Path], int], floor: int, low_space: Callable[[], str],
              expect_sha: str | None = None) -> str:
    """Copie `src` vers `dest` SOUS SON NOM FINAL et retourne le sha256 du contenu copié (lu au passage : une seule lecture).

    Contrôle l'espace libre du disque de `dest` avant de commencer puis tous les 256 Mo : sous `floor`, la copie s'arrête avec
    `low_space()` (le fichier coupé sera recopié à la prochaine publication). `expect_sha` : « Fichier corrompu » si le contenu
    copié ne le porte pas (lecture d'un partage abîmé ou à moitié recopié)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if free_bytes(dest.parent) < floor:
        raise TreeError(low_space())
    digest, since_check = hashlib.sha256(), 0
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        while chunk := fin.read(_CHUNK):
            fout.write(chunk)
            digest.update(chunk)
            since_check += len(chunk)
            if since_check >= _SPACE_CHECK_EVERY:
                since_check = 0
                if free_bytes(dest.parent) < floor:
                    raise TreeError(low_space())
    sha = digest.hexdigest()
    if expect_sha is not None and sha != expect_sha:
        raise TreeError(f"Fichier corrompu (sha256 différent) : {src.name}")
    return sha


def publish(folder: Path, *, db_file: Path, immutable: list[tuple[Path, str]], small: dict[str, str],
            free_bytes: Callable[[Path], int], floor: int, low_space: Callable[[], str]) -> dict:
    """Copie vers `folder`, dans cet ordre : les fichiers immuables MANQUANTS (modèles, parquet), les petits JSON (index), puis la
    base (seul gros fichier réécrit). Le manifeste est écrit par l'appelant, en dernier. Retourne les empreintes à y inscrire :
    `files` (base et petits fichiers : taille, sha256), `tree` (fichiers immuables : taille) et `uploaded` (fichiers et octets écrits)."""
    uploaded_files = uploaded_bytes = 0
    tree: dict[str, dict] = {}
    for src, rel in immutable:
        rel = safe_rel(rel)
        size = src.stat().st_size
        tree[rel] = {"size": size}
        target = folder / rel
        if target.exists() and target.stat().st_size == size:
            continue                                   # déjà publié et complet : jamais recopié
        copy_file(src, target, free_bytes=free_bytes, floor=floor, low_space=low_space)
        uploaded_files += 1
        uploaded_bytes += size

    files: dict[str, dict] = {}
    for rel, text in small.items():
        data = text.encode("utf-8")
        target = folder / safe_rel(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        uploaded_files += 1
        uploaded_bytes += len(data)

    sha = copy_file(db_file, folder / DB_REL, free_bytes=free_bytes, floor=floor, low_space=low_space)
    files[DB_REL] = {"sha256": sha, "size": db_file.stat().st_size}
    uploaded_files += 1
    uploaded_bytes += db_file.stat().st_size
    return {"files": files, "tree": tree, "uploaded": {"files": uploaded_files, "bytes": uploaded_bytes}}


def verify(folder: Path, manifest: dict) -> None:
    """Le partage est-il complet ? Chaque fichier annoncé existe avec la bonne taille (sinon il n'est « pas entièrement recopié »
    par le dossier partagé : on réessaiera plus tard) ; les petits fichiers sont aussi contrôlés par sha256. La base ne l'est qu'à
    la copie (`copy_file(expect_sha=...)`) : la lire deux fois coûterait deux fois son téléchargement depuis Google Drive."""
    def incomplete(rel: str) -> TreeError:
        return TreeError(f"Fichier annoncé mais pas entièrement recopié par le dossier partagé : {rel}")

    for rel, meta in manifest["files"].items():
        path = folder / safe_rel(rel)
        if not path.is_file() or path.stat().st_size != meta["size"]:
            raise incomplete(rel)
        if rel != DB_REL and sha256_file(path) != meta["sha256"]:
            raise TreeError(f"Fichier corrompu (sha256 différent) : {rel}")
    for rel, meta in manifest.get("tree", {}).items():
        path = folder / safe_rel(rel)
        if not path.is_file() or path.stat().st_size != meta["size"]:
            raise incomplete(rel)


def read_json(folder: Path, rel: str) -> dict:
    return json.loads((folder / safe_rel(rel)).read_text(encoding="utf-8"))
