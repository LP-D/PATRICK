"""Journal de prédictions chaîné (migration 0040) : écriture, vérification de la chaîne, scellement de l'existant.

Une ligne = un signal émis ou une issue connue, horodatée (UTC, microsecondes), avec le SHA-256 du fichier de modèle qui l'a produit et l'empreinte de la
ligne précédente. L'empreinte d'une ligne couvre tous ses champs et l'empreinte précédente : changer un champ, supprimer ou insérer une ligne casse
la chaîne à cet endroit. `verify` la rejoue de bout en bout.

Écrire dans le journal ne doit JAMAIS empêcher d'écrire une prédiction : les crochets de `tracking/db.py` ignorent les erreurs SQLite d'ici."""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import sqlite3
import threading

from patrick.tracking.prediction_archive import live_index_hint

GENESIS = "0" * 64
_TRIGGERS = (
    ("CREATE TRIGGER IF NOT EXISTS prediction_journal_no_update BEFORE UPDATE ON prediction_journal "
     "BEGIN SELECT RAISE(ABORT, 'prediction_journal est append-only : modification refusée'); END"),
    ("CREATE TRIGGER IF NOT EXISTS prediction_journal_no_delete BEFORE DELETE ON prediction_journal "
     "BEGIN SELECT RAISE(ABORT, 'prediction_journal est append-only : suppression refusée'); END"),
)
_hash_cache: dict[tuple, str] = {}
_lock = threading.Lock()
_PAYLOAD_FIELDS = ("recorded_at", "kind", "origin", "run_id", "trial_id", "target", "horizon", "signal_date", "y_pred", "p_up", "y_true", "model_hash",
                   "config_hash")


def ensure_triggers(conn: sqlite3.Connection) -> None:
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'prediction_journal_%'")}
    if len(have) >= len(_TRIGGERS):
        return
    for ddl in _TRIGGERS:
        conn.execute(ddl)


def _num(v):
    return None if v is None else round(float(v), 10)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


def entry_hash(prev_hash: str, row: dict) -> str:
    payload = [row.get(f) for f in _PAYLOAD_FIELDS]
    return hashlib.sha256((prev_hash + "|" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)).encode("utf-8")).hexdigest()


def model_hash(artifact_path: str | None) -> str | None:
    """SHA-256 du fichier de modèle exporté (mis en mémoire par chemin, date et taille) ; `None` si le fichier est absent."""
    if not artifact_path or not os.path.exists(artifact_path):
        return None
    st = os.stat(artifact_path)
    key = (artifact_path, st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _hash_cache.get(key)
    if hit:
        return hit
    h = hashlib.sha256()
    with open(artifact_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with _lock:
        _hash_cache[key] = digest
        if len(_hash_cache) > 64:
            _hash_cache.pop(next(iter(_hash_cache)))
    return digest


def _trial_context(conn: sqlite3.Connection, trial_id: int) -> dict | None:
    row = conn.execute("SELECT r.run_id, r.target, r.horizon, r.config_hash, t.artifact_path FROM trial t JOIN run r ON r.run_id = t.run_id WHERE t.trial_id = ?",
                       (trial_id,)).fetchone()
    if row is None:
        return None
    return {"run_id": row[0], "target": row[1], "horizon": int(row[2]), "config_hash": row[3], "model_hash": model_hash(row[4])}


def _append(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Ajoute des lignes à la suite de la chaîne dans UNE transaction exclusive (deux processus ne peuvent pas lire la même dernière empreinte)."""
    if not rows:
        return 0
    ensure_triggers(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        last = conn.execute("SELECT entry_hash FROM prediction_journal ORDER BY journal_id DESC LIMIT 1").fetchone()
        prev = last[0] if last else GENESIS
        for r in rows:
            r = {**r, "y_pred": _num(r.get("y_pred")), "p_up": _num(r.get("p_up")), "y_true": _num(r.get("y_true"))}
            r.setdefault("recorded_at", _utc_now())
            h = entry_hash(prev, r)
            conn.execute("INSERT INTO prediction_journal (recorded_at, kind, origin, run_id, trial_id, target, horizon, signal_date, y_pred, p_up, y_true, "
                         "model_hash, config_hash, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (r["recorded_at"], r["kind"], r.get("origin", "live"), r.get("run_id"), r.get("trial_id"), r["target"], r["horizon"], r["signal_date"],
                          r.get("y_pred"), r.get("p_up"), r.get("y_true"), r.get("model_hash"), r.get("config_hash"), prev, h))
            prev = h
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def record_signals(conn: sqlite3.Connection, trial_id: int, ts: list, y_pred, p_up=None, origin: str = "live") -> int:
    """Journalise les signaux (premier écrit gagne : un signal déjà journalisé pour cet essai et cette date n'est jamais rejournalisé)."""
    ctx = _trial_context(conn, trial_id)
    if ctx is None:
        return 0
    seen = {r[0] for r in conn.execute("SELECT signal_date FROM prediction_journal WHERE trial_id = ? AND kind = 'signal'", (trial_id,))}
    ups = p_up if p_up is not None else [None] * len(ts)
    rows = []
    for t, yp, up in zip(ts, y_pred, ups, strict=True):
        day = str(t)[:10]
        if day in seen:
            continue
        seen.add(day)
        rows.append({"kind": "signal", "origin": origin, "trial_id": trial_id, "signal_date": day, "y_pred": yp, "p_up": up, **ctx})
    return _append(conn, rows)


def record_outcome(conn: sqlite3.Connection, trial_id: int, ts: str, y_true: float, origin: str = "live") -> int:
    """Journalise une issue connue ; sans effet si la dernière issue journalisée de ce signal est identique (un jugement corrigé s'ajoute)."""
    ctx = _trial_context(conn, trial_id)
    if ctx is None:
        return 0
    day = str(ts)[:10]
    last = conn.execute("SELECT y_true FROM prediction_journal WHERE trial_id = ? AND signal_date = ? AND kind = 'outcome' ORDER BY journal_id DESC LIMIT 1",
                        (trial_id, day)).fetchone()
    if last is not None and last[0] is not None and abs(last[0] - float(y_true)) < 1e-12:
        return 0
    return _append(conn, [{"kind": "outcome", "origin": origin, "trial_id": trial_id, "signal_date": day, "y_true": y_true, **ctx}])


def verify(conn: sqlite3.Connection) -> dict:
    """Rejoue la chaîne : chaque ligne doit relier l'empreinte précédente et se recalculer à l'identique. Renvoie `ok`, le nombre de lignes lues et, si
    la chaîne est cassée, l'identifiant de la première ligne fautive et le motif (`prev_mismatch`, `hash_mismatch`)."""
    prev = GENESIS
    n = 0
    cols = ("journal_id", *_PAYLOAD_FIELDS, "prev_hash", "entry_hash")
    for rec in conn.execute(f"SELECT {', '.join(cols)} FROM prediction_journal ORDER BY journal_id"):
        d = dict(zip(cols, rec, strict=True))
        n += 1
        if d["prev_hash"] != prev:
            return {"ok": False, "n": n, "first_bad": d["journal_id"], "reason": "prev_mismatch"}
        if entry_hash(prev, d) != d["entry_hash"]:
            return {"ok": False, "n": n, "first_bad": d["journal_id"], "reason": "hash_mismatch"}
        prev = d["entry_hash"]
    return {"ok": True, "n": n, "first_bad": None, "reason": None, "head": prev if n else None}


def seal_existing(conn: sqlite3.Connection, batch: int = 500) -> dict:
    """Scelle les prédictions live déjà stockées qui n'ont pas de ligne de journal (origine `backfill`) : signal, puis issue si elle est connue. Par lots
    de `batch` lignes, des transactions courtes (la base peut être utilisée par un worker)."""
    done = conn.execute("SELECT trial_id, signal_date FROM prediction_journal WHERE kind = 'signal'").fetchall()
    have = {(t, d) for t, d in done}
    rows = conn.execute(f"SELECT trial_id, ts, y_pred, p_up, y_true FROM prediction INDEXED BY {live_index_hint(conn)} WHERE split = 'live' ORDER BY ts").fetchall()
    ctx_cache: dict[int, dict | None] = {}
    sealed = outcomes = 0
    pending: list[dict] = []

    def flush():
        nonlocal pending
        if pending:
            _append(conn, pending)
            pending = []

    for trial_id, ts, y_pred, p_up, y_true in rows:
        day = str(ts)[:10]
        if (trial_id, day) in have:
            continue
        if trial_id not in ctx_cache:
            ctx_cache[trial_id] = _trial_context(conn, trial_id)
        ctx = ctx_cache[trial_id]
        if ctx is None:
            continue
        pending.append({"kind": "signal", "origin": "backfill", "trial_id": trial_id, "signal_date": day, "y_pred": y_pred, "p_up": p_up, **ctx})
        sealed += 1
        if y_true is not None:
            pending.append({"kind": "outcome", "origin": "backfill", "trial_id": trial_id, "signal_date": day, "y_true": y_true, **ctx})
            outcomes += 1
        if len(pending) >= batch:
            flush()
    flush()
    return {"sealed": sealed, "outcomes": outcomes, "rows": len(rows)}


def safe(fn, *args, **kwargs) -> None:
    """Appelle une écriture de journal en ignorant toute erreur SQLite : une prédiction ne doit jamais échouer à cause du journal."""
    with contextlib.suppress(sqlite3.Error):
        fn(*args, **kwargs)
