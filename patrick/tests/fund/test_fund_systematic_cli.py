"""`patrick fund rule-create|rule-list|rule-apply`. Aucun réseau."""
from __future__ import annotations

import json

import fund_support as fs
import pytest
from test_fund_systematic import SCORES, TODAY, _config, _model
from typer.testing import CliRunner

from patrick.cli import app
from patrick.fund import store
from patrick.tracking import db as trackdb


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def test_create_list_apply_through_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect()
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _model(conn, scores=SCORES)
    conn.close()
    cfg_file = tmp_path / "rule.json"
    cfg_file.write_text(json.dumps(_config(tid)), encoding="utf-8")
    runner = CliRunner()

    created = runner.invoke(app, ["fund", "rule-create", "--strategy", sid, "--name", "ML seuils",
                                  "--config", str(cfg_file)])
    assert created.exit_code == 0, created.output
    rule_id = created.output.split()[-1]

    listed = runner.invoke(app, ["fund", "rule-list", "--strategy", sid])
    assert rule_id in listed.output and "0.6" in listed.output

    applied = runner.invoke(app, ["fund", "rule-apply", rule_id, "--today", TODAY.isoformat()])
    assert applied.exit_code == 0, applied.output
    assert "5 ordre(s) placé(s)" in applied.output
    again = runner.invoke(app, ["fund", "rule-apply", rule_id, "--today", TODAY.isoformat()])
    assert "0 ordre(s) placé(s), 5 déjà présent(s)" in again.output


def test_create_with_a_bad_threshold_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect()
    sid = store.create_strategy(conn, "Macro CTO", "CTO", 100_000, "2026-01-05")
    tid = _model(conn)
    conn.close()
    cfg_file = tmp_path / "rule.json"
    cfg_file.write_text(json.dumps(_config(tid, enter=0.4)), encoding="utf-8")

    result = CliRunner().invoke(app, ["fund", "rule-create", "--strategy", sid, "--name", "x",
                                      "--config", str(cfg_file)])

    assert result.exit_code == 1 and "Refusé" in result.output
