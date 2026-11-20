"""Laboratoire de stratégies (`patrick/strategylab/`, `/strategies`) : construction des rendements, évaluation, straddle, événements, routes."""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.strategylab import core, events, jobs, prices, service, straddle
from patrick.tracking import db
from patrick.webapp.app import app


# ------------------------------------------------------------------ cours synthétiques
def _prices(seed: int, jumps: dict | None = None, start="2006-01-02", end="2025-06-30", sigma=0.012) -> pd.DataFrame:
    """Marche aléatoire quotidienne ; `jumps` : `{date ISO: rendement}` ajoutés ce jour-là (le jour 0 des événements)."""
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0002, sigma, len(days))
    for d, j in (jumps or {}).items():
        if pd.Timestamp(d) in days:
            rets[days.get_loc(pd.Timestamp(d))] += j
    close = 100 * np.cumprod(1 + rets)
    opn = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.002, len(days)))
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close) * 1.002, "low": np.minimum(opn, close) * 0.998, "close": close}, index=days)


class FakePrices:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames, self.calls = frames, []

    def ohlc(self, symbol: str, start: str):
        self.calls.append(symbol)
        return self.frames.get(symbol)


def _events(symbol: str, dates: list[str], group="tous", entry_price=float("nan")) -> pd.DataFrame:
    df = pd.DataFrame({"symbol": symbol, "at": pd.to_datetime(dates), "entry_price": entry_price, "group": group})
    df.attrs["dropped"] = 0
    return df


def _every(n: int, start="2008-03-03", step_days=45) -> list[str]:
    return [(pd.Timestamp(start) + pd.Timedelta(days=step_days * i)).strftime("%Y-%m-%d") for i in range(n)]


# ------------------------------------------------------------------ rendements : calculs exacts
def test_entry_modes_compute_exact_returns():
    px = _prices(1)
    day = pd.Timestamp("2015-06-10")
    i0 = px.index.get_loc(day)
    ev = _events("AAA", ["2015-06-10"], entry_price=50.0)
    src = FakePrices({"AAA": px})
    cases = {
        "close_prev": px["close"].iloc[i0 + 0] / px["close"].iloc[i0 - 1] - 1,          # k = 1 : clôture du jour 0
        "open_day0": px["close"].iloc[i0] / px["open"].iloc[i0] - 1,                    # k = 1 : le soir même
        "close_day0": px["close"].iloc[i0 + 1] / px["close"].iloc[i0] - 1,
    }
    for entry, expected in cases.items():
        table, skipped = core.build_returns(ev, src, core.EventParams(entry=entry, max_exit=5, cost_bps=0))
        assert not skipped and table.loc[0, "day0"] == day
        assert table.loc[0, "k1"] == pytest.approx(expected), entry
    # k = 3 en close_prev : trois séances après la clôture de la veille
    table, _ = core.build_returns(ev, src, core.EventParams(entry="close_prev", max_exit=5, cost_bps=0))
    assert table.loc[0, "k3"] == pytest.approx(px["close"].iloc[i0 + 2] / px["close"].iloc[i0 - 1] - 1)


def test_costs_are_subtracted_from_every_exit_day():
    px = _prices(2)
    ev = _events("AAA", ["2012-05-15"])
    free, _ = core.build_returns(ev, FakePrices({"AAA": px}), core.EventParams(max_exit=3, cost_bps=0))
    paid, _ = core.build_returns(ev, FakePrices({"AAA": px}), core.EventParams(max_exit=3, cost_bps=25))
    assert [free.loc[0, f"k{k}"] - paid.loc[0, f"k{k}"] for k in (1, 2, 3)] == pytest.approx([0.0025] * 3)


def test_after_close_timestamp_moves_day_zero_to_the_next_session():
    px = _prices(3)
    ev = _events("AAA", ["2015-06-10 16:00:00", "2015-06-10 09:00:00"])
    table, _ = core.build_returns(ev, FakePrices({"AAA": px}), core.EventParams(max_exit=2, cost_bps=0))
    assert sorted(table["day0"].tolist()) == [pd.Timestamp("2015-06-10"), pd.Timestamp("2015-06-11")]


def test_price_entry_uses_the_file_price_and_drops_implausible_ones():
    px = _prices(4)
    first_close = float(px["close"].loc["2015-06-10"])
    ok = _events("AAA", ["2015-06-10"], entry_price=first_close / 1.2)          # première clôture à +20 % : plausible
    absurd = _events("AAA", ["2015-06-10"], entry_price=first_close / 10_000)    # unités différentes : +999 900 % -> écarté
    missing = _events("AAA", ["2015-06-10"])
    src = FakePrices({"AAA": px})
    table, _ = core.build_returns(ok, src, core.EventParams(entry="price", max_exit=3, cost_bps=0))
    assert table.loc[0, "k1"] == pytest.approx(0.2)
    for ev, reason in ((absurd, "incohérent"), (missing, "absent")):
        table, skipped = core.build_returns(ev, src, core.EventParams(entry="price", max_exit=3))
        assert table.empty and any(reason in why for why in skipped)


def test_events_without_prices_or_beyond_the_data_are_counted_not_fatal():
    px = _prices(5, end="2020-12-31")
    ev = pd.concat([_events("AAA", ["2015-03-02", "2030-01-02"]), _events("ZZZ", ["2015-03-02"])], ignore_index=True)
    table, skipped = core.build_returns(ev, FakePrices({"AAA": px}), core.EventParams(max_exit=3))
    assert len(table) == 1 and skipped == {"hors des cours disponibles": 1, "cours introuvables": 1}


def test_recent_events_keep_nan_for_sessions_not_yet_elapsed():
    px = _prices(6, end="2021-06-30")
    ev = _events("AAA", ["2021-06-24"])                                          # 4 séances de données seulement
    table, _ = core.build_returns(ev, FakePrices({"AAA": px}), core.EventParams(entry="close_prev", max_exit=10, cost_bps=0))
    assert not math.isnan(table.loc[0, "k1"]) and math.isnan(table.loc[0, "k9"])


# ------------------------------------------------------------------ évaluation
def _synthetic_world(effect: float, n=24, seed=10):
    """Trois titres, `n` événements chacun ; `effect` = hausse moyenne du jour 0."""
    dates = _every(n)
    frames, ev = {}, []
    for i, sym in enumerate(("AAA", "BBB", "CCC")):
        shifted = [(pd.Timestamp(d) + pd.Timedelta(days=3 * i)).strftime("%Y-%m-%d") for d in dates]
        jumps = {d: effect for d in shifted}
        frames[sym] = _prices(seed + i, jumps)
        ev.append(_events(sym, shifted, group=("A" if i == 0 else "B")))
    return pd.concat(ev, ignore_index=True), FakePrices(frames)


def test_a_real_one_day_effect_is_found_validated_and_declared_robust():
    ev, src = _synthetic_world(effect=0.03)
    res = service.run_event(ev, src, core.EventParams(entry="close_prev", max_exit=10, cost_bps=0, n_boot=500))
    assert res["curve"][0]["mean"] > 0.02 and res["best"]["mean"] > 0.02          # le saut du jour 0 est visible dès J+1, la dérive l'allonge ensuite
    assert res["bootstrap"]["ci_low"][0] > 0 and res["split"]["available"] and res["split"]["holds"]
    assert res["verdict"]["label"] == "robust" and all(res["verdict"]["flags"][f] for f in ("enough_events", "ci_above_zero", "oos_holds", "not_concentrated"))
    assert {g["group"] for g in res["groups"]} == {"A", "B"}
    assert res["n_events"] == 72 and res["n_complete"] == 72 and res["n_symbols"] == 3


def test_pure_noise_is_not_declared_robust():
    ev, src = _synthetic_world(effect=0.0, seed=21)
    res = service.run_event(ev, src, core.EventParams(entry="close_prev", max_exit=15, cost_bps=10, n_boot=500))
    assert res["verdict"]["label"] != "robust"


def test_best_day_chosen_in_sample_can_fail_out_of_sample():
    # 40 événements anciens à +10 % au jour 3, 20 récents à -8 % : le jour 3 gagne sur l'apprentissage et s'effondre ensuite.
    V = np.vstack([np.tile([0.0, 0.0, 0.10, 0.02], (40, 1)), np.tile([0.0, 0.0, -0.08, -0.02], (20, 1))])
    s = core.split_validation(V, 0.67, 500, 1)
    assert s["available"] and s["k"] == 3 and s["train_mean"] > 0.09 and s["test_mean"] < 0 and s["holds"] is False
    assert core.split_validation(V[:8], 0.67, 200, 1)["available"] is False


def test_trade_metrics_known_values():
    m = core.trade_metrics(np.array([0.10, -0.05, 0.20, -0.10]), 100)
    assert m["win_rate"] == 0.5 and m["total_pnl"] == pytest.approx(15.0) and m["profit_factor"] == pytest.approx(2.0)
    assert m["max_drawdown"] == pytest.approx(-10.0) and m["max_losing_streak"] == 1 and m["best"] == 0.20 and m["worst"] == -0.10


def test_curve_bootstrap_and_concentration_basics():
    V = np.array([[0.05, 0.10], [-0.02, 0.01], [0.03, 0.06], [np.nan, 0.02]])
    c = core.curve(V)
    assert c[0]["n"] == 3 and c[1]["n"] == 4 and c[0]["mean"] == pytest.approx(0.02) and c[0]["win"] == pytest.approx(2 / 3)
    C = core.complete_rows(V)
    assert C.shape == (3, 2)
    b = core.bootstrap(np.tile(C, (20, 1)), 300, 1)
    assert b["best_k"] == 2 and sum(b["best_freq"]) == pytest.approx(1.0) and b["ci_low"][1] <= b["ci_high"][1]
    # un seul coup d'éclat porte la moyenne : sans lui elle devient négative
    r = np.array([-0.01] * 19 + [0.5])
    conc = core.concentration(r, np.array(["A"] * 19 + ["B"]), np.array([2020] * 20))
    assert conc["trimmed_mean"] < 0 < r.mean() and conc["top5_symbols"][0]["symbol"] == "B"
    camp = core.campaign(r, 100, n_trades=10, n=2000)
    assert camp["p05"] <= camp["p50"] <= camp["p95"]


def test_parameter_validation_messages():
    for kwargs, message in [({"entry": "x"}, "Mode d'entrée"), ({"max_exit": 0}, "jour de sortie"), ({"cost_bps": 900}, "frais"),
                            ({"split_frac": 0.1}, "anciens"), ({"n_boot": 5}, "rééchantillonnages"), ({"stake": 0}, "mise")]:
        with pytest.raises(core.StrategyError, match=message):
            core.EventParams(**kwargs).validate()


def test_too_few_complete_events_gives_a_clear_error():
    ev = _events("AAA", ["2015-03-02", "2015-06-02", "2015-09-01"])
    with pytest.raises(core.StrategyError, match="trajectoire complète"):
        service.run_event(ev, FakePrices({"AAA": _prices(7)}), core.EventParams(max_exit=5))


# ------------------------------------------------------------------ straddle
def test_black_scholes_put_call_parity_and_atm_approximation():
    s, k, t, v, r = 100.0, 100.0, 7 / 365, 0.4, 0.04
    call, put = straddle.bs(s, k, t, v, "call", r), straddle.bs(s, k, t, v, "put", r)
    assert call - put == pytest.approx(s - k * math.exp(-r * t), abs=1e-9)
    assert straddle.straddle_value(s, k, t, v, r) == pytest.approx(0.8 * s * v * math.sqrt(t), rel=0.05)
    assert straddle.bs(120, 100, 0, 0.3, "call", r) == 20 and straddle.bs(80, 100, 0, 0.3, "put", r) == 20


def test_straddle_wins_on_big_moves_and_loses_on_quiet_days():
    big, calm = _synthetic_world(effect=0.0)[0], None
    dates = _every(30, start="2010-03-01")
    jumps_big = {d: 0.12 * (1 if i % 2 else -1) for i, d in enumerate(dates)}
    big_src = FakePrices({"AAA": _prices(31, jumps_big)})
    calm_src = FakePrices({"AAA": _prices(31, None, sigma=0.004)})
    ev = _events("AAA", dates)
    p = straddle.StraddleParams(n_boot=300)
    big_res = service.run_straddle(ev, big_src, p)
    calm_res = service.run_straddle(ev, calm_src, p)
    assert big_res["best"]["mean"] > 0 and calm_res["best"]["mean"] < 0
    assert big_res["mean_move"] > calm_res["mean_move"] and big_res["cost_per_contract"] == pytest.approx(4 * (0.65 + 2.5 + 0.5))
    assert len(big_res["sensitivity"]) == len(straddle.MATURITIES) * len(straddle.EXIT_RATIOS)
    # un écrasement de volatilité plus fort réduit le rendement moyen à maturité fixée
    row = sorted((c for c in big_res["sensitivity"] if c["maturity"] == 7), key=lambda c: c["exit_ratio"])
    assert row[0]["mean"] < row[-1]["mean"]


def test_straddle_skips_events_without_enough_history():
    px = _prices(8, start="2015-01-01")
    res = straddle.price_event(px["close"].to_numpy(), px.index, 10, straddle.StraddleParams())
    assert res is None


def test_straddle_parameter_validation():
    for kwargs, message in [({"maturity_days": 0}, "maturité"), ({"strike_factor": 2}, "strike"), ({"entry_iv_mult": 9}, "volatilité d'entrée"),
                            ({"exit_iv_ratio": 5}, "ratio"), ({"lookback": 5}, "fenêtre")]:
        with pytest.raises(core.StrategyError, match=message):
            straddle.StraddleParams(**kwargs).validate()


# ------------------------------------------------------------------ événements et cours importés
def test_events_csv_accepts_the_ipo_study_columns_and_drops_bad_rows():
    raw = ("trade_date,issuer,symbol,offer_price,open_price\n2000-05-12,Sequoia,SQSW,8.0,10.25\n120-11-01,Alon,ALDW,16.0,17.0\n"
           "2001-03-02,Foo,bad symbol!,5,6\n2003-04-04,Bar,BAR,12,13\n")
    ev = events.parse_events_csv(raw.encode(), "iposcoop.csv")
    assert list(ev["symbol"]) == ["SQSW", "BAR"] and ev["entry_price"].tolist() == [8.0, 12.0] and ev.attrs["dropped"] == 2
    assert ev["group"].unique().tolist() == ["tous"]


@pytest.mark.parametrize("raw, message", [("a,b\n1,2", "introuvables"), ("symbol\nAAPL", "au moins une colonne"), ("symbol,date\nbad!,x", "aucun événement exploitable")])
def test_events_csv_errors(raw, message):
    with pytest.raises(events.EventsError, match=message):
        events.parse_events_csv(raw.encode(), "e.csv")


def test_apple_keynotes_are_converted_to_new_york_time_and_fall_in_session():
    ev = events.apple_keynotes()
    assert len(ev) == 18 and set(ev["symbol"]) == {"AAPL"}
    assert ev["at"].iloc[0] == pd.Timestamp("2007-01-09 12:00") and ev["at"].iloc[1] == pd.Timestamp("2008-06-09 13:00")
    assert (ev["at"].dt.hour < 16).all()


def test_symbols_and_download_budget():
    assert events.parse_symbols("aapl, MSFT ; ^GSPC  bad! AAPL") == ["AAPL", "MSFT", "^GSPC"]
    csv = b"symbol,date,open,high,low,close\n" + b"\n".join(f"AAA,2020-01-{d:02d},10,11,9,10.5".encode() for d in range(1, 10))
    uploaded = prices.UploadedPrices(csv, "p.csv")
    assert prices.downloads_needed(["AAA", "BBB"], uploaded) == []                       # sans repli : rien à télécharger
    assert prices.downloads_needed(["AAA", "BBB"], prices.UploadedPrices(csv, "p.csv", fallback=FakePrices({}))) == ["BBB"]
    assert prices.downloads_needed(["AAA", "BBB"], FakePrices({})) == ["AAA", "BBB"]
    assert len(uploaded.ohlc("AAA", "2020-01-01")) == 9 and uploaded.ohlc("ZZZ", "2020-01-01") is None
    with pytest.raises(prices.PricesError, match="introuvables"):
        prices.UploadedPrices(b"foo,bar\n1,2", "x.csv")


def test_yahoo_earnings_events_ignore_failed_symbols():
    def fetch(symbol, limit):
        if symbol == "BAD":
            raise RuntimeError("réseau")
        return pd.DataFrame({"published_at": pd.to_datetime(["2024-02-01 21:30:00+00:00", "2024-05-02 21:30:00+00:00"]), "label": ["a", "b"], "group": ["beat", "miss"]})
    ev = events.yahoo_earnings_events(["AAA", "BAD"], 10, fetch)
    assert len(ev) == 2 and ev.attrs["failed"] == ["BAD"] and ev["at"].iloc[0] == pd.Timestamp("2024-02-01 16:30:00")     # New York, après la clôture : 16 h 30
    with pytest.raises(events.EventsError, match="Aucun résultat"):
        events.yahoo_earnings_events(["BAD"], 10, fetch)


# ------------------------------------------------------------------ routes
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    frames = {"AAPL": _prices(41), "MSFT": _prices(42), "AAA": _prices(43)}
    monkeypatch.setattr(prices, "YahooPrices", lambda: FakePrices(frames))
    return TestClient(app)


def _wait(client, job_id):
    for _ in range(240):
        status = client.get(f"/api/strategies/jobs/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.25)
    raise AssertionError("l'étude ne se termine pas")


def test_page_is_a_frame_and_listed_in_the_simulation_menu(client):
    html = client.get("/strategies").text
    assert 'id="st-app"' in html and 'id="st-i18n"' in html and "apple_keynotes" in html
    assert 'href="/strategies"' in client.get("/").text
    assert "Strategies" in client.get("/strategies", cookies={"patrick_lang": "en"}).text


def test_preset_study_end_to_end_and_last_result_is_kept(client):
    assert client.get("/api/strategies/last/event").json() == {"result": None}
    params = '{"entry": "close_prev", "max_exit": 10, "n_boot": 300}'
    job = client.post("/api/strategies/run", data={"kind": "event", "source": "preset", "preset": "apple_keynotes", "params": params}).json()
    status = _wait(client, job["id"])
    assert status["status"] == "done", status
    res = client.get("/api/strategies/last/event").json()["result"]
    assert res["kind"] == "event" and res["n_events"] == 18 and res["n_symbols"] == 1 and len(res["curve"]) == 10
    assert res["verdict"]["label"] in ("robust", "fragile", "none")


def test_file_upload_study_with_uploaded_prices_and_straddle_kind(client):
    ev_csv = "symbol,date,group\n" + "\n".join(f"AAA,{d},g{i % 2}" for i, d in enumerate(_every(40, "2010-03-01"))) + "\n"
    px = _prices(44)
    px_csv = "symbol,date,open,high,low,close\n" + "\n".join(f"AAA,{d:%Y-%m-%d},{r.open},{r.high},{r.low},{r.close}" for d, r in px.iterrows())
    files = {"events_file": ("ev.csv", ev_csv.encode(), "text/csv"), "prices_file": ("px.csv", px_csv.encode(), "text/csv")}
    job = client.post("/api/strategies/run", data={"kind": "straddle", "source": "file", "params": '{"n_boot": 300}'}, files=files).json()
    assert _wait(client, job["id"])["status"] == "done"
    res = client.get("/api/strategies/last/straddle").json()["result"]
    assert res["kind"] == "straddle" and res["n_events"] == 40 and res["sensitivity"] and {g["group"] for g in res["groups"]} == {"g0", "g1"}


def test_uploaded_prices_do_not_fall_back_to_yahoo_unless_asked(client):
    dates = _every(30, "2010-03-01")
    ev_csv = ("symbol,date\n" + "\n".join(f"AAA,{d}\nAAPL,{d}" for d in dates) + "\n").encode()          # AAPL est absent du fichier de cours, présent chez Yahoo (faux)
    px = _prices(45)
    px_csv = ("symbol,date,open,high,low,close\n" + "\n".join(f"AAA,{d:%Y-%m-%d},{r.open},{r.high},{r.low},{r.close}" for d, r in px.iterrows())).encode()
    files = {"events_file": ("ev.csv", ev_csv, "text/csv"), "prices_file": ("px.csv", px_csv, "text/csv")}
    params = '{"max_exit": 5, "n_boot": 300}'
    job = client.post("/api/strategies/run", data={"kind": "event", "source": "file", "params": params}, files=files).json()
    assert _wait(client, job["id"])["status"] == "done"
    res = client.get("/api/strategies/last/event").json()["result"]
    assert res["n_symbols"] == 1 and res["skipped"] == {"cours introuvables": 30}                      # AAPL écarté, jamais téléchargé
    job = client.post("/api/strategies/run", data={"kind": "event", "source": "file", "params": params, "fallback": "true"}, files=files).json()
    assert _wait(client, job["id"])["status"] == "done"
    assert client.get("/api/strategies/last/event").json()["result"]["n_symbols"] == 2


def test_yahoo_earnings_source_runs_in_the_job(client, monkeypatch):
    def fake(symbol, limit):
        return pd.DataFrame({"published_at": pd.to_datetime([f"{y}-{m:02d}-15 13:00:00+00:00" for y in range(2010, 2024) for m in (2, 5, 8, 11)]),
                             "label": "x", "group": ["beat", "miss"] * 28})
    monkeypatch.setattr("patrick.research.event_sources.yahoo_earnings", fake)
    job = client.post("/api/strategies/run", data={"kind": "event", "source": "yahoo", "tickers": "AAPL, MSFT", "quarters": "40", "params": '{"max_exit": 5, "n_boot": 300}'}).json()
    assert _wait(client, job["id"])["status"] == "done"
    res = client.get("/api/strategies/last/event").json()["result"]
    assert res["n_symbols"] == 2 and {g["group"] for g in res["groups"]} == {"beat", "miss"}


def test_bad_inputs_are_rejected_immediately(client):
    def run(**data):
        return client.post("/api/strategies/run", data=data, files=data.pop("files", None))
    assert run(kind="nope", source="preset", preset="apple_keynotes").status_code == 400
    assert run(kind="event", source="preset", preset="inconnu").status_code == 400
    assert run(kind="event", source="file").status_code == 400                                       # fichier manquant
    assert run(kind="event", source="yahoo", tickers="").status_code == 400
    bad = client.post("/api/strategies/run", data={"kind": "event", "source": "preset", "preset": "apple_keynotes", "params": '{"max_exit": 0}'})
    assert bad.status_code == 400 and "jour de sortie" in bad.json()["detail"]
    unknown = client.post("/api/strategies/run", data={"kind": "event", "source": "preset", "preset": "apple_keynotes", "params": '{"pirate": 1}'})
    assert unknown.status_code == 400 and "inconnu" in unknown.json()["detail"]
    assert client.get("/api/strategies/last/inconnu").status_code == 400
    assert client.get("/api/strategies/jobs/nope").status_code == 404


def test_a_failing_study_reports_its_error_without_crashing(client):
    ev_csv = b"symbol,date\nZZZ,2015-03-02\nZZZ,2015-06-02\n"
    job = client.post("/api/strategies/run", data={"kind": "event", "source": "file", "params": "{}"}, files={"events_file": ("e.csv", ev_csv, "text/csv")}).json()
    status = _wait(client, job["id"])
    assert status["status"] == "error" and "Aucun événement exploitable" in status["error"]


def test_only_one_study_per_kind_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path))
    first = jobs.start("event", lambda progress: time.sleep(0.5) or {"kind": "event"})
    assert jobs.start("event", lambda progress: {"kind": "event"}).id == first.id
    for _ in range(240):                                 # attente bornée plutôt qu'un délai fixe (machine chargée)
        if jobs.get(first.id).status != "running":
            break
        time.sleep(0.25)
    assert jobs.get(first.id).status == "done" and jobs.load_last("event") == {"kind": "event"}
