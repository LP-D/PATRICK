"""Cache des résultats de la page Économétrie : « calculer une fois ».

Un résultat est rangé sous une clé qui est l'empreinte de TOUT ce qui le détermine : l'étude, la série (symbole, source, transformation, fenêtre,
et une empreinte des valeurs elles-mêmes), les paramètres, et la version du code. Si la série reçoit une nouvelle cotation, ou si on change un
paramètre, ou si on bumpe `CODE_VERSION`, la clé change : jamais de résultat périmé servi par erreur.

Stockage : un fichier JSON compressé par résultat sous `<cache>/econometrics/`, écrit de façon atomique (fichier temporaire puis `os.replace`) —
un lecteur voit l'ancien fichier ou le nouveau, jamais un fichier tronqué (incident du 2026-10-10 sur le cache des séries). Un fichier illisible vaut
« pas de cache ». Au-delà de `MAX_ENTRIES`, les plus anciens sont supprimés.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from patrick import paths

CODE_VERSION = "1"            # à incrémenter quand le calcul d'une étude change de façon visible
MAX_ENTRIES = 600
EVICT_SLACK = 40               # on ne nettoie qu'au-delà de MAX_ENTRIES + marge, pour ne pas lister le dossier à chaque écriture
_lock = threading.Lock()


def directory() -> Path:
    d = paths.cache_dir() / "econometrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fingerprint(series: pd.Series) -> dict:
    """Empreinte des données d'une série : longueur, dernière date, et condensé des valeurs (arrondies pour ignorer le bruit de flottant)."""
    s = pd.Series(series).dropna()
    values = np.round(s.to_numpy(dtype=float), 10)
    last = s.index[-1]
    return {"n": len(s), "last": last.strftime("%Y-%m-%d") if hasattr(last, "strftime") else str(last),
            "digest": hashlib.sha1(values.tobytes()).hexdigest()[:16]}


def cache_key(**parts) -> str:
    payload = json.dumps({"code": CODE_VERSION, **parts}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:32]


def _path(key: str) -> Path:
    return directory() / f"{key}.json.gz"


def load(key: str) -> dict | None:
    p = _path(key)
    try:
        return json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, EOFError, gzip.BadGzipFile):
        return None


def save(key: str, payload: dict) -> None:
    p = _path(key)
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        tmp.write_bytes(gzip.compress(json.dumps(payload, default=str, allow_nan=False).encode("utf-8")))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    _evict()


def _evict() -> None:
    with _lock:
        try:
            files = [(f.stat().st_mtime, f) for f in directory().glob("*.json.gz")]
        except OSError:
            return
        if len(files) <= MAX_ENTRIES + EVICT_SLACK:
            return
        for _, f in sorted(files)[:len(files) - MAX_ENTRIES]:
            f.unlink(missing_ok=True)
