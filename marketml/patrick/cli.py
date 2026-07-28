"""CLI `patrick` — `ingest` (peuple/rafraîchit le data lake local) et `run`
(pipeline complet bout-en-bout : features -> walk-forward -> sélection -> grille
-> Optuna -> meilleur modèle exporté)."""
from __future__ import annotations

import typer

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb
from patrick.tracking import report as report_module
from patrick import worker as worker_module

app = typer.Typer(help="PATRICK — pipeline ML/DL multi-actifs autonome.")


@app.command(name="ingest")
def ingest_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force: bool = typer.Option(False, "--force", help="Retélécharge même si en cache"),
) -> None:
    cfg = RunConfig.from_yaml(config)
    store = DataStore()
    df = ingest(cfg.objective, cfg.universe, store, force=force)
    typer.echo(f"Ingestion terminée : {df.shape[0]} lignes x {df.shape[1]} colonnes.")


@app.command(name="run")
def run_cmd(
    config: str = typer.Option(..., "--config", help="Chemin du YAML de run"),
    force_ingest: bool = typer.Option(False, "--force-ingest",
                                       help="Retélécharge les données même si en cache"),
) -> None:
    cfg = RunConfig.from_yaml(config)
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
    """Relance un run à partir de sa config persistée en base (Phase 3.2) :
    utile après une interruption (worker tué, machine redémarrée en plein
    tuning). Le scan de grille (avant Optuna) est toujours rejoué en entier —
    pas de checkpointing à ce niveau, hors scope Phase 3 — mais les essais
    Optuna déjà terminés pour chaque config sont repris via l'étude
    persistante sqlite (`<output_dir>/optuna.db`, `load_if_exists=True`)
    plutôt que refaits depuis zéro."""
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
) -> None:
    """Export HTML d'un run (Phase 3.3) : config, essais, métriques, baselines,
    validité statistique (holdout/DM/PBO si le run vient de l'interface web),
    contexte de reproductibilité — lu uniquement depuis `patrick.db`, sans
    dépendre des artefacts CSV/joblib du run."""
    try:
        path = report_module.save_report(run_id, output_path=output)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(f"Rapport généré : {path}")


@app.command(name="worker")
def worker_cmd(
    idle_timeout: float = typer.Option(
        600.0, "--idle-timeout", help="Arrêt automatique après N secondes sans job en attente"),
    poll_interval: float = typer.Option(
        1.0, "--poll-interval", help="Intervalle de sondage de la file (secondes)"),
) -> None:
    """Worker de la file de jobs (Phase 3.1) : process séparé qui exécute les
    runs soumis depuis l'interface web. Normalement lancé automatiquement par
    le serveur web (`ensure_worker_running`, cf. `webapp/run_manager.py`) —
    cette commande sert au lancement manuel/debug, ou en tant que service
    dédié si on préfère ne pas dépendre de l'auto-spawn."""
    worker_module.run_worker_loop(poll_interval=poll_interval, idle_timeout=idle_timeout)


@app.command(name="serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Adresse d'écoute"),
    port: int = typer.Option(8000, "--port", help="Port d'écoute"),
    reload: bool = typer.Option(False, "--reload", help="Recharge à chaud (dev)"),
) -> None:
    """Lance l'interface web (formulaire de config + suivi de run + leaderboard),
    en remplacement de l'édition manuelle du YAML. Nécessite l'extra `web`
    (`pip install -e ".[web]"`)."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Dépendances web manquantes. Installe-les avec : pip install -e \".[web]\"")
        raise typer.Exit(code=1)
    typer.echo(f"patrick web sur http://{host}:{port}")
    uvicorn.run("patrick.webapp.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
