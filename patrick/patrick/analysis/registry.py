"""Répertoire des sections d'analyse d'un run ML/DL et mémoire de frames.

`build(conn, run_id, section, params)` renvoie `None` si le run n'existe pas, sinon un dictionnaire JSON-isable. Une frame (prédictions de
l'essai + niveau de la cible + rendements) se charge en 0,5 à 1 s sur la vraie base : une page ouvre une douzaine de sections, la frame
est donc gardée quelques minutes (`FRAME_TTL_S`) plutôt que relue à chaque section. Un run terminé ne change pas ; seules les lignes
`live` s'ajoutent, d'où un délai court."""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from patrick.analysis import (
    frames,
    sec_meta,
    sec_perf,
    sec_predict,
    sec_regimes,
    sec_robust,
)
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx

FRAME_TTL_S = 180
FRAME_CACHE_MAX = 6

SECTIONS: dict[str, Callable[[Ctx], dict]] = {
    "overview": sec_meta.overview,
    "protocol": sec_meta.protocol,
    "timeline": sec_predict.timeline,
    "rolling": sec_predict.rolling,
    "scatter": sec_predict.scatter,
    "confusion": sec_predict.confusion,
    "calibration": sec_predict.calibration,
    "folds": sec_meta.folds,
    "equity": sec_perf.equity,
    "errors": sec_perf.errors,
    "regimes": sec_regimes.regimes,
    "features": sec_meta.features,
    "trials": sec_meta.trials,
    "robustness": sec_robust.robustness,
    "holdout_live": sec_meta.holdout_live,
    "paths": sec_meta.paths,
    "notes": sec_meta.notes,
    "guide": sec_robust.guide,
}

_cache: OrderedDict[tuple, tuple[float, frames.Frame]] = OrderedDict()
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def get_frame(conn: sqlite3.Connection, run_id: str, trial_id: int | None = None, db_key: str = "") -> frames.Frame | None:
    key = (db_key, run_id, trial_id)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < FRAME_TTL_S:
            _cache.move_to_end(key)
            return hit[1]
    fr = frames.load_frame(conn, run_id, trial_id)
    if fr is None:
        return None
    with _lock:
        _cache[key] = (now, fr)
        while len(_cache) > FRAME_CACHE_MAX:
            _cache.popitem(last=False)
    return fr


def build(conn: sqlite3.Connection, run_id: str, section: str, params: dict | None = None, db_key: str = "") -> dict | None:
    if section not in SECTIONS:
        raise KeyError(section)
    params = params or {}
    trial_id = None
    if params.get("trial"):
        try:
            trial_id = int(params["trial"])
        except (TypeError, ValueError):
            trial_id = None
    fr = get_frame(conn, run_id, trial_id, db_key)
    if fr is None:
        return None
    return sc.jsonable(SECTIONS[section](Ctx(conn, fr, params)))
