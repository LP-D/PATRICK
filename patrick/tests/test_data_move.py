"""`patrick data` : état, création et déplacement de la racine de données (spec 2026-10-21, §6).

Tout se passe sur des arbres et de petites bases sous `tmp_path` : jamais le vrai `~/.patrick`, jamais la vraie base."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from patrick import data_move, paths, settings
from patrick.cli import app as cli_app
from patrick.tracking import db as trackdb


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """Un PC sans racine de données réglée : tout vit dans son dossier maison `tmp_path/home`."""
    for var in ("PATRICK_DATA_ROOT", "PATRICK_STORE_ROOT", "PATRICK_CACHE_ROOT", "PATRICK_FEATURE_CACHE_ROOT"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PATRICK_DB_PATH", str(home / "patrick.db"))
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(home / "settings.json"))
    return SimpleNamespace(home=home, tmp=tmp_path)


def make_db(path: Path, artifacts: list[str | None]) -> str:
    """Petite base : un run, un essai par valeur de `trial.artifact_path`."""
    conn = trackdb.connect(str(path))
    trackdb.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    trackdb.create_run(conn, "r1", "T", 5, "snap", json.dumps({}), "cfg", "sha", 42)
    for artifact in artifacts:
        conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                     "artifact_path) VALUES ('r1', 'all', 'lgbm', 'tpe', 10, 'shap', '{}', 0, ?)", (artifact,))
    conn.commit()
    conn.close()
    return str(path)


# --- init / status -----------------------------------------------------------------------------------------------

def test_init_root_creates_the_seven_folders_and_a_readme(tmp_path):
    root = data_move.init_root(str(tmp_path / "PATRICK DATA"))

    assert root == tmp_path / "PATRICK DATA"
    assert data_move.COMPONENTS == ("store", "models", "feature_cache", "cache", "backups", "archive", "reports")
    assert all((root / name).is_dir() for name in data_move.COMPONENTS)
    assert "patrick data status" in (root / "README.txt").read_text(encoding="utf-8")


def test_init_root_refuses_a_missing_parent_and_a_relative_path_and_creates_nothing(tmp_path):
    with pytest.raises(data_move.MoveError):
        data_move.init_root(str(tmp_path / "absent" / "PATRICK DATA"))
    with pytest.raises(data_move.MoveError):
        data_move.init_root("PATRICK DATA")
    assert not (tmp_path / "absent").exists()


def test_status_without_a_data_root(pc):
    out = data_move.status()

    assert out["data_root"] is None and out["available"] is True and out["db"] == str(pc.home / "patrick.db")
    assert [c["name"] for c in out["components"]] == list(data_move.COMPONENTS)
    assert out["unresolved"] == {"artifact_paths": 0, "store_index": 0} and out["progress"] is None


def test_status_with_a_missing_data_root(pc, monkeypatch):
    absent = pc.tmp / "PATRICK DATA"
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(absent))

    out = data_move.status()

    assert out["available"] is False and out["data_root"] == str(absent)
    assert all(c["exists"] is False for c in out["components"])
    assert not absent.exists()


def test_status_counts_only_the_unresolved_absolute_paths(pc):
    model = pc.home / "models" / "1" / "a.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"x")
    make_db(pc.home / "patrick.db", [str(model), str(pc.home / "models" / "2" / "gone.joblib"),
                                     "runs\\rel\\x.joblib", None, ""])
    snap = pc.home / "store" / "snapshot=2026-07-28"
    snap.mkdir(parents=True)
    (snap / "a__1.parquet").write_bytes(b"p")
    (pc.home / "store" / "_index.json").write_text(json.dumps({"k": {"snapshots": [
        {"path": str(snap / "a__1.parquet")}, {"path": str(snap / "b__2.parquet")}]}}), encoding="utf-8")

    assert data_move.status()["unresolved"] == {"artifact_paths": 1, "store_index": 1}


def test_cli_status_and_init(pc):
    root = pc.tmp / "PATRICK DATA"

    assert CliRunner().invoke(cli_app, ["data", "init", str(root)]).exit_code == 0
    assert (root / "models").is_dir()
    out = CliRunner().invoke(cli_app, ["data", "status"])

    assert out.exit_code == 0 and "Racine de données" in out.output and "Dossier maison" in out.output


# --- phase 1 : préconditions et copie ----------------------------------------------------------------------------

TREE = {"store/snapshot=2026-07-28/a__1.parquet": b"parquet", "store/_index.json": b"{}", "models/1/m.joblib": b"model",
        "feature_cache/ab/k.parquet": b"fc", "cache/x.json": b"c", "backups/patrick_backup_1.db": b"db",
        "archive/old.txt": b"o", "reports/r.html": b"<p>"}


def make_tree(root: Path) -> None:
    for rel, data in TREE.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def listing(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def calm(monkeypatch):
    """Ni serveur qui écoute ni manque de place : le terrain où `check_preconditions` ne dit rien."""
    monkeypatch.setattr(data_move.runtime, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(data_move.sync, "_free_bytes", lambda path: 10**12)


def test_preconditions_are_silent_on_a_calm_pc(pc, calm):
    make_tree(pc.home)

    assert data_move.check_preconditions(str(pc.tmp / "PATRICK DATA"), db_path=str(pc.home / "patrick.db"), port=8000) == []


def test_preconditions_block_a_running_job_a_listening_server_and_a_lack_of_space(pc, calm, monkeypatch):
    make_tree(pc.home)
    db = make_db(pc.home / "patrick.db", [])
    conn = trackdb.connect(db)
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'running')")
    conn.commit()
    conn.close()
    target = str(pc.tmp / "PATRICK DATA")

    assert any("entraînement" in m for m in data_move.check_preconditions(target, db_path=db, port=8000))

    monkeypatch.setattr(data_move.runtime, "port_open", lambda port, *a, **k: True)
    assert any("PATRICK est ouvert" in m for m in data_move.check_preconditions(target, db_path=str(pc.tmp / "none.db"), port=8000))

    monkeypatch.setattr(data_move.runtime, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(data_move.sync, "_free_bytes", lambda path: 0)
    assert any("espace" in m for m in data_move.check_preconditions(target, db_path=str(pc.tmp / "none.db"), port=8000))


def test_preconditions_refuse_a_badly_chosen_target(pc, calm, monkeypatch):
    active = pc.tmp / "R1"
    active.mkdir()
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(active))
    make_tree(active)
    share = pc.tmp / "share"
    share.mkdir()
    settings.save({data_move.sync.KEY_SYNC_FOLDER: str(share)})
    db = str(pc.tmp / "none.db")

    def reasons(target: Path) -> str:
        return " | ".join(data_move.check_preconditions(str(target), db_path=db, port=8000))

    assert "déjà" in reasons(active)                              # la racine active elle-même
    assert "dossier maison" in reasons(pc.home / "data")          # dans le dossier maison
    assert "source" in reasons(active / "sous-dossier")           # dans la source
    assert "contient" in reasons(pc.tmp)                          # contient la source
    assert "partage" in reasons(share / "donnees")                # dans le dossier de partage
    assert "partage" in reasons(pc.tmp)                           # contient le dossier de partage
    assert "n'existe pas" in reasons(pc.tmp / "absent" / "PATRICK DATA")   # lecteur / dossier parent absent


def test_copy_copies_every_component_to_a_folder_with_a_space_and_leaves_the_source_alone(pc):
    make_tree(pc.home)
    target = pc.tmp / "PATRICK DATA"

    out = data_move.copy_components(str(target))

    assert out["files"] == len(TREE) and out["skipped"] == 0 and out["bytes"] == sum(len(b) for b in TREE.values())
    assert {k: v for k, v in listing(target).items() if k != "README.txt"} == TREE
    assert {k: v for k, v in listing(pc.home).items() if k != data_move.STATE_NAME} == TREE     # la source ne bouge pas
    assert data_move.status()["progress"]["phase"] == "copied"


def test_copy_resumes_after_an_interruption_and_skips_what_is_already_there(pc):
    make_tree(pc.home)
    target = pc.tmp / "PATRICK DATA"
    (target / "models" / "1").mkdir(parents=True)
    (target / "models" / "1" / "m.joblib").write_bytes(b"mod")                  # copie tronquée
    (target / "store").mkdir()
    (target / "store" / "_index.json.part").write_bytes(b"orphelin")           # reste d'un envoi interrompu

    first = data_move.copy_components(str(target))
    second = data_move.copy_components(str(target))

    assert (target / "models" / "1" / "m.joblib").read_bytes() == b"model"
    assert not (target / "store" / "_index.json.part").exists()
    assert first["files"] == len(TREE) and second["files"] == 0 and second["skipped"] == len(TREE)


def test_copy_detects_a_corrupted_copy_of_the_models_or_the_store(pc, monkeypatch):
    make_tree(pc.home)

    def corrupting(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"X" * src.stat().st_size)                              # même taille, autre contenu

    monkeypatch.setattr(data_move, "_copy_file", corrupting)

    with pytest.raises(data_move.MoveError, match="sha256"):
        data_move.copy_components(str(pc.tmp / "PATRICK DATA"))


def test_cli_move_stops_on_a_blocking_precondition(pc, monkeypatch):
    monkeypatch.setattr(data_move.runtime, "port_open", lambda port, *a, **k: True)

    out = CliRunner().invoke(cli_app, ["data", "move", str(pc.tmp / "PATRICK DATA")])

    assert out.exit_code == 1 and "Refusé" in out.output and "PATRICK est ouvert" in out.output
    assert not (pc.tmp / "PATRICK DATA").exists()


# --- phase 2 : bascule et journal --------------------------------------------------------------------------------

OLD_STORE = r"C:\Users\leonp\.patrick\store"
NEW_STORE = r"D:\PATRICK DATA\store"
windows_only = pytest.mark.skipif(os.name != "nt", reason="chemins Windows : lettre de lecteur, antislash, casse insensible")


@windows_only
def test_rebase_path_handles_mixed_separators_and_case():
    mixed = r"C:\Users\leonp/.patrick/store\snapshot=2026-07-28\raw_IDX_VIX__02b2bd20a711.parquet"   # tel que dans _index.json

    assert data_move.rebase_path(mixed, OLD_STORE, NEW_STORE) == (
        r"D:\PATRICK DATA\store\snapshot=2026-07-28\raw_IDX_VIX__02b2bd20a711.parquet")
    assert data_move.rebase_path(r"c:\users\LEONP\.PATRICK\store\snapshot=1\f.parquet", OLD_STORE, NEW_STORE) == (
        r"D:\PATRICK DATA\store\snapshot=1\f.parquet")
    assert data_move.rebase_path(OLD_STORE, OLD_STORE, NEW_STORE) == NEW_STORE


@windows_only
def test_rebase_path_leaves_other_paths_alone():
    assert data_move.rebase_path(r"C:\Users\leonp\.patrick\models\1\m.joblib", OLD_STORE, NEW_STORE) is None
    assert data_move.rebase_path(r"C:\Users\leonp\.patrick\store2\x.parquet", OLD_STORE, NEW_STORE) is None   # préfixe, pas un dossier parent
    assert data_move.rebase_path("runs\\GSPC_34\\m.joblib", OLD_STORE, NEW_STORE) is None


def prepare(pc, *, extra_models: tuple[str, ...] = (), copy: bool = True) -> SimpleNamespace:
    """Une source avec modèles, base et index du magasin à séparateurs mixtes, déjà copiée vers `tmp/PATRICK DATA`."""
    model = pc.home / "models" / "1" / "m.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    relative = "runs\\GSPC_34\\GSPC_34_best_model_h1.joblib"
    elsewhere = str(pc.tmp / "ailleurs" / "x.joblib")                  # absolu sur tout système, jamais existé
    db = make_db(pc.home / "patrick.db", [str(model), relative, None, "", elsewhere,
                                         *(str(pc.home / "models" / name / "x.joblib") for name in extra_models)])
    store = pc.home / "store"
    (store / "snapshot=2026-07-28").mkdir(parents=True)
    (store / "snapshot=2026-07-28" / "a__1.parquet").write_bytes(b"parquet")
    mixed = str(store).replace("\\", "/") + "\\snapshot=2026-07-28\\a__1.parquet"
    (store / "_index.json").write_text(json.dumps({"k": {"rows": 1, "snapshots": [{"snapshot_id": "s1", "path": mixed}]}}),
                                       encoding="utf-8")
    target = pc.tmp / "PATRICK DATA"
    if copy:
        data_move.copy_components(str(target))
    return SimpleNamespace(db=db, target=target, model=model, relative=relative, store=store, elsewhere=elsewhere)


def artifact_paths(db: str) -> list:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT artifact_path FROM trial ORDER BY trial_id")]
    finally:
        conn.close()


def test_switch_rewrites_only_the_absolute_model_paths_and_the_copied_index_then_sets_the_root(pc):
    p = prepare(pc)
    source_index = (p.store / "_index.json").read_bytes()
    new_model = str(p.target / "models" / "1" / "m.joblib")

    journal = data_move.switch(str(p.target), db_path=p.db)

    assert artifact_paths(p.db) == [new_model, p.relative, None, "", p.elsewhere]
    new_index = json.loads((p.target / "store" / "_index.json").read_text(encoding="utf-8"))
    assert new_index["k"]["snapshots"][0]["path"] == str(p.target / "store" / "snapshot=2026-07-28" / "a__1.parquet")
    assert (p.store / "_index.json").read_bytes() == source_index                  # l'index de la source ne bouge pas
    assert settings.load()["data_root"] == str(p.target) and paths.data_root() == p.target
    assert journal["artifact_paths"] == [[1, str(p.model), new_model]] and journal["target"] == str(p.target)
    assert json.loads((pc.home / data_move.JOURNAL_NAME).read_text(encoding="utf-8")) == journal
    assert data_move.status()["unresolved"] == {"artifact_paths": 1, "store_index": 0}   # `elsewhere` n'a jamais existé


def test_a_second_switch_changes_nothing_and_keeps_the_journal(pc):
    p = prepare(pc)
    first = data_move.switch(str(p.target), db_path=p.db)
    journal_bytes = (pc.home / data_move.JOURNAL_NAME).read_bytes()
    paths_after_first = artifact_paths(p.db)

    second = data_move.switch(str(p.target), db_path=p.db)

    assert second == first and (pc.home / data_move.JOURNAL_NAME).read_bytes() == journal_bytes
    assert artifact_paths(p.db) == paths_after_first


def test_a_failure_in_the_sql_transaction_changes_nothing(pc):
    p = prepare(pc, extra_models=("boom",))
    conn = sqlite3.connect(p.db)
    conn.execute("CREATE TRIGGER boom BEFORE UPDATE OF artifact_path ON trial WHEN NEW.artifact_path LIKE '%boom%' "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    conn.commit()
    conn.close()
    before = artifact_paths(p.db)
    index_before = (p.target / "store" / "_index.json").read_bytes()

    with pytest.raises(data_move.MoveError, match="aucune modification"):
        data_move.switch(str(p.target), db_path=p.db)

    assert artifact_paths(p.db) == before
    assert "data_root" not in settings.load()
    assert (p.target / "store" / "_index.json").read_bytes() == index_before
    assert not (pc.home / data_move.JOURNAL_NAME).exists()


# --- phase 3 : contrôle, retour arrière, finalisation ------------------------------------------------------------

def switched(pc) -> SimpleNamespace:
    p = prepare(pc)
    data_move.switch(str(p.target), db_path=p.db)
    return p


def test_verify_is_ok_after_a_valid_switch_and_flags_a_missing_moved_file(pc):
    p = switched(pc)

    assert data_move.verify(p.db) == {"artifact_unresolved": 0, "store_unresolved": 0, "ok": True}

    (p.target / "models" / "1" / "m.joblib").unlink()
    (p.target / "store" / "snapshot=2026-07-28" / "a__1.parquet").unlink()
    broken = data_move.verify(p.db)

    assert broken == {"artifact_unresolved": 1, "store_unresolved": 1, "ok": False}


def test_verify_without_a_journal_is_refused(pc):
    with pytest.raises(data_move.MoveError, match="journal"):
        data_move.verify()


def test_rollback_restores_the_old_values_and_the_setting_and_leaves_the_source_intact(pc):
    p = prepare(pc)
    before = artifact_paths(p.db)
    model_bytes, index_bytes = p.model.read_bytes(), (p.store / "_index.json").read_bytes()
    data_move.switch(str(p.target), db_path=p.db)

    out = data_move.rollback(p.db)

    assert out["status"] == "rolled_back" and artifact_paths(p.db) == before
    assert "data_root" not in settings.load() and paths.data_root() == pc.home
    assert p.model.read_bytes() == model_bytes and (p.store / "_index.json").read_bytes() == index_bytes
    assert data_move.rollback(p.db)["status"] == "rolled_back"                        # sans effet la deuxième fois


def test_finalize_deletes_only_the_components_of_the_source_and_then_rollback_is_refused(pc):
    p = switched(pc)
    (pc.home / "logs").mkdir()
    (pc.home / "logs" / "x.log").write_text("journal", encoding="utf-8")

    out = data_move.finalize()

    assert sorted(out["removed"]) == ["models", "store"]
    assert not (pc.home / "models").exists() and not (pc.home / "store").exists()
    assert (pc.home / "patrick.db").exists() and (pc.home / "settings.json").exists() and (pc.home / "logs" / "x.log").exists()
    assert (p.target / "models" / "1" / "m.joblib").read_bytes() == b"model"
    with pytest.raises(data_move.MoveError, match="finalize"):
        data_move.rollback(p.db)


def test_finalize_refuses_when_the_check_fails_and_deletes_nothing(pc):
    p = switched(pc)
    (p.target / "models" / "1" / "m.joblib").unlink()

    with pytest.raises(data_move.MoveError):
        data_move.finalize()

    assert p.model.exists() and (p.store / "_index.json").exists()


def test_finalize_refuses_when_nothing_was_switched(pc):
    with pytest.raises(data_move.MoveError, match="finaliser"):
        data_move.finalize()


def test_cli_move_runs_the_three_phases_then_finalize_needs_a_yes(pc, calm):
    p = prepare(pc, copy=False)

    moved = CliRunner().invoke(cli_app, ["data", "move", str(p.target)])

    assert moved.exit_code == 0 and "Copie terminée" in moved.output and "--finalize" in moved.output
    assert settings.load()["data_root"] == str(p.target)
    refused = CliRunner().invoke(cli_app, ["data", "move", "--finalize"], input="n\n")
    assert refused.exit_code == 1 and p.model.exists()
    accepted = CliRunner().invoke(cli_app, ["data", "move", "--finalize"], input="o\n")
    assert accepted.exit_code == 0 and not p.model.exists() and (p.target / "models" / "1" / "m.joblib").exists()


def test_cli_finalize_takes_no_folder_and_rollback_works(pc, calm):
    p = prepare(pc, copy=False)
    CliRunner().invoke(cli_app, ["data", "move", str(p.target)])

    both = CliRunner().invoke(cli_app, ["data", "move", str(p.target), "--finalize"], input="o\n")
    back = CliRunner().invoke(cli_app, ["data", "rollback"])

    assert both.exit_code == 1 and "aucun dossier" in both.output and p.model.exists()
    assert back.exit_code == 0 and "data_root" not in settings.load()
