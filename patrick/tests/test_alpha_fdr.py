"""Famille BH des cibles alpha : séparée des cibles brutes (F05), p-value unilatérale (le modèle doit faire MIEUX)."""
from __future__ import annotations

import pytest

from patrick.tracking import db as trackdb
from patrick.tracking import history, stats


def _target(conn, label, dm_stat, p_value, horizon=5, kind="class_specific"):
    """Un run terminé sur `label`, avec un résultat Diebold-Mariano sur le holdout."""
    run_id = f"run_{label}_{horizon}".replace("^", "").replace("_", "")
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, "api")
    trackdb.create_run(conn, run_id, target=label, horizon=horizon, snapshot_id="snap", config_json="{}",
                       config_hash="h", git_sha="s", seed=1)
    conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
    conn.execute("INSERT INTO dm_result (run_id, kind, baseline, dm_stat, p_value, sample, n_obs) "
                 "VALUES (?, ?, 'BASELINE_persistence', ?, ?, 'holdout', 300)", (run_id, kind, dm_stat, p_value))
    conn.commit()
    return run_id


def _families(conn, **kw):
    return {family: set(stats.fdr_across_targets(conn, family=family, **kw)["results"])
            for family in ("raw", "alpha", "all")}


def test_alpha_targets_form_their_own_family_and_the_raw_family_is_unchanged(conn):
    _target(conn, "^GSPC", -2.0, 0.04)
    _target(conn, "AAPL", 0.3, 0.76)
    _target(conn, "MC.PA__alpha_^STOXX50E", 1.1, 0.27)
    _target(conn, "SOP.PA__alpha_^STOXX50E", 1.8, 0.07)

    fam = _families(conn)

    assert fam["raw"] == {"^GSPC", "AAPL"}
    assert fam["alpha"] == {"MC.PA__alpha_^STOXX50E", "SOP.PA__alpha_^STOXX50E"}
    assert fam["all"] == fam["raw"] | fam["alpha"]


def test_the_default_family_is_the_raw_one(conn):
    """Le comportement d'avant l'existence des cibles alpha est celui par défaut : leur présence ne change rien."""
    _target(conn, "^GSPC", -2.0, 0.04)
    before = stats.fdr_across_targets(conn)
    _target(conn, "MC.PA__alpha_^STOXX50E", -3.0, 0.003)

    after = stats.fdr_across_targets(conn)

    assert after["n_tested"] == before["n_tested"] == 1
    assert after["results"] == before["results"]


def test_a_significantly_worse_model_is_never_a_discovery_by_default(conn):
    """dm_stat > 0 = le modèle fait MOINS BIEN que sa baseline. Avant la correction, la p-value bilatérale
    transformait ce cas en « découverte » ; vrai pour la famille alpha comme pour la famille brute."""
    for family, worse, better in (("alpha", "WORSE__alpha_X", "BETTER__alpha_X"), ("raw", "WORSE", "BETTER")):
        _target(conn, worse, 3.5, 0.0007)                    # significativement pire
        _target(conn, better, -3.5, 0.0007)                  # significativement meilleur
        result = stats.fdr_across_targets(conn, family=family)["results"]

        assert result[worse]["significant"] is False and result[better]["significant"] is True
        assert result[better]["best_run_p_value"] == pytest.approx(0.00035)
        assert result[worse]["best_run_p_value"] == pytest.approx(1 - 0.00035)


def test_the_two_sided_behaviour_is_still_available_explicitly(conn):
    _target(conn, "WORSE", 3.5, 0.0007)

    legacy = stats.fdr_across_targets(conn, one_sided=False)["results"]["WORSE"]

    assert legacy["significant"] is True and legacy["best_run_p_value"] == pytest.approx(0.0007)


def test_one_sided_keeps_the_sidak_adjustment_over_several_horizons(conn):
    _target(conn, "A__alpha_X", -2.0, 0.05, horizon=5)
    _target(conn, "A__alpha_X", -1.0, 0.30, horizon=20)

    result = stats.fdr_across_targets(conn, family="alpha")["results"]["A__alpha_X"]

    assert result["n_runs_with_p_value"] == 2 and result["best_run_p_value"] == pytest.approx(0.025)


def test_family_of_a_label():
    assert stats.family_of("^GSPC") == "raw" and stats.family_of("MC.PA__alpha_^STOXX50E") == "alpha"


def test_history_pages_look_an_alpha_target_up_in_its_own_family(conn):
    """Sans cela, la page d'un run alpha ne trouverait jamais sa cible dans la famille brute (résultat vide)."""
    run_id = _target(conn, "MC.PA__alpha_^STOXX50E", -2.5, 0.013)
    _target(conn, "AAPL", -2.0, 0.04)

    detail = history.run_detail(conn, run_id)
    target = history.target_detail(conn, "MC.PA__alpha_^STOXX50E")
    raw_target = history.target_detail(conn, "AAPL")

    assert detail["target_fdr"] is not None and detail["fdr_result"]["n_tested"] == 1
    assert target["target_fdr"] is not None and set(target["fdr_result"]["results"]) == {"MC.PA__alpha_^STOXX50E"}
    assert raw_target["target_fdr"] is not None and set(raw_target["fdr_result"]["results"]) == {"AAPL"}
