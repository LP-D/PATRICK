"""Per-series local Parquet layer: one file per raw series (a Yahoo ticker or
a FRED series), keyed by `(ticker, vintage)`.

`data/store.py::DataStore` keeps the WHOLE aligned raw frame of a run's
target (`raw_<target>`) as one immutable snapshot -- this layer splits that
same content per series so a series downloaded for one target can be read
back without reloading (or re-downloading) another target's full frame.

`vintage`: the identifier of the data version the series comes from --
`ingest()` passes the `snapshot_id` of the frame it was split from (whose
content hash already folds in the FRED ALFRED `vintage_realtime_date`, if
any, and every Yahoo revision), so two different vintages of the same
ticker never share a file. Files are immutable once written: an existing
`(ticker, vintage)` is never rewritten (same "never overwrite a snapshot"
rule as `DataStore`).
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd


def _default_series_dir() -> str:
    """Read from the environment on every call (same convention as
    `data/store.py::_default_store_dir`) -- tests isolate it via
    `PATRICK_SERIES_ROOT`."""
    return os.environ.get("PATRICK_SERIES_ROOT") or os.path.expanduser("~/.patrick/series")


def _safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(part))


class SeriesStore:
    def __init__(self, root: str | None = None):
        self.root = root or _default_series_dir()
        os.makedirs(self.root, exist_ok=True)

    def path(self, ticker: str, vintage: str) -> str:
        return os.path.join(self.root, f"ticker={_safe(ticker)}", f"vintage={_safe(vintage)}.parquet")

    def exists(self, ticker: str, vintage: str) -> bool:
        return os.path.exists(self.path(ticker, vintage))

    def save(self, ticker: str, vintage: str, series: pd.Series) -> str:
        """Atomic write (temp file in the same directory + `os.replace`).
        No-op if `(ticker, vintage)` already exists -- immutable."""
        path = self.path(ticker, vintage)
        if os.path.exists(path):
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        frame = series.rename(str(ticker)).to_frame()
        fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=os.path.dirname(path))
        os.close(fd)
        try:
            frame.to_parquet(tmp)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return path

    def load(self, ticker: str, vintage: str) -> pd.Series:
        path = self.path(ticker, vintage)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Série '{ticker}' (vintage '{vintage}') absente du cache local.")
        return pd.read_parquet(path).iloc[:, 0]

    def list_vintages(self, ticker: str) -> list[str]:
        d = os.path.join(self.root, f"ticker={_safe(ticker)}")
        if not os.path.isdir(d):
            return []
        return sorted(f[len("vintage="):-len(".parquet")] for f in os.listdir(d)
                      if f.startswith("vintage=") and f.endswith(".parquet"))

    def save_frame(self, df: pd.DataFrame, vintage: str) -> int:
        """Splits an aligned raw frame into one file per column. Returns the
        number of series newly written."""
        written = 0
        for col in df.columns:
            if not self.exists(col, vintage):
                self.save(col, vintage, df[col])
                written += 1
        return written
