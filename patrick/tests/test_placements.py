"""Placements : lecture des VL, stockage, optimisation, scénarios, analyse complète et routes (`patrick/placements/`, `/placements`)."""
from __future__ import annotations

import io
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.placements import jobs, loader, optimize, scenarios, service, stats, store
from patrick.tracking import db
from patrick.webapp.app import app


# ------------------------------------------------------------------ données de test
def _nav_series(mu: float, sigma: float, seed: int, start: str = "2012-01-02", end: str = "2026-06-30", every: int = 1) -> pd.Series:
    """VL synthétique : marche aléatoire log-normale sur les jours ouvrés (un jour sur `every`)."""
    dates = pd.bdate_range(start, end)[::every]
    rng = np.random.default_rng(seed)
    rets = rng.normal(mu / 252, sigma / np.sqrt(252), len(dates))
    return pd.Series(100 * np.cumprod(1 + rets), index=dates, name=f"f{seed}")


def _csv(series: pd.Series, decimal: str = ".", sep: str = ",", fmt: str = "%Y-%m-%d") -> bytes:
    lines = ["date" + sep + "nav"] + [f"{d.strftime(fmt)}{sep}{('%.4f' % v).replace('.', decimal)}" for d, v in series.items()]
    return "\n".join(lines).encode("utf-8")


FUNDS = {
    "alpha_actions": _nav_series(0.09, 0.16, 1),
    "beta_obligations": _nav_series(0.03, 0.04, 2),
    "gamma_mixte": _nav_series(0.06, 0.08, 3),
    "delta_recent": _nav_series(0.07, 0.12, 4, start="2016-03-01"),
    "monetaire_euro": _nav_series(0.015, 0.002, 5),
}


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    return tmp_path / "data"


def _navs() -> pd.DataFrame:
    return pd.concat([s.rename(k) for k, s in FUNDS.items()], axis=1, sort=True).sort_index()


# ------------------------------------------------------------------ loader
def test_csv_iso_comma_and_french_formats_give_the_same_series():
    s = FUNDS["alpha_actions"].iloc[:300]
    iso = loader.read_csv_nav(_csv(s), "a.csv")
    french = loader.read_csv_nav(_csv(s, decimal=",", sep=";", fmt="%d/%m/%Y"), "a.csv")
    assert len(iso) == len(french) == 300
    assert np.allclose(iso.values, french.values, atol=1e-3) and (iso.index == french.index).all()


def test_csv_with_other_column_names_and_junk_rows():
    raw = "Date;VL\n03/01/2022;10,5\n04/01/2022;10,7\nTotal;\n" + "\n".join(f"{d.strftime('%d/%m/%Y')};{10 + i * .01:.2f}".replace(".", ",") for i, d in enumerate(pd.bdate_range("2022-01-05", periods=40)))
    s = loader.read_csv_nav(raw.encode(), "x.csv")
    assert len(s) == 42 and s.index.is_monotonic_increasing


@pytest.mark.parametrize("raw, message", [
    ("date,nav\n" + "\n".join(f"2022-01-{d:02d},{-1 if d == 5 else 10}" for d in range(1, 29)), "négative ou nulle"),
    ("date,nav\n2022-01-01,10\n2022-01-02,11", "VL lisibles seulement"),
    ("valeurs\n1\n2\n3", "colonne de dates et une colonne de VL"),
])
def test_csv_errors_are_explicit(raw, message):
    with pytest.raises(loader.LoaderError, match=message):
        loader.read_csv_nav(raw.encode(), "bad.csv")


def test_xlsx_export_with_title_header_rows():
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Liste des valeurs liquidatives du fonds FINAMA ACTIONS INTERNATIONALES en date du 17/09/2026"])
    ws.append([])
    ws.append(["Date", "VL (EUR)"])
    for i, d in enumerate(pd.bdate_range("2025-01-01", periods=60)):
        ws.append([d.strftime("%d/%m/%Y"), f"{100 + i * .1:.2f}".replace(".", ",")])
    buf = io.BytesIO()
    wb.save(buf)
    parsed = loader.parse_upload("export.xlsx", buf.getvalue())
    assert parsed.key == "finama_actions_internationales" and parsed.label == "FINAMA ACTIONS INTERNATIONALES"
    assert len(parsed.series) == 60 and parsed.series.iloc[0] == pytest.approx(100.0)


def test_unsupported_format_and_hostile_name():
    with pytest.raises(loader.LoaderError, match="format non pris en charge"):
        loader.parse_upload("fonds.exe", b"x")
    parsed = loader.parse_upload("../../etc/passwd Fonds.csv", _csv(FUNDS["alpha_actions"].iloc[:50]))
    assert loader.KEY_RE.match(parsed.key)               # la clé sert de nom de fichier : jamais de séparateur


def test_merge_series_flags_overlap_and_new_points():
    a = FUNDS["alpha_actions"].iloc[:100]
    b = FUNDS["alpha_actions"].iloc[80:150]
    merged, check = loader.merge_series(a.rename("k"), b.rename("k"))
    assert len(merged) == 150 and check["points_communs"] == 20 and check["nouveaux_points"] == 50 and check["ecart_max"] == 0.0


# ------------------------------------------------------------------ store
def test_store_roundtrip_and_path_safety(data_root):
    ds = store.create_dataset("Mon PEE")
    for key, s in FUNDS.items():
        store.add_fund(ds, loader.ParsedFund(key, key.replace("_", " ").title(), s.rename(key), f"{key}.csv", "csv"))
    meta = store.get_meta(ds)
    assert set(meta["funds"]) == set(FUNDS) and meta["cash"] == "monetaire_euro"      # le monétaire est reconnu à son nom
    navs, _ = store.load_navs(ds)
    assert list(navs.columns).count("alpha_actions") == 1 and len(navs) > 3000
    store.update_settings(ds, amount=5000, excluded={"beta_obligations": True})
    navs, _ = store.load_navs(ds)
    assert "beta_obligations" not in navs.columns
    for bad in ("../x", "..", "a/b", "A B", ""):
        with pytest.raises(store.StoreError):
            store.get_meta(bad)
    store.remove_fund(ds, "gamma_mixte")
    assert "gamma_mixte" not in store.get_meta(ds)["funds"]
    store.delete_dataset(ds)
    assert store.list_datasets() == []


# ------------------------------------------------------------------ optimisation et scénarios
def _panel() -> pd.DataFrame:
    navs = _navs()
    last = min(navs[c].dropna().index.max() for c in navs.columns)
    return stats.monthly_navs(navs, last).pct_change(fill_method=None).loc["2016-04-30":].dropna(axis=1, how="any")


def test_optimizers_respect_budget_and_cap():
    R = _panel()
    cash = "monetaire_euro"
    for name, fn in optimize.OPTIMIZERS.items():
        for cap in (1.0, 0.4):
            w = optimize.clean_weights(fn(R, cash, cap, k=4))
            assert w.sum() == pytest.approx(1.0) and (w >= -1e-9).all(), name
            if cap < 1:
                assert (w.drop(cash) <= cap + 1e-6).all(), name
    # le portefeuille de variance minimale est plus calme que le 1/N
    risky = [c for c in R.columns if c != cash]
    w_min = optimize.clean_weights(optimize.opt_min_vol(R, cash, 1.0, k=4))
    assert (R @ w_min).std() < R[risky].mean(axis=1).std()


def test_walk_forward_compares_to_one_over_n_and_flags_short_samples():
    R = _panel()
    wf = optimize.walk_forward(R, "monetaire_euro", optimize.opt_max_sharpe, 0.5, freq=12, min_train=60, k=3)
    assert wf["mois_hors_echantillon"] == len(range(60, len(R) - 11, 12)) * 12
    assert wf["sharpe"] is not None and wf["sharpe_1n"] is not None and wf["peu_fiable"] == (wf["mois_hors_echantillon"] < 36)
    short = optimize.walk_forward(R.iloc[:70], "monetaire_euro", optimize.opt_max_sharpe, 0.5, freq=12, min_train=60, k=3)
    assert short["peu_fiable"] is True


def test_recentred_scenarios_hit_the_target_and_quantiles_are_ordered():
    p = _panel()["alpha_actions"]
    target = 0.04
    ann = scenarios.method_boot_blocks(p, 60, n=4000, target_cagr=target)
    assert np.median(ann) == pytest.approx(target, abs=0.01)
    stationary = scenarios.method_boot_stationary(p, 60, n=4000, target_cagr=target)
    assert np.median(stationary) == pytest.approx(target, abs=0.012)
    s = scenarios.summary(ann, 60)
    assert s["ann_p05"] < s["ann_p25"] < s["ann_p50"] < s["ann_p75"] < s["ann_p95"] and 0 <= s["proba_perte"] <= 1
    assert scenarios.method_boot_blocks(p, 60, n=500, seed=3).tolist() == scenarios.method_boot_blocks(p, 60, n=500, seed=3).tolist()   # graine : reproductible


def test_unreliable_garch_is_masked_not_shown():
    p = _panel()["beta_obligations"]
    out, info = scenarios.run_methods(p, 36, 0.03, ["GARCH résidus", "bootstrap blocs 6 mois"], n=1000)
    assert set(info) >= {"alpha", "beta", "persistance", "fiable", "motif"}
    assert (out["GARCH résidus"]["prudent"] is None) == (not info["fiable"])
    assert out["bootstrap blocs 6 mois"]["prudent"] is not None


def test_fan_has_one_point_per_year():
    fan = scenarios.fan(_panel()["alpha_actions"], 4, None, n=1000)
    assert fan["annees"] == [1, 2, 3, 4] and all(len(fan[f"p{q:02d}"]) == 4 for q in scenarios.QUANTILES)
    assert fan["p05"][-1] < fan["p50"][-1] < fan["p95"][-1]


# ------------------------------------------------------------------ analyse complète
def _quick_params(**kw) -> service.Params:
    base = dict(objectives=("max_sharpe", "min_vol"), caps=(1.0, 0.5), methods=("bootstrap blocs 6 mois", "GARCH résidus"), n_sims=1000, k_starts=3, horizon_years=3)
    base.update(kw)
    return service.Params(**base)


def test_analyse_returns_a_complete_json_ready_result():
    steps = []
    res = service.analyse(_navs(), {k: k.title() for k in FUNDS}, "monetaire_euro", _quick_params(), lambda f, m: steps.append(f))
    json.dumps(res, allow_nan=False)                                  # aucun NaN : le JSON est strict
    assert steps == sorted(steps) and steps[-1] == 1.0
    assert len(res["windows"]) == 2 and res["windows"][0]["months"] > res["windows"][1]["months"]
    assert len(res["portfolios"]) == 2 * 2 * 2                         # fenêtres x objectifs x plafonds
    for pf in res["portfolios"]:
        assert sum(w["weight"] for w in pf["weights"]) == pytest.approx(1.0, abs=0.02)
        assert pf["id"].startswith(pf["window"] + "|")
        if pf["cap"]:
            assert all(w["weight"] <= pf["cap"] + 1e-6 for w in pf["weights"] if w["key"] != "monetaire_euro")
    assert set(res["ranking"]) == {w["id"] for w in res["windows"]}
    assert res["cash"]["key"] == "monetaire_euro" and res["last_common"] == "2026-06-30"
    assert set(res["charts"]) == {w["id"] for w in res["windows"]}
    first = res["charts"][res["windows"][0]["id"]]
    assert len(first["dates"]) == len(first["one_over_n"]) == res["windows"][0]["months"] + 1


def test_analyse_explicit_windows_stale_fund_and_fixed_cash():
    navs = _navs()
    navs.loc["2025-06-01":, "delta_recent"] = np.nan                    # un fonds qui s'arrête un an avant les autres
    res = service.analyse(navs, {}, None, _quick_params(windows=("2013-01-31",), objectives=("max_sharpe",), caps=(1.0,)))
    assert res["cash"]["fixed"] is True and res["windows"][0]["id"].startswith("2013-01")
    assert any("Dernière VL ancienne" in w for w in res["warnings"])


@pytest.mark.parametrize("kwargs, message", [
    ({"horizon_years": 0}, "horizon"), ({"objectives": ("inconnu",)}, "Objectif"), ({"caps": (0.01,)}, "plafond"),
    ({"methods": ("magie",)}, "Méthode"), ({"n_sims": 10}, "simulations"), ({"windows": ("2013-01-31",) * 4}, "fenêtres"),
])
def test_invalid_parameters_are_rejected_with_a_clear_message(kwargs, message):
    with pytest.raises(service.AnalysisError, match=message):
        _quick_params(**kwargs).validate()


def test_analyse_needs_two_risky_funds():
    with pytest.raises(service.AnalysisError, match="au moins 2 fonds"):
        service.analyse(_navs()[["alpha_actions", "monetaire_euro"]], {}, "monetaire_euro", _quick_params())


def test_rank_ignores_missing_walk_forward():
    pfs = [{"window": "w", "id": "a", "metrics": {"sharpe": 1.0, "cagr": 0.1, "vol": 0.1}, "walk_forward": {"sharpe": None}},
           {"window": "w", "id": "b", "metrics": {"sharpe": 0.5, "cagr": 0.05, "vol": 0.05}, "walk_forward": {"sharpe": 0.3}}]
    assert service.rank(pfs)["w"] == {"wf_sharpe": "b", "sharpe": "a", "cagr": "a", "vol": "b"}


# ------------------------------------------------------------------ routes
@pytest.fixture
def client(data_root, tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    return TestClient(app)


def _files(*keys: str) -> list:
    return [("files", (f"{k}.csv", _csv(FUNDS[k]), "text/csv")) for k in keys]


def test_page_is_a_frame_and_listed_in_the_simulation_menu(client):
    html = client.get("/placements").text
    assert 'id="pl-app"' in html and 'id="pl-i18n"' in html and "Placements" in html
    assert 'href="/placements"' in client.get("/").text
    en = client.get("/placements", cookies={"patrick_lang": "en"}).text
    assert "Investments" in en


def test_full_workflow_import_run_read_result_delete(client):
    created = client.post("/api/placements/datasets", data={"name": "Mon PEE"}, files=_files(*FUNDS)).json()
    ds_id = created["id"]
    assert [r["ok"] for r in created["report"]] == [True] * 5
    ds = created["dataset"]
    assert ds["cash"] == "monetaire_euro" and len(ds["funds"]) == 5 and len(ds["windows"]) >= 2
    assert client.get("/api/placements/datasets").json()[0]["id"] == ds_id
    assert client.get(f"/api/placements/datasets/{ds_id}/result").json() == {"result": None}

    body = {"horizon_years": 3, "objectives": ["max_sharpe"], "caps": [1.0], "methods": ["bootstrap blocs 6 mois"], "n_sims": 1000, "min_train": 60}
    job = client.post(f"/api/placements/datasets/{ds_id}/analyse", json=body).json()
    for _ in range(240):
        status = client.get(f"/api/placements/jobs/{job['id']}").json()
        if status["status"] != "running":
            break
        time.sleep(0.5)
    assert status["status"] == "done", status
    result = client.get(f"/api/placements/datasets/{ds_id}/result").json()["result"]
    assert result["dataset"]["id"] == ds_id and len(result["portfolios"]) == 2
    assert client.get("/api/placements/datasets").json()[0]["has_result"] is True

    assert client.post(f"/api/placements/datasets/{ds_id}/settings", json={"amount": 2500, "excluded": {"beta_obligations": True}}).json()["amount"] == 2500
    assert client.delete(f"/api/placements/datasets/{ds_id}/funds/gamma_mixte").json()["funds"].get("gamma_mixte") is None
    assert client.delete(f"/api/placements/datasets/{ds_id}").json() == {"deleted": ds_id}
    assert client.get(f"/api/placements/datasets/{ds_id}").status_code == 404


def test_import_reports_each_file_and_rejects_an_all_bad_upload(client):
    mixed = _files("alpha_actions") + [("files", ("notes.docx", b"nope", "application/octet-stream"))]
    out = client.post("/api/placements/datasets", data={"name": "Mix"}, files=mixed).json()
    assert [r["ok"] for r in out["report"]] == [True, False] and "format non pris en charge" in out["report"][1]["error"]
    bad = client.post("/api/placements/datasets", data={"name": "Rien"}, files=[("files", ("a.docx", b"x", "application/octet-stream"))])
    assert bad.status_code == 400 and "Aucun fichier exploitable" in bad.json()["detail"]
    assert len(client.get("/api/placements/datasets").json()) == 1       # le jeu vide n'est pas resté sur le disque


def test_api_rejects_hostile_ids_and_bad_parameters(client):
    assert client.get("/api/placements/datasets/..%2F..%2Fx").status_code in (400, 404)
    assert client.get("/api/placements/datasets/BAD ID").status_code == 400
    assert client.get("/api/placements/jobs/nope").status_code == 404
    created = client.post("/api/placements/datasets", data={"name": "P"}, files=_files("alpha_actions", "monetaire_euro")).json()
    bad = client.post(f"/api/placements/datasets/{created['id']}/analyse", json={"horizon_years": 5, "caps": [0.01]})
    assert bad.status_code == 400 and "plafond" in bad.json()["detail"]
    too_few = client.post(f"/api/placements/datasets/{created['id']}/analyse", json={"n_sims": 1000})
    assert too_few.status_code == 200
    for _ in range(40):                                  # un fonds risqué seulement : l'analyse échoue proprement, sans planter le serveur
        status = client.get(f"/api/placements/jobs/{too_few.json()['id']}").json()
        if status["status"] != "running":
            break
        time.sleep(0.25)
    assert status["status"] == "error" and "au moins 2 fonds" in status["error"]


def test_only_one_analysis_runs_per_dataset(data_root, monkeypatch):
    ds = store.create_dataset("Concurrence")
    for key, s in FUNDS.items():
        store.add_fund(ds, loader.ParsedFund(key, key, s.rename(key), f"{key}.csv", "csv"))
    gate = {"go": False}
    monkeypatch.setattr(service, "analyse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")) if gate["go"] else time.sleep(0.6) or {"portfolios": []})
    first = jobs.start(ds, _quick_params())
    assert jobs.start(ds, _quick_params()).id == first.id
    time.sleep(1.0)
    assert jobs.get(first.id).status == "done"
