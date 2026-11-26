"""Résumé du matin lisible sur téléphone (FO28) et démonstration en une commande (FO29), du 25/11."""
from __future__ import annotations

import sys
import types

from typer.testing import CliRunner

from patrick.cli import app as cli_app
from patrick.live import morning
from patrick.tracking import db as trackdb


def _champion(conn, target, horizon, y_pred, p_up):
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    rid = f"r-{target}-{horizon}"
    trackdb.create_run(conn, rid, target, horizon, "snap", "{}", "cfg", "sha", 1)
    trial = trackdb.create_trial(conn, rid, "GLOBAL", "XGBoost", "none", 8, "shap")
    trackdb.add_predictions(conn, trial, fold_index=None, split="live", ts=["2026-11-24", "2026-11-25"], y_true=[None, None],
                            y_pred=[0, y_pred], y_proba=[0.5, 0.6], p_up=[0.5, p_up])
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) VALUES (?, ?, ?, ?, 't')", (target, horizon, rid, trial))


def test_the_morning_page_lists_the_last_signals_by_conviction_without_personal_data(tmp_path):
    conn = trackdb.connect()
    try:
        _champion(conn, "^GSPC", 1, 3, 0.58)
        _champion(conn, "EURUSD=X", 5, 0, 0.21)
        conn.commit()
        path = morning.write(conn, str(tmp_path))
    finally:
        conn.close()
    text = path.read_text(encoding="utf-8")
    assert text.index("EURUSD=X") < text.index("^GSPC")                      # 21 % est plus loin de 50 % que 58 %
    assert "▼ baisse" in text and "▲ hausse" in text and "2026-11-25" in text and "€" not in text


def test_demo_builds_a_synthetic_database_in_its_own_folder(tmp_path, monkeypatch):
    started = {}
    for name in ("PATRICK_DB_PATH", "PATRICK_LIVE_REFRESH", "PATRICK_NO_AUTO_WORKER", "PATRICK_DATA_ROOT", "PATRICK_CACHE_ROOT",
                 "PATRICK_FEATURE_CACHE_ROOT", "PATRICK_SETTINGS_PATH", "PATRICK_INSTRUMENT_LOOKUP", "PATRICK_ADVICE_PREWARM"):
        monkeypatch.setenv(name, "avant")                  # la commande écrit ces variables : monkeypatch les rend après le test
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **kw: started.update(kw)))
    result = CliRunner().invoke(cli_app, ["demo", "--folder", str(tmp_path / "demo"), "--port", "8799"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "demo" / "patrick.db").exists() and started["port"] == 8799
