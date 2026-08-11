"""`patrick` CLI -- `ingest` (populates/refreshes the local data lake) and
`run` (full end-to-end pipeline: features -> walk-forward -> selection ->
grid -> Optuna -> exported best model).

Command `help=` strings and `typer.echo()` output stay in French, matching
the rest of the French-language product surface (see the D4 translation
scope note in `README.md`)."""
from __future__ import annotations

import typer

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb
from patrick.tracking import report as report_module
from patrick import predict as predict_module
from patrick import worker as worker_module

app = typer.Typer(help="PATRICK — pipeline ML/DL multi-actifs autonome.")
audit_app = typer.Typer(help="Diagnostics d'audit -- lecture/mesure, n'entraînent jamais un modèle de production.")
app.add_typer(audit_app, name="audit")


@app.command(name="ingest")
def ingest_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force: bool = typer.Option(False, "--force", help="Retélécharge même si en cache"),
) -> None:
    """Downloads and prepares the raw data (Phase 0): Yahoo Finance tickers
    and FRED series per the config. Data is cached locally (`~/.patrick/data`)
    and reused by default -- `--force` re-triggers the download, useful after
    a universe change or to fetch the latest prices/macro data.

    Example:

    \b
        patrick ingest --config configs/examples/vix_direction.yaml
        patrick ingest --config configs/examples/vix_direction.yaml --force
    """
    cfg = RunConfig.from_yaml(config)
    store = DataStore()
    df = ingest(cfg.objective, cfg.universe, store, force=force, data_quality=cfg.data_quality)
    typer.echo(f"Ingestion terminée : {df.shape[0]} lignes x {df.shape[1]} colonnes.")


@app.command(name="run")
def run_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force_ingest: bool = typer.Option(False, "--force-ingest",
                                       help="Retélécharge les données même si en cache"),
    name: str | None = typer.Option(None, "--name", help="Nom du run ; par défaut, déduit de la cible"),
) -> None:
    """Full end-to-end pipeline (Phase 1-4): data ingestion -> feature
    selection (SHAP) -> walk-forward cross-validation -> model grid -> Optuna
    tuning -> terminal holdout -> export of the best model. Configuration
    read from a YAML file (see `configs/examples/`). The result (leaderboard,
    best model, reproducibility context) is stored in the SQLite database and
    the Parquet cache.

    Example:

    \b
        patrick run --config configs/examples/vix_direction.yaml
        patrick run --config configs/examples/vix_direction.yaml --force-ingest
    """
    cfg = RunConfig.from_yaml(config)
    if name:
        cfg.name = name
    result = run_pipeline(cfg, force_ingest=force_ingest)
    typer.echo(f"\n[TERMINÉ] {len(result['leaderboard'])} lignes de leaderboard "
               f"en {result['elapsed_s']/60:.1f}min")
    if result["final_best"]:
        typer.echo(f"Meilleur modèle final : {result['final_best']}")
    if result["model_path"]:
        typer.echo(f"Modèle exporté : {result['model_path']}")


@app.command(name="resume")
def resume_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Identifiant du run à reprendre (table `run`)"),
) -> None:
    """Relaunches a run from its config persisted in the database (Phase 3.2):
    useful after an interruption (worker killed, machine restarted mid-tuning).
    The grid scan (before Optuna) is always replayed in full -- no
    checkpointing at that level, out of Phase 3 scope -- but Optuna trials
    already completed for each config are resumed via the persistent sqlite
    study (`<output_dir>/optuna.db`, `load_if_exists=True`) rather than redone
    from scratch."""
    conn = trackdb.connect()
    row = trackdb.get_run(conn, run_id)
    conn.close()
    if row is None:
        typer.echo(f"Run introuvable : {run_id}")
        raise typer.Exit(code=1)
    config = RunConfig.model_validate_json(row["config_json"])
    typer.echo(f"Reprise de '{config.name}' (run {run_id}, statut précédent={row['status']})...")
    result = run_pipeline(config)
    typer.echo(f"\n[TERMINÉ] {len(result['leaderboard'])} lignes de leaderboard "
               f"en {result['elapsed_s']/60:.1f}min")
    if result["final_best"]:
        typer.echo(f"Meilleur modèle final : {result['final_best']}")
    if result["model_path"]:
        typer.echo(f"Modèle exporté : {result['model_path']}")


@app.command(name="report")
def report_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Identifiant du run (table `run`)"),
    output: str = typer.Option(
        None, "--output", help="Chemin du fichier HTML (défaut : ~/.patrick/reports/<run_id>.html)"),
    fdr_alpha: float = typer.Option(
        0.10, "--fdr-alpha",
        help="Seuil FDR (Phase 6.4) pour la correction Benjamini-Hochberg entre cibles"),
) -> None:
    """HTML export of a run (Phase 3.3): config, trials, metrics, baselines,
    statistical validity (holdout/DM/PBO if the run came from the web
    interface), reproducibility context -- read solely from `patrick.db`,
    with no dependency on the run's CSV/joblib artifacts."""
    try:
        path = report_module.save_report(run_id, output_path=output, fdr_alpha=fdr_alpha)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(f"Rapport généré : {path}")


@app.command(name="predict")
def predict_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Identifiant du run (table `run`)"),
    live: bool = typer.Option(False, "--live", help="Score le modèle sur les données du jour (paper trading)"),
) -> None:
    """Production prediction (Phase 4.6), without retraining or reselecting
    anything -- loads the run's already-exported model. `--live`: writes
    today's prediction to `prediction` (split='live') BEFORE knowing the
    outcome, and along the way backfills past live predictions whose horizon
    has now elapsed.

    Example cron (every weekday at 22:00, after US market close):

    \b
        0 22 * * 1-5 cd /chemin/vers/patrick && patrick predict --run-id <id> --live
    """
    if not live:
        typer.echo("Seul --live est supporté pour l'instant (patrick predict --run-id <id> --live).")
        raise typer.Exit(code=1)
    result = predict_module.predict_live(run_id)
    typer.echo(f"[LIVE] {result['ts']} -> classe prédite={result['y_pred']} "
               f"(confiance={result['y_proba']:.3f}) | {result['n_outcomes_updated']} résultat(s) live mis à jour")


@app.command(name="worker")
def worker_cmd(
    idle_timeout: float = typer.Option(
        600.0, "--idle-timeout", help="Arrêt automatique après N secondes sans job en attente"),
    poll_interval: float = typer.Option(
        1.0, "--poll-interval", help="Intervalle de sondage de la file (secondes)"),
) -> None:
    """Job queue worker (Phase 3.1): separate process that executes runs
    submitted from the web interface. Normally launched automatically by the
    web server (`ensure_worker_running`, see `webapp/run_manager.py`) -- this
    command is for manual launch/debugging, or as a dedicated service if you
    prefer not to rely on auto-spawn."""
    worker_module.run_worker_loop(poll_interval=poll_interval, idle_timeout=idle_timeout)


@app.command(name="serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Adresse d'écoute"),
    port: int = typer.Option(8000, "--port", help="Port d'écoute"),
    reload: bool = typer.Option(False, "--reload", help="Recharge à chaud (dev)"),
) -> None:
    """Launches the web interface (synthesis dashboard on `/`, config form +
    run tracking + leaderboard on `/launch`), replacing manual YAML editing.
    Requires the `web` extra (`pip install -e ".[web]"`)."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Dépendances web manquantes. Installe-les avec : pip install -e \".[web]\"")
        raise typer.Exit(code=1)
    typer.echo(f"patrick web sur http://{host}:{port}")
    uvicorn.run("patrick.webapp.app:app", host=host, port=port, reload=reload)


@audit_app.command(name="degradation")
def audit_degradation_cmd(
    targets: str = typer.Option(
        None, "--targets",
        help="Symboles cibles séparés par des virgules (défaut : 1 indice US, 1 action "
             "europe, 1 paire FX, 1 matière première, 1 crypto -- cf. patrick/audit.py::DEFAULT_TARGETS)"),
    seed: int = typer.Option(42, "--seed", help="Seed unique, identique aux 4 configurations"),
    output_dir: str = typer.Option(
        "runs/audit_degradation", "--output-dir", help="Dossier de sortie des runs + du CSV/markdown"),
) -> None:
    """Correction report, C7 -- measures the real impact of the Phase 0 leak
    fixes (purge/embargo, as-of alignment, FRED vintages) by comparing 4
    stacked configurations (baseline_before -> +purge -> +vintages -> full)
    on the same target/seed universe. Runs the real pipeline (yfinance/FRED
    network access required); fails explicitly if FRED_API_KEY is not set
    (the +vintages configuration is meaningless without it)."""
    from patrick import audit as audit_module

    target_list = None
    if targets:
        symbols = [s.strip() for s in targets.split(",") if s.strip()]
        by_symbol = {t["target_symbol"]: t for t in audit_module.DEFAULT_TARGETS}
        target_list = [
            by_symbol.get(sym, {"label": sym, "target_symbol": sym, "target_source": "yfinance",
                                 "yf_tickers": [], "fred_series": {}, "start_date": "2015-01-01"})
            for sym in symbols
        ]

    try:
        result = audit_module.run_degradation_audit(targets=target_list, seed=seed, output_dir=output_dir)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    typer.echo(f"\n[TERMINÉ] {len(result['rows'])} lignes -- "
               f"CSV : {result['csv_path']} -- markdown : {result['md_path']}")


if __name__ == "__main__":
    app()
