"""Campagne alpha : configurations générées, critère de découverte du protocole, rapport."""
from __future__ import annotations

import pytest
import yaml

from patrick.config.schema import RunConfig
from patrick.research import alpha_campaign as ac
from patrick.tracking import db as trackdb

TEMPLATE = {
    "name": "mc_pa_alpha",
    "objective": {"target_symbol": "MC.PA", "target_source": "yfinance", "target_kind": "alpha", "horizons": [5, 20],
                  "flat_thr": 0.003, "regimes": ["GLOBAL"]},
    "universe": {"start_date": "2008-01-01", "yf_tickers": ["^GSPC", "^FCHI"], "fred_series": {"NFCI": "NFCI"}},
    "output": {"dir": "runs/mc_pa_alpha", "seed": 42},
}


def test_make_config_changes_only_the_target_the_name_and_the_output_dir():
    cfg = ac.make_config(TEMPLATE, "NEX.PA")

    assert cfg["objective"]["target_symbol"] == "NEX.PA" and cfg["name"] == "nex_pa_alpha"
    assert cfg["output"] == {"dir": "runs/nex_pa_alpha", "seed": 42}
    assert cfg["objective"]["horizons"] == [5, 20] and cfg["universe"] == TEMPLATE["universe"]
    assert TEMPLATE["objective"]["target_symbol"] == "MC.PA"                       # le modèle n'est pas modifié
    assert RunConfig.model_validate(cfg).objective.run_label() == "NEX.PA__alpha_^STOXX50E"


def test_make_config_refuses_a_template_that_is_not_alpha():
    raw = {**TEMPLATE, "objective": {**TEMPLATE["objective"], "target_kind": "raw"}}
    with pytest.raises(ValueError, match="alpha"):
        ac.make_config(raw, "NEX.PA")


def test_write_configs_writes_one_yaml_per_symbol(tmp_path):
    paths = ac.write_configs(TEMPLATE, ["NEX.PA", "RXL.PA"], tmp_path)
    assert [p.name for p in paths] == ["nex_pa_alpha.yaml", "rxl_pa_alpha.yaml"]
    assert yaml.safe_load(paths[1].read_text(encoding="utf-8"))["objective"]["target_symbol"] == "RXL.PA"


# --------------------------------------------------------------------------- critère de découverte

def _result(conn, symbol, dm_stat, p_value, *, horizon=5, bench="^STOXX50E"):
    label = f"{symbol}__alpha_{bench}"
    run_id = f"r_{symbol}_{horizon}".replace(".", "").replace("^", "")
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, "api")
    trackdb.create_run(conn, run_id, target=label, horizon=horizon, snapshot_id="snap", config_json="{}",
                       config_hash="h", git_sha="s", seed=1)
    conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
    trial = trackdb.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    conn.execute("UPDATE trial SET is_best = 1 WHERE trial_id = ?", (trial,))
    conn.execute("INSERT INTO dm_result (run_id, kind, baseline, dm_stat, p_value, sample, n_obs) "
                 "VALUES (?, 'class_specific', 'BASELINE_persistence', ?, ?, 'holdout', 300)", (run_id, dm_stat, p_value))
    conn.commit()
    return trial


SYMBOLS = ["A.PA", "B.PA", "C.PA", "D.PA", "E.PA"]


def _evaluate(conn, sharpes, symbols=SYMBOLS, q=0.10):
    return ac.evaluate_campaign(conn, symbols, q=q, holdout_sharpe=lambda c, trial_id: sharpes.get(trial_id, 0.0))


def test_a_discovery_needs_both_a_significant_one_sided_test_and_a_positive_net_sharpe(conn):
    t_both = _result(conn, "A.PA", -4.0, 0.0001)            # significatif ET rentable
    t_stat = _result(conn, "B.PA", -4.0, 0.0001)            # significatif mais Sharpe net négatif
    t_money = _result(conn, "C.PA", -0.5, 0.60)             # rentable mais pas significatif
    t_worse = _result(conn, "D.PA", 4.0, 0.0001)            # significativement PIRE que la baseline
    _result(conn, "E.PA", 0.2, 0.84)
    sharpes = {t_both: 0.9, t_stat: -0.3, t_money: 1.2, t_worse: 1.5}

    report = _evaluate(conn, sharpes)

    verdict = {r["symbol"]: r["discovery"] for r in report["rows"]}
    assert verdict == {"A.PA": True, "B.PA": False, "C.PA": False, "D.PA": False, "E.PA": False}
    assert report["n_discoveries"] == 1 and report["m"] == 5


def test_a_run_that_failed_counts_in_the_family_with_p_equal_one(conn):
    """Protocole : aucune valeur n'est retirée ; un run absent compte comme p = 1 (m reste 5, jamais 4)."""
    t = _result(conn, "A.PA", -3.0, 0.002)
    report = _evaluate(conn, {t: 1.0})

    missing = next(r for r in report["rows"] if r["symbol"] == "B.PA")
    assert missing["status"] == "absent" and missing["p_adjusted_campaign"] == 1.0 and missing["discovery"] is False
    assert report["m"] == 5


def test_the_multiplicity_correction_uses_the_whole_family(conn):
    """p = 0,03 est « significatif » seul ; sur 12 tests (11 nuls) le seuil BH devient 0,10 / 12."""
    t = _result(conn, "A.PA", -2.2, 0.06)                    # unilatéral 0,03
    for s in ("B.PA", "C.PA", "D.PA", "E.PA"):
        _result(conn, s, 0.1, 0.9)
    many = SYMBOLS + [f"X{i}.PA" for i in range(7)]

    alone = _evaluate(conn, {t: 1.0}, symbols=["A.PA"])
    family = _evaluate(conn, {t: 1.0}, symbols=many)

    assert alone["rows"][0]["discovery"] is True and family["rows"][0]["discovery"] is False
    assert family["m"] == 12


def test_the_report_is_rendered_with_the_table_and_the_verdict(conn):
    t = _result(conn, "A.PA", -4.0, 0.0001)
    for s in ("B.PA", "C.PA", "D.PA", "E.PA"):
        _result(conn, s, 0.1, 0.9)
    report = _evaluate(conn, {t: 0.9})

    text = ac.render_markdown(report, title="Campagne test")

    assert "# Campagne test" in text and "| A.PA |" in text and "1 découverte" in text and "m = 5" in text
    assert "oui" in text and "non" in text


def test_a_campaign_without_discovery_says_so(conn):
    for s in SYMBOLS:
        _result(conn, s, 0.3, 0.76)
    report = _evaluate(conn, {})
    assert report["n_discoveries"] == 0 and "0 découverte" in ac.render_markdown(report)


# --------------------------------------------------------------------------- exécution séquentielle

def test_run_campaign_runs_one_after_the_other_and_a_failure_does_not_stop_it(tmp_path):
    paths = ac.write_configs(TEMPLATE, ["NEX.PA", "RXL.PA", "IPS.PA"], tmp_path / "cfg")
    seen = []

    def runner(cmd, log_path):
        seen.append((cmd[-1].rsplit("\\", 1)[-1].rsplit("/", 1)[-1], cmd[1:4]))
        log_path.write_text("[TERMINÉ] ok" if "rxl" in cmd[-1] else "plantage", encoding="utf-8")
        return 1 if "nex" in cmd[-1] else 0

    out = ac.run_campaign(paths, tmp_path / "logs", python="python", runner=runner)

    assert [name for name, _ in seen] == ["nex_pa_alpha.yaml", "rxl_pa_alpha.yaml", "ips_pa_alpha.yaml"]
    assert seen[0][1] == ["-m", "patrick.cli", "run"]
    assert [o["returncode"] for o in out] == [1, 0, 0] and not any(o["skipped"] for o in out)


def test_run_campaign_skips_what_is_already_done_so_it_can_be_resumed(tmp_path):
    paths = ac.write_configs(TEMPLATE, ["NEX.PA", "RXL.PA"], tmp_path / "cfg")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "nex_pa_alpha.log").write_text("... [TERMINÉ] 112 lignes", encoding="utf-8")
    ran = []

    out = ac.run_campaign(paths, tmp_path / "logs", python="python",
                          runner=lambda cmd, log: ran.append(cmd[-1]) or 0)

    assert [o["skipped"] for o in out] == [True, False] and len(ran) == 1 and "rxl" in ran[0]


def test_cli_report_reads_the_database_and_prints_the_verdict(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from patrick.cli import app
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect()
    _result(conn, "A.PA", 0.3, 0.76)
    conn.close()
    out_file = tmp_path / "rapport.md"

    result = CliRunner().invoke(app, ["research", "alpha-campaign-report", "--symbols", "A.PA,B.PA",
                                      "--output", str(out_file)])

    assert result.exit_code == 0, result.output
    text = out_file.read_text(encoding="utf-8")
    assert "0 découverte" in text and "| B.PA | absent" in text and "m = 2" in text
