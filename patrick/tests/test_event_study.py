"""Generic event study module: point-in-time day 0, abnormal returns,
aggregate tests (size and power checked by simulation)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.research import event_study as es

DAYS = pd.bdate_range("2015-01-01", periods=2000)


def _market(seed=0):
    rng = np.random.default_rng(seed)
    rm = rng.normal(0.0003, 0.01, len(DAYS))
    return pd.Series(100 * np.exp(np.cumsum(rm)), index=DAYS), rm


def _asset(rm, beta=1.2, seed=1, jumps=None):
    rng = np.random.default_rng(seed)
    r = 0.0001 + beta * rm + rng.normal(0, 0.012, len(DAYS))
    for day, size in (jumps or {}).items():
        r[DAYS.get_loc(day)] += size
    return pd.Series(100 * np.exp(np.cumsum(r)), index=DAYS)


def test_event_after_the_close_starts_on_the_next_session():
    d0 = es.event_day_zero("2019-09-10 18:30", DAYS)
    assert d0 == pd.Timestamp("2019-09-11")


def test_event_before_the_close_is_the_same_session():
    assert es.event_day_zero("2019-09-10 13:00", DAYS) == pd.Timestamp("2019-09-10")


def test_weekend_event_moves_to_monday():
    assert es.event_day_zero("2019-09-14", DAYS) == pd.Timestamp("2019-09-16")


def test_timezone_aware_timestamp_is_converted_to_market_time():
    # 22:30 in Paris = 16:30 in New York: after the close.
    assert es.event_day_zero(pd.Timestamp("2019-09-10 22:30", tz="Europe/Paris"), DAYS) == pd.Timestamp("2019-09-11")


def test_known_abnormal_jumps_are_recovered_and_significant():
    market, rm = _market()
    events = list(DAYS[400:1900:75])
    asset = _asset(rm, jumps={d: 0.04 for d in events})
    study = es.run_event_study(asset, events, benchmark=market, event_window=(-2, 2))
    t = study.tests()
    assert t["n_events"] == len(events)
    assert t["caar"] == pytest.approx(0.04, abs=0.01)
    assert t["p_bmp"] < 0.001 and t["p_patell"] < 0.001


def test_no_effect_rejects_at_about_the_nominal_rate():
    rejections = 0
    for seed in range(60):
        market, rm = _market(seed)
        asset = _asset(rm, seed=seed + 100)
        events = list(DAYS[400:1900:75])
        if es.run_event_study(asset, events, benchmark=market, event_window=(-2, 2)).tests()["p_bmp"] < 0.05:
            rejections += 1
    assert rejections <= 8


def test_overlapping_windows_are_flagged():
    market, rm = _market()
    asset = _asset(rm)
    study = es.run_event_study(asset, [DAYS[500], DAYS[505]], benchmark=market, event_window=(-5, 10))
    assert study.overlapping_events


def test_events_without_enough_history_are_skipped_not_crashing():
    market, rm = _market()
    study = es.run_event_study(_asset(rm), [DAYS[10], DAYS[-3]], benchmark=market)
    assert study.n_events == 0 and len(study.skipped) == 2


def test_constant_mean_model_needs_no_benchmark():
    _market_prices, rm = _market()
    study = es.run_event_study(_asset(rm), list(DAYS[400:1900:150]), model="constant_mean")
    assert study.n_events > 5
    assert len(study.caar()) == 26


def test_publication_exactly_at_the_close_is_not_in_the_close():
    """Yahoo stamps after-close earnings at 16:00:00 ET exactly (Netflix,
    every quarter since 2021): the closing print cannot contain them."""
    assert es.event_day_zero("2019-04-16 16:00", DAYS) == pd.Timestamp("2019-04-17")
    assert es.event_day_zero(pd.Timestamp("2019-04-16 16:00", tz="America/New_York"), DAYS) == \
        pd.Timestamp("2019-04-17")
    assert es.event_day_zero("2019-04-16 15:59", DAYS) == pd.Timestamp("2019-04-16")


def _fat_asset(rm, seed, jumps=None):
    rng = np.random.default_rng(seed)
    r = 0.0001 + 1.2 * rm + 0.008 * rng.standard_t(3, len(DAYS))
    for day, size in (jumps or {}).items():
        r[DAYS.get_loc(day)] += size
    return pd.Series(100 * np.exp(np.cumsum(r)), index=DAYS)


def test_unsigned_events_are_detected_by_the_abnormal_variance_tests():
    """Keynotes, earnings: the direction is unknown ex ante, positive and
    negative reactions cancel in the CAAR -- the question is whether the
    price moves MORE than usual around day 0."""
    market, rm = _market()
    events = list(DAYS[400:1900:75])
    jumps = {d: (0.05 if i % 2 else -0.05) for i, d in enumerate(events)}
    study = es.run_event_study(_asset(rm, jumps=jumps), events, benchmark=market, event_window=(-2, 2))
    assert study.tests()["p_bmp"] > 0.05
    v = study.abnormal_variance((0, 1))
    assert v["p_chi2"] < 0.001 and v["p_rank"] < 0.001
    assert v["mean_z2"] > 3


def test_rank_variance_test_keeps_its_size_under_fat_tails():
    """Student-t(3) residuals: the chi2 version assumes Gaussian abnormal
    returns; the rank version compares each event's |CAR| with the same
    statistic on its own estimation window, so it does not."""
    rejections = 0
    for seed in range(60):
        market, rm = _market(seed)
        study = es.run_event_study(_fat_asset(rm, seed + 200), list(DAYS[400:1900:75]),
                                   benchmark=market, event_window=(-2, 2))
        rejections += study.abnormal_variance((0, 1))["p_rank"] < 0.05
    assert rejections <= 8


def test_markdown_report_lists_groups_and_events():
    market, rm = _market()
    events = list(DAYS[400:1900:150])
    asset = _asset(rm, jumps={d: 0.05 for d in events})
    up = es.run_event_study(asset, events[:5], benchmark=market, labels=[f"e{i}" for i in range(5)])
    rest = es.run_event_study(asset, events[5:], benchmark=market)
    md = es.render_markdown({"beat": up, "miss": rest, "vide": es.run_event_study(asset, [], benchmark=market)},
                            "Test")
    assert md.startswith("# Test")
    assert "| beat | 5 |" in md and "| vide | 0 |" in md
    assert md.count("\n| e") == 5


def test_signed_tests_on_the_reaction_sub_window():
    market, rm = _market()
    events = list(DAYS[400:1900:75])
    asset = _asset(rm, jumps={d: 0.04 for d in events})
    study = es.run_event_study(asset, events, benchmark=market, event_window=(-5, 20))
    react = study.tests((0, 0))
    assert react["caar"] == pytest.approx(0.04, abs=0.006)
    assert react["p_bmp"] < study.tests()["p_bmp"]      # same jump, less noise around it


def test_cli_event_study_from_a_csv(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from patrick import cli
    from patrick.data.sources import yfinance_source

    market, rm = _market()
    asset = _asset(rm, jumps={d: 0.05 for d in DAYS[400:1900:150]})
    monkeypatch.setattr(yfinance_source, "download_one", lambda t, s: market if t == "^GSPC" else asset)
    csv = tmp_path / "ev.csv"
    csv.write_text("# commentaire\npublished_at,label\n" +
                   "".join(f"{d:%Y-%m-%d} 12:00,e{i}\n" for i, d in enumerate(DAYS[400:1900:150])))
    out = tmp_path / "r.md"
    runner = CliRunner()
    res = runner.invoke(cli.app, ["research", "event-study", "--ticker", "X", "--events", str(csv),
                                  "--output", str(out)])
    assert res.exit_code == 0, res.output
    assert "| tous | 10 |" in out.read_text()
    both = runner.invoke(cli.app, ["research", "event-study", "--ticker", "X", "--events", str(csv), "--earnings"])
    assert both.exit_code != 0
    bad = tmp_path / "bad.csv"
    bad.write_text("date,label\n2019-01-02,x\n")
    assert runner.invoke(cli.app, ["research", "event-study", "--ticker", "X", "--events", str(bad)]).exit_code != 0
