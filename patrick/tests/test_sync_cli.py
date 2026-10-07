"""`patrick sync push|pull` : la restauration est refusée tant qu'un run tourne
(le remplacement de la base ne doit pas concurrencer un worker)."""
from __future__ import annotations

import json
import sqlite3

from typer.testing import CliRunner

from patrick.cli import app
from patrick.tracking import db as trackdb


def _seed(path: str, *, personal: bool) -> None:
    conn = trackdb.connect(path)
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "run_1", "^TEST", 5, "snap1", json.dumps({}), "h", "sha", 42)
    if personal:
        conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('a1', 'PEA', 'PEA', 'real')")
    conn.commit()
    conn.close()


def test_push_then_pull_through_the_cli_keeps_local_wealth(tmp_path, monkeypatch):
    pc1, pc2, share = str(tmp_path / "pc1.db"), str(tmp_path / "pc2.db"), str(tmp_path / "share")
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    _seed(pc1, personal=True)
    runner = CliRunner()

    monkeypatch.setenv("PATRICK_DB_PATH", pc1)
    pushed = runner.invoke(app, ["sync", "push", "--to", share])
    assert pushed.exit_code == 0, pushed.output
    assert "wealth_account" in pushed.output                 # annoncée comme vidée dans l'export

    monkeypatch.setenv("PATRICK_DB_PATH", pc2)
    _seed(pc2, personal=False)
    conn = sqlite3.connect(pc2)
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('b1', 'CTO', 'CTO', 'real')")
    conn.commit()
    conn.close()
    pulled = runner.invoke(app, ["sync", "pull", "--from", share])
    assert pulled.exit_code == 0, pulled.output
    conn = sqlite3.connect(pc2)
    assert [r[0] for r in conn.execute("SELECT account_id FROM wealth_account")] == ["b1"]
    conn.close()


def test_pull_is_refused_while_a_job_is_running(tmp_path, monkeypatch):
    pc1, pc2, share = str(tmp_path / "pc1.db"), str(tmp_path / "pc2.db"), str(tmp_path / "share")
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    _seed(pc1, personal=False)
    runner = CliRunner()
    monkeypatch.setenv("PATRICK_DB_PATH", pc1)
    assert runner.invoke(app, ["sync", "push", "--to", share]).exit_code == 0

    monkeypatch.setenv("PATRICK_DB_PATH", pc2)
    _seed(pc2, personal=False)
    conn = sqlite3.connect(pc2)
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'running')")
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["sync", "pull", "--from", share])

    assert result.exit_code == 1
    assert "run est en cours" in result.output


def test_push_include_personal_to_github_is_refused(tmp_path, monkeypatch):
    pc1 = str(tmp_path / "pc1.db")
    _seed(pc1, personal=True)
    monkeypatch.setenv("PATRICK_DB_PATH", pc1)

    result = CliRunner().invoke(app, ["sync", "push", "--to", "github", "--include-personal"])

    assert result.exit_code == 1
    assert "Refusé" in result.output


# --- sync setup / status / auto / merge -----------------------------------------------------------------

def _pc_env(tmp_path, monkeypatch, name: str) -> str:
    """Environnement d'un « PC » : base, état/réglages et magasin propres, sauvegardes dans tmp_path."""
    from patrick.tracking import backup

    (tmp_path / name).mkdir(exist_ok=True)               # réglages ET état de synchro propres à chaque PC
    db = str(tmp_path / f"{name}.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / name / "settings.json"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / f"{name}_store"))
    monkeypatch.setattr(backup, "DEFAULT_BACKUP_DIR", str(tmp_path / f"{name}_backups"))
    return db


def _add_run(path: str, run_id: str) -> None:
    conn = trackdb.connect(path)
    trackdb.upsert_snapshot(conn, "snap_" + run_id, "h" + run_id, None, None, None)
    trackdb.create_run(conn, run_id, "^TEST", 5, "snap_" + run_id, json.dumps({}), "h", "sha", 42)
    conn.close()


def test_auto_without_setup_explains_what_to_do(tmp_path, monkeypatch):
    _pc_env(tmp_path, monkeypatch, "pc1")

    result = CliRunner().invoke(app, ["sync", "auto"])

    assert result.exit_code == 1 and "sync setup" in result.output


def test_setup_rejects_a_missing_folder(tmp_path, monkeypatch):
    _pc_env(tmp_path, monkeypatch, "pc1")

    result = CliRunner().invoke(app, ["sync", "setup", "--folder", str(tmp_path / "nope")])

    assert result.exit_code == 1 and "introuvable" in result.output


def test_two_pcs_sync_through_the_cli(tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    runner = CliRunner()

    pc1 = _pc_env(tmp_path, monkeypatch, "pc1")
    _add_run(pc1, "run_a")
    assert runner.invoke(app, ["sync", "setup", "--folder", str(share)]).exit_code == 0
    status = runner.invoke(app, ["sync", "status"])
    assert "vide" in status.output and "publier ce PC" in status.output
    auto1 = runner.invoke(app, ["sync", "auto"])
    assert auto1.exit_code == 0 and "publication" in auto1.output

    pc2 = _pc_env(tmp_path, monkeypatch, "pc2")
    _add_run(pc2, "run_b")
    assert runner.invoke(app, ["sync", "setup", "--folder", str(share)]).exit_code == 0
    assert "fusionner le partage puis publier ce PC" in runner.invoke(app, ["sync", "status"]).output
    auto2 = runner.invoke(app, ["sync", "auto"])
    assert auto2.exit_code == 0 and "fusion" in auto2.output and "publication" in auto2.output
    conn = sqlite3.connect(pc2)
    assert {r[0] for r in conn.execute("SELECT run_id FROM run")} == {"run_a", "run_b"}
    conn.close()

    monkeypatch.setenv("PATRICK_DB_PATH", pc1)
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "pc1" / "settings.json"))
    assert "fusion" in runner.invoke(app, ["sync", "auto"]).output
    assert "tout est à jour" in runner.invoke(app, ["sync", "status"]).output
    assert "Rien à faire" in runner.invoke(app, ["sync", "auto"]).output


def test_manual_push_refuses_to_overwrite_an_unmerged_share(tmp_path, monkeypatch):
    share = tmp_path / "share"
    runner = CliRunner()
    pc1 = _pc_env(tmp_path, monkeypatch, "pc1")
    _add_run(pc1, "run_a")
    assert runner.invoke(app, ["sync", "push", "--to", str(share)]).exit_code == 0

    pc2 = _pc_env(tmp_path, monkeypatch, "pc2")
    _add_run(pc2, "run_b")
    refused = runner.invoke(app, ["sync", "push", "--to", str(share)])
    assert refused.exit_code == 1 and "pas fusionnées" in refused.output

    forced = runner.invoke(app, ["sync", "push", "--to", str(share), "--force"])
    assert forced.exit_code == 0


def test_merge_dry_run_leaves_the_local_database_alone(tmp_path, monkeypatch):
    share = tmp_path / "share"
    runner = CliRunner()
    pc1 = _pc_env(tmp_path, monkeypatch, "pc1")
    _add_run(pc1, "run_a")
    assert runner.invoke(app, ["sync", "push", "--to", str(share)]).exit_code == 0

    pc2 = _pc_env(tmp_path, monkeypatch, "pc2")
    _add_run(pc2, "run_b")
    preview = tmp_path / "preview.db"
    result = runner.invoke(app, ["sync", "merge", "--from", str(share), "--dry-run-to", str(preview)])

    assert result.exit_code == 0 and "1 run(s) importé(s)" in result.output and "à blanc" in result.output
    conn = sqlite3.connect(pc2)
    assert {r[0] for r in conn.execute("SELECT run_id FROM run")} == {"run_b"}
    conn.close()
    conn = sqlite3.connect(preview)
    assert {r[0] for r in conn.execute("SELECT run_id FROM run")} == {"run_a", "run_b"}
    conn.close()


def test_setup_marks_this_pc_as_the_wealth_reference(tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    _pc_env(tmp_path, monkeypatch, "pc1")
    runner = CliRunner()

    plain = runner.invoke(app, ["sync", "setup", "--folder", str(share)])
    assert plain.exit_code == 0 and "référence" not in plain.output          # défaut : inchangé
    assert "adopté du PC de référence" in runner.invoke(app, ["sync", "status"]).output

    marked = runner.invoke(app, ["sync", "setup", "--folder", str(share), "--wealth-reference"])
    assert "il le publie" in marked.output
    assert "ce PC est la référence" in runner.invoke(app, ["sync", "status"]).output

    runner.invoke(app, ["sync", "setup", "--folder", str(share), "--no-wealth-reference"])
    assert "adopté du PC de référence" in runner.invoke(app, ["sync", "status"]).output
