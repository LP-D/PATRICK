"""`scripts/check_fund_catalog.py` : le rapport liste les contrats servis et signale les racines sans données."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import fund_support as fs
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_fund_catalog.py"


@pytest.fixture
def script(monkeypatch):
    fs.freeze_today(monkeypatch)
    spec = importlib.util.spec_from_file_location("check_fund_catalog", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_lists_served_contracts_and_empty_roots(script):
    def download(symbol, start=None):
        return fs.fake_download("ESZ26.CME") if symbol.startswith("ESH26") else (None, None)

    report = script.check(download)
    assert report["ES"] == ["ESH26.CME"] and report["CL"] == [] and set(report) >= {"ES", "CL", "NG", "GC"}


def test_main_exits_with_1_when_a_root_has_no_contract(script, monkeypatch, capsys):
    monkeypatch.setattr(script.prices, "download_bars", lambda symbol, start=None: (None, None))
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "AUCUN CONTRAT SERVI" in out and "À retirer du catalogue" in out


def test_main_exits_with_0_when_every_root_is_served(script, monkeypatch, capsys):
    monkeypatch.setattr(script.prices, "download_bars", lambda symbol, start=None: fs.fake_download("ESZ26.CME"))
    assert script.main() == 0
    assert "OK" in capsys.readouterr().out
