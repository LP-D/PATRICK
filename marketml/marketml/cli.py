"""CLI `marketml` — `ingest` (peuple/rafraîchit le data lake local) et `run`
(pipeline complet bout-en-bout : features -> walk-forward -> sélection -> grille
-> Optuna -> meilleur modèle exporté)."""
from __future__ import annotations

import typer

from marketml.config.schema import RunConfig
from marketml.data.ingest import ingest
from marketml.data.store import DataStore
from marketml.pipeline.engine import run_pipeline

app = typer.Typer(help="MarketML — pipeline ML/DL multi-actifs autonome.")


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


if __name__ == "__main__":
    app()
