"""Questions en langage naturel sur un run (A27) : contexte compact, requête envoyée, refus, erreurs, garde-fou de fuite, route."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from patrick.analysis import run_qa
from patrick.tracking import db


def _make_run(conn, run_id="run1"):
    cfg = {"name": run_id, "objective": {"target_symbol": "^VIX", "horizons": [5]}, "validation": {"scheme": "walkforward"},
           "universe": {"yf_tickers": ["^VIX", "^GSPC"], "fred_series": {"DGS10": "DGS10"}}}
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, "^VIX", 5, f"snap_{run_id}", json.dumps(cfg), "cfghash", "sha", 42)
    db.finish_run(conn, run_id, status="done", n_trials=1)
    trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.52})
    db.add_fold_metrics(conn, trial_id, 0, "holdout", {"F1_dir": 0.51})
    db.save_dm_result(conn, run_id, {"baseline": "majority", "dm_stat": -0.4, "p_value": 0.69}, sample="holdout")
    ts = pd.bdate_range("2026-03-02", periods=200)
    y = np.random.default_rng(0).integers(0, 2, len(ts))
    db.add_predictions(conn, trial_id, fold_index=1, split="test", ts=ts, y_true=y, y_pred=y, y_proba=np.full(len(ts), 0.6), p_up=None)
    return trial_id


class _FakeMessages:
    def __init__(self, response):
        self.response, self.requests = response, []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


def _client(text="Le F1 de 0,51 au holdout est celui du hasard.", stop="end_turn"):
    response = SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                               stop_reason=stop, model=run_qa.MODEL, usage=SimpleNamespace(input_tokens=1200, output_tokens=40,
                                                                                            cache_read_input_tokens=0))
    messages = _FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "patrick.db"))
    yield c
    c.close()


def test_context_is_compact_and_carries_the_figures(conn):
    _make_run(conn)
    ctx = run_qa.run_context(conn, "run1")
    assert ctx["run"]["target"] == "^VIX" and ctx["holdout"] == pytest.approx(0.51)
    assert ctx["diebold_mariano"]["p_value"] == pytest.approx(0.69)
    assert ctx["evaluated_period"] == {"first": "2026-03-02", "last": pd.bdate_range("2026-03-02", periods=200)[-1].strftime("%Y-%m-%d")}
    assert ctx["config"]["universe_size"] == 2 and ctx["config"]["fred_series"] == 1
    assert len(json.dumps(ctx)) < 20000
    assert run_qa.run_context(conn, "nope") is None


def test_lists_are_truncated():
    out = run_qa._compact({"x": list(range(30)), "f": 0.123456789})
    assert out["x"][-1] == "… 18 de plus" and len(out["x"]) == run_qa.MAX_LIST + 1 and out["f"] == 0.1235


def test_ask_sends_rules_cached_context_and_fallbacks(conn):
    _make_run(conn)
    ctx = run_qa.run_context(conn, "run1")
    client, messages = _client()
    out = run_qa.ask("  Le modèle bat-il la référence ?  ", ctx, client=client)
    req = messages.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["fallbacks"] == "default" and req["betas"] == [run_qa.FALLBACK_BETA]
    assert req["output_config"] == {"effort": "medium"} and "thinking" not in req and "temperature" not in req
    assert req["system"][0]["text"] == run_qa.SYSTEM and req["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert '"^VIX"' in req["system"][1]["text"] and req["messages"] == [{"role": "user", "content": "Le modèle bat-il la référence ?"}]
    assert out["answer"].startswith("Le F1") and out["refused"] is False and out["usage"]["input"] == 1200


def test_leak_note_counts_dates_after_the_cutoff(conn):
    _make_run(conn)
    ctx = run_qa.run_context(conn, "run1")
    leak = run_qa.leak_note(ctx)
    assert leak["cutoff"] == "2026-06-30" and 0 < leak["clean_share"] < 1          # mars-décembre 2026 : seule la fin est propre
    assert run_qa.leak_note({"evaluated_period": {}})["clean_share"] is None


def test_refusal_and_empty_question():
    client, _ = _client(text="", stop="refusal")
    out = run_qa.ask("question", {"evaluated_period": {}}, client=client)
    assert out["refused"] is True and "refusé" in out["answer"]
    with pytest.raises(ValueError):
        run_qa.ask("   ", {}, client=client)


def test_route_answers_404s_and_explains_a_missing_sdk(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app

    path = tmp_path / "patrick.db"
    monkeypatch.setenv("PATRICK_DB_PATH", str(path))
    c = db.connect(str(path))
    _make_run(c)
    c.close()
    client = TestClient(app)
    page = client.get("/runs/run1").text
    assert "Questions sur ce run" in page and 'data-run-id="run1"' in page and "run_qa.js" in page
    fake, _ = _client()
    monkeypatch.setattr(run_qa, "_client", lambda: fake)
    resp = client.post("/api/runs/run1/ask", json={"question": "Résume ce run"})
    assert resp.status_code == 200 and resp.json()["answer"].startswith("Le F1")
    assert client.post("/api/runs/nope/ask", json={"question": "x"}).status_code == 404

    def unavailable():
        raise run_qa.QAUnavailable("Le module « anthropic » n'est pas installé")
    monkeypatch.setattr(run_qa, "_client", unavailable)
    resp = client.post("/api/runs/run1/ask", json={"question": "x"})
    assert resp.status_code == 503 and "anthropic" in resp.json()["detail"]


def test_missing_credentials_become_a_clear_message():
    class NoKey:
        def create(self, **kwargs):
            raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set."')
    client = SimpleNamespace(beta=SimpleNamespace(messages=NoKey()))
    with pytest.raises(run_qa.QAUnavailable, match="ANTHROPIC_API_KEY"):
        run_qa.ask("question", {"evaluated_period": {}}, client=client)
