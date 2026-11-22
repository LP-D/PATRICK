"""Sprint 1 -- le benchmark est reproductible et son instrumentation ne change
aucun résultat. Aucun test des optimisations futures (caches, profils, ...)."""
from __future__ import annotations

import pytest

from patrick.benchmark import artifacts, profiler, reference, runner
from patrick.pipeline import engine
from patrick.tracking import db as trackdb

# -- rapides ---------------------------------------------------------------

def test_dataset_is_deterministic_and_config_identical():
    a, b = reference.make_raw(reference.TINY.dataset), reference.make_raw(reference.TINY.dataset)
    assert a.equals(b)
    assert reference.make_raw(reference.REFERENCE.dataset).shape[0] == reference.REFERENCE.dataset.n_days
    ca = reference.make_config(reference.TINY, "walkforward", "x")
    cb = reference.make_config(reference.TINY, "walkforward", "y")   # autre dossier de sortie
    assert reference.config_digest(ca) == reference.config_digest(cb)
    assert ca.output.seed == reference.PIPELINE_SEED
    other = reference.make_config(reference.TINY, "cpcv", "x")
    assert reference.config_digest(other) != reference.config_digest(ca)


def test_profiler_self_time_excludes_children():
    t = iter(x * 1.0 for x in range(100))
    prof = profiler.Profiler(clock=lambda: next(t), cpu_clock=lambda: 0.0, sample_memory=False)
    prof._t_start, prof._cpu_start = 0.0, 0.0
    with prof.span("phase_a", "phase"), prof.span("child"):
        pass
    agg = prof.components[("phase_a", "child")]
    assert agg.count == 1 and agg.self_s == agg.inclusive_s
    assert prof.phases["phase_a"]["wall_s"] > agg.inclusive_s   # la phase englobe l'enfant


def test_install_restores_every_patched_attribute():
    before = (engine._FoldContext.prepare, engine._select, engine._tune, engine.select_features,
              trackdb.get_cached_selection, trackdb.sqlite3)
    with profiler.install(profiler.Profiler(sample_memory=False)):
        assert engine._FoldContext.prepare is not before[0]
    after = (engine._FoldContext.prepare, engine._select, engine._tune, engine.select_features,
             trackdb.get_cached_selection, trackdb.sqlite3)
    assert before == after


def test_compare_baselines_detects_a_difference(tmp_path):
    for name, val in (("a", "1"), ("b", "2")):
        d = tmp_path / name
        d.mkdir()
        (d / "x.csv").write_text(f"v\n{val}\n")
        (d / "digests.json").write_text(f'{{"x.csv": "{val}", "__all__": "{val}"}}')
    res = artifacts.compare_baselines(str(tmp_path / "a"), str(tmp_path / "a"))
    assert res["identical"]
    res = artifacts.compare_baselines(str(tmp_path / "a"), str(tmp_path / "b"))
    assert not res["identical"] and res["differences"][0]["max_abs_diff"] == 1.0


# -- pipeline complet (lents) ---------------------------------------------------

@pytest.mark.slow
@pytest.mark.parametrize("scheme", ["walkforward", "cpcv"])
def test_instrumentation_does_not_change_results_and_run_is_reproducible(tmp_path, scheme):
    spec = reference.TINY
    plain = runner.run_scenario(spec, scheme, tmp_path / "plain", instrument=False, baseline_dir=tmp_path / "b_plain")
    inst1 = runner.run_scenario(spec, scheme, tmp_path / "i1", instrument=True, baseline_dir=tmp_path / "b_i1")
    inst2 = runner.run_scenario(spec, scheme, tmp_path / "i2", instrument=True, baseline_dir=tmp_path / "b_i2")

    # même snapshot / même configuration / même seed
    assert plain["snapshot"]["data_hash"] == inst1["snapshot"]["data_hash"] == inst2["snapshot"]["data_hash"]
    assert plain["config_digest"] == inst1["config_digest"] == inst2["config_digest"]
    assert plain["seed"] == inst1["seed"] == inst2["seed"] == reference.PIPELINE_SEED

    # l'instrumentation ne change aucun artefact ; deux runs instrumentés non plus
    for other in (tmp_path / "b_i1", tmp_path / "b_i2"):
        cmp = artifacts.compare_baselines(str(tmp_path / "b_plain"), str(other))
        assert cmp["identical"], cmp
    assert plain["digests"]["__all__"] == inst1["digests"]["__all__"] == inst2["digests"]["__all__"]

    # les compteurs (pas les temps) sont reproductibles
    assert inst1["deterministic_view"] == inst2["deterministic_view"]
    counters = inst1["profile_data"]["counter_totals"]
    assert counters["sqlite.commit"] > 0 and counters["scaler.fit_transform"] > 0
    if scheme == "walkforward":   # CPCV a sa propre topologie, sans `_FoldContext.prepare`
        assert counters["fold_context.prepare"] > 0 and counters["fit_eval_full.calls"] > 0
    # l'instrumentation restaure le moteur
    assert not hasattr(engine._FoldContext.prepare, "__wrapped__")
