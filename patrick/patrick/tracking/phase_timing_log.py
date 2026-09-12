"""Log de timing lisible par run (Phase 4) -- complément TEXTE BRUT à
`run_phase_timing` (table SQLite, `tracking/db.py::record_phase_timing`), pas
un remplacement : la table reste la source de vérité interrogeable en SQL
(historique complet, drift inter-runs -- `history.py::phase_timing_drift_for_target`),
ce module ne fait qu'exposer, pour UN run donné, la même décomposition déjà
utilisée par l'affichage web (`history.py::phase_breakdown_for_run`) dans un
fichier consultable sans requête DB -- utile pour un `patrick run` lancé
manuellement en CLI.

Réutilise `phase_breakdown_for_run()` telle quelle pour l'agrégation (sommes
par phase, occurrences, `unaccounted_s`) plutôt que de réinterroger
`run_phase_timing` une seconde fois avec une logique parallèle : ce module ne
fait QUE mettre en forme et écrire sur disque le dict qu'elle retourne.

Format retenu : un tableau texte à colonnes séparées par `|`
(`phase | durée | % du total`) -- aucun format pré-existant de ce type n'a
été trouvé dans les .md d'audit de ce dépôt (`AUDIT_ENVIRONNEMENT.md`,
`AUDIT_REPO.md`, `AUDIT_RECONCILIATION_MAIN.md`, `KNOWN_ISSUES.md` :
recherchés, aucun tableau phase/durée/pourcentage n'y figure) -- le seul
précédent trouvé est la notation informelle "824s / 34%" utilisée dans le
docstring de la migration 0017 et un commentaire de `test_db.py` pour
désigner une durée + son pourcentage du total. Le tableau à colonnes `|` lui
-même reprend la convention déjà omniprésente dans les tableaux Markdown de
ce projet (ex. `ARCHITECTURE.md`). Choix documenté ici plutôt que deviné en
silence.
"""
from __future__ import annotations

import os


def _format_duration(seconds: float) -> str:
    """Secondes entières avec suffixe 's' -- même convention que "824s" déjà
    utilisée dans ce projet (migration 0017, test_db.py) pour une durée de
    phase, jamais reconvertie en minutes (les runs mesurés vont de quelques
    secondes à plusieurs milliers, un format unique reste plus facile à
    comparer d'une ligne à l'autre qu'un mélange s/m)."""
    return f"{int(round(seconds))}s"


def _format_pct(seconds: float, total: float | None) -> str:
    if not total:  # total=None (run pas encore fini) ou total=0 (edge case)
        return "n/a"
    return f"{seconds / total * 100:.1f}%"


def format_phase_timing_report(run_id: str, breakdown: dict) -> str:
    """Fonction pure : aucun I/O, aucun accès DB -- prend directement la
    forme retournée par `tracking.history.phase_breakdown_for_run()` :
    `{"run_total_s": int|None, "unaccounted_s": int|None,
      "phases": [{"phase": str, "duration_s": int, "occurrences": int}, ...]}`
    (déjà triée par durée décroissante par cette fonction -- non re-triée
    ici) et produit le texte du fichier `<run_id>_phase_timing.txt`.

    `run_total_s`/pourcentages peuvent être `None` si le run n'a pas encore
    de `finished_at` (cf. docstring de `phase_breakdown_for_run`) -- affiché
    explicitement comme tel ("n/a"), jamais une exception ni un pourcentage
    inventé."""
    total = breakdown.get("run_total_s")
    phases = breakdown.get("phases") or []
    unaccounted = breakdown.get("unaccounted_s")

    rows: list[tuple[str, float]] = []
    for p in phases:
        label = p["phase"]
        if p.get("occurrences", 1) > 1:
            label = f"{label} (x{p['occurrences']})"
        rows.append((label, p["duration_s"]))
    if unaccounted is not None:
        # Pseudo-phase, jamais une ligne de `run_phase_timing` -- même
        # sémantique que `phase_breakdown_for_run` : temps du run non
        # couvert par les phases instrumentées (export modele, diagnostic
        # holdout non exerces, etc. selon les phases presentes).
        rows.append(("non_comptabilise", unaccounted))

    lines: list[str] = []
    lines.append(f"Run: {run_id}")
    lines.append(f"Total: {_format_duration(total) if total is not None else 'inconnu (run non termine)'}")
    lines.append("")

    if not rows:
        lines.append("(aucune phase enregistree pour ce run)")
        return "\n".join(lines) + "\n"

    table = [("phase", "durée", "% du total")]
    for label, duration in rows:
        table.append((label, _format_duration(duration), _format_pct(duration, total)))

    col_widths = [max(len(row[i]) for row in table) for i in range(3)]

    def fmt_row(row: tuple[str, str, str]) -> str:
        return " | ".join(cell.ljust(col_widths[i]) if i == 0 else cell.rjust(col_widths[i])
                           for i, cell in enumerate(row))

    lines.append(fmt_row(table[0]))
    lines.append("-+-".join("-" * w for w in col_widths))
    for row in table[1:]:
        lines.append(fmt_row(row))

    return "\n".join(lines) + "\n"


def write_phase_timing_log(out_dir: str, run_id: str, breakdown: dict) -> str:
    """Écrit le rapport à côté des autres artefacts de ce run (leaderboard
    CSV/xlsx, `<name>_tuned.csv`, `<name>_best_model_h<horizon>.joblib` --
    voir `pipeline/leaderboard.py::export`, `tracking/export.py`), dans le
    même `config.output.dir`. Nommé par `run_id` (pas par `config.name`, déjà
    utilisé par les artefacts partagés entre horizons d'un même batch) --
    `run_id` identifie sans ambiguïté LE run/horizon dont ce fichier décrit
    le timing, et se lit directement en face de la même colonne `run_id`
    dans les tables `run`/`run_phase_timing`."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{run_id}_phase_timing.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_phase_timing_report(run_id, breakdown))
    return path
