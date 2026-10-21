"""Explorateur de données (page `/donnees`) : contenu du data lake, vue « point dans le temps », révisions entre deux instantanés, calendrier
estimé des publications, listes de suivi et import d'une série personnelle.

Lecture seule sur les séries de marché (`raw_*`). Le seul chemin d'écriture est `commit_import` : il crée une clé `user_<nom>` qui n'écrase
jamais une clé du pipeline. Les dates d'un fichier importé sont prises comme dates de DISPONIBILITÉ : une série publiée avec retard doit être
décalée avant l'import (la page le rappelle)."""
from __future__ import annotations

import base64
import io
import re

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc
from patrick.data import quality
from patrick.data.sources.yfinance_source import clean_symbol

MAX_POINTS = 700
MAX_IMPORT_BYTES = 8_000_000
MAX_IMPORT_COLUMNS = 40
MIN_IMPORT_ROWS = 30
_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
USER_PREFIX = "user_"


class DataError(ValueError):
    """Entrée invalide : le message est un code (`unknown_key`, `unknown_snapshot`, `unknown_column`, `bad_date`, `bad_name`, `too_large`...)."""


# --------------------------------------------------------------------------------------------------------------------- lake
def _kind(key: str) -> str:
    return "raw" if key.startswith("raw_") else "user" if key.startswith(USER_PREFIX) else "other"


def lake_index(store) -> dict:
    """Une ligne par clé du data lake, lue dans l'index seul (aucun fichier parquet ouvert)."""
    idx = store.info()
    rows = []
    n_snap = 0
    for key, v in idx.items():
        snaps = v.get("snapshots", [])
        if not snaps:
            continue
        n_snap += len(snaps)
        last = snaps[-1]
        rows.append({"key": key, "symbol": key.removeprefix("raw_"), "kind": _kind(key), "n_snapshots": len(snaps),
                     "created_at": last.get("created_at"), "rows": last.get("rows"), "cols": last.get("cols"), "date_min": (last.get("date_min") or "")[:10] or None,
                     "date_max": (last.get("date_max") or "")[:10] or None, "pit_version": last.get("pit_version")})
    rows.sort(key=lambda r: r["key"].lower())
    return sc.jsonable({"keys": rows, "n_keys": len(rows), "n_snapshots": n_snap, "root": store.root})


def _frame(store, key: str, snapshot_id: str | None) -> pd.DataFrame:
    if not store.exists(key):
        raise DataError("unknown_key")
    try:
        df = store.load(key, snapshot_id)
    except FileNotFoundError as exc:
        raise DataError("unknown_snapshot") from exc
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index)
    return df.sort_index()


def _as_of(df: pd.DataFrame, as_of) -> pd.Timestamp:
    if as_of in (None, ""):
        return df.index[-1]
    try:
        t = pd.Timestamp(as_of).normalize()
    except (ValueError, TypeError) as exc:
        raise DataError("bad_date") from exc
    if t < df.index[0]:
        raise DataError("before_start")
    return t


def snapshot_at(store, key: str, when) -> dict | None:
    """Instantané qui était le plus récent à la date `when` (ce que le pipeline aurait lu ce jour-là)."""
    t = pd.Timestamp(when).normalize()
    best = None
    for e in store.list_snapshots(key):
        created = pd.Timestamp((e.get("created_at") or "")[:10]) if e.get("created_at") else None
        if created is not None and created <= t:
            best = e
    return best


def frame_detail(store, key: str, snapshot_id: str | None = None, as_of=None) -> dict:
    """Pour chaque colonne : dernière valeur visible à `as_of`, date du dernier changement, ancienneté, part de valeurs présentes sur 252 jours.

    Les cadres du pipeline sont alignés sur les dates de publication (`pit_version`) puis remplis vers l'avant : une valeur qui ne change plus
    depuis longtemps est soit une série peu fréquente, soit une série figée ; l'écran compare l'ancienneté au rythme habituel de la série."""
    snaps = store.list_snapshots(key)
    df = _frame(store, key, snapshot_id)
    t = _as_of(df, as_of)
    vis = df.loc[:t]
    cols = []
    for c in vis.columns:
        s = vis[c]
        valid = s.dropna()
        if valid.empty:
            cols.append({"column": str(c), "status": "empty", "last_value": None, "first_date": None, "last_date": None, "last_change": None,
                         "stale_days": None, "typical_days": None, "coverage_252": 0.0})
            continue
        numeric = pd.api.types.is_numeric_dtype(valid)
        changed = valid.ne(valid.shift())
        change_dates = valid.index[changed.to_numpy()]
        last_change = change_dates[-1]
        spacing = pd.Series(change_dates[-60:]).diff().dt.days.median() if len(change_dates) > 2 else None
        typical = float(spacing) if spacing is not None and np.isfinite(spacing) else None
        stale = int((t - last_change).days)
        limit = max(7.0, 2.0 * typical + 3.0) if typical is not None else 7.0
        cols.append({"column": str(c), "status": "stale" if stale > limit else "ok",
                     "last_value": float(valid.iloc[-1]) if numeric else str(valid.iloc[-1]), "first_date": str(valid.index[0].date()),
                     "last_date": str(valid.index[-1].date()), "last_change": str(last_change.date()), "stale_days": stale, "typical_days": typical,
                     "coverage_252": float(s.tail(252).notna().mean())})
    cols.sort(key=lambda r: ({"stale": 0, "empty": 1, "ok": 2}[r["status"]], -(r["stale_days"] or 0)))
    current = snapshot_at(store, key, t)
    return sc.jsonable({
        "key": key, "snapshot_id": df.attrs.get("snapshot_id"), "as_of": str(t.date()), "date_min": str(df.index[0].date()), "date_max": str(df.index[-1].date()),
        "rows": len(df), "visible_rows": len(vis), "n_columns": int(df.shape[1]),
        "snapshots": [{"snapshot_id": e["snapshot_id"], "created_at": e.get("created_at"), "rows": e.get("rows"), "cols": e.get("cols"),
                       "date_max": (e.get("date_max") or "")[:10], "hash": e.get("content_hash"), "pit_version": e.get("pit_version")} for e in snaps],
        "known_snapshot": current["snapshot_id"] if current else None, "columns": cols,
        "counts": {"ok": sum(c["status"] == "ok" for c in cols), "stale": sum(c["status"] == "stale" for c in cols), "empty": sum(c["status"] == "empty" for c in cols)},
    })


def column_series(store, key: str, column: str, snapshot_id: str | None = None, as_of=None, compare: str | None = None) -> dict:
    """Courbe d'une colonne telle que visible à `as_of` (+ la suite en grisé) ; avec `compare`, la même courbe dans un autre instantané."""
    df = _frame(store, key, snapshot_id)
    if column not in df.columns:
        raise DataError("unknown_column")
    t = _as_of(df, as_of)
    s = df[column].dropna()
    vis, after = s.loc[:t], s.loc[t:].iloc[1:]
    iv = sc.thin_indices(len(vis), MAX_POINTS)
    ia = sc.thin_indices(len(after), max(2, MAX_POINTS // 5)) if len(after) else np.array([], dtype=int)
    out = {"column": column, "as_of": str(t.date()), "snapshot_id": df.attrs.get("snapshot_id"),
           "dates": [str(vis.index[i].date()) for i in iv], "values": [float(vis.iloc[i]) for i in iv],
           "after_dates": [str(after.index[i].date()) for i in ia], "after_values": [float(after.iloc[i]) for i in ia]}
    if compare:
        other = _frame(store, key, compare)
        if column in other.columns:
            o = other[column].dropna().loc[:t]
            jo = sc.thin_indices(len(o), MAX_POINTS)
            out["compare"] = {"snapshot_id": other.attrs.get("snapshot_id"), "dates": [str(o.index[i].date()) for i in jo], "values": [float(o.iloc[i]) for i in jo]}
    return sc.jsonable(out)


def snapshot_revisions(store, key: str, a: str, b: str, rel_tol: float = 1e-9) -> dict:
    """Cellules qui diffèrent entre deux instantanés d'une même clé : l'historique a-t-il été réécrit (révisions, corrections) ?

    Les cellules passées de vide à valeur, ou l'inverse, sont comptées à part. L'instantané le plus récent sert de référence ;
    `revised_old` compte les changements de dates antérieures de plus de 5 jours à sa création (donc des révisions, pas du simple ajout)."""
    A, B = _frame(store, key, a), _frame(store, key, b)
    ea = next(e for e in store.list_snapshots(key) if e["snapshot_id"] == A.attrs["snapshot_id"])
    eb = next(e for e in store.list_snapshots(key) if e["snapshot_id"] == B.attrs["snapshot_id"])
    if (ea.get("created_at") or "") > (eb.get("created_at") or ""):
        A, B, ea, eb = B, A, eb, ea
    idx = A.index.intersection(B.index)
    cols = [c for c in A.columns if c in B.columns and pd.api.types.is_numeric_dtype(A[c]) and pd.api.types.is_numeric_dtype(B[c])]
    xa, xb = A.loc[idx, cols].to_numpy(dtype=float), B.loc[idx, cols].to_numpy(dtype=float)
    both = np.isfinite(xa) & np.isfinite(xb)
    diff = np.where(both, np.abs(xa - xb), 0.0)
    scale = np.maximum(np.abs(xb), 1e-12)
    changed = both & (diff > rel_tol * scale + 1e-12)
    appeared = np.isfinite(xb) & ~np.isfinite(xa)
    vanished = np.isfinite(xa) & ~np.isfinite(xb)
    cutoff = pd.Timestamp((eb.get("created_at") or "")[:10]) - pd.Timedelta(days=5) if eb.get("created_at") else None
    old = np.asarray(idx < cutoff) if cutoff is not None else np.zeros(len(idx), dtype=bool)
    rows = []
    for j, c in enumerate(cols):
        n = int(changed[:, j].sum())
        na, nv = int(appeared[:, j].sum()), int(vanished[:, j].sum())
        if not (n or na or nv):
            continue
        hit = np.where(changed[:, j] | appeared[:, j] | vanished[:, j])[0]
        rows.append({"column": str(c), "changed": n, "appeared": na, "vanished": nv, "revised_old": int((changed[:, j] & old).sum()),
                     "max_rel": float((diff[:, j] / scale[:, j])[changed[:, j]].max()) if n else None,
                     "first": str(idx[hit[0]].date()), "last": str(idx[hit[-1]].date())})
    rows.sort(key=lambda r: (-r["revised_old"], -r["changed"], -r["appeared"]))
    return sc.jsonable({
        "key": key, "older": ea["snapshot_id"], "newer": eb["snapshot_id"], "older_created": ea.get("created_at"), "newer_created": eb.get("created_at"),
        "common_rows": len(idx), "rows_only_older": len(A.index.difference(B.index)), "rows_only_newer": len(B.index.difference(A.index)),
        "columns_compared": len(cols), "columns_only_older": [str(c) for c in A.columns if c not in B.columns][:30], "columns_only_newer": [str(c) for c in B.columns if c not in A.columns][:30],
        "cells_changed": int(changed.sum()), "cells_appeared": int(appeared.sum()), "cells_vanished": int(vanished.sum()),
        "cells_revised_old": int((changed & old[:, None]).sum()), "columns": rows[:80], "n_columns_affected": len(rows)})


# ----------------------------------------------------------------------------------------------------------------- calendrier
def release_calendar(store, as_of=None) -> dict:
    """Prochaine publication ESTIMÉE de chaque série FRED d'entraînement : fin de la période suivante + délai de publication du dépôt.

    Ce n'est pas un calendrier officiel (les dates réelles bougent : jours fériés, arrêts administratifs) ; c'est la règle que le pipeline
    applique pour ne pas lire une valeur avant sa publication. Une série dont la date estimée est dépassée de plus de la marge est « en retard »."""
    from patrick.clock import utc_today
    from patrick.config import defaults as D
    from patrick.data import freshness, publication_lag

    today = pd.Timestamp(as_of).normalize() if as_of else pd.Timestamp(utc_today()).normalize()
    series = {sid: label for label, sid in {**D.FEATURE_ONLY_FRED_SERIES, **D.MACRO_ONLY_FRED_SERIES}.items()}
    rows = []
    for sid, label in sorted(series.items()):
        obs = store.series_observation(sid)
        last = pd.Timestamp(obs["date_max"][:10]) if obs and obs.get("date_max") else None
        per = freshness.fred_periodicity(sid)
        row = {"series": sid, "label": label, "periodicity": per, "last_obs": str(last.date()) if last is not None else None}
        if last is None:
            rows.append({**row, "next_expected": None, "days_until": None, "late_bdays": None, "state": "unknown"})
            continue
        next_ref = last + freshness._NEXT_PERIOD[per]
        expected = publication_lag.availability_dates(pd.DatetimeIndex([next_ref]), sid)[0]
        late = freshness.fred_business_days_late(sid, last, per, as_of=today)
        margin = freshness.FRED_RELEASE_MARGIN_BDAYS[per]
        days = int((expected.normalize() - today).days)
        rows.append({**row, "next_expected": str(expected.date()), "days_until": days, "late_bdays": late,
                     "state": "late" if late > margin else ("soon" if 0 <= days <= 14 else "later")})
    rows.sort(key=lambda r: (r["next_expected"] is None, r["next_expected"] or ""))
    return sc.jsonable({"as_of": str(today.date()), "rows": rows, "n_late": sum(r["state"] == "late" for r in rows), "n_soon": sum(r["state"] == "soon" for r in rows)})


# ----------------------------------------------------------------------------------------------------------- listes de suivi
def price_column(store, key: str) -> pd.Series | None:
    """Colonne de prix d'une clé `raw_<symbole>` (celle du symbole, sinon `Close`), lue seule dans le parquet."""
    import pyarrow.parquet as pq

    entry = store.latest_entry(key)
    if not entry:
        return None
    symbol = key[4:]
    names = pq.ParquetFile(entry["path"]).schema.names
    col = clean_symbol(symbol) if clean_symbol(symbol) in names else ("Close" if "Close" in names else None)
    if col is None:
        return None
    s = pd.read_parquet(entry["path"], columns=[col])[col].dropna()
    s.index = pd.DatetimeIndex(s.index)
    return s.sort_index()


def _change(s: pd.Series, n: int) -> float | None:
    if len(s) <= n:
        return None
    base = float(s.iloc[-1 - n])
    return float(s.iloc[-1]) / base - 1.0 if base else None


def watchlist_overview(store, symbols: list[str], as_of=None) -> dict:
    """Dernier cours, variations et fraîcheur de chaque symbole de la liste ; un symbole absent du lake est listé, jamais ignoré."""
    today = pd.Timestamp(as_of).normalize() if as_of else pd.Timestamp.now().normalize()
    rows = []
    for sym in symbols:
        s = price_column(store, f"raw_{sym}")
        if s is None or s.empty:
            rows.append({"symbol": sym, "in_lake": False})
            continue
        last = s.index[-1]
        spark = s.iloc[-120:]
        k = sc.thin_indices(len(spark), 40)
        rows.append({"symbol": sym, "in_lake": True, "last_date": str(last.date()), "last_price": float(s.iloc[-1]),
                     "stale_bdays": int(np.busday_count(last.date(), today.date())) if last < today else 0, "n_obs": len(s),
                     "d1": _change(s, 1), "d5": _change(s, 5), "d21": _change(s, 21), "d63": _change(s, 63), "d252": _change(s, 252),
                     "spark": [float(spark.iloc[i]) for i in k]})
    return sc.jsonable({"rows": rows, "n_missing": sum(not r["in_lake"] for r in rows)})


def lake_symbols(store) -> list[str]:
    return sorted(k[4:] for k, v in store.info().items() if k.startswith("raw_") and v.get("snapshots"))


# ------------------------------------------------------------------------------------------------------------------ import
def _read_table(filename: str, data: bytes) -> pd.DataFrame:
    if len(data) > MAX_IMPORT_BYTES:
        raise DataError("too_large")
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            return pd.read_excel(io.BytesIO(data), engine="openpyxl")
        except Exception as exc:
            raise DataError("bad_file") from exc
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise DataError("bad_file")
    first = text.splitlines()[0] if text.strip() else ""
    counts = {d: first.count(d) for d in (";", "\t", ",", "|")}
    sep = max(counts, key=counts.get) if max(counts.values()) > 0 else ","
    try:
        df = pd.read_csv(io.StringIO(text), sep=sep)
        comma = r"^\s*-?\d+,\d+\s*$"
        if any(not pd.api.types.is_numeric_dtype(df[c]) and df[c].astype(str).str.match(comma).mean() >= 0.8 for c in df.columns):
            df = pd.read_csv(io.StringIO(text), sep=sep, decimal=",")
        return df
    except Exception as exc:
        raise DataError("bad_file") from exc


def _date_column(df: pd.DataFrame, hint: str | None) -> str:
    if hint:
        if hint not in df.columns:
            raise DataError("unknown_column")
        return hint
    for c in df.columns:
        if re.search(r"date|jour|day|time|période|period", str(c), re.IGNORECASE):
            return c
    return df.columns[0]


def parse_upload(filename: str, data: bytes, date_column: str | None = None, dayfirst: bool | None = None) -> pd.DataFrame:
    """Table du fichier → DataFrame indexé par date (croissante, sans doublon), colonnes numériques seulement."""
    raw = _read_table(filename, data)
    if raw.shape[1] < 2 or len(raw) == 0:
        raise DataError("too_few_columns")
    dc = _date_column(raw, date_column)
    col = raw[dc].astype(str).str.strip()
    if dayfirst is None:
        dayfirst = bool(col.str.match(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}").mean() > 0.8)
    dates = pd.to_datetime(col, errors="coerce", dayfirst=dayfirst, format="mixed")
    frame = raw.drop(columns=[dc]).copy()
    frame.index = pd.DatetimeIndex(dates)
    dropped = []
    keep = {}
    for c in frame.columns:
        num = pd.to_numeric(frame[c], errors="coerce")
        if num.notna().mean() >= 0.8:
            keep[str(c).strip()[:60]] = num
        else:
            dropped.append(str(c))
    out = pd.DataFrame(keep, index=frame.index)
    out.attrs.update({"date_column": dc, "dayfirst": dayfirst, "dropped": dropped, "n_raw_rows": len(raw), "bad_dates": int(dates.isna().sum())})
    out = out[out.index.notna()]
    out.attrs["duplicates"] = int(out.index.duplicated().sum())
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.iloc[:, :MAX_IMPORT_COLUMNS]


def preview_import(frame: pd.DataFrame) -> dict:
    """Ce que le fichier contient et ce qui cloche (dates illisibles, doublons, trous, prix figés, variations aberrantes), avant tout enregistrement."""
    a = frame.attrs
    issues = []
    for c in frame.columns:
        s = frame[c].rename(c)
        for fn in (quality.check_frozen_prices, quality.check_quote_gaps, quality.check_aberrant_returns):
            iss = fn(s)
            if iss is not None:
                issues.append(iss.to_dict())
    ok = len(frame) >= MIN_IMPORT_ROWS and frame.shape[1] >= 1
    sample = frame.tail(5)
    idx = sc.thin_indices(len(frame), 200)
    return sc.jsonable({
        "ok": ok, "rows": len(frame), "columns": [str(c) for c in frame.columns], "date_column": a.get("date_column"), "dayfirst": a.get("dayfirst"),
        "date_min": str(frame.index[0].date()) if len(frame) else None, "date_max": str(frame.index[-1].date()) if len(frame) else None,
        "bad_dates": a.get("bad_dates", 0), "duplicates": a.get("duplicates", 0), "dropped_columns": a.get("dropped", []), "n_raw_rows": a.get("n_raw_rows"),
        "min_rows": MIN_IMPORT_ROWS, "issues": issues, "head": [{"date": str(d.date()), **{str(c): v for c, v in r.items()}} for d, r in sample.iterrows()],
        "spark": {str(c): [None if not np.isfinite(frame[c].iloc[i]) else float(frame[c].iloc[i]) for i in idx] for c in list(frame.columns)[:6]},
        "spark_dates": [str(frame.index[i].date()) for i in idx]})


def import_key(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME.match(name):
        raise DataError("bad_name")
    return USER_PREFIX + name


def commit_import(store, name: str, frame: pd.DataFrame, filename: str) -> dict:
    """Enregistre le fichier sous `user_<nom>` dans le data lake (nouvelle clé, jamais une clé du pipeline)."""
    key = import_key(name)
    if len(frame) < MIN_IMPORT_ROWS or frame.shape[1] < 1:
        raise DataError("too_short")
    clean = frame.copy()
    clean.attrs = {}
    snapshot_id = store.save(key, clean, meta={"source": "user_import", "filename": (filename or "")[:120], "pit_version": "user-supplied"})
    return {"key": key, "snapshot_id": snapshot_id, "rows": len(frame), "columns": [str(c) for c in frame.columns]}


def decode_payload(body: dict) -> tuple[str, bytes]:
    """Corps JSON `{filename, csv}` (texte) ou `{filename, b64}` (binaire, pour Excel) → (nom, octets)."""
    filename = str(body.get("filename") or "import.csv")[:120]
    if isinstance(body.get("csv"), str):
        return filename, body["csv"].encode("utf-8")
    if isinstance(body.get("b64"), str):
        try:
            return filename, base64.b64decode(body["b64"], validate=False)
        except ValueError as exc:
            raise DataError("bad_file") from exc
    raise DataError("no_file")
