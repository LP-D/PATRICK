"""Signal regroupé par paire cible-horizon : base, commande `patrick audit signal`, carte de Synthèse, cartes de lots (`tracking/pooled_signal.py`)."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from patrick.cli import app as cli_app
from patrick.tracking import db, pooled_signal
from patrick.webapp import launch_batches
from patrick.webapp.app import app


def _seed_pair(conn, target: str, horizon: int, run_ids: list[str], *, signal: float, n: int = 260, seed: int = 0) -> None:
    """Un run terminé par identifiant, dont le holdout porte `signal` (0 = bruit pur) sur P(hausse) ; mêmes dates, même direction réelle."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    dates = [d.strftime("%Y-%m-%d") for d in __import__("pandas").bdate_range("2025-06-01", periods=n)]
    for i, run_id in enumerate(run_ids):
        db.create_run(conn, run_id, target, horizon, "snap", "{}", "cfg", "sha", 1)
        trial = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial)
        p_up = 0.5 + signal * (y - 0.5) + rng.normal(scale=0.35, size=n) * 0.2 + 0.0 * i
        db.add_predictions(conn, trial, fold_index=0, split="holdout", ts=dates, y_true=np.where(y == 1, 3.0, 0.0).tolist(),
                           y_pred=np.where(p_up > 0.5, 3, 0).tolist(), y_proba=[0.6] * n, p_up=np.clip(p_up, 0.01, 0.99).tolist())
        db.finish_run(conn, run_id, status="done", n_trials=1)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    conn = db.connect(path)
    db.upsert_snapshot(conn, "snap", "h", 1, 1, "api")
    _seed_pair(conn, "^VIX", 5, ["vix_a", "vix_b"], signal=0.55, seed=1)           # signal net
    for k in range(25):
        _seed_pair(conn, f"AB{k}.PA", 1, [f"ab{k}_a"], signal=0.0, seed=300 + k)       # bruit pur : de quoi donner du poids à la correction
    conn.commit()
    yield conn
    conn.close()


def test_compute_all_flags_the_real_signal_and_none_of_the_noise(seeded):
    rows = pooled_signal.compute_all(seeded, n_shift=400)
    by_target = {r["target"]: r for r in rows}
    assert by_target["^VIX"]["significant"] is True and by_target["^VIX"]["n_runs"] == 2
    assert by_target["^VIX"]["auc"] > 0.8
    assert not any(r["significant"] for r in rows if r["target"] != "^VIX")
    assert all(r["q_value"] is not None for r in rows)


def test_save_load_and_summary_roundtrip(seeded):
    assert pooled_signal.summary(seeded) is None                      # jamais calculé
    rows = pooled_signal.compute_all(seeded, n_shift=400)
    pooled_signal.save(seeded, rows)
    pooled_signal.save(seeded, rows)                                   # idempotent : la table est remplacée, pas complétée
    loaded = pooled_signal.load(seeded)
    assert len(loaded) == len(rows) == 26
    summary = pooled_signal.summary(seeded)
    assert summary["n_tested"] == 26 and summary["n_significant"] >= 1 and summary["alpha"] == 0.10
    assert summary["classes"][0]["class"] == "volatility_index"       # la plus forte AUC regroupée en tête


def test_suspect_runs_do_not_enter_the_pooled_test(seeded):
    seeded.execute("UPDATE run SET config_json = ? WHERE run_id = 'vix_a'", ('{"objective": {"target_source": "fred"}}',))
    seeded.commit()
    pairs = pooled_signal.holdout_pairs(seeded)
    assert pairs[("^VIX", 5)]["run_ids"] == ["vix_b"]                  # le run marqué suspect (cible macro retirée) est écarté


def test_the_audit_signal_command_writes_the_table(seeded):
    result = CliRunner().invoke(cli_app, ["audit", "signal", "--shifts", "200"])
    assert result.exit_code == 0, result.output
    assert "paires cible-horizon testées" in result.output and "volatility_index" in result.output
    assert len(pooled_signal.load(seeded)) == 26


def test_the_synthesis_page_shows_the_pooled_signals_card(seeded):
    client = TestClient(app)
    assert "Signaux regroupés" not in client.get("/").text
    pooled_signal.save(seeded, pooled_signal.compute_all(seeded, n_shift=200))
    html = client.get("/").text
    assert "Signaux regroupés" in html and "26" in html


def test_batch_cards_put_measured_classes_first_and_show_the_measure():
    sources = {"^GSPC": "yfinance", "^VIX": "yfinance", "GC=F": "yfinance"}
    plain = launch_batches.by_asset_class(["^GSPC", "^VIX", "GC=F"], [], sources)
    assert plain[0]["key"] == "equities_us" and plain[0]["auc"] is None
    ranked = launch_batches.by_asset_class(["^GSPC", "^VIX", "GC=F"], [], sources, evidence={
        "volatility_index": {"auc": 0.61, "n_significant": 19}, "equities_us": {"auc": 0.52, "n_significant": 3}})
    assert [c["key"] for c in ranked][:2] == ["volatility_index", "equities_us"]
    assert ranked[0]["auc"] == 0.61 and ranked[0]["n_significant"] == 19 and ranked[2]["auc"] is None


def test_the_launch_batches_fragment_displays_the_class_auc(seeded):
    pooled_signal.save(seeded, pooled_signal.compute_all(seeded, n_shift=200))
    html = TestClient(app).get("/fragments/launch-batches?family=ml").text
    assert "AUC 0." in html


def test_the_table_refreshes_itself_when_empty_or_old_and_only_then(seeded, monkeypatch):
    calls = []
    real = pooled_signal.compute_all
    monkeypatch.setattr(pooled_signal, "compute_all", lambda conn, **kw: calls.append(1) or real(conn, n_shift=400))

    first = pooled_signal.refresh_if_stale(seeded)
    again = pooled_signal.refresh_if_stale(seeded)

    assert first["refreshed"] is True and first["n_pairs"] == 26 and first["n_significant"] >= 1
    assert again == {"refreshed": False, "n_pairs": 26, "n_significant": None} and len(calls) == 1
    seeded.execute("UPDATE pooled_signal SET computed_at = datetime('now', '-8 days')")
    seeded.commit()
    assert pooled_signal.refresh_if_stale(seeded)["refreshed"] is True and len(calls) == 2
    assert pooled_signal.summary(seeded)["n_tested"] == 26


def test_a_refresh_with_nothing_testable_keeps_the_previous_measure(seeded, monkeypatch):
    pooled_signal.save(seeded, pooled_signal.compute_all(seeded, n_shift=200))
    seeded.execute("UPDATE pooled_signal SET computed_at = datetime('now', '-30 days')")
    seeded.commit()
    monkeypatch.setattr(pooled_signal, "compute_all", lambda conn, **kw: [])

    assert pooled_signal.refresh_if_stale(seeded)["refreshed"] is False
    assert len(pooled_signal.load(seeded)) == 26


def test_the_daily_refresh_never_raises_when_the_pooled_signal_fails(tmp_path, monkeypatch):
    from patrick import live_refresh

    def boom(conn, **kw):
        raise RuntimeError("panne")
    monkeypatch.setattr(pooled_signal, "refresh_if_stale", boom)

    assert live_refresh.refresh_pooled_signal(str(tmp_path / "patrick.db")) is None
