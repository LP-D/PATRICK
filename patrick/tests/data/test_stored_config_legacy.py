"""Relire la configuration ENREGISTRÉE d'un run : un champ absent de l'enregistrement date d'avant son ajout.

`selection.one_se_rule` est activée par défaut (ADR 0006), mais un run lancé avant le champ a tourné sans elle : le reprendre
(`patrick resume`) avec le défaut d'aujourd'hui changerait la règle de sélection ET le hachage de configuration, donc le nom des
études Optuna — les essais déjà faits ne seraient plus retrouvés. L'enregistrement absent de la clé se relit donc « désactivée ».
"""
from __future__ import annotations

import json

import pytest

from patrick import cli
from patrick.config.schema import RunConfig
from patrick.pipeline import engine
from patrick.tracking import db as trackdb


def _legacy_json(**selection) -> str:
    """La configuration telle qu'enregistrée AVANT le champ : la clé `one_se_rule` n'y figure pas."""
    data = json.loads(RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "X"},
                                                "output": {"dir": "out"}}).model_dump_json())
    data["selection"].pop("one_se_rule")
    data["selection"].update(selection)
    return json.dumps(data)


def test_a_stored_config_without_the_field_reads_as_disabled():
    assert RunConfig.from_stored_json(_legacy_json()).selection.one_se_rule is False


def test_a_stored_config_without_a_selection_block_reads_as_disabled():
    data = json.loads(_legacy_json())
    del data["selection"]
    assert RunConfig.from_stored_json(json.dumps(data)).selection.one_se_rule is False


@pytest.mark.parametrize("stored", [True, False])
def test_a_stored_value_is_kept(stored):
    assert RunConfig.from_stored_json(_legacy_json(one_se_rule=stored)).selection.one_se_rule is stored


def test_the_reloaded_legacy_config_has_the_hash_it_had_when_the_run_started():
    original = RunConfig.model_validate({"name": "t", "objective": {"target_symbol": "X"}, "output": {"dir": "out"},
                                         "selection": {"one_se_rule": False}})
    assert engine._config_hash(RunConfig.from_stored_json(_legacy_json())) == engine._config_hash(original)


def test_resume_replays_a_run_stored_before_the_field_under_the_rule_it_ran_with(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "snap", "hash", 0, 1, "api")
    trackdb.create_run(conn, "t_h3_deadbeef", target="X", horizon=3, snapshot_id="snap", config_json=_legacy_json(),
                       config_hash="x", git_sha="x", seed=42)
    conn.close()
    seen: dict = {}

    def spy(config, **kwargs):
        seen["rule"] = config.selection.one_se_rule
        raise RuntimeError("stop")

    monkeypatch.setattr(cli, "run_pipeline", spy)
    with pytest.raises(RuntimeError, match="stop"):
        cli.resume_cmd(run_id="t_h3_deadbeef")
    assert seen["rule"] is False
