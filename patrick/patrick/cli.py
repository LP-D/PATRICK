"""`patrick` CLI -- `ingest` (populates/refreshes the local data lake) and
`run` (full end-to-end pipeline: features -> walk-forward -> selection ->
grid -> Optuna -> exported best model).

Command `help=` strings and `typer.echo()` output stay in French, matching
the rest of the French-language product surface (see the D4 translation
scope note in `README.md`)."""
from __future__ import annotations

import typer

from patrick import predict as predict_module
from patrick import worker as worker_module
from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb
from patrick.tracking import report as report_module

app = typer.Typer(help="PATRICK — pipeline ML/DL multi-actifs autonome.")
audit_app = typer.Typer(help="Diagnostics d'audit -- lecture/mesure, n'entraînent jamais un modèle de production.")
app.add_typer(audit_app, name="audit")
research_app = typer.Typer(help="Études de recherche -- lecture/mesure, n'entraînent aucun modèle.")
app.add_typer(research_app, name="research")

MIN_HISTORY_YEARS_OPTION = typer.Option(
    None, "--min-history-years",
    help=(f"Anciennete minimale d'historique exigee a l'ingestion (annees), "
          f"remplace la valeur du YAML si fournie -- entier entre "
          f"{D.MIN_HISTORY_YEARS_BOUNDS['min_allowed']} et {D.MIN_HISTORY_YEARS_BOUNDS['max_allowed']}."),
)


def _apply_min_history_years_override(cfg: RunConfig, min_history_years: int | None) -> None:
    """CHANTIER (feature/equity-asset-class, suite) -- meme regle de bornes
    que `webapp/forms.py::build_config_dict` (validation sur la valeur
    SOUMISE uniquement, jamais sur le defaut YAML/`RunConfig`)."""
    if min_history_years is None:
        return
    lo = D.MIN_HISTORY_YEARS_BOUNDS["min_allowed"]
    hi = D.MIN_HISTORY_YEARS_BOUNDS["max_allowed"]
    if not (lo <= min_history_years <= hi):
        typer.echo(f"--min-history-years doit être un entier entre {lo} et {hi} (reçu {min_history_years}).")
        raise typer.Exit(code=1)
    cfg.data_quality.min_history_years = min_history_years


def _reject_unsupported_fundamentals_features(cfg: RunConfig) -> None:
    """CHANTIER (feature/equity-asset-class, suite) -- validation a la
    SOUMISSION (avant ingestion) : yfinance n'offre aucune source
    point-in-time pour les fondamentaux (voir `features/
    equity_fundamentals.py`) -- `enable_fundamentals_features: true` n'a
    aucun champ formulaire ni option CLI positive (seule voie de soumission
    reelle : YAML/`--config`), rejete ici plutot que de laisser le run
    echouer en profondeur, en plein milieu du pipeline, une fois deja
    lance (garde complementaire, pas redondant : celui du wrapper reste le
    filet de securite pour toute construction directe de `RunConfig`)."""
    if cfg.features.enable_fundamentals_features:
        typer.echo(
            "features.enable_fundamentals_features=true refuse : yfinance ne fournit aucune "
            "source point-in-time pour les fondamentaux (etat actuel seulement, potentiellement "
            "retraite) -- les injecter comme feature introduirait un biais look-ahead deja "
            "demontre empiriquement. Voir features/equity_fundamentals.py."
        )
        raise typer.Exit(code=1)


@app.command(name="ingest")
def ingest_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force: bool = typer.Option(False, "--force", help="Retélécharge même si en cache"),
    min_history_years: int | None = MIN_HISTORY_YEARS_OPTION,
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
    _reject_unsupported_fundamentals_features(cfg)
    _apply_min_history_years_override(cfg, min_history_years)
    store = DataStore()
    df = ingest(cfg.objective, cfg.universe, store, force=force, data_quality=cfg.data_quality)
    typer.echo(f"Ingestion terminée : {df.shape[0]} lignes x {df.shape[1]} colonnes.")


def _echo_exported_models(result: dict) -> None:
    """Fix report [per-horizon export]: `run_pipeline` now exports one model
    per horizon with a valid result (`result["model_paths"]`), not just
    `result["model_path"]` (the single global winner, kept for backward
    compatibility -- e.g. a run with only one horizon still gets exactly one
    line here, unchanged from before this fix)."""
    model_paths = result.get("model_paths") or {}
    if len(model_paths) > 1:
        for horizon in sorted(model_paths):
            typer.echo(f"Modèle exporté (h={horizon}j) : {model_paths[horizon]}")
    elif result.get("model_path"):
        typer.echo(f"Modèle exporté : {result['model_path']}")


@app.command(name="run")
def run_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force_ingest: bool = typer.Option(False, "--force-ingest",
                                       help="Retélécharge les données même si en cache"),
    name: str | None = typer.Option(None, "--name", help="Nom du run ; par défaut, déduit de la cible"),
    min_history_years: int | None = MIN_HISTORY_YEARS_OPTION,
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
    _apply_min_history_years_override(cfg, min_history_years)
    _reject_unsupported_fundamentals_features(cfg)
    result = run_pipeline(cfg, force_ingest=force_ingest)
    typer.echo(f"\n[TERMINÉ] {len(result['leaderboard'])} lignes de leaderboard "
               f"en {result['elapsed_s']/60:.1f}min")
    if result["final_best"]:
        typer.echo(f"Meilleur modèle final : {result['final_best']}")
    _echo_exported_models(result)


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
    _echo_exported_models(result)


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


@audit_app.command(name="speed")
def audit_speed_cmd(
    db: str = typer.Option(None, "--db", help="Base patrick.db (défaut : PATRICK_DB_PATH / ~/.patrick/patrick.db)"),
    target: str = typer.Option(None, "--target",
                               help="Cible dont le snapshot brut le plus récent sert à mesurer le coût par famille"),
    n_folds: int = typer.Option(5, "--n-folds", help="Folds walk-forward (les familles paramétriques sont refittées par fold)"),
    output: str = typer.Option(None, "--output", help="Fichier markdown de sortie (défaut : stdout)"),
) -> None:
    """Les composants coûteux sont-ils réellement utilisés ? Part du pool,
    part des features retenues par les modèles exportés, fréquences de
    sélection walk-forward et coût mesuré, par famille de features. Lecture
    seule : n'entraîne ni n'exporte aucun modèle."""
    from patrick import audit_speed
    from patrick.config.schema import RunConfig
    from patrick.data.store import DataStore
    from patrick.pipeline.engine import build_base_feature_pool, build_parametric_pool
    from patrick.tracking import db as trackdb

    conn = trackdb.connect(db)
    try:
        usage = audit_speed.usage_from_db(conn)
        if target:
            raw = DataStore().load(f"raw_{target}")
            row = conn.execute("SELECT config_json FROM run WHERE target = ? ORDER BY started_at DESC LIMIT 1",
                               (target,)).fetchone()
            config = RunConfig.model_validate_json(row[0]) if row else RunConfig.model_validate(
                {"objective": {"target_symbol": target}})
            from patrick.data.sources.yfinance_source import clean_symbol
            pool = build_base_feature_pool(raw, config, clean_symbol(target)).columns.union(
                build_parametric_pool(raw, config, fit_end_idx=None).columns)
            audit_speed.add_pool(usage, pool)
            costs = audit_speed.measure_family_costs(raw, fit_end_idx=int(len(raw) * 0.6))
            for fam, seconds in costs.items():
                usage.setdefault(fam, audit_speed.FamilyUsage(fam)).cost_s = seconds
    finally:
        conn.close()
    report = audit_speed.render_markdown(usage, n_folds=n_folds)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        typer.echo(f"Rapport écrit : {output}")
    else:
        typer.echo(report)


@audit_app.command(name="tickers")
def audit_tickers_cmd(
    scope: str = typer.Option("all", "--scope", help="default | equities | extended | all"),
    output: str = typer.Option(None, "--output", help="Fichier markdown de sortie (défaut : stdout)"),
    workers: int = typer.Option(8, "--workers", help="Requêtes Yahoo en parallèle"),
) -> None:
    """Vérifie en direct que Yahoo sert chaque ticker yfinance de l'univers :
    historique non vide, frais (<= 7 séances), profond (>= 750 séances).
    Lecture seule ; ne modifie aucune configuration."""
    from patrick.config import defaults as D
    from patrick.config import equity_universe as EQ
    from patrick.config import universe_extension as UX
    from patrick.data import ticker_check

    pools = {
        "default": [s for s, _, src in D.DEFAULT_TARGET_CHOICES if src == "yfinance"],
        "equities": list(EQ.EQUITY_UNIVERSE),
        "extended": [s for s, _, _ in UX.extended_target_choices()],
    }
    if scope not in (*pools, "all"):
        raise typer.BadParameter(f"scope inconnu : {scope}")
    symbols = [s for k, v in pools.items() if scope in (k, "all") for s in v]
    report = ticker_check.render_markdown(ticker_check.check_many(symbols, workers=workers))
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        typer.echo(f"Rapport écrit : {output}")
    else:
        typer.echo(report)


@research_app.command(name="event-study")
def research_event_study_cmd(
    ticker: str = typer.Option(..., "--ticker", help="Actif étudié (ticker yfinance)"),
    events: str = typer.Option(None, "--events", help="CSV : published_at[,label][,group]"),
    earnings: bool = typer.Option(False, "--earnings", help="Publications de résultats Yahoo (groupes beat/miss)"),
    benchmark: str = typer.Option("^GSPC", "--benchmark", help="Indice du modèle de marché"),
    model: str = typer.Option("market", "--model", help="market | market_adjusted | constant_mean"),
    pre: int = typer.Option(-5, "--pre", help="Début de la fenêtre d'événement (séances)"),
    post: int = typer.Option(20, "--post", help="Fin de la fenêtre d'événement (séances)"),
    start: str = typer.Option("2005-01-01", "--start", help="Début de l'historique de prix"),
    title: str = typer.Option(None, "--title", help="Titre du rapport"),
    output: str = typer.Option(None, "--output", help="Fichier markdown de sortie (défaut : stdout)"),
) -> None:
    """Étude d'événements (MacKinlay) : rendements anormaux autour de
    publications horodatées, J0 = première séance dont la clôture suit
    strictement la publication."""
    from patrick.data.sources.yfinance_source import download_one
    from patrick.research import event_sources
    from patrick.research import event_study as es

    if bool(events) == earnings:
        raise typer.BadParameter("indiquer exactement une source : --events FICHIER ou --earnings")
    ev = event_sources.yahoo_earnings(ticker) if earnings else event_sources.read_events_csv(events)
    prices = download_one(ticker, start)
    bench = download_one(benchmark, start) if model != "constant_mean" else None
    if prices is None or (model != "constant_mean" and bench is None):
        typer.echo("Historique de prix indisponible.")
        raise typer.Exit(code=1)
    kwargs = {"benchmark": bench, "model": model, "event_window": (pre, post)}
    groups = {"tous": es.run_event_study(prices, list(ev["published_at"]), labels=list(ev["label"]), **kwargs)}
    for name, sub in ev.groupby("group", sort=True):
        if ev["group"].nunique() > 1:
            groups[str(name)] = es.run_event_study(prices, list(sub["published_at"]), labels=list(sub["label"]),
                                                   **kwargs)
    report = es.render_markdown(groups, title or f"Étude d'événements -- {ticker} vs {benchmark}")
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        typer.echo(f"Rapport écrit : {output}")
    else:
        typer.echo(report)


if __name__ == "__main__":
    app()
