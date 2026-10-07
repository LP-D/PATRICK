"""Fusion de deux bases `patrick.db` (celle de ce PC et celle d'un partage).

Deux PC qui lancent des runs chacun de leur côté produisent des bases
disjointes : un simple « remplacer par le partage » perdrait les runs locaux,
un « publier » perdrait ceux du partage. Ici on prend l'UNION de la recherche.

Identité d'un run : son `run_id` (texte, dérivé de la configuration), identique
sur les deux PC. Les identifiants entiers (`trial.trial_id`) sont des clés de
substitution propres à chaque base : les essais d'un run importé reçoivent
`trial_id + décalage` (décalage = plus grand `trial_id` déjà présent), et toutes
les tables qui y renvoient (`fold_metric`, `holdout_diagnostic`, `prediction`,
`champion`, `model_archive`) sont décalées de la même valeur.

Règles :
- un run déjà présent localement n'est jamais modifié ni complété (les
  prédictions « live » restent donc sur le PC qui les a produites);
- `champion` : le plus récent (`promoted_at`) gagne pour une même (cible, horizon);
- `trial_registry` (compteur d'essais du DSR) : union dédoublonnée;
- caches (`shap_selection_cache`, `vol_model_cache`) : union par clé;
- jamais fusionnés par union : patrimoine (`wealth_*`), fonds (`fund_*`), `simulation`
  (les deux PC avaient importé les mêmes comptes sous des identifiants différents, une
  union créerait des doublons). Le patrimoine et les fonds ont un PC de RÉFÉRENCE qui les
  publie; les autres les remplacent par les siens (`adopt_personal_tables`). `simulation`
  et l'état d'exécution (`worker_heartbeat`; jobs importés mis en erreur) restent locaux.
"""
from __future__ import annotations

import sqlite3

# Tables rattachées à un run par `run_id`, clé primaire naturelle : INSERT OR IGNORE.
_RUN_KEYED = ("baseline_metric", "dm_result", "feature_stability", "run_feature_stability",
              "screening_decision")
# Tables rattachées à un essai (`trial_id`), décalé comme `trial`.
_TRIAL_KEYED = ("fold_metric", "holdout_diagnostic", "prediction")
# Union par clé primaire naturelle, sans lien avec un run.
_BY_KEY = ("snapshot", "excluded_symbol", "drift_feature_reference",
           "shap_selection_cache", "vol_model_cache")


# Patrimoine et fonds : un PC « référence » les publie, les autres les REMPLACENT par ceux du partage
# (`adopt_personal_tables`). Parents avant enfants. `simulation` en est exclue : elle renvoie à des
# `trial_id` propres à chaque base.
ADOPTED_PERSONAL_TABLES = ("wealth_account", "wealth_movement", "fund_strategy", "fund_rule", "fund_order",
                           "fund_price", "fund_price_meta")


class MergeError(RuntimeError):
    """Les deux bases ne sont pas fusionnables (schémas différents...)."""


def adopt_personal_tables(dst_path: str, src_path: str) -> dict[str, int]:
    """Remplace dans `dst_path` le patrimoine et les fonds par ceux de `src_path` (le PC de référence).
    Une transaction : en cas d'erreur, rien n'est écrit. Renvoie le nombre de lignes par table."""
    conn = sqlite3.connect(dst_path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")          # ordre de recopie libre, contrôlé à la fin
        conn.execute("ATTACH DATABASE ? AS src", (src_path,))
        for table in ADOPTED_PERSONAL_TABLES:
            _shared_columns(conn, table)
        counts: dict[str, int] = {}
        conn.execute("BEGIN")
        try:
            for table in reversed(ADOPTED_PERSONAL_TABLES):
                conn.execute(f'DELETE FROM main."{table}"')
            for table in ADOPTED_PERSONAL_TABLES:
                counts[table] = _insert(conn, table)
            orphans = conn.execute("PRAGMA foreign_key_check").fetchall()
            if orphans:
                raise MergeError(f"Patrimoine du partage incohérent ({len(orphans)} clé(s) orpheline(s)).")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return counts
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _shared_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    main, src = _columns(conn, "main", table), set(_columns(conn, "src", table))
    missing = [c for c in main if c not in src]
    if missing:
        raise MergeError(f"Schémas différents : {table} n'a pas {', '.join(missing)} dans le partage "
                         "(mets le code à jour sur les deux PC).")
    return main


def _insert(conn: sqlite3.Connection, table: str, *, where: str = "", off: int = 0,
            or_ignore: bool = False, skip: tuple[str, ...] = (), override: dict[str, str] | None = None) -> int:
    """`INSERT INTO main.<table> SELECT ... FROM src.<table> AS s WHERE <where>`; renvoie le nombre
    de lignes ajoutées. `trial_id` est décalé de `off`; `skip` : colonnes laissées à la base
    (clés auto-incrémentées); `override` : expression SQL de remplacement par colonne."""
    cols = [c for c in _shared_columns(conn, table) if c not in skip]
    override = override or {}
    exprs = []
    for c in cols:
        if c in override:
            exprs.append(override[c])
        elif c == "trial_id" and off:
            exprs.append(f"s.trial_id + {int(off)}")
        else:
            exprs.append(f's."{c}"')
    verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
    before = conn.total_changes
    conn.execute(f'{verb} INTO main."{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                 f'SELECT {", ".join(exprs)} FROM src."{table}" AS s {where}')
    return conn.total_changes - before


def _trial_offset(conn: sqlite3.Connection) -> int:
    top = conn.execute("SELECT COALESCE(MAX(trial_id), 0) FROM main.trial").fetchone()[0]
    seq = conn.execute("SELECT COALESCE((SELECT seq FROM main.sqlite_sequence WHERE name = 'trial'), 0)").fetchone()[0]
    return max(top, seq)


def merge_databases(dst_path: str, src_path: str, *, fast: bool = False) -> dict:
    """Fusionne la recherche de `src_path` dans `dst_path` (modifiée en place, en UNE transaction :
    en cas d'erreur, rien n'est écrit). Les deux bases doivent être migrées à la même version.
    `fast` : ni fsync ni journal, réservé à une COPIE de travail jetable (un échec ou une coupure en
    cours de route l'abîme : on la jette, jamais la base d'origine).

    Renvoie : `new_runs`, `local_only_runs` (runs de `dst` absents de `src`), `trial_offset`,
    `new_trial_ids` (identifiants d'essai côté `src` des runs importés) et le détail des lignes ajoutées."""
    conn = sqlite3.connect(dst_path, isolation_level=None)
    try:
        if fast:
            # Ni fsync ni journal : une fusion de plusieurs Go écrit ~10x plus vite, et en cas d'échec
            # l'appelant jette la copie de travail.
            conn.execute("PRAGMA journal_mode = DELETE")
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("ATTACH DATABASE ? AS src", (src_path,))
        for table in ("run", "trial", "prediction"):
            _shared_columns(conn, table)

        dst_runs = {r[0] for r in conn.execute("SELECT run_id FROM main.run")}
        src_runs = {r[0] for r in conn.execute("SELECT run_id FROM src.run")}
        new_runs = sorted(src_runs - dst_runs)
        report: dict = {"new_runs": len(new_runs), "local_only_runs": len(dst_runs - src_runs),
                        "trial_offset": 0, "new_trial_ids": [], "added": {}}

        conn.execute("CREATE TEMP TABLE _new_runs (run_id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO _new_runs VALUES (?)", [(r,) for r in new_runs])
        conn.execute("CREATE TEMP TABLE _new_snapshots (snapshot_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO _new_snapshots SELECT snapshot_id FROM src.snapshot "
                     "WHERE snapshot_id NOT IN (SELECT snapshot_id FROM main.snapshot)")

        added = report["added"]
        in_new_runs = "WHERE s.run_id IN (SELECT run_id FROM temp._new_runs)"

        conn.execute("BEGIN")
        try:
            # Ordre = dépendances (clés étrangères) : snapshot, job, run, trial, puis tout le reste.
            added["snapshot"] = _insert(conn, "snapshot", or_ignore=True)
            added["data_quality_issue"] = _insert(
                conn, "data_quality_issue", skip=("id",),
                where="WHERE s.snapshot_id IN (SELECT snapshot_id FROM temp._new_snapshots)")
            added["job"] = _insert(
                conn, "job", or_ignore=True,
                override={"status": "CASE WHEN s.status IN ('queued', 'running') THEN 'error' ELSE s.status END",
                          "error": "CASE WHEN s.status IN ('queued', 'running') "
                                   "THEN COALESCE(s.error, 'Interrompu : importé par patrick sync') ELSE s.error END",
                          "worker_pid": "NULL"})
            added["run"] = _insert(conn, "run", where=in_new_runs)

            off = _trial_offset(conn)
            report["trial_offset"] = off
            report["new_trial_ids"] = [r[0] for r in conn.execute(
                "SELECT trial_id FROM src.trial WHERE run_id IN (SELECT run_id FROM temp._new_runs) ORDER BY trial_id")]
            conn.execute("CREATE TEMP TABLE _new_trials (trial_id INTEGER PRIMARY KEY)")
            conn.executemany("INSERT INTO _new_trials VALUES (?)", [(t,) for t in report["new_trial_ids"]])
            added["trial"] = _insert(conn, "trial", off=off, where=in_new_runs)
            by_new_trial = "WHERE s.trial_id IN (SELECT trial_id FROM temp._new_trials)"
            for table in _TRIAL_KEYED:
                added[table] = _insert(conn, table, off=off, where=by_new_trial)

            for table in _RUN_KEYED:
                added[table] = _insert(conn, table, or_ignore=True, where=in_new_runs)
            added["run_phase_timing"] = _insert(conn, "run_phase_timing", skip=("phase_timing_id",), where=in_new_runs)
            added["model_archive"] = _insert(conn, "model_archive", skip=("archive_id",), off=off, where=in_new_runs)

            # Registre des essais (DSR) : union dédoublonnée sur tout le contenu.
            reg = [c for c in _shared_columns(conn, "trial_registry") if c != "registry_id"]
            same = " AND ".join(f'm."{c}" IS s."{c}"' for c in reg)
            added["trial_registry"] = _insert(
                conn, "trial_registry", skip=("registry_id",),
                where=f"WHERE NOT EXISTS (SELECT 1 FROM main.trial_registry m WHERE {same})")

            added["champion"] = _merge_champions(conn, off)

            for table in _BY_KEY:
                if table != "snapshot":
                    added[table] = _insert(conn, table, or_ignore=True)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        orphans = conn.execute("PRAGMA foreign_key_check").fetchall()
        if orphans:
            raise MergeError(f"Fusion incohérente ({len(orphans)} clé(s) étrangère(s) orpheline(s), "
                             f"ex. {orphans[0]}) : abandonnée.")
        return report
    finally:
        conn.close()


def _merge_champions(conn: sqlite3.Connection, off: int) -> int:
    """Le champion le plus récent gagne pour une même (cible, horizon). Seuls les champions dont le
    run est importé sont repris : leur `trial_id` est connu (décalé), alors que celui d'un run déjà
    présent localement n'a pas de correspondance sûre entre les deux bases."""
    cols = _shared_columns(conn, "champion")
    exprs = ["s.trial_id + %d" % off if c == "trial_id" else f's."{c}"' for c in cols]
    before = conn.total_changes
    conn.execute(
        f'INSERT OR REPLACE INTO main.champion ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
        f'SELECT {", ".join(exprs)} FROM src.champion AS s '
        "WHERE s.run_id IN (SELECT run_id FROM temp._new_runs) AND NOT EXISTS ("
        "SELECT 1 FROM main.champion m WHERE m.target = s.target AND m.horizon = s.horizon "
        "AND m.promoted_at >= s.promoted_at)")
    return conn.total_changes - before
