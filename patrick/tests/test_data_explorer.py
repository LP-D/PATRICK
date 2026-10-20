"""Explorateur de données (`patrick/analysis/data_explorer.py`, `tracking/watchlists.py`, `/donnees`) : vue point dans le temps, révisions, calendrier, import, listes."""
from __future__ import annotations

import base64
import io
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.analysis import data_explorer as dx
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.tracking import watchlists as wl
from patrick.webapp import data_routes
from patrick.webapp.app import app


def _frame(n=400, seed=1, shift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    price = 100 * np.cumprod(1 + rng.normal(0, 0.01, n)) + shift
    monthly = pd.Series(np.nan, index=idx)
    monthly.iloc[::21] = np.arange(len(monthly.iloc[::21])) * 0.1 + 2.0 + shift
    frozen = pd.Series(np.cumsum(rng.normal(0, 1, n)), index=idx)
    frozen.iloc[-60:] = frozen.iloc[-61]
    return pd.DataFrame({"TEST": price, "monthly": monthly.ffill(), "frozen": frozen, "empty": np.nan}, index=idx)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    s = DataStore()
    older = _frame()
    s.save("raw_TEST", older, meta={"pit_version": "pit-test"})
    newer = _frame(n=420)
    newer.iloc[10:15, 1] += 5.0                                                                       # historique réécrit
    s.save("raw_TEST", newer, meta={"pit_version": "pit-test"})
    return s


def test_lake_index_lists_keys_with_kind_and_counts(store):
    out = dx.lake_index(store)
    row = out["keys"][0]
    assert out["n_keys"] == 1 and out["n_snapshots"] == 2 and row["key"] == "raw_TEST" and row["kind"] == "raw" and row["symbol"] == "TEST"
    assert row["n_snapshots"] == 2 and row["rows"] == 420 and row["cols"] == 4 and row["pit_version"] == "pit-test"
    store.save("user_mine", _frame().iloc[:, :1])
    assert {k["key"]: k["kind"] for k in dx.lake_index(store)["keys"]} == {"raw_TEST": "raw", "user_mine": "user"}


def test_frame_detail_flags_stale_empty_and_respects_as_of(store):
    d = dx.frame_detail(store, "raw_TEST")
    by = {c["column"]: c for c in d["columns"]}
    assert by["TEST"]["status"] == "ok" and by["monthly"]["status"] == "ok" and by["frozen"]["status"] == "stale" and by["empty"]["status"] == "empty"
    assert by["monthly"]["typical_days"] == pytest.approx(29, abs=3) and by["frozen"]["stale_days"] > 60
    assert d["counts"] == {"ok": 2, "stale": 1, "empty": 1} and d["columns"][0]["column"] == "frozen"      # figées en tête
    json.dumps(d, allow_nan=False)
    early = dx.frame_detail(store, "raw_TEST", as_of="2024-06-03")
    assert early["visible_rows"] < early["rows"] and early["as_of"] == "2024-06-03" and all((c["last_date"] or "") <= "2024-06-03" for c in early["columns"])
    assert {c["column"]: c["status"] for c in early["columns"]}["frozen"] == "ok"                       # le gel n'existait pas encore


def test_snapshot_in_force_on_a_date_is_the_latest_one_created_by_then(store):
    snaps = store.list_snapshots("raw_TEST")
    assert dx.snapshot_at(store, "raw_TEST", "2024-02-01") is None                                       # le lake n'existait pas encore
    assert dx.snapshot_at(store, "raw_TEST", "2999-01-01")["snapshot_id"] == snaps[-1]["snapshot_id"]
    assert dx.frame_detail(store, "raw_TEST", as_of="2025-01-01")["known_snapshot"] is None and len(snaps) == 2


def test_frame_detail_errors(store):
    for kwargs, code in (({"key": "raw_NOPE"}, "unknown_key"), ({"key": "raw_TEST", "snapshot_id": "x"}, "unknown_snapshot"),
                         ({"key": "raw_TEST", "as_of": "pas une date"}, "bad_date"), ({"key": "raw_TEST", "as_of": "1990-01-01"}, "before_start")):
        with pytest.raises(dx.DataError, match=code):
            dx.frame_detail(store, **kwargs)


def test_column_series_hides_the_future_and_overlays_a_snapshot(store):
    snaps = store.list_snapshots("raw_TEST")
    out = dx.column_series(store, "raw_TEST", "monthly", snaps[-1]["snapshot_id"], "2024-09-02", compare=snaps[0]["snapshot_id"])
    assert max(out["dates"]) <= "2024-09-02" and min(out["after_dates"]) > "2024-09-02" and out["compare"]["snapshot_id"] == snaps[0]["snapshot_id"]
    assert len(out["dates"]) == len(out["values"]) and max(out["compare"]["dates"]) <= "2024-09-02"
    with pytest.raises(dx.DataError, match="unknown_column"):
        dx.column_series(store, "raw_TEST", "nope")


def test_snapshot_revisions_finds_rewritten_history_and_new_rows(store):
    a, b = (e["snapshot_id"] for e in store.list_snapshots("raw_TEST"))
    out = dx.snapshot_revisions(store, "raw_TEST", b, a)                                                  # l'ordre demandé n'importe pas
    assert out["older"] == a and out["newer"] == b and out["rows_only_newer"] == 20 and out["rows_only_older"] == 0
    cols = {c["column"]: c for c in out["columns"]}
    assert cols["monthly"]["changed"] >= 5 and cols["monthly"]["max_rel"] > 0.5 and cols["monthly"]["first"] >= "2024-01-15"
    assert out["cells_changed"] >= 5 and out["n_columns_affected"] == len(out["columns"])
    json.dumps(out, allow_nan=False)


def test_snapshot_revisions_clean_when_only_rows_are_appended(store, tmp_path):
    s2 = DataStore(str(tmp_path / "store2"))
    base = _frame()
    s2.save("raw_X", base)
    s2.save("raw_X", pd.concat([base, _frame(n=450).iloc[400:]]))
    a, b = (e["snapshot_id"] for e in s2.list_snapshots("raw_X"))
    out = dx.snapshot_revisions(s2, "raw_X", a, b)
    assert out["cells_changed"] == 0 and out["columns"] == [] and out["rows_only_newer"] == 50


class _FakeSeriesStore:
    def __init__(self, last):
        self.last = last

    def series_observation(self, sid):
        return {"date_max": self.last.get(sid, self.last["*"])}


def test_release_calendar_orders_by_estimated_date_and_marks_late_series():
    from patrick.config import defaults as D
    ids = sorted({**D.FEATURE_ONLY_FRED_SERIES, **D.MACRO_ONLY_FRED_SERIES}.values())
    late_id = ids[0]
    cal = dx.release_calendar(_FakeSeriesStore({"*": "2026-10-10", late_id: "2024-01-02"}), as_of="2026-10-20")
    assert len(cal["rows"]) == len(ids) and cal["as_of"] == "2026-10-20"
    dates = [r["next_expected"] for r in cal["rows"]]
    assert dates == sorted(dates) and {r["series"]: r for r in cal["rows"]}[late_id]["state"] == "late" and cal["n_late"] >= 1
    json.dumps(cal, allow_nan=False)
    unknown = dx.release_calendar(_FakeSeriesStore({"*": None}), as_of="2026-10-20")
    assert all(r["state"] == "unknown" for r in unknown["rows"]) and unknown["rows"][0]["next_expected"] is None


def test_watchlist_overview_reads_only_the_price_column_and_lists_missing_symbols(store):
    idx = pd.bdate_range("2025-01-01", periods=300)
    store.save("raw_AAA", pd.DataFrame({"AAA": np.linspace(100, 130, 300), "other": np.arange(300.0)}, index=idx))
    store.save("raw_CLOSE", pd.DataFrame({"Close": np.linspace(50, 40, 300)}, index=idx))
    out = dx.watchlist_overview(store, ["AAA", "CLOSE", "MISSING"], as_of="2026-03-05")
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["AAA"]["in_lake"] and by["AAA"]["last_price"] == pytest.approx(130.0) and by["AAA"]["d1"] > 0 and by["AAA"]["d252"] > 0 and len(by["AAA"]["spark"]) <= 40
    assert by["CLOSE"]["d21"] < 0 and by["MISSING"] == {"symbol": "MISSING", "in_lake": False} and out["n_missing"] == 1
    assert dx.lake_symbols(store)[:2] == ["AAA", "CLOSE"]


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_parse_upload_handles_semicolon_decimal_comma_and_day_first_dates():
    rows = "\n".join(f"{d.strftime('%d/%m/%Y')};{100 + i * 0.5:.2f}".replace(".", ",") + f";texte{i}" for i, d in enumerate(pd.bdate_range("2024-01-01", periods=60)))
    df = dx.parse_upload("prix.csv", _csv("Date;Prix;Libellé\n" + rows))
    assert list(df.columns) == ["Prix"] and len(df) == 60 and df.index[0] == pd.Timestamp("2024-01-01") and df["Prix"].iloc[1] == pytest.approx(100.5)
    assert df.attrs["dropped"] == ["Libellé"] and df.attrs["dayfirst"] is True and df.attrs["date_column"] == "Date"


def test_parse_upload_reports_bad_and_duplicate_dates_and_sorts():
    text = "date,v\n2024-01-03,3\n2024-01-01,1\nnot a date,9\n2024-01-02,2\n2024-01-02,22\n"
    df = dx.parse_upload("x.csv", _csv(text))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-01-01", "2024-01-02", "2024-01-03"] and df["v"].tolist() == [1, 22, 3]
    assert df.attrs["bad_dates"] == 1 and df.attrs["duplicates"] == 1


def test_parse_upload_reads_excel_and_rejects_bad_input():
    buf = io.BytesIO()
    pd.DataFrame({"jour": pd.bdate_range("2024-01-01", periods=40), "x": range(40), "y": np.linspace(1, 2, 40)}).to_excel(buf, index=False)
    df = dx.parse_upload("a.xlsx", buf.getvalue())
    assert list(df.columns) == ["x", "y"] and len(df) == 40 and df.attrs["date_column"] == "jour"
    with pytest.raises(dx.DataError, match="too_few_columns"):
        dx.parse_upload("a.csv", _csv("date\n2024-01-01\n"))
    with pytest.raises(dx.DataError, match="too_large"):
        dx.parse_upload("a.csv", b"x" * (dx.MAX_IMPORT_BYTES + 1))
    with pytest.raises(dx.DataError, match="bad_file"):
        dx.parse_upload("a.xlsx", b"pas un classeur")
    with pytest.raises(dx.DataError, match="unknown_column"):
        dx.parse_upload("a.csv", _csv("date,v\n2024-01-01,1\n"), date_column="zzz")


def test_preview_import_flags_frozen_gaps_and_aberrant_values():
    idx = pd.bdate_range("2023-01-02", periods=300)
    rng = np.random.default_rng(5)
    v = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.005, 300)), index=idx)
    v.iloc[100:108] = v.iloc[99]                                                                      # prix figés
    v.iloc[200] = v.iloc[199] * 40                                                                    # valeur aberrante
    frame = pd.DataFrame({"px": v})
    frame.attrs.update({"date_column": "date", "dayfirst": False, "dropped": [], "n_raw_rows": 300, "bad_dates": 0, "duplicates": 0})
    prev = dx.preview_import(frame)
    reasons = {i["reason"] for i in prev["issues"]}
    assert prev["ok"] and {"prix_figes", "rendement_aberrant"} <= reasons and prev["rows"] == 300 and len(prev["head"]) == 5
    json.dumps(prev, allow_nan=False)
    short = dx.preview_import(frame.iloc[:10])
    assert short["ok"] is False


def test_commit_import_writes_a_user_key_and_never_a_pipeline_key(store):
    frame = _frame().iloc[:, :2]
    frame.attrs["secret"] = "x"
    out = dx.commit_import(store, "ma_serie", frame, "ma_serie.csv")
    assert out["key"] == "user_ma_serie" and store.exists("user_ma_serie") and not store.exists("raw_ma_serie")
    entry = store.latest_entry("user_ma_serie")
    assert entry["pit_version"] == "user-supplied" and entry["source"] == "user_import" and entry["filename"] == "ma_serie.csv"
    out2 = dx.commit_import(store, "raw_TEST", frame, "x.csv")                                         # un nom « raw_ » reste dans l'espace user_
    assert out2["key"] == "user_raw_test" and store.list_snapshots("raw_TEST")[-1]["rows"] == 420
    for bad in ("Bad Name", "../x", "", "a" * 41, "é"):
        with pytest.raises(dx.DataError, match="bad_name"):
            dx.commit_import(store, bad, frame, "x.csv")
    with pytest.raises(dx.DataError, match="too_short"):
        dx.commit_import(store, "court", frame.iloc[:5], "x.csv")


def test_decode_payload():
    assert dx.decode_payload({"filename": "a.csv", "csv": "x"}) == ("a.csv", b"x")
    assert dx.decode_payload({"b64": base64.b64encode(b"abc").decode()}) == ("import.csv", b"abc")
    with pytest.raises(dx.DataError, match="no_file"):
        dx.decode_payload({})


# ------------------------------------------------------------------------------------------------------ listes de suivi
@pytest.fixture
def conn(tmp_path):
    c = trackdb.connect(str(tmp_path / "w.db"))
    yield c
    c.close()


def test_watchlist_crud_normalises_inputs(conn):
    wid = wl.create(conn, "  Énergie  ", "xom, CVX  ^GSPC;XOM", "Énergie, À surveiller, énergie, <b>", "une note")
    item = wl.get(conn, wid)
    assert item["name"] == "Énergie" and item["symbols"] == ["xom", "CVX", "^GSPC", "XOM"] and item["tags"] == ["énergie", "à surveiller", "b"] and item["note"] == "une note"
    wl.update(conn, wid, symbols=["AAPL"], note="autre")
    again = wl.get(conn, wid)
    assert again["symbols"] == ["AAPL"] and again["name"] == "Énergie" and again["note"] == "autre" and again["updated_at"] >= item["updated_at"]
    assert [w["name"] for w in wl.list_all(conn)] == ["Énergie"]
    wl.delete(conn, wid)
    assert wl.list_all(conn) == []


def test_watchlist_validation(conn):
    wid = wl.create(conn, "A")
    for call, code in ((lambda: wl.create(conn, "  "), "name_required"), (lambda: wl.create(conn, "a"), "name_taken"), (lambda: wl.create(conn, "B", "ok, <script>"), "bad_symbol"),
                       (lambda: wl.create(conn, "C", [f"S{i}" for i in range(201)]), "too_many_symbols"), (lambda: wl.update(conn, 999, name="x"), "not_found"),
                       (lambda: wl.delete(conn, 999), "not_found")):
        with pytest.raises(wl.WatchlistError, match=code):
            call()
    other = wl.create(conn, "B")
    with pytest.raises(wl.WatchlistError, match="name_taken"):
        wl.update(conn, other, name="A")
    assert wl.get(conn, wid)["name"] == "A" and wl.get(conn, 12345) is None


# ----------------------------------------------------------------------------------------------------------------- API
@pytest.fixture
def client(store, tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    return TestClient(app)


def test_pages_and_read_api(client):
    r = client.get("/donnees")
    assert r.status_code == 200 and "dx-root" in r.text and 'href="/donnees"' in client.get("/").text
    lake = client.get("/api/donnees/lake").json()
    assert lake["n_keys"] == 1
    snaps = client.get("/api/donnees/frame?key=raw_TEST").json()["snapshots"]
    assert len(snaps) == 2
    assert client.get("/api/donnees/frame?key=raw_NOPE").status_code == 404
    assert client.get("/api/donnees/frame?key=raw_TEST&as_of=zzz").status_code == 422
    s = client.get("/api/donnees/series?key=raw_TEST&column=TEST&as_of=2024-06-03")
    assert s.status_code == 200 and "NaN" not in s.text
    assert client.get("/api/donnees/series?key=raw_TEST&column=nope").status_code == 404
    rev = client.get(f"/api/donnees/revisions?key=raw_TEST&a={snaps[0]['snapshot_id']}&b={snaps[1]['snapshot_id']}")
    assert rev.status_code == 200 and rev.json()["cells_changed"] >= 5
    assert client.get("/api/donnees/revisions?key=raw_TEST&a=x&b=y").status_code == 404
    assert client.get("/api/donnees/calendar").status_code == 200 and client.get("/api/donnees/symbols").json() == ["TEST"]


def test_watchlist_api_roundtrip(client):
    created = client.post("/api/donnees/watchlists", json={"name": "Ma liste", "symbols": "TEST, MISSING", "tags": "a, b"})
    assert created.status_code == 201
    wid = created.json()["watchlist_id"]
    assert client.post("/api/donnees/watchlists", json={"name": "Ma liste"}).status_code == 422
    assert client.post("/api/donnees/watchlists", json={"name": "", "symbols": ""}).status_code == 422
    assert client.post("/api/donnees/watchlists", content=b"pas du json").status_code == 400
    ov = client.get(f"/api/donnees/watchlists/{wid}/overview").json()
    assert ov["name"] == "Ma liste" and ov["n_missing"] == 1 and {r["symbol"]: r["in_lake"] for r in ov["rows"]} == {"TEST": True, "MISSING": False}
    assert client.patch(f"/api/donnees/watchlists/{wid}", json={"symbols": ["TEST"]}).status_code == 200
    assert client.patch("/api/donnees/watchlists/999", json={"name": "x"}).status_code == 404
    assert [w["symbols"] for w in client.get("/api/donnees/watchlists").json()] == [["TEST"]]
    assert client.delete(f"/api/donnees/watchlists/{wid}").status_code == 200 and client.delete(f"/api/donnees/watchlists/{wid}").status_code == 404
    assert client.get("/api/donnees/watchlists/999/overview").status_code == 404


def test_import_api_previews_without_writing_then_commits(client, store):
    text = "date,valeur\n" + "\n".join(f"{d.date()},{100 + i}" for i, d in enumerate(pd.bdate_range("2024-01-01", periods=60)))
    body = {"filename": "v.csv", "csv": text}
    prev = client.post("/api/donnees/import", json=body)
    assert prev.status_code == 200 and prev.json()["rows"] == 60 and not store.exists("user_v")
    bad = client.post("/api/donnees/import", json={**body, "commit": True, "name": "Nom Invalide"})
    assert bad.status_code == 422 and bad.json()["detail"] == "bad_name" and not store.exists("user_nom_invalide")
    ok = client.post("/api/donnees/import", json={**body, "commit": True, "name": "v"})
    assert ok.status_code == 200 and ok.json()["saved"]["key"] == "user_v" and store.exists("user_v")
    short = client.post("/api/donnees/import", json={"filename": "s.csv", "csv": "date,v\n2024-01-01,1\n2024-01-02,2\n", "commit": True, "name": "s"})
    assert short.status_code == 422 and short.json()["detail"] == "too_short"
    b64 = base64.b64encode(text.encode()).decode()
    assert client.post("/api/donnees/import", json={"filename": "v.csv", "b64": b64}).json()["rows"] == 60
    assert client.post("/api/donnees/import", json={}).status_code == 422


def test_ticker_check_validates_the_symbol_and_delegates(client, monkeypatch):
    assert client.post("/api/donnees/ticker-check", json={"symbol": "bad symbol!"}).status_code == 422
    from patrick.data import ticker_check
    monkeypatch.setattr(ticker_check, "check_ticker", lambda s: {"symbol": s, "status": "ok", "n_obs": 900, "first": "2020-01-01", "last": "2026-10-19", "stale_bdays": 1, "reason": None})
    r = client.post("/api/donnees/ticker-check", json={"symbol": "AAPL"})
    assert r.status_code == 200 and r.json()["status"] == "ok" and data_routes._SYMBOL.match("^GSPC")
