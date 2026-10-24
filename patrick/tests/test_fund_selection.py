"""Fonds, pilote automatique : sélection automatique des modèles pertinents (spec 2026-10-16, §3). Aucun réseau."""
from __future__ import annotations

import datetime as dt

import pytest

from patrick.config import defaults as D
from patrick.fund import selection, store
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats

TODAY = dt.date(2026, 10, 16)
FRED_SYMBOL = next(sym for sym, _, src in D.DEFAULT_TARGET_CHOICES if src == "fred")


class World:
    """Une base avec des cellules (cible x horizon) dotées d'un champion, de signaux live et de preuves statistiques."""

    def __init__(self, conn, monkeypatch):
        self.conn, self.bh = conn, {}
        trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
        monkeypatch.setattr(trackstats, "fdr_across_targets", lambda c, alpha=0.10, **kw: {
            "results": {t: {"significant": v[0], "p_value": v[1]} for t, v in self.bh.items()},
            "n_tested": len(self.bh), "n_with_p_value": len(self.bh), "n_untestable": 0, "alpha": alpha,
            "n_bh_significant": sum(1 for v in self.bh.values() if v[0])})

    def cell(self, target: str, horizon: int = 5, *, live: tuple | list | None = ("2026-10-15", 3, 0.6), suffix: str = "", dm_p: float | None = 0.01,
             bh: tuple[bool, float] = (True, 0.02), f1: float | None = None, champion=True) -> int:
        conn = self.conn
        run_id = f"run_{target}_{horizon}{suffix}".replace("^", "")
        trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap1", config_json="{}",
                           config_hash="h", git_sha="sha", seed=42)
        trial_id = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
        trackdb.mark_best_trial(conn, trial_id, artifact_path=None)
        trackdb.finish_run(conn, run_id, "done")
        for row in ([live] if isinstance(live, tuple) else live or []):      # un signal, ou une liste de signaux
            conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, ?, 'live', NULL, ?, ?)",
                         (trial_id, row[0], row[1], row[2]))
        if dm_p is not None:
            conn.execute("INSERT INTO dm_result (run_id, kind, baseline, dm_stat, p_value) VALUES (?, 'class_specific', 'persistence', 2.0, ?)",
                         (run_id, dm_p))
        if f1 is not None:
            conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) VALUES (?, 0, 'holdout', 'F1_dir', ?)",
                         (trial_id, f1))
        if champion:
            conn.execute("INSERT OR REPLACE INTO champion (target, horizon, run_id, trial_id, reason) VALUES (?, ?, ?, ?, 'first')",
                         (target, horizon, run_id, trial_id))
        self.bh.setdefault(target, bh)
        conn.commit()
        return trial_id


    def signal(self, trial_id: int, day: str, y_pred: int, proba: float = 0.6) -> None:
        """Un signal live de plus (le jour passe : on le voit arriver)."""
        self.conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, ?, 'live', NULL, ?, ?)",
                          (trial_id, day, y_pred, proba))
        self.conn.commit()


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _codes(result) -> dict[str, int]:
    return {row["code"]: row["n"] for row in result["excluded"]}


def test_strict_keeps_only_cells_with_all_the_evidence_ranked_by_dm_p_value(conn, world):
    world.cell("AAA", 5, dm_p=0.04)
    world.cell("BBB", 1, dm_p=0.001)
    world.cell("BBB", 5, dm_p=0.20)                           # DM non concluant : exclu, la cible BBB reste retenue pour h1
    world.cell("CCC", 5, dm_p=0.01, bh=(False, 0.40))         # cible écartée par la correction BH

    out = selection.select_models(conn, selection.Policy(), today=TODAY)

    assert [(m["target"], m["horizon"]) for m in out["selected"]] == [("BBB", 1), ("AAA", 5)]
    assert _codes(out) == {"dm": 1, "bh": 1}
    assert out["n_cells"] == 4
    best = out["selected"][0]
    assert best["dm_p"] == 0.001 and best["bh_p"] == 0.02 and best["last_signal"] == {"ts": "2026-10-15", "direction": "UP"}
    assert best["trial_id"] and best["run_id"] == "run_BBB_1" and best["algo"] == "XGBoost"


def test_the_large_tier_ignores_the_multiple_testing_evidence(conn, world):
    world.cell("AAA", dm_p=0.9, bh=(False, 0.9))
    world.cell("BBB", dm_p=None, bh=(False, 1.0))

    out = selection.select_models(conn, selection.Policy(tier="large"), today=TODAY)

    assert sorted(m["target"] for m in out["selected"]) == ["AAA", "BBB"]
    assert out["excluded"] == []


def test_each_exclusion_has_its_own_code_and_detail(conn, world):
    world.cell(FRED_SYMBOL)
    world.cell("AAA__alpha_BBB")
    world.cell("DDD", 504)
    world.cell("EEE", f1=0.99)
    world.cell("FFF", live=None)
    world.cell("GGG", live=("2026-10-01", 3, 0.6))
    world.cell("HHH", dm_p=None)

    out = selection.select_models(conn, selection.Policy(), today=TODAY)

    assert out["selected"] == []
    assert _codes(out) == {"fred": 1, "alpha": 1, "descriptive": 1, "suspect": 1, "no_live": 1, "stale": 1, "dm": 1}
    detail = {c["target"]: c for c in out["excluded_cells"]}
    assert "0,99" in detail["EEE"]["detail"] and "2026-10-01" in detail["GGG"]["detail"]
    assert "Diebold-Mariano" in detail["HHH"]["detail"]


def test_a_cell_without_a_champion_is_not_considered(conn, world):
    world.cell("AAA", champion=False)

    out = selection.select_models(conn, selection.Policy(), today=TODAY)

    assert out["selected"] == [] and out["n_cells"] == 0


def test_only_the_champion_trial_counts_even_if_a_later_run_exists(conn, world):
    tid = world.cell("AAA")
    other = trackdb.create_trial(conn, "run_AAA_5", "GLOBAL", "LightGBM", "SMOTE", 3, "shap")     # essai non champion du même run
    conn.execute("INSERT INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba) VALUES (?, '2026-10-16', 'live', NULL, 0, 0.9)",
                 (other,))
    conn.commit()

    (model,) = selection.select_models(conn, selection.Policy(), today=TODAY)["selected"]

    assert model["trial_id"] == tid and model["last_signal"] == {"ts": "2026-10-15", "direction": "UP"}


def test_the_signal_freshness_window_follows_the_policy(conn, world):
    world.cell("AAA", live=("2026-10-10", 3, 0.6))

    assert selection.select_models(conn, selection.Policy(fresh_days=7), today=TODAY)["selected"] != []
    assert _codes(selection.select_models(conn, selection.Policy(fresh_days=3), today=TODAY)) == {"stale": 1}


def test_the_cap_keeps_the_best_ranked_models(conn, world):
    for i, p in enumerate((0.04, 0.01, 0.03, 0.02)):
        world.cell(f"T{i}", dm_p=p)

    out = selection.select_models(conn, selection.Policy(max_models=2), today=TODAY)

    assert [m["target"] for m in out["selected"]] == ["T1", "T3"]
    assert _codes(out) == {"cap": 2}


def test_the_last_signal_direction_comes_from_the_predicted_class(conn, world):
    world.cell("AAA", live=("2026-10-15", 0, 0.7))

    (model,) = selection.select_models(conn, selection.Policy(), today=TODAY)["selected"]

    assert model["last_signal"]["direction"] == "DOWN"


@pytest.mark.parametrize("patch, message", [
    ({"tier": "folle"}, "tier"), ({"alpha_dm": 0}, "alpha_dm"), ({"alpha_dm": 1.5}, "alpha_dm"),
    ({"alpha_bh": "x"}, "alpha_bh"), ({"fresh_days": 0}, "fresh_days"), ({"max_models": 0}, "max_models"),
    ({"max_models": 1.5}, "max_models"), ({"fresh_days": True}, "fresh_days")])
def test_policy_rejects_bad_values(patch, message):
    with pytest.raises(store.FundError, match=message):
        selection.Policy.from_dict(patch)


def test_policy_round_trips_and_ignores_unknown_keys():
    policy = selection.Policy.from_dict({"tier": "large", "max_models": 12, "inconnu": 1})

    assert policy.tier == "large" and policy.max_models == 12 and policy.alpha_dm == 0.05
    assert selection.Policy.from_dict(policy.to_dict()) == policy


# --- périmètre : horizons et classes d'actifs (une stratégie par classe, à horizon 1) -----------------------------

def test_the_scope_keeps_only_the_wanted_horizons_and_asset_groups(conn, world):
    world.cell("GC=F", 1)
    world.cell("GC=F", 5)
    world.cell("CL=F", 1)
    world.cell("AAPL", 1)
    scope = selection.Policy(horizons=(1,), groups=("Matières premières (futures)",))

    out = selection.select_models(conn, scope, today=TODAY)

    assert [(m["target"], m["horizon"]) for m in out["selected"]] == [("CL=F", 1), ("GC=F", 1)]
    assert out["n_cells"] == 2 and out["n_total"] == 4 and out["excluded"] == []      # hors périmètre : ni exclu ni compté


def test_a_target_outside_every_group_is_never_in_a_group_scope(conn, world):
    world.cell("AAA", 1)

    out = selection.select_models(conn, selection.Policy(groups=("Matières premières (futures)",)), today=TODAY)

    assert out["selected"] == [] and out["n_cells"] == 0


def test_policy_scope_validation_and_round_trip():
    policy = selection.Policy.from_dict({"horizons": [1, 5], "groups": ["Devises (majeures)"]})

    assert policy.horizons == (1, 5) and policy.groups == ("Devises (majeures)",)
    assert selection.Policy.from_dict(policy.to_dict()) == policy
    assert selection.Policy().horizons is None and selection.Policy().groups is None
    for bad in ({"horizons": [0]}, {"horizons": "1"}, {"horizons": [True]}, {"groups": "Devises"}, {"groups": [3]}):
        with pytest.raises(store.FundError):
            selection.Policy.from_dict(bad)
