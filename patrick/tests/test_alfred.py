"""ALFRED par défaut (`data/alfred.py`) : première publication de chaque observation, fenêtres de vintages, repli hybride
avant la couverture d'ALFRED, repli FRED si la série n'y existe pas, cache, comparaison FRED/ALFRED. Aucun accès réseau :
une fausse session répond aux deux points d'accès de l'API."""
from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

from patrick.cache_manager import LocalCache
from patrick.config.schema import UniverseConfig
from patrick.data import alfred
from patrick.data.sources import fred_source


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            resp = requests.Response()
            resp.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=resp)


class FakeAlfred:
    """Série mensuelle `M` : vintages à partir de 2020-03 ; `D` : 5 vintages quotidiens ; `GONE` : absente d'ALFRED."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        # (date d'observation, date de première publication, première valeur, valeur actuelle)
        self.monthly = [("2019-10-01", "2019-11-14", 90.0, 91.0), ("2019-11-01", "2019-12-13", 95.0, 96.0),
                        ("2019-12-01", "2020-01-15", 98.0, 99.0), ("2020-01-01", "2020-02-14", 100.0, 101.0),
                        ("2020-02-01", "2020-03-13", 110.0, 112.0), ("2020-03-01", "2020-04-15", 120.0, 120.0),
                        ("2020-04-01", "2020-05-15", 130.0, 133.0)]
        self.alfred_from = "2020-02-14"          # ALFRED n'archive la série qu'à partir de là (comme NFCI : 2011)
        self.daily = [("2020-06-01", "2020-06-02", 1.0), ("2020-06-02", "2020-06-03", 1.1), ("2020-06-03", "2020-06-04", 1.2),
                      ("2020-06-04", "2020-06-05", 1.3), ("2020-06-05", "2020-06-08", 1.4)]

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        sid = params["series_id"]
        vintage_call = url.endswith("vintagedates") or params.get("output_type") == 4
        if sid == "GONE" and vintage_call:
            return FakeResponse(400, {"error_message": "series does not exist in ALFRED"})
        if url.endswith("vintagedates"):
            dates = ([r[1] for r in self.monthly if r[1] >= self.alfred_from] if sid == "M" else [r[1] for r in self.daily])
            return FakeResponse(200, {"vintage_dates": dates, "count": len(dates)})
        if params.get("output_type") == 4:
            lo, hi = params["realtime_start"], params["realtime_end"]
            rows = ([(o, r, v) for o, r, v, _ in self.monthly if r >= self.alfred_from] if sid == "M"
                    else list(self.daily))
            obs = [{"date": o, "realtime_start": r, "value": str(v)} for o, r, v in rows if lo <= r <= hi]
            return FakeResponse(200, {"observations": obs})
        cur = [(o, c) for o, _, _, c in self.monthly] if sid == "M" else [(o, v) for o, _, v in self.daily]
        if sid == "GONE":
            cur = [("2020-01-01", 5.0), ("2020-02-01", 5.1)]
        return FakeResponse(200, {"observations": [{"date": d, "value": str(v)} for d, v in cur]})


@pytest.fixture
def cache(tmp_path):
    return LocalCache(str(tmp_path / "cache"))


def test_every_new_run_defaults_to_alfred_but_a_stored_config_keeps_its_own_alignment(tmp_path):
    """Un run neuf (formulaire web, YAML) part en ALFRED ; une configuration enregistrée AVANT (sans clé, ou avec
    `publication_lag`) est rechargée telle quelle par predict/explain/reprise : la prédiction live doit aligner les
    données comme l'entraînement l'a fait."""
    from patrick.config import defaults as D
    from patrick.config.schema import RunConfig
    from patrick.webapp import forms

    assert D.DEFAULT_FRED_POINT_IN_TIME == "alfred"
    assert forms.default_config_dict()["universe"]["fred_point_in_time"] == "alfred"
    yaml_path = tmp_path / "c.yaml"
    yaml_path.write_text("name: t\nobjective: {target_symbol: X, target_source: yfinance, horizons: [1]}\n"
                         "output: {dir: out}\n", encoding="utf-8")
    assert RunConfig.from_yaml(str(yaml_path)).universe.fred_point_in_time == "alfred"
    stored_before = RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "X", "target_source": "yfinance",
                                                                          "horizons": [1]}, "output": {"dir": "out"}})
    assert stored_before.universe.fred_point_in_time == "publication_lag"
    assert UniverseConfig().fred_point_in_time == "publication_lag"


def test_windows_never_exceed_the_vintage_limit(monkeypatch):
    monkeypatch.setattr(alfred, "MAX_VINTAGES_PER_REQUEST", 2)
    vintages = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    windows = alfred._windows(vintages)
    assert windows == [(alfred.FAR_PAST, "2020-01-02"), ("2020-01-03", "2020-01-06"), ("2020-01-07", alfred.FAR_FUTURE)]


def test_daily_series_is_downloaded_in_several_windows_and_nothing_is_lost(monkeypatch, cache):
    monkeypatch.setattr(alfred, "MAX_VINTAGES_PER_REQUEST", 2)
    fake = FakeAlfred()
    result = alfred.alfred_series("D", "2020-01-01", "k", cache=cache, session=fake)
    obs_calls = [p for _, p in fake.calls if p.get("output_type") == 4]
    assert len(obs_calls) == 3                                   # 5 vintages, 2 par fenêtre
    assert result.mode == "alfred" and len(result.series) == 5
    assert list(result.series.index.strftime("%Y-%m-%d")) == ["2020-06-02", "2020-06-03", "2020-06-04", "2020-06-05", "2020-06-08"]


def test_each_value_enters_on_its_real_release_date_with_its_first_value(cache):
    fake = FakeAlfred()
    result = alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake)
    s = result.series
    assert s.loc["2020-03-13"] == 110.0 and s.loc["2020-04-15"] == 120.0     # premières valeurs, pas 112 / révisions
    assert s.loc["2020-05-15"] == 130.0 and s.loc["2020-02-14"] == 100.0


def test_history_before_alfred_coverage_uses_the_current_version_on_an_estimated_date(cache):
    fake = FakeAlfred()
    result = alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake)
    assert result.mode == "hybrid" and result.info["n_alfred"] == 4 and result.info["n_backfilled"] >= 2
    # octobre 2019 : version actuelle (91), datée par la table de retards (jamais avant la fin du mois), avant le 1er vintage
    first = result.series.iloc[0]
    assert first == 91.0
    assert pd.Timestamp("2019-10-31") < result.series.index[0] < pd.Timestamp("2020-02-14")
    assert result.series.index.is_monotonic_increasing and not result.series.index.has_duplicates


def test_a_series_missing_from_alfred_falls_back_to_fred_and_the_lag_table(cache):
    result = alfred.alfred_series("GONE", "2020-01-01", "k", cache=cache, session=FakeAlfred())
    assert result.mode == "fred" and len(result.series) == 2
    assert result.series.index[0] > pd.Timestamp("2020-01-01")       # datée par la table de retards, pas par l'observation


def test_an_alfred_outage_never_loses_the_series(cache, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("réseau coupé")

    fake = FakeAlfred()
    monkeypatch.setattr(alfred, "load_series_data", boom)
    result = alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake)
    assert result.mode == "fred" and len(result.series) == 7


def test_the_cache_avoids_a_second_download(cache):
    fake = FakeAlfred()
    alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake)
    n = len(fake.calls)
    alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake)
    assert len(fake.calls) == n
    alfred.alfred_series("M", "2020-01-01", "k", cache=cache, session=fake, refresh=True)
    assert len(fake.calls) > n


def test_compare_with_fred_measures_revisions_coverage_and_publication_delay(cache):
    out = alfred.compare_with_fred("M", "2019-01-01", "k", cache=cache, session=FakeAlfred())
    assert out["mode"] == "hybrid" and out["n_compared"] == 4
    assert out["share_revised"] == pytest.approx(3 / 4)               # janvier, février et avril révisés ; mars identique
    assert out["max_abs_revision"] == pytest.approx(3.0)
    assert out["lag_real_days"] >= 1 and out["lag_assumed_days"] >= 1
    assert out["lost_years_if_alfred_only"] > 0


def test_compare_with_fred_flags_a_series_absent_from_alfred(cache):
    out = alfred.compare_with_fred("GONE", "2020-01-01", "k", cache=cache, session=FakeAlfred())
    assert out["mode"] == "fred" and out["n_compared"] == 0 and "ALFRED" in out["note"]


def test_the_fred_universe_uses_alfred_and_reports_last_observations(monkeypatch, cache):
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(alfred.requests, "get", FakeAlfred().get)
    monkeypatch.setattr(alfred, "LocalCache", lambda *a, **k: cache)
    frame = fred_source.download_fred_universe({"Mensuelle": "M", "Absente": "GONE"}, "2020-01-01", first_release=True)
    assert frame.attrs["point_in_time"] is True
    assert frame.attrs["alfred_modes"] == {"Mensuelle": "hybrid", "Absente": "fred"}
    assert frame.attrs["last_obs"]["Mensuelle"] == "2020-04-01"
    assert set(frame.columns) == {"Mensuelle", "Absente"}


def test_payload_roundtrip_keeps_everything():
    rel = pd.DataFrame({"obs_date": pd.to_datetime(["2020-01-01"]), "release_date": pd.to_datetime(["2020-02-14"]), "value": [1.5]})
    cur = pd.Series([1.6], index=pd.to_datetime(["2020-01-01"]))
    rel2, cur2, fv = alfred._from_payload(json.loads(json.dumps(alfred._to_payload(rel, cur, "2020-01-01", "2000-01-01"))))
    assert rel2.equals(rel) and cur2.equals(cur) and fv == "2020-01-01"


def _monthly(first_values, current_values):
    idx = pd.date_range("2015-01-01", periods=len(first_values), freq="MS")
    rel = pd.DataFrame({"obs_date": idx, "release_date": idx + pd.Timedelta(days=45), "value": first_values})
    return rel, pd.Series(current_values, index=idx)


def test_a_rebased_level_is_kept_in_its_current_version_not_chained_from_first_releases():
    """PCEPI : chaque première publication est dans la base du moment (+10 points tous les 12 mois) -> sauts artificiels."""
    n = 48
    current = [100 + 0.2 * i for i in range(n)]
    first = [100 + 0.2 * i + 10 * (i // 12) for i in range(n)]
    rel, cur = _monthly(first, current)
    assert alfred.level_break_ratio(rel, cur) > alfred.LEVEL_BREAK_RATIO
    result = alfred.assemble("PCEPI", rel, cur, "2015-02-15")
    assert result.mode == "fred" and result.info["level_break"] > 4
    assert result.series.max() < 111                                  # niveau actuel, pas la chaîne à +30 points


def test_a_smooth_series_is_never_flagged_as_rebased():
    n = 48
    current = [100 + 0.2 * i for i in range(n)]
    first = [v + 0.05 * (i % 3) for i, v in enumerate(current)]       # petites révisions
    rel, cur = _monthly(first, current)
    assert alfred.level_break_ratio(rel, cur) < 2
    assert alfred.assemble("X", rel, cur, "2015-02-15").mode in ("alfred", "hybrid")
    assert alfred.level_break_ratio(rel.iloc[:10], cur.iloc[:10]) is None   # trop court pour conclure


def test_relaunching_an_old_run_moves_it_to_alfred_but_never_touches_an_audit(tmp_path, monkeypatch):
    """« Relancer » suit les règles d'aujourd'hui : un run enregistré avec `publication_lag` repart en ALFRED ; un audit
    `reference_date` (qui mesure l'ancienne fuite) reste tel quel."""
    from fastapi.testclient import TestClient

    from patrick.tracking import db as trackdb
    from patrick.webapp import forms, run_manager
    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(run_manager, "ensure_worker_running", lambda: None)
    conn = trackdb.connect(str(tmp_path / "p.db"))
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    for run_id, mode in (("old", "publication_lag"), ("audit", "reference_date")):
        cfg = forms.default_config_dict()
        cfg["name"] = run_id
        cfg["universe"]["fred_point_in_time"] = mode
        trackdb.create_run(conn, run_id, "^VIX", 5, "snap", json.dumps(cfg), "c", "s", 42)
    conn.close()
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    for run_id in ("old", "audit"):
        assert client.post(f"/runs/{run_id}/relaunch", follow_redirects=False).status_code == 303
    conn = trackdb.connect(str(tmp_path / "p.db"))
    modes = [json.loads(r[0])["universe"]["fred_point_in_time"] for r in conn.execute("SELECT config_json FROM job ORDER BY rowid")]
    conn.close()
    assert modes == ["alfred", "reference_date"]
