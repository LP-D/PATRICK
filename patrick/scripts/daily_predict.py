"""Phase 2 -- inférence programmée quotidienne : appelle `patrick predict
--live` (`patrick.predict.predict_live`) pour CHAQUE (ticker, horizon) qui a
aujourd'hui un modèle réellement exploitable -- un run `status='done'` en
base ET dont le trial gagnant (`is_best=1`) a un `artifact_path` qui pointe
vers un fichier `.joblib` qui existe VRAIMENT sur disque (l'audit préalable
sur la DB de production a trouvé des lignes `trial.artifact_path` non NULL
pointant vers des fichiers déjà supprimés/déplacés -- la simple présence
d'une ligne en base ne suffit pas).

Ne ré-entraîne et ne resélectionne jamais rien (même garantie que
`predict_live` lui-même) : charge le modèle déjà exporté de chaque run et
écrit une prédiction `split='live'`.

Isolation des erreurs (exigence Phase 2) : une exception sur UN (ticker,
horizon) est capturée, loggée, et n'empêche JAMAIS le traitement des autres
candidats -- voir `run_daily_predictions`.

Chemins relatifs (`trial.artifact_path`) : ils ont été écrits par le pipeline
avec, comme répertoire courant, le checkout de déploiement réel (typiquement
`C:\\...\\PATRICK\\patrick`), PAS forcément le répertoire courant de ce
script au moment où il est lancé (le Planificateur de tâches Windows peut
démarrer un script avec un tout autre "Start in"). `--base-dir` permet de le
préciser explicitement ; par défaut, c'est `os.getcwd()` au lancement.

Usage (exécuté avec le venv du projet, idéalement avec `--base-dir` pointant
vers le checkout de déploiement réel) :
    python scripts/daily_predict.py
    python scripts/daily_predict.py --base-dir "C:\\Users\\leonp\\PATRICK\\patrick"
    python scripts/daily_predict.py --dry-run
    python scripts/daily_predict.py --limit 3 --log-file daily_predict.log

Planification Windows : voir `scripts/schtasks_daily_predict.ps1` à côté de
ce fichier (documente la commande `schtasks /create ...` -- ne l'exécute
pas).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from patrick import predict as predict_module  # noqa: F401  (re-exporté pour compatibilité)
from patrick.live_refresh import (  # noqa: F401  (la logique vit dans le package, partagée avec l'app web)
    PredictCandidate, PredictOutcome, RunSummary, find_predictable_candidates, run_daily_predictions,
)
from patrick.tracking import db as trackdb

logger = logging.getLogger("patrick.scripts.daily_predict")


def remeasure_stale_drift(candidates: list[PredictCandidate], db_path: str | None = None,
                          measure_fn=None, today=None, limit: int = 10) -> dict:
    """Politique de dérive du 2026-09-26 (`validation/drift_policy.py`) :
    re-mesure le PSI des (ticker, horizon) jamais mesurés ou mesurés il y a
    plus de `REMEASURE_DAYS` jours, au plus `limit` par nuit (~30 s chacun :
    reconstruction complète du pool de features). Une erreur sur un item est
    loggée et n'arrête jamais les suivants ; elle ne change pas le code de
    sortie du script (celui-ci reste celui des prédictions)."""
    from patrick.clock import utc_today
    from patrick.validation import drift_policy

    if measure_fn is None:
        from patrick.explain import compute_drift_for_ticker_horizon as measure_fn
    today = today or utc_today()
    conn = trackdb.connect(db_path)
    try:
        latest = {(sym, int(h)): at for sym, h, at in conn.execute(
            "SELECT symbol, horizon, MAX(computed_at) FROM drift_psi_history GROUP BY symbol, horizon")}
    finally:
        conn.close()
    due = [c for c in candidates if drift_policy.needs_remeasure(latest.get((c.target, c.horizon)), today)]
    report = {"measured": 0, "failed": 0, "skipped_fresh": len(candidates) - len(due),
              "deferred": max(0, len(due) - limit)}
    for c in due[:limit]:
        try:
            result = measure_fn(c.target, c.horizon, db_path=db_path)
            if result is None:
                logger.info("DRIFT target=%s horizon=%s : pas de référence de dérive", c.target, c.horizon)
                report["failed"] += 1
                continue
            logger.info("DRIFT target=%s horizon=%s : %d feature(s) mesurée(s)", c.target, c.horizon, len(result))
            report["measured"] += 1
        except Exception:
            logger.exception("DRIFT FAIL target=%s horizon=%s", c.target, c.horizon)
            report["failed"] += 1
    return report


def print_summary(summary: RunSummary) -> None:
    n_ok, n_fail = len(summary.successes), len(summary.failures)
    print(f"\n=== Résumé : {n_ok} succès / {n_fail} échec(s) sur {len(summary.outcomes)} "
          "(ticker, horizon) ===")
    for o in summary.successes:
        d = o.detail or {}
        print(f"  OK   {o.candidate.target:12s} h={o.candidate.horizon:<3} run_id={o.candidate.run_id} "
              f"ts={d.get('ts')} y_pred={d.get('y_pred')} y_proba={d.get('y_proba')}")
    for o in summary.failures:
        print(f"  FAIL {o.candidate.target:12s} h={o.candidate.horizon:<3} run_id={o.candidate.run_id} "
              f"-- {o.error}")


def _configure_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=handlers, force=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=None,
                         help="Chemin vers patrick.db (défaut : ~/.patrick/patrick.db, "
                              "cf. patrick.tracking.db.default_db_path)")
    parser.add_argument("--base-dir", default=None,
                         help="Répertoire de base pour résoudre les artifact_path relatifs et pour "
                              "charger les modèles (chdir effectué dans ce répertoire avant tout "
                              "appel predict_live) -- défaut : cwd du process au lancement. En "
                              "production, doit être le checkout de déploiement réel "
                              "(ex: C:\\Users\\leonp\\PATRICK\\patrick).")
    parser.add_argument("--dry-run", action="store_true",
                         help="Liste les candidats trouvés sans appeler predict_live.")
    parser.add_argument("--limit", type=int, default=None,
                         help="Limite le nombre de candidats traités (utile pour un test manuel "
                              "restreint plutôt que l'univers complet).")
    parser.add_argument("--log-file", default=None,
                         help="Fichier de log en plus de stdout (utile sous le Planificateur de "
                              "tâches Windows, dont la sortie standard n'est pas toujours capturée).")
    parser.add_argument("--no-drift", action="store_true",
                         help="Ne re-mesure pas la dérive (PSI) des modèles après les prédictions.")
    parser.add_argument("--drift-limit", type=int, default=10,
                         help="Nombre maximal de (ticker, horizon) dont le PSI est re-mesuré par exécution "
                              "(~30 s chacun ; les suivants sont reportés).")
    args = parser.parse_args(argv)

    _configure_logging(args.log_file)

    if args.base_dir:
        base_dir = os.path.abspath(args.base_dir)
        logger.info("chdir -> %s", base_dir)
        os.chdir(base_dir)

    conn = trackdb.connect(args.db_path)
    try:
        candidates = find_predictable_candidates(conn)
    finally:
        conn.close()

    if args.limit is not None:
        candidates = candidates[: args.limit]

    logger.info("%d (ticker, horizon) exploitable(s) trouvé(s)", len(candidates))
    for c in candidates:
        logger.info("  candidat : target=%s horizon=%s run_id=%s trial_id=%s", c.target, c.horizon,
                    c.run_id, c.trial_id)

    if args.dry_run:
        print(f"[DRY-RUN] {len(candidates)} candidat(s), aucun appel à predict_live.")
        return 0

    if not candidates:
        print("Aucun (ticker, horizon) exploitable trouvé -- rien à faire.")
        return 0

    summary = run_daily_predictions(candidates, db_path=args.db_path)
    print_summary(summary)
    if not args.no_drift:
        drift_report = remeasure_stale_drift(candidates, db_path=args.db_path, limit=args.drift_limit)
        print(f"Dérive (PSI) : {drift_report['measured']} re-mesurée(s), {drift_report['failed']} échec(s), "
              f"{drift_report['skipped_fresh']} à jour, {drift_report['deferred']} reportée(s) à demain.")
    return 1 if summary.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
