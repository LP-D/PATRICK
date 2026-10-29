"""`patrick storage ...` : entretien du stockage (ADR 0009). Toutes les commandes qui suppriment ou réécrivent en masse refusent de tourner
avec un worker vivant : une suppression en masse tient le verrou d'écriture et a déjà tué deux runs (incident du 27/09)."""
from __future__ import annotations

import shutil
from pathlib import Path

import typer

from patrick import cache_eviction, paths
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.tracking import prediction_archive as archive

storage_app = typer.Typer(help="Stockage : archivage des prédictions du scan, index, statistiques, caches. Jamais avec un worker vivant.")


def _db_files(path: str) -> int:
    p = Path(path)
    return sum(f.stat().st_size for f in (p, Path(f"{path}-wal"), Path(f"{path}-shm")) if f.exists())


def _gb(n: float) -> str:
    return f"{n / 1e9:,.2f} Go".replace(",", " ").replace(".", ",")


def _n(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _connect_idle(*, force: bool = False):
    """Connexion pour un entretien en masse : refuse si un worker est vivant ou si un job tourne."""
    conn = trackdb.connect(trackdb.default_db_path())
    busy = jobs_db.worker_is_alive(conn) or conn.execute("SELECT 1 FROM job WHERE status = 'running' LIMIT 1").fetchone()
    if busy and not force:
        conn.close()
        typer.echo("Un worker est vivant ou un job tourne : arrête-le (et `patrick serve`) avant cet entretien de la base.", err=True)
        raise typer.Exit(code=2)
    return conn


@storage_app.command(name="report")
def report_cmd() -> None:
    """Ce qui pèse : fichier de la base, lignes de prédiction par échantillon, caches, archive, cache de variables."""
    db = trackdb.default_db_path()
    conn = trackdb.connect(db)
    try:
        typer.echo(f"base : {_gb(_db_files(db))} ({db})")
        for split, n in conn.execute("SELECT split, COUNT(*) FROM prediction GROUP BY split ORDER BY 2 DESC"):
            typer.echo(f"  prédictions {split:<8} {_n(n):>14}")
        for table in ("vol_model_cache", "shap_selection_cache", "fold_metric", "trial"):
            typer.echo(f"  {table:<26} {_n(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]):>14} lignes")
        n_text = conn.execute("SELECT COUNT(*) FROM vol_model_cache WHERE typeof(result_json) = 'text'").fetchone()[0]
        typer.echo(f"  vol_model_cache en clair (à compresser) : {_n(n_text)}")
        index_sql = "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'prediction'"
        typer.echo("  index de prédiction : " + ", ".join(r[0] for r in conn.execute(index_sql)))
    finally:
        conn.close()
    files = cache_eviction.evict_feature_cache(root=paths.feature_cache_dir(), dry_run=True)
    typer.echo(f"cache de variables : {files['files']} fichiers, {_gb(files['bytes'])} (plafond {_gb(files['cap'])})")
    arch = archive.archive_root()
    size = sum(f.stat().st_size for f in arch.glob("*.parquet")) if arch.is_dir() else 0
    typer.echo(f"archive des prédictions : {_gb(size)} ({arch})")


@storage_app.command(name="archive-predictions")
def archive_predictions_cmd(
    run: list[str] = typer.Option(None, "--run", help="Seulement ce run (répétable) ; sans option : tous les runs terminés"),  # noqa: B008
    top_k: int = typer.Option(archive.DEFAULT_TOP_K, "--top-k", help="Essais de tête gardés en base en plus du meilleur"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compte seulement, ne modifie rien"),
    restore: list[str] = typer.Option(None, "--restore", help="Remet en base l'archive de ce run (répétable)"),  # noqa: B008
) -> None:
    """Archive en Parquet puis retire de la base les prédictions de scan des essais hors tête (le meilleur et le top-K restent)."""
    conn = _connect_idle()
    try:
        if restore:
            for run_id in restore:
                typer.echo(f"{run_id} : {_n(archive.restore_run(conn, run_id))} lignes remises en base")
            return
        run_ids = list(run) if run else archive.finished_run_ids(conn)
        totals = {"rows": 0, "deleted": 0, "bytes": 0}

        def show(result: dict) -> None:
            for key in totals:
                totals[key] += result[key]
            if result["rows"]:
                suffix = "à archiver" if dry_run else f"-> {_gb(result['bytes'])}"
                typer.echo(f"{result['run_id']} : {_n(result['rows'])} lignes de {result['trials']} essais {suffix}")

        archive.archive_runs(conn, run_ids, top_k=top_k, dry_run=dry_run, progress=show)
        verb = "à archiver" if dry_run else "archivées"
        typer.echo(f"{len(run_ids)} runs examinés : {_n(totals['rows'])} lignes {verb}, {_n(totals['deleted'])} supprimées de la base, "
                   f"{_gb(totals['bytes'])} d'archive. L'espace libéré n'est rendu au disque que par `patrick storage vacuum`.")
    finally:
        conn.close()


@storage_app.command(name="reindex")
def reindex_cmd() -> None:
    """Supprime `idx_pred_path`, remplace `idx_pred_split` par un index partiel sur les prédictions `live`. À lancer APRÈS l'archivage."""
    conn = _connect_idle()
    try:
        for line in archive.reindex_predictions(conn):
            typer.echo(line)
    finally:
        conn.close()


@storage_app.command(name="analyze")
def analyze_cmd(limit: int = typer.Option(1000, "--limit", help="Lignes examinées par index (PRAGMA analysis_limit)")) -> None:
    """Statistiques du planificateur SQLite (`sqlite_stat1`, absent jusqu'ici) : ANALYZE borné, puis `PRAGMA optimize`."""
    conn = _connect_idle()
    try:
        archive.optimize_planner(conn, limit)
        conn.execute("PRAGMA optimize")
        typer.echo(f"sqlite_stat1 : {conn.execute('SELECT COUNT(*) FROM sqlite_stat1').fetchone()[0]} lignes")
    finally:
        conn.close()


@storage_app.command(name="compress-caches")
def compress_caches_cmd(limit: int = typer.Option(0, "--limit", help="Nombre maximal d'entrées à compresser (0 : toutes)")) -> None:
    """Compresse (zlib, sans perte) les entrées en clair de `vol_model_cache` (~26 Go sur 31 : environ 2,3 fois plus petit)."""
    conn = _connect_idle()
    try:
        def show(done: int, saved: int) -> None:
            if done % 5000 < 500:
                typer.echo(f"  {_n(done)} entrées, {_gb(saved)} gagnés")

        result = cache_eviction.recompress_vol_cache(conn, limit_rows=limit or None, progress=show)
        typer.echo(f"{_n(result['recompressed'])} entrées compressées, {_gb(result['bytes_saved'])} gagnés.")
    finally:
        conn.close()


@storage_app.command(name="evict")
def evict_cmd(
    feature_cache_gb: float = typer.Option(None, "--feature-cache-gb", help="Plafond du cache de variables (défaut : réglage ou 150 Go)"),
    db_days: int = typer.Option(0, "--db-days", help="Supprime les entrées de cache de la base plus vieilles que N jours (0 : aucune)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compte seulement"),
) -> None:
    """Éviction : cache de variables (les moins récemment lus d'abord) et, si demandé, entrées anciennes des caches de la base."""
    cap = None if feature_cache_gb is None else int(feature_cache_gb * 1e9)
    result = cache_eviction.evict_feature_cache(cap, dry_run=dry_run)
    typer.echo(f"cache de variables : {_gb(result['bytes'])} -> retire {result['removed_files']} fichiers ({_gb(result['removed_bytes'])}), "
               f"plafond {_gb(result['cap'])}")
    if db_days:
        conn = _connect_idle()
        try:
            for table, n in cache_eviction.prune_db_caches(conn, db_days, dry_run=dry_run).items():
                typer.echo(f"{table} : {_n(n)} entrées de plus de {db_days} jours")
        finally:
            conn.close()


@storage_app.command(name="vacuum")
def vacuum_cmd(yes: bool = typer.Option(False, "--yes", help="Confirme (réécrit tout le fichier ; arrêter aussi `patrick serve`)")) -> None:
    """Rend l'espace libéré au disque (VACUUM). Réécrit toute la base : demande autant d'espace libre que son poids."""
    db = trackdb.default_db_path()
    size = _db_files(db)
    free = shutil.disk_usage(Path(db).parent).free
    if free < size * 1.1:
        typer.echo(f"Espace libre insuffisant : {_gb(free)} pour une base de {_gb(size)} (il en faut {_gb(size * 1.1)}).", err=True)
        raise typer.Exit(code=1)
    if not yes:
        typer.echo(f"VACUUM réécrit {_gb(size)} et bloque la base le temps qu'il dure. Relance avec --yes (worker et `patrick serve` arrêtés).")
        raise typer.Exit(code=0)
    conn = _connect_idle()
    try:
        conn.execute("VACUUM")
        # En mode WAL, VACUUM écrit d'abord la nouvelle base dans le journal : sans cette troncature, la taille lue juste après
        # compte encore le journal (44 Go affichés le 29/10 pour une base qui n'en faisait plus que 13).
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    typer.echo(f"base après VACUUM : {_gb(_db_files(db))} (avant : {_gb(size)})")
