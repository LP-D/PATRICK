# PATRICK

Multi-asset ML/DL walk-forward pipeline: ingest, engineer features, select
via SHAP, grid-search sampler×algo, tune with Optuna, validate against
leakage/overfitting, and track everything in SQLite — configurable per
target via YAML, currently exercised on two targets (VIX, AAPL).

## Current status

**Universe covered: `^VIX` and `AAPL` only** (`configs/examples/vix_direction.yaml`,
`configs/examples/aapl_direction.yaml`). There is no bulk-launch mechanism —
`patrick run` trains one target per invocation, one YAML file per target.
Scaling to a larger universe is a deliberate next step, not yet built (see
Known limitations).

## Installation

```bash
cd patrick
pip install -e .
```

## Commands

Verified against `patrick <command> --help` on the current codebase.

### `patrick ingest`
Downloads and caches raw data (Yahoo Finance tickers + FRED series) for a
config's universe. Cached locally (`~/.patrick/data`) and reused by default.

```bash
patrick ingest --config configs/examples/vix_direction.yaml
patrick ingest --config configs/examples/vix_direction.yaml --force   # re-download
```

### `patrick run`
Full pipeline: ingestion → feature engineering → walk-forward CV → grid
search (sampler × N features × algo) → Optuna tuning → terminal holdout →
best-model export. Config is a single YAML, one target per file.

```bash
patrick run --config configs/examples/vix_direction.yaml
patrick run --config configs/examples/vix_direction.yaml --force-ingest
patrick run --config configs/examples/vix_direction.yaml --name my_custom_run
```

### `patrick resume --run-id <id>`
Resumes an interrupted run from its config persisted in `run` (SQLite). The
grid scan is always replayed in full; Optuna trials already completed for
each config are picked up from the persisted study (`<output_dir>/optuna.db`)
instead of restarting.

### `patrick report --run-id <id>`
Exports a self-contained HTML report for a run (config, trials, metrics,
baselines, holdout/DM/PBO, FDR correction across targets) read entirely from
`patrick.db` — no dependency on the run's CSV/joblib artifacts.

```bash
patrick report --run-id <run_id>
patrick report --run-id <run_id> --fdr-alpha 0.05
```

### `patrick predict --run-id <id> [--live]`
Scores the already-exported model on today's data without retraining or
re-selecting features. `--live` writes the day's prediction (`split='live'`)
before the outcome is known, and backfills `y_true` for past live
predictions whose horizon has since elapsed.

```bash
# Cron example (weekdays 22:00, after US close)
0 22 * * 1-5 cd /path/to/patrick && patrick predict --run-id <id> --live
```

### `patrick worker`
Job-queue worker (separate process) that executes runs submitted from the
web interface. Auto-spawned by `patrick serve`; run manually for debugging
or as a standalone service.

### `patrick serve`
Launches the web interface.

```bash
patrick serve                              # http://127.0.0.1:8000
patrick serve --host 0.0.0.0 --port 9000
patrick serve --reload                     # dev, hot reload
```

Pages (nav: Synthèse · Lancer · Historique · Univers · Simulateur · Phase 9):

- `/` — synthesis dashboard: coverage, per-target DM/BH quality, latest
  prediction, winning-model metrics by direction, recent-run history. No page
  cache, recomputed on every load from the database.
- `/launch` — the config form (target/horizons/features/validation/models),
  run tracking, launch queue. Was on `/` before the synthesis dashboard
  replaced it there.
- `/runs`, `/runs/{id}` — run history browser and detail page.
- `/universe` — configured target universe crossed with run history.
- `/targets/{ticker}` — aggregated run history for one target.
- `/simulate` — position-sizing/backtest simulator on a trained model.
- `/phase9` — decision journal + named snapshots only (manual review audit
  trail persisted in SQLite). Signal quality and regime classification, shown
  here in an earlier iteration, moved to `/` (regime classification is not
  wired to any production path — see `KNOWN_ISSUES.md`).

### `patrick audit degradation`
Diagnostic tool — measures the real impact of the Phase 0 leakage fixes
(purge/embargo, as-of alignment, FRED vintages) by comparing 4 stacked
configurations on the same targets/seed. Requires network access and
`FRED_API_KEY`; never run in CI/sandbox.

```bash
export FRED_API_KEY=...
patrick audit degradation
patrick audit degradation --targets "^GSPC,BTC-USD" --seed 7 --output-dir runs/my_audit
```

**Windows quick launch**: `PATRICK.bat` (repo root) activates `.venv` and
runs `patrick serve` from a double-click.

## Configuration (YAML)

See `configs/examples/vix_direction.yaml` and `configs/examples/aapl_direction.yaml`.
Main sections: `objective` (target, horizons, regimes), `universe`
(feature-pool tickers/FRED series), `features` (enabled families),
`validation` (folds, purge, `holdout_months` [12-24]), `selection` (method,
N grid), `sampler`, `models` (algos, calibration, stacking), `tuning`
(Optuna).

## Architecture

See **`METHODOLOGY.md`** for the full detail of the anti-leakage/anti-overfitting
guarantees (walk-forward, purge/embargo, point-in-time vintages, multi-testing
correction, holdout, baselines), the specific bugs found and fixed along the
way, and the SQLite/Parquet persistence architecture — not duplicated here.
In short: `patrick/data` ingests and caches; `patrick/features` builds a
causal feature pool per fold; `patrick/selection` picks features (SHAP by
default); `patrick/pipeline/engine.py` runs the walk-forward grid scan and
calls into `patrick/tuning` (Optuna) and `patrick/validation` (leakage
guards, statistical validity — DM, PBO, FDR); `patrick/tracking` persists
everything to SQLite (`~/.patrick/patrick.db`) and exports Parquet snapshots;
`patrick/simulate` turns predictions into a backtested position/P&L curve;
`patrick/webapp` and `patrick/cli.py` are the two front doors to the same
`run_pipeline()`.

## Performance

Measured on a 4-core sandbox machine, synthetic-data ingestion (real
yfinance/FRED network access unavailable in that environment), single
horizon, **at the exact grid density of `configs/examples/vix_direction.yaml`**
(11 `N_features` values × 5 algos including CatBoost × 5 walk-forward folds,
Optuna `top_k=5`/`n_trials=100`/`cv_splits=3` with `MedianPruner` — pruner is
hardcoded in `tuning/optuna_runner.py`, not a config toggle, and has been
present since the project's first commit): **~16 minutes per horizon**, i.e.
roughly 1h36 extrapolated linearly to all 6 horizons of the VIX config.

This is markedly faster than a **~10-20h figure previously reported for a
full VIX run**, which could not be reproduced or traced to any log, database
row, or grid configuration different from the one measured above — the grid,
tuning parameters, and pruner were confirmed identical back to the very
first commit. The discrepancy remains unexplained (possibly a different
execution environment, real network I/O not captured by the synthetic
benchmark, or a figure that was never itself a verified measurement) —
treat the ~1h36 figure as the best available real measurement, not as a
guarantee that reproduces under all conditions, particularly with real data
ingestion.

## Known limitations

- **No bulk-launch mechanism.** `patrick run` trains one target per
  invocation. Training a larger universe currently means running the CLI
  once per target (or via the web form's multi-target queue, one job per
  target) — no `--targets all` or equivalent.
- **Universe currently limited to VIX and AAPL** — no broader coverage has
  been validated end-to-end yet.
- **Deflated Sharpe Ratio (`validation/dsr.py`)** is implemented and tested
  but **not yet called from the pipeline** — it needs a P&L curve to
  deflate, tied to the simulator (`patrick/simulate`), not wired in.
- **FRED point-in-time vintages** (`data/sources/fred_source.py`,
  `realtime_date`) are implemented and tested but **not yet wired per-fold**
  into the walk-forward engine — the persisted snapshot reflects "today's"
  data, not a per-fold vintage.
- **Real-data verification is partial.** The full pipeline has been run
  end-to-end on real yfinance/FRED data on a machine with network access at
  least once (VIX), surfacing and fixing real bugs (FRED series crossing
  zero, FRED scraping fragility). It has **not** been re-verified with real
  data since the most recent leakage/statistical-validity fixes — the
  original F1_dir≈0.610 reference is expected to move once re-validated.
- **Test suite**: `pytest` (224 tests, fast, excludes `@pytest.mark.slow`)
  during development; `pytest -m slow` (42 tests: full pipeline runs,
  worker subprocess, EGARCH, webapp smoke) before a commit/push or in CI.

## Development notes

Run `scripts/check_env_sync.sh` at the start of any agent session on this
repo, before any other git or Python command — it confirms the local
worktree's `HEAD` is a legitimate ancestor of (or in sync with) the remote,
and that `import patrick` resolves under the current worktree rather than a
stale path. This exists because an execution environment previously
restarted from a frozen snapshot without any error surfacing, silently
running work against outdated code for part of a session.
