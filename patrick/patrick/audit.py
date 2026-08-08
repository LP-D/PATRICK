"""Correction report, C7 -- `patrick audit degradation`: measures the real
impact of the phase-0 leakage fixes (purge/embargo, per-asset-class as-of
alignment, FRED/ALFRED vintages) by comparing 4 stacked configurations on
the same target universe and the same seed. Runs the REAL pipeline
(`ingest()`/`run_pipeline()`, no monkeypatching) -- therefore requires real
network access (yfinance/FRED), never available in this sandbox. Validated
here via `tests/test_audit_degradation.py` (sources monkeypatched at the
`yfinance.download`/`requests.get` level, not `ingest()` itself, so the real
`ingest()`/`_attach_snapshot_context` code still runs).

The 4 configurations are CUMULATIVE (each adds one fix on top of the
previous one), not independent -- this isolates the marginal contribution of
each fix rather than measuring 4 unordered combinations:
  - baseline_avant : no phase-0 fix (purge/embargo disabled,
    as-of alignment disabled, no vintage).
  - +purge         : + purge/embargo (Phase 0.1).
  - +vintages      : + FRED/ALFRED vintages (Phase 0.5) -- requires
    FRED_API_KEY (scrape fallback = always the current revision, a vintage
    is impossible there, see `data/sources/fred_source.py`).
  - complet        : + per-asset-class as-of alignment (Phase 0.4) --
    current production configuration.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta

from patrick.config.schema import (
    ModelsConfig,
    ObjectiveConfig,
    OutputConfig,
    RunConfig,
    SamplerConfig,
    SelectionConfig,
    TuningConfig,
    UniverseConfig,
    ValidationConfig,
)
from patrick.data.sources.fred_source import FRED_API_KEY_ENV, FRED_API_URL
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb

CONFIGURATIONS: tuple[str, ...] = ("baseline_avant", "+purge", "+vintages", "complet")

METRIC_COLUMNS: tuple[str, ...] = ("BalAcc_4cls", "MCC_4cls", "F1_dir")

# One asset per class (Phase 0 concerns the whole yfinance/FRED surface, not a
# single market) -- realistic tickers/FRED series, consistent with
# `configs/examples/*.yaml` and `webapp/forms.py::TARGET_GROUPS`.
DEFAULT_TARGETS: list[dict] = [
    {"label": "indice_us", "target_symbol": "^GSPC", "target_source": "yfinance",
     "yf_tickers": ["^VIX", "TLT"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
     "start_date": "2015-01-01"},
    {"label": "action_europe", "target_symbol": "MC.PA", "target_source": "yfinance",
     "yf_tickers": ["^FCHI", "EURUSD=X"], "fred_series": {"T10Y2Y": "T10Y2Y"},
     "start_date": "2015-01-01"},
    {"label": "paire_fx", "target_symbol": "EURUSD=X", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "GC=F"], "fred_series": {"DTWEXBGS": "DTWEXBGS"},
     "start_date": "2015-01-01"},
    {"label": "matiere_premiere", "target_symbol": "GC=F", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "DX-Y.NYB"], "fred_series": {"T10YIE": "T10YIE"},
     "start_date": "2015-01-01"},
    {"label": "crypto", "target_symbol": "BTC-USD", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "ETH-USD"], "fred_series": {"NFCI": "NFCI"},
     "start_date": "2018-01-01"},
]


def _vintage_date_for_audit() -> str:
    """Deliberately distinct from today: omitting `realtime_date` (or setting
    it to today's date) makes the FRED API return `realtime_start=
    realtime_end=today` BY DEFAULT -- indistinguishable from the no-vintage
    case. One year back makes the difference visible (logged URL, retrieved
    values) and verifiable by the user under real conditions."""
    return (date.today() - timedelta(days=365)).isoformat()


def _config_for(target: dict, configuration: str, seed: int, output_dir: str) -> RunConfig:
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"unknown configuration: {configuration!r} (expected: {CONFIGURATIONS})")
    purge_on = configuration in ("+purge", "+vintages", "complet")
    vintages_on = configuration in ("+vintages", "complet")
    session_lag_on = configuration == "complet"

    return RunConfig(
        name=f"audit_degradation_{target['label']}_{configuration.lstrip('+').replace(' ', '_')}",
        objective=ObjectiveConfig(
            target_symbol=target["target_symbol"],
            target_source=target.get("target_source", "yfinance"),
            horizons=[5],
            regimes=["GLOBAL"],
            disable_session_lag=not session_lag_on,
        ),
        universe=UniverseConfig(
            yf_tickers=target.get("yf_tickers", []),
            fred_series=target.get("fred_series", {}),
            start_date=target.get("start_date", "2015-01-01"),
            vintage_realtime_date=_vintage_date_for_audit() if vintages_on else None,
        ),
        validation=ValidationConfig(
            n_wf_folds=3, purge=purge_on, embargo_enabled=purge_on,
        ),
        selection=SelectionConfig(method="shap", n_features_grid=[8]),
        sampler=SamplerConfig(candidates=["SMOTE"]),
        models=ModelsConfig(algos=["RandomForest"]),
        # Tuning disabled: the audit compares the effect of the leakage fixes,
        # not the quality of an Optuna budget -- 4 configs x 5 targets with
        # tuning enabled would be needlessly long for the question asked here.
        tuning=TuningConfig(enabled=False),
        output=OutputConfig(dir=output_dir, seed=seed),
    )


def _masked_fred_url(series_id: str, start: str, api_key: str, realtime_date: str | None) -> str:
    masked = f"{api_key[:4]}{'*' * max(len(api_key) - 4, 4)}" if api_key else "*absent*"
    url = f"{FRED_API_URL}?series_id={series_id}&api_key={masked}&file_type=json&observation_start={start}"
    if realtime_date:
        url += f"&realtime_start={realtime_date}&realtime_end={realtime_date}"
    return url


def _last_snapshot_fred_source(db_path: str | None) -> str | None:
    """The `fred_source` of the most recent `snapshot` row -- reliable here
    because every `run_pipeline(force_ingest=True)` call inserts a fresh row
    (snapshot_id derived from content, see `data/store.py::save`), never a
    collision between two configurations that genuinely differ."""
    conn = trackdb.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fred_source FROM snapshot ORDER BY created_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _extract_row(target_label: str, configuration: str, result: dict, db_path: str | None) -> dict:
    final_best = result.get("final_best") or {}
    fred_src = _last_snapshot_fred_source(db_path)
    if fred_src is None:
        print(f"  [WARN AUDIT] snapshot.fred_source is NULL for {target_label}/{configuration} -- "
              "unexpected on a real run (correction report, C7: this field is only None if "
              "`ingest()` was monkeypatched without reproducing `_attach_snapshot_context`, never on "
              "this path). Check that no monkeypatch of `ingest()` remains.")
    row = {"target": target_label, "configuration": configuration, "fred_source": fred_src,
           "n_evaluations": len(result.get("leaderboard")) if result.get("leaderboard") is not None else 0}
    for col in METRIC_COLUMNS:
        row[col] = final_best.get(col)
    return row


def _export(rows: list[dict], output_dir: str) -> tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    fieldnames = ["target", "configuration", *METRIC_COLUMNS, "fred_source", "n_evaluations"]

    csv_path = os.path.join(output_dir, "degradation_audit.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    md_path = os.path.join(output_dir, "degradation_audit.md")
    header = "| " + " | ".join(fieldnames) + " |"
    sep = "|" + "|".join(["---"] * len(fieldnames)) + "|"
    body = "\n".join("| " + " | ".join(str(row.get(c, "")) for c in fieldnames) + " |" for row in rows)
    with open(md_path, "w") as f:
        f.write("\n".join([header, sep, body]) + "\n")

    return csv_path, md_path


def run_degradation_audit(targets: list[dict] | None = None, seed: int = 42,
                           output_dir: str = "runs/audit_degradation",
                           db_path: str | None = None, store: DataStore | None = None) -> dict:
    api_key = os.environ.get(FRED_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY not set: the \"+vintages\" configuration is meaningless without it "
            "-- the scrape fallback (public fredgraph.csv) can only return the CURRENT revision "
            "of each series, never a point-in-time ALFRED vintage (see "
            "patrick/data/sources/fred_source.py). Set the environment variable before "
            "re-running `patrick audit degradation` (free key: "
            "https://fred.stlouisfed.org/docs/api/api_key.html)."
        )

    targets = targets if targets is not None else DEFAULT_TARGETS
    store = store or DataStore()

    rows: list[dict] = []
    url_logged = False
    for target in targets:
        for configuration in CONFIGURATIONS:
            cfg = _config_for(target, configuration, seed, output_dir)
            if not url_logged and cfg.universe.fred_series:
                series_id = next(iter(cfg.universe.fred_series.values()))
                print(f"[AUDIT] FRED URL (1st series of the 1st target, key masked): "
                      f"{_masked_fred_url(series_id, cfg.universe.start_date, api_key, cfg.universe.vintage_realtime_date)}")
                url_logged = True
            print(f"[AUDIT] {target['label']} / {configuration} ...")
            # force_ingest=True: `ingest()`'s cache key does not depend on
            # `vintage_realtime_date`/`disable_session_lag` (see docstring of
            # `data/ingest.py::ingest`) -- without this, the 2nd-4th configuration
            # of the same target would silently reuse the 1st one's data.
            result = run_pipeline(cfg, store=store, force_ingest=True, db_path=db_path)
            rows.append(_extract_row(target["label"], configuration, result, db_path))

    csv_path, md_path = _export(rows, output_dir)
    print(f"[AUDIT] {len(rows)} lignes -> {csv_path} / {md_path}")
    return {"rows": rows, "csv_path": csv_path, "md_path": md_path}
