"""Suites de la relecture de `patrick data` (mineurs M3 et M4) : l'état de la commande après un déplacement terminé, et l'invite de
`--finalize` qui dit ce qu'elle va supprimer.

Tout sur de petits arbres sous `tmp_path` (fixtures de `test_data_move.py`)."""
from __future__ import annotations

import json

from test_data_move import (  # noqa: F401  (fixtures et aides)
    calm,
    pc,
    prepare,
    switched,
)
from typer.testing import CliRunner

from patrick import data_move
from patrick.cli import app as cli_app


def test_status_does_not_call_a_finished_copy_in_progress(pc):  # noqa: F811
    switched(pc)                                              # copie terminée (phase « copied »), bascule faite

    out = CliRunner().invoke(cli_app, ["data", "status"])

    assert out.exit_code == 0 and "Déplacement en cours" not in out.output and "interrompu" not in out.output


def test_status_still_reports_an_interrupted_copy(pc):  # noqa: F811
    (pc.home / data_move.STATE_NAME).write_text(json.dumps({"phase": "copy", "component": "models", "files_done": 12,
                                                            "bytes_done": 1000, "total_bytes": 5000, "target": "D:\\PATRICK DATA"}),
                                                encoding="utf-8")

    out = CliRunner().invoke(cli_app, ["data", "status"])

    assert "Copie en cours ou interrompue" in out.output and "models" in out.output


def test_rollback_removes_the_progress_file(pc):  # noqa: F811
    p = switched(pc)
    assert (pc.home / data_move.STATE_NAME).exists()

    data_move.rollback(p.db)

    assert not (pc.home / data_move.STATE_NAME).exists()


def test_finalize_removes_the_progress_file(pc):  # noqa: F811
    switched(pc)
    assert (pc.home / data_move.STATE_NAME).exists()

    data_move.finalize()

    assert not (pc.home / data_move.STATE_NAME).exists()


def test_the_finalize_prompt_names_what_it_will_delete_and_what_it_checks(pc):  # noqa: F811
    p = switched(pc)

    out = CliRunner().invoke(cli_app, ["data", "move", "--finalize"], input="n\n")

    assert out.exit_code == 1 and p.model.exists()
    for expected in (str(pc.home), "models", "store", str(p.target), "avant la suppression"):
        assert expected in out.output
    assert "la copie a été contrôlée" not in out.output       # l'ancienne phrase affirmait un contrôle pas encore fait
