"""CLI `patrick` — `ingest` (peuple/rafraîchit le data lake local) et `run`
(pipeline complet bout-en-bout : features -> walk-forward -> sélection -> grille
-> Optuna -> meilleur modèle exporté)."""
from __future__ import annotations

import typer

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline

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
