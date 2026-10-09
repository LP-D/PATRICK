"""Champion / challenger duel (`pipeline/champion_duel.py`), fast: the
holdout evaluation (`engine._evaluate_holdout`) is replaced by known
scores, the decision logic and its database effects are real."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.pipeline import champion_duel, engine
from patrick.tracking import champions
from patrick.tracking import db as trackdb

H = 5


def _config(name: str, flat_thr: float = 0.003, holdout_months: int = 15, **features) -> RunConfig:
    raw = {"name": name,
           "objective": {"target_symbol": "^TEST", "horizons": [H], "regimes": ["GLOBAL"], "flat_thr": flat_thr},
           "validation": {"holdout_months": holdout_months}}
    if features:
        raw["features"] = features
    return RunConfig.model_validate(raw)


def _run_with_best(conn, tmp_path, run_id: str, config: RunConfig, algo: str, started: str) -> int:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, run_id, target="^TEST", horizon=H, snapshot_id="snap1",
                       config_json=config.model_dump_json(), config_hash="h", git_sha="sha", seed=42)
    with conn:
        conn.execute("UPDATE run SET status = 'done', started_at = datetime('now', ?) WHERE run_id = ?",
                     (started, run_id))
    tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", 4, "shap")
    path = str(tmp_path / f"{run_id}_best_model_h{H}.joblib")
    with open(path, "wb") as f:
        f.write(b"model")
    with open(path[: -len(".joblib")] + "_meta.json", "w") as f:
        json.dump({"feature_names": ["a", "b", "c", "d"], "best_params": {"max_depth": 3}, "N": 4,
                   "algo": algo, "sampler": "SMOTE", "regime": "GLOBAL"}, f)
    trackdb.mark_best_trial(conn, tid, artifact_path=path)
    return tid


@pytest.fixture
def setup(conn, tmp_path, monkeypatch):
    """An incumbent (older run, algo 'ChampAlgo') and this run's challenger
    ('ChalAlgo'); `scores` sets what each side scores on the holdout."""
    # The incumbent was trained with another target threshold and holdout
    # length: the duel must score it with THIS run's definitions.
    champ_tid = _run_with_best(conn, tmp_path, "champ_run", _config("old", flat_thr=0.01, holdout_months=12),
                               "ChampAlgo", "-2 days")
    chal_config = _config("new")
    chal_tid = _run_with_best(conn, tmp_path, "chal_run", chal_config, "ChalAlgo", "-1 hours")
    scores = {"ChampAlgo": 0.55, "ChalAlgo": 0.60}
    calls = []

    def fake_evaluate(conn_, snapshot_id, pool_builder, target_col, feature_pool, config, all_dates_full,
                      n_wf, best_cfg, seed, universe=None):
        calls.append({"algo": best_cfg["algo"], "config": config, "pool_builder": pool_builder,
                      "n_wf": n_wf, "best_cfg": best_cfg})
        f1 = scores[best_cfg["algo"]]
        return None if f1 is None else {"metrics": {"F1_dir": f1}, "n_test": 300}

    monkeypatch.setattr(engine, "_evaluate_holdout", fake_evaluate)
    monkeypatch.setattr(engine, "_FoldUniverse", lambda raw, target_col, config: "universe")
    dates = pd.bdate_range("2010-01-01", periods=1000)
    st = SimpleNamespace(conn=conn, config=chal_config, run_ids={H: "chal_run"}, target_col="IDX_TEST",
                         snapshot_id="snap1", seed=42, raw=pd.DataFrame(index=dates),
                         pool_builder=SimpleNamespace(fold_cuts=[400, 500, 600, 700, 800, 900]),
                         feature_pool=["a", "b"], all_dates_full=dates, n_wf=900, universe=None,
                         is_walkforward=True, has_holdout=True)
    best_h = {"horizon": H, "regime": "GLOBAL", "N": 4, "sampler": "SMOTE", "algo": "ChalAlgo",
              "best_params": "{}"}
    return SimpleNamespace(st=st, best_h=best_h, champ_tid=champ_tid, chal_tid=chal_tid,
                           scores=scores, calls=calls, conn=conn)


def _duel(s):
    return champion_duel.duel_and_promote(s.st, {H: s.best_h}, {H: s.chal_tid})[H]


def _run_exists(conn, run_id: str) -> bool:
    return conn.execute("SELECT COUNT(*) FROM run WHERE run_id = ?", (run_id,)).fetchone()[0] == 1


def test_a_better_challenger_takes_the_title_and_the_old_champion_is_archived_then_pruned(setup):
    d = _duel(setup)

    assert d["decision"] == "challenger_wins"
    cur = champions.current(setup.conn, "^TEST", H)
    assert (cur["run_id"], cur["trial_id"], cur["implicit"]) == ("chal_run", setup.chal_tid, False)
    archived = champions.list_archive(setup.conn, "^TEST", H)
    assert [(a["run_id"], a["role"]) for a in archived] == [("champ_run", "replaced_champion")]
    duel = json.loads(archived[0]["duel_json"])
    assert duel["winner"] == "challenger"
    assert duel["challenger"]["f1_dir"] == pytest.approx(0.60)
    assert duel["champion"]["f1_dir"] == pytest.approx(0.55)
    assert duel["holdout_start"] == str(setup.st.all_dates_full[900].date())
    assert not _run_exists(setup.conn, "champ_run")
    assert _run_exists(setup.conn, "chal_run")


def test_a_worse_challenger_is_archived_then_pruned_and_the_champion_becomes_explicit(setup):
    setup.scores["ChalAlgo"] = 0.50

    d = _duel(setup)

    assert d["decision"] == "champion_wins"
    cur = champions.current(setup.conn, "^TEST", H)
    assert (cur["run_id"], cur["implicit"]) == ("champ_run", False)
    assert [(a["run_id"], a["role"]) for a in champions.list_archive(setup.conn)] == [
        ("chal_run", "rejected_challenger")]
    assert not _run_exists(setup.conn, "chal_run")
    assert _run_exists(setup.conn, "champ_run")


def test_a_tie_keeps_the_champion(setup):
    setup.scores["ChalAlgo"] = 0.55
    assert _duel(setup)["decision"] == "champion_wins"
    assert champions.current(setup.conn, "^TEST", H)["run_id"] == "champ_run"


def test_both_sides_are_scored_on_the_same_split_with_the_challengers_target_definition(setup):
    _duel(setup)

    champ_call = next(c for c in setup.calls if c["algo"] == "ChampAlgo")
    chal_call = next(c for c in setup.calls if c["algo"] == "ChalAlgo")
    assert champ_call["n_wf"] == chal_call["n_wf"] == 900
    assert champ_call["config"].objective == setup.st.config.objective
    assert champ_call["config"].validation == setup.st.config.validation
    assert champ_call["config"].name == "old"  # the champion's own configuration otherwise
    assert champ_call["best_cfg"]["best_params"] == {"max_depth": 3}
    assert champ_call["pool_builder"] is setup.st.pool_builder  # same feature settings -> pool reused


def test_the_champions_pool_is_rebuilt_when_its_feature_settings_differ(setup, monkeypatch):
    other = _config("old", flat_thr=0.01, holdout_months=12, families=["technical", "long_cycle"])
    with setup.conn:
        setup.conn.execute("UPDATE run SET config_json = ? WHERE run_id = 'champ_run'", (other.model_dump_json(),))
    built = {}

    class FakeBuilder:
        def __init__(self, raw, config, target_col, base_pool, fold_cuts, conn=None, snapshot_id=None):
            built["families"] = config.features.families
            built["fold_cuts"] = fold_cuts
            self.fold_cuts = fold_cuts

        def get(self, cut):
            return pd.DataFrame(columns=["IDX_TEST", "lc_1", "lc_2"])

    monkeypatch.setattr(engine, "build_base_feature_pool", lambda raw, config, target_col: pd.DataFrame())
    monkeypatch.setattr(engine, "_FoldPoolBuilder", FakeBuilder)

    _duel(setup)

    champ_call = next(c for c in setup.calls if c["algo"] == "ChampAlgo")
    assert built["families"] == ["technical", "long_cycle"]
    assert built["fold_cuts"] == setup.st.pool_builder.fold_cuts
    assert isinstance(champ_call["pool_builder"], FakeBuilder)


def test_first_model_of_a_pair_is_crowned_directly(setup):
    with setup.conn:
        setup.conn.execute("UPDATE run SET status = 'failed' WHERE run_id = 'champ_run'")
    d = _duel(setup)
    assert d["decision"] == "promoted_first"
    cur = champions.current(setup.conn, "^TEST", H)
    assert (cur["run_id"], cur["reason"]) == ("chal_run", "first")
    assert champions.list_archive(setup.conn) == []


@pytest.mark.parametrize("unscorable", ["ChalAlgo", "ChampAlgo"])
def test_nothing_changes_when_one_side_cannot_be_scored(setup, unscorable):
    setup.scores[unscorable] = None
    assert _duel(setup)["decision"] == "not_compared"
    assert champions.list_champions(setup.conn) == []
    assert champions.list_archive(setup.conn) == []
    assert _run_exists(setup.conn, "chal_run") and _run_exists(setup.conn, "champ_run")


def test_nothing_changes_without_a_holdout(setup):
    setup.st.has_holdout = False
    assert _duel(setup)["decision"] == "not_compared"
    assert champions.list_archive(setup.conn) == []
    assert _run_exists(setup.conn, "chal_run") and _run_exists(setup.conn, "champ_run")


def test_a_failing_duel_keeps_the_status_quo_and_does_not_raise(setup, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_evaluate_holdout", broken)
    d = _duel(setup)
    assert d["decision"] == "error" and "boom" in d["error"]
    assert champions.list_champions(setup.conn) == []
    assert _run_exists(setup.conn, "chal_run") and _run_exists(setup.conn, "champ_run")


def test_the_challengers_known_holdout_evaluation_is_reused(setup):
    known = {"metrics": {"F1_dir": 0.70}, "n_test": 300}
    d = champion_duel.duel_and_promote(setup.st, {H: setup.best_h}, {H: setup.chal_tid}, {H: known})[H]
    assert d["challenger_f1_dir"] == pytest.approx(0.70)
    assert [c["algo"] for c in setup.calls] == ["ChampAlgo"]


def test_a_suspect_challenger_never_takes_the_title(setup):
    """F1_dir 0.99 = fuite de données (data/alignment.py), pas une performance."""
    setup.scores["ChalAlgo"] = 0.99
    d = _duel(setup)
    assert d["decision"] == "suspect_not_promoted"
    assert champions.list_champions(setup.conn) == []
    assert champions.list_archive(setup.conn) == []
    assert _run_exists(setup.conn, "chal_run") and _run_exists(setup.conn, "champ_run")


def test_a_suspect_champion_is_replaced_by_a_sane_challenger_even_if_it_scores_lower(setup):
    setup.scores["ChampAlgo"] = 0.97       # le titulaire « parfait » est une fuite
    setup.scores["ChalAlgo"] = 0.52
    d = _duel(setup)
    assert d["decision"] == "challenger_wins" and d["why"] == "suspect champion"
    cur = champions.current(setup.conn, "^TEST", H)
    assert (cur["run_id"], cur["reason"]) == ("chal_run", "replaced_suspect_champion")
    assert [(a["run_id"], a["role"]) for a in champions.list_archive(setup.conn)] == [("champ_run", "replaced_champion")]


def test_an_explicit_suspect_champion_is_replaced_without_re_evaluating_it(setup):
    champions.promote(setup.conn, "^TEST", H, "champ_run", setup.champ_tid, reason="first", holdout_f1_dir=0.99)
    setup.scores["ChalAlgo"] = 0.51
    d = _duel(setup)
    assert d["decision"] == "challenger_wins"
    assert not [c for c in setup.calls if c["algo"] == "ChampAlgo"], "le titulaire suspect n'est pas rejoué"
