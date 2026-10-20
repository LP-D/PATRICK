"""Sections d'analyse d'un run ML/DL sur un run synthétique (`tests/analysis_support.py`) : chiffres recalculés à la main, dégradations
propres quand le niveau de la cible manque, CPCV, JSON sérialisable."""
from __future__ import annotations

import json

import numpy as np
import pytest
from analysis_support import seed_run

from patrick.analysis import frames, registry
from patrick.analysis import stats_core as sc


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    yield conn, info
    registry.clear_cache()
    conn.close()


def build(conn, info, section, **params):
    return registry.build(conn, info["run_id"], section, {k: str(v) for k, v in params.items()}, db_key="t")


def test_every_section_returns_json_serialisable_dict(seeded):
    conn, info = seeded
    for section in registry.SECTIONS:
        out = build(conn, info, section)
        assert isinstance(out, dict), section
        json.dumps(out, allow_nan=False)                      # pas de NaN/inf dans le JSON


def test_unknown_run_and_unknown_section(seeded):
    conn, info = seeded
    assert registry.build(conn, "nope", "overview", {}) is None
    with pytest.raises(KeyError):
        registry.build(conn, info["run_id"], "nope", {})


def test_frame_reads_levels_from_snapshot_and_computes_forward_returns(seeded):
    conn, info = seeded
    fr = frames.load_frame(conn, info["run_id"])
    assert fr.levels is not None and len(fr.levels) == len(info["prices"])
    t = fr.df[fr.df["split_name"] == "test"].iloc[0]
    expected = info["prices"].shift(-info["horizon"]).loc[t.ts] / info["prices"].loc[t.ts] - 1
    assert t.ret == pytest.approx(expected)
    assert fr.df["split_name"].isin(["test", "holdout", "live"]).all()
    live = fr.df[fr.df["split_name"] == "live"]
    assert live["ut"].isna().all() and len(live) == 3


def test_frame_without_snapshot_degrades_with_note(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, with_store=False)
    fr = frames.load_frame(conn, info["run_id"])
    assert fr.levels is None and fr.notes
    for section in ("equity", "scatter"):
        out = registry.build(conn, info["run_id"], section, {}, db_key="none")
        assert out["available"] is False and out["reason"] == "no_returns"
    assert registry.build(conn, info["run_id"], "confusion", {}, db_key="none")["available"] is True
    registry.clear_cache()


def test_overview_headline_matches_manual_accuracy(seeded):
    conn, info = seeded
    out = build(conn, info, "overview")
    fr = frames.load_frame(conn, info["run_id"])
    test = fr.df[(fr.df["split_name"] == "test")]
    manual = float(((test["ut"] >= 0.5) == test["up"]).mean())
    assert out["headline"]["test"]["acc"] == pytest.approx(manual)
    assert out["headline"]["test"]["n"] == len(test)
    assert out["splits"]["live"]["pending"] == 3
    assert out["trial"]["algo"] == "XGBoost" and out["run"]["name"] == "TST_test"
    assert out["has_levels"] is True


def test_confusion_counts_and_binary_collapse(seeded):
    conn, info = seeded
    out = build(conn, info, "confusion")
    t = out["splits"]["test"]
    assert np.array(t["cm"]).sum() == t["n"]
    cm = np.array(t["cm"])
    # le tableau haut/bas est le regroupement 2x2 de la matrice à 4 classes
    assert t["bin_cm"][1][1] == cm[2:, 2:].sum() and t["bin_cm"][0][0] == cm[:2, :2].sum()
    assert [c["support"] for c in t["classes"]] == cm.sum(axis=1).tolist()
    assert {f["fold"] for f in out["by_fold"] if f["split"] == "test"} == {1, 2, 3}
    assert 0.5 < t["roc"]["auc"] < 1.0                                    # signal 60 % : AUC nettement > 0,5
    assert t["roc"]["fpr"][0] == 0 and t["roc"]["tpr"][-1] == 1


def test_calibration_bins_cover_all_probabilities(seeded):
    conn, info = seeded
    out = build(conn, info, "calibration")
    q = out["splits"]["test"]["quantile"]
    assert sum(b["n"] for b in q["bins"]) == q["n"] > 100
    assert 0.0 <= q["ece"] <= 1.0 and q["brier"] > 0
    assert out["by_fold"]
    assert np.array(out["splits"]["test"]["hist_up"]["counts"]).sum() + np.array(out["splits"]["test"]["hist_down"]["counts"]).sum() == q["n"]


def test_timeline_modes_and_window(seeded):
    conn, info = seeded
    full = build(conn, info, "timeline")
    assert full["available"] and full["mode"] == "bins" and len(full["points"]) <= 360
    assert full["price"] and full["folds"][0]["split"] == "test"
    start = full["range"][0]
    narrow = build(conn, info, "timeline", start=start, end=str(np.datetime64(start) + 100))
    assert narrow["mode"] == "days" and 0 < narrow["n"] <= 700
    assert set(narrow["points"][0]) >= {"t", "yt", "yp", "ut", "p", "ok", "ret"}
    assert build(conn, info, "timeline", start="2099-01-01")["available"] is False


def test_rolling_window_series_and_bounds(seeded):
    conn, info = seeded
    out = build(conn, info, "rolling", window=100)
    assert out["window"] == 100
    acc = [a for a in out["acc"] if a is not None]
    assert acc and all(0 <= a <= 1 for a in acc)
    assert all(lo <= a <= hi for lo, a, hi in zip(out["lo"], out["acc"], out["hi"], strict=True) if a is not None)
    assert len(out["cum_edge"]) == len(out["t"])


def test_scatter_deciles_ordered_and_ic_positive_with_skill(seeded):
    conn, info = seeded
    out = build(conn, info, "scatter")
    assert out["available"] and 8 <= len(out["deciles"]) <= 10
    assert sum(d["n"] for d in out["deciles"]) == out["n"]
    ps = [d["p_mean"] for d in out["deciles"]]
    assert ps == sorted(ps)
    assert len(out["points"]["p"]) == len(out["points"]["ret"]) <= 1500


def test_equity_h1_matches_manual_long_short(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, horizon=1, live=0)
    out = registry.build(conn, info["run_id"], "equity", {"cost_bps": "0"}, db_key="eq")
    assert out["available"]
    fr = frames.load_frame(conn, info["run_id"])
    d = fr.df[fr.df["split_name"].isin(["test", "holdout"])].drop_duplicates("ts").set_index("ts")
    pos = np.where(d["up"], 1.0, -1.0)
    pos = __import__("pandas").Series(pos, index=d.index)
    daily = fr.daily
    dates = __import__("pandas").to_datetime(out["dates"])
    expected = (pos.reindex(daily.index).ffill().shift(1).fillna(0.0) * daily.fillna(0.0)).reindex(dates)
    assert np.allclose(out["series"]["long_short"]["gross"], expected.to_numpy(), atol=1e-6)
    s0 = out["stats"]["long_short"]["all"]
    out_cost = registry.build(conn, info["run_id"], "equity", {"cost_bps": "50"}, db_key="eq")
    assert out_cost["stats"]["long_short"]["all"]["total"] < s0["total"]            # les coûts coûtent
    assert out["stats"]["buy_hold"]["all"]["total"] == pytest.approx(
        float(np.prod(1 + daily.reindex(dates).fillna(0.0).to_numpy()) - 1), rel=1e-4)
    assert out["stats"]["long_flat"]["exposure"]["mean_abs"] <= 1.0
    registry.clear_cache()


def test_errors_tables_partition_the_sample(seeded):
    conn, info = seeded
    out = build(conn, info, "errors")
    n = out["n"]
    for key in ("fold", "year", "pred_class"):
        assert sum(r["n"] for r in out["tables"][key]) <= n
    assert sum(r["n"] for r in out["tables"]["fold"]) == n
    assert {r["key"] for r in out["tables"]["vol"]} <= {"vol_low", "vol_mid", "vol_high"}
    assert out["streaks"] and out["streaks"][0]["length"] >= out["streaks"][-1]["length"]
    assert 0 < out["overall_error_rate"] < 1


def test_protocol_folds_are_chronological_with_estimated_train_end(seeded):
    conn, info = seeded
    out = build(conn, info, "protocol")
    folds = out["folds"]
    assert [f["split"] for f in folds] == ["test", "test", "test", "holdout"]
    starts = [f["test_start"] for f in folds]
    assert starts == sorted(starts)
    assert all(f["train_end"] < f["test_start"] for f in folds)
    assert folds[0]["n_train"] is not None and folds[1]["n_train"] > folds[0]["n_train"]


def test_folds_trials_features_holdout_live(seeded):
    conn, info = seeded
    folds = build(conn, info, "folds")
    assert folds["available"] and folds["baselines"]["majority"]["test"]["Acc_dir"] == pytest.approx(0.54)
    trials = build(conn, info, "trials")
    assert trials["n_in_run"] == 3 and trials["trials"][0]["is_best"] is True
    feats = build(conn, info, "features")
    assert feats["available"] and feats["selection"][0]["feature"] == "CL_ret_1d"
    assert {f["family"] for f in feats["selection"]} >= {"momentum", "zscore", "volatility_model"}
    hl = build(conn, info, "holdout_live")
    assert hl["live"]["n"] == 3 and hl["live"]["resolved"] == 0 and hl["compare"]["holdout"]["n"] > 50
    assert build(conn, info, "paths")["reason"] == "not_cpcv"


def test_robustness_separates_skill_from_noise(tmp_path, monkeypatch):
    registry.clear_cache()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    conn, info = seed_run(tmp_path / "a", monkeypatch, skill=0.72, seed=3)
    skilled = registry.build(conn, info["run_id"], "robustness", {"n_perm": "200", "n_boot": "100"}, db_key="s")
    assert skilled["samples"]["test"]["perm_acc"]["p_value"] < 0.02
    assert skilled["samples"]["test"]["shift"][10]["lag"] == 0
    best = max(skilled["samples"]["test"]["shift"], key=lambda c: c["acc"])
    assert best["lag"] == 0
    registry.clear_cache()
    conn2, _ = seed_run(tmp_path / "b", monkeypatch, run_id="run_noise", skill=0.5, seed=4)
    noise = registry.build(conn2, "run_noise", "robustness", {"n_perm": "200", "n_boot": "100"}, db_key="n")
    assert noise["samples"]["test"]["perm_acc"]["p_value"] > 0.02
    assert noise["stability"]["leave_one_fold_out"]
    registry.clear_cache()


def test_guide_flags_a_noise_model_and_never_advises(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, skill=0.5, seed=5)
    out = registry.build(conn, info["run_id"], "guide", {}, db_key="g")
    keys = {i["key"] for i in out["items"]}
    assert {"acc_vs_majority", "trials"} <= keys
    first = next(i for i in out["items"] if i["key"] == "acc_vs_majority")
    assert first["level"] == "warn"
    assert out["items"][0]["level"] == "warn"                                 # les avertissements passent d'abord
    registry.clear_cache()


def test_cpcv_run_exposes_paths_and_single_path_views(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, scheme="cpcv", live=0)
    paths = registry.build(conn, info["run_id"], "paths", {}, db_key="c")
    assert paths["available"] and len(paths["paths"]) == 2 and paths["summary"]["F1_dir"]["n"] == 2
    conf = registry.build(conn, info["run_id"], "confusion", {}, db_key="c")
    assert conf["available"]
    tl = registry.build(conn, info["run_id"], "timeline", {}, db_key="c")
    assert tl["available"]                                                    # une seule trajectoire, pas de dates doublées
    ov = registry.build(conn, info["run_id"], "overview", {}, db_key="c")
    assert ov["scheme"] == "cpcv"
    registry.clear_cache()


def test_sc_clean_used_by_registry_replaces_nan(seeded):
    conn, info = seeded
    out = build(conn, info, "calibration")
    assert "NaN" not in json.dumps(out)
    assert sc.jsonable(float("nan")) is None


def test_regimes_section_is_causal_and_partitions_the_sample(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch)
    out = registry.build(conn, info["run_id"], "regimes", {"n_states": "2"}, db_key="hmm")
    assert out["available"] and out["n_states"] == 2
    assert set(out["share"]) == {"calme", "normal", "stress"} and abs(sum(out["share"].values()) - 1.0) < 1e-9
    assert out["fit_end"] < out["t"][0]                                   # ajusté avant le premier jour évalué : pas de regard vers l'avenir
    assert sum(r["n"] for r in out["table"]) <= 1000 + 400 and {r["key"] for r in out["table"]} <= {"calme", "normal", "stress"}
    assert all(0.0 <= p <= 1.0 for p in out["stress"]) and set(out["code"]) <= {0, 1, 2}
    assert out["n_changes"] >= 0 and out["longest"] == sorted(out["longest"], key=lambda r: -r["days"])
    registry.clear_cache()


def test_regimes_unavailable_without_levels(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, with_store=False)
    out = registry.build(conn, info["run_id"], "regimes", {}, db_key="hmm0")
    assert out["available"] is False and out["reason"] == "no_returns"
    registry.clear_cache()
