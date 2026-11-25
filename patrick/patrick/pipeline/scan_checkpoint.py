"""Reprise d'un run au niveau du scan (A14) : les ajustements déjà faits par un lancement interrompu ne sont pas refaits.

Avant, la reprise d'un job (worker) ou `patrick resume` rejouait le même instantané de données et reprenait les études Optuna, mais
refaisait tout le scan (grille N × échantillonneur × algorithme sur chaque pli et chaque horizon), souvent l'essentiel de la durée.

Chaque ajustement du scan (`engine._fit_eval_full` : métriques, prédictions, confiance, P(hausse) d'un candidat sur un pli) est écrit
ici dès qu'il est calculé. La clé couvre tout ce dont le résultat dépend :
- l'identité du lancement : empreinte de configuration, instantané de données, version du code (commit git, empreinte du code des
  variables) ;
- le pli : horizon, numéro, régime, mode (fenêtre totale de présélection ou pli walk-forward) ;
- le candidat : nombre de variables, échantillonneur, algorithme, graine, colonnes retenues ;
- le CONTENU des matrices du pli (empreinte des octets de X et y d'entraînement et de test, et des poids d'échantillon) : un résultat ne
  ressert que pour des entrées identiques au bit près.
Un run neuf écrit sans jamais lire (même comportement qu'avant, au bit près) ; seule une reprise (instantané imposé) relit. Le dossier
est effacé à la fin d'un run réussi ; ceux d'un run jamais repris s'effacent d'eux-mêmes au bout de `MAX_AGE_DAYS`.

Format : un fichier `.npz` par ajustement (tableaux numpy, métriques en JSON), écrit atomiquement (fichier temporaire puis
renommage) : un arrêt brutal au milieu d'une écriture laisse au pire un ajustement à refaire, jamais un résultat tronqué.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

MAX_AGE_DAYS = 14
DIRNAME = "scan_checkpoint"


def digest(*arrays) -> str:
    """Empreinte du contenu exact de tableaux numpy (forme, type et octets) ; `None` compte comme une valeur."""
    h = hashlib.blake2b(digest_size=16)
    for a in arrays:
        if a is None:
            h.update(b"<none>")
            continue
        arr = np.ascontiguousarray(a)
        h.update(f"{arr.dtype.str}{arr.shape}".encode())
        h.update(arr.tobytes())
    return h.hexdigest()


def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"métrique non sérialisable : {type(o).__name__}")


class ScanCheckpoint:
    """Résultats d'ajustement du scan d'un lancement, dans `<output.dir>/scan_checkpoint/<identité>/`."""

    def __init__(self, output_dir: str | os.PathLike, identity: dict, read: bool):
        self.root = Path(output_dir) / DIRNAME
        token = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:20]
        self.dir = self.root / token
        self.read = read
        self.hits = 0
        self.writes = 0

    def key(self, **parts) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.npz"

    def load(self, key: str):
        """`(met, y_pred, confidence, p_up)` déjà calculé, ou None (run neuf, ou ajustement jamais terminé)."""
        if not self.read:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as z:
                met = json.loads(str(z["met"]))
                y_pred = z["y_pred"]
                confidence = z["confidence"] if "confidence" in z.files else None
                p_up = z["p_up"] if "p_up" in z.files else None
        except (OSError, ValueError, KeyError):
            return None                                   # fichier abîmé : l'ajustement est refait
        self.hits += 1
        return met, y_pred, confidence, p_up

    def save(self, key: str, result) -> None:
        met, y_pred, confidence, p_up = result
        try:
            payload = {"met": np.array(json.dumps(met, default=_json_default)), "y_pred": np.asarray(y_pred)}
        except TypeError:
            return                                        # métrique inattendue : pas de point de reprise pour cet ajustement
        if confidence is not None:
            payload["confidence"] = np.asarray(confidence)
        if p_up is not None:
            payload["p_up"] = np.asarray(p_up)
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                np.savez(fh, **payload)
            os.replace(tmp, path)
            self.writes += 1
        except OSError:
            return                                        # disque plein ou dossier en lecture seule : le run continue sans reprise

    def clear(self) -> None:
        """Efface les points de reprise de ce lancement (run terminé)."""
        shutil.rmtree(self.dir, ignore_errors=True)

    def purge_old(self, max_age_days: float = MAX_AGE_DAYS) -> int:
        """Efface les dossiers d'autres lancements plus vieux que `max_age_days` (runs interrompus jamais repris)."""
        if not self.root.is_dir():
            return 0
        limit = time.time() - max_age_days * 86400
        removed = 0
        for d in self.root.iterdir():
            if d.is_dir() and d != self.dir and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed
