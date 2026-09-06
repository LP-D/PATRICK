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
from dataclasses import dataclass, field
from datetime import datetime, timezone

from patrick import predict as predict_module
from patrick.tracking import db as trackdb

logger = logging.getLogger("patrick.scripts.daily_predict")


@dataclass
class PredictCandidate:
    """Un (ticker, horizon) avec un run `done` exploitable identifié en base."""
    target: str
    horizon: int
    run_id: str
    trial_id: int
    artifact_path: str


@dataclass
class PredictOutcome:
    """Résultat de l'appel `predict_live` pour un candidat -- succès ou échec."""
    candidate: PredictCandidate
    ok: bool
    detail: dict | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""


@dataclass
class RunSummary:
    """Agrégat succès/échecs d'une exécution complète (tous les candidats)."""
    outcomes: list[PredictOutcome] = field(default_factory=list)

    @property
    def successes(self) -> list[PredictOutcome]:
        return [o for o in self.outcomes if o.ok]

    @property
    def failures(self) -> list[PredictOutcome]:
        return [o for o in self.outcomes if not o.ok]

    def add(self, outcome: PredictOutcome) -> None:
        self.outcomes.append(outcome)


def find_predictable_candidates(conn, base_dir: str | None = None) -> list[PredictCandidate]:
    """Un candidat par (target, horizon) : le run `status='done'` le plus
    récent dont le trial `is_best=1` a un `artifact_path` non vide ET dont le
    fichier existe réellement -- vérifié sur disque, pas seulement en base
    (voir audit, module docstring).

    Chemins relatifs résolus contre `base_dir` (défaut `os.getcwd()`), pas
    contre l'emplacement de ce script -- `predict_live()` (non modifié ici)
    fait `joblib.load(artifact_path)` tel quel, donc c'est le cwd du
    PROCESS au moment de l'appel qui doit correspondre, pas celui de ce
    fichier source."""
    base_dir = base_dir or os.getcwd()
    rows = conn.execute(
        "SELECT r.run_id, r.target, r.horizon, t.trial_id, t.artifact_path "
        "FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "WHERE r.status = 'done' AND t.artifact_path IS NOT NULL AND t.artifact_path != '' "
        "ORDER BY r.target, r.horizon, r.finished_at DESC"
    ).fetchall()

    latest_per_pair: dict[tuple[str, int], PredictCandidate] = {}
    for run_id, target, horizon, trial_id, artifact_path in rows:
        key = (target, horizon)
        if key in latest_per_pair:
            continue  # déjà gardé le plus récent (lignes triées DESC par finished_at)
        resolved = artifact_path if os.path.isabs(artifact_path) else os.path.join(base_dir, artifact_path)
        if not os.path.exists(resolved):
            logger.debug("Ignoré (fichier introuvable) : target=%s horizon=%s run_id=%s artifact_path=%s "
                         "(résolu: %s)", target, horizon, run_id, artifact_path, resolved)
            continue
        latest_per_pair[key] = PredictCandidate(target=target, horizon=horizon, run_id=run_id,
                                                  trial_id=trial_id, artifact_path=artifact_path)
    return list(latest_per_pair.values())


def run_daily_predictions(candidates: list[PredictCandidate], predict_live_fn=None,
                           db_path: str | None = None) -> RunSummary:
    """Appelle `predict_live_fn(candidate.run_id, db_path=db_path)` pour
    chaque candidat, un par un. Exigence Phase 2 : une exception sur UN item
    ne doit JAMAIS interrompre le traitement des suivants -- try/except par
    item, erreur loggée, boucle continue.

    `predict_live_fn` est injectable (mocké dans les tests) ; par défaut,
    `patrick.predict.predict_live`."""
    if predict_live_fn is None:
        predict_live_fn = predict_module.predict_live

    summary = RunSummary()
    for candidate in candidates:
        started_at = datetime.now(timezone.utc).isoformat()
        logger.info("START target=%s horizon=%s run_id=%s", candidate.target, candidate.horizon,
                    candidate.run_id)
        try:
            detail = predict_live_fn(candidate.run_id, db_path=db_path)
            finished_at = datetime.now(timezone.utc).isoformat()
            logger.info("OK    target=%s horizon=%s run_id=%s y_pred=%s y_proba=%s "
                        "n_outcomes_updated=%s", candidate.target, candidate.horizon, candidate.run_id,
                        detail.get("y_pred"), detail.get("y_proba"), detail.get("n_outcomes_updated"))
            summary.add(PredictOutcome(candidate=candidate, ok=True, detail=detail,
                                        started_at=started_at, finished_at=finished_at))
        except Exception as exc:  # noqa: BLE001 -- volontaire : isole les échecs par candidat
            finished_at = datetime.now(timezone.utc).isoformat()
            logger.exception("FAIL  target=%s horizon=%s run_id=%s -- %s", candidate.target,
                             candidate.horizon, candidate.run_id, exc)
            summary.add(PredictOutcome(candidate=candidate, ok=False, error=str(exc),
                                        started_at=started_at, finished_at=finished_at))
    return summary


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
    return 1 if summary.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
