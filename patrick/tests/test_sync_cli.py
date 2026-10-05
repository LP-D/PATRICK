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
