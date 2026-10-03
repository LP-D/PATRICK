"""Catalogue de futures, règles d'échéance, classes d'actifs et plafonds de levier CFD."""
from __future__ import annotations

import datetime as dt
import re

import pytest

from patrick.fund import instruments as ins


def test_every_catalog_entry_is_well_formed():
    assert {"ES", "CL", "NG", "GC"} <= set(ins.FUTURES_CATALOG)
    for root, spec in ins.FUTURES_CATALOG.items():
        assert spec.root == root and spec.multiplier > 0 and spec.margin > 0 and spec.commission > 0
        assert spec.tick_size > 0 and spec.expiry_rule in ins.EXPIRY_RULES
        assert spec.months and all(1 <= m <= 12 for m in spec.months)
        assert re.fullmatch(rf"{root}[FGHJKMNQUVXZ]\d\d\.(CME|CBT|NYM|CMX)", spec.yahoo_symbol(2026, spec.months[0]))


def test_listed_contracts_are_future_sorted_and_labelled():
    listed = ins.listed_contracts("ES", dt.date(2026, 10, 3))
    assert [c["label"] for c in listed][:3] == ["Z26", "H27", "M27"]
    assert listed[0]["symbol"] == "ESZ26.CME" and listed[0]["expiry"] == "2026-12-18"
    assert len(listed) == 6
    assert all(c["expiry"] > "2026-10-03" for c in listed)
    assert [c["expiry"] for c in listed] == sorted(c["expiry"] for c in listed)
    crude = ins.listed_contracts("CL", dt.date(2026, 10, 3))
    assert crude[0]["label"] == "X26" and len(crude) == 8        # V26 est déjà échu
    assert len(ins.listed_contracts("CL", dt.date(2026, 10, 3), n=3)) == 3


def test_listed_contracts_roll_over_the_year_end():
    assert ins.listed_contracts("GC", dt.date(2026, 12, 20))[0]["label"] == "Z26"           # échoit le 29 décembre
    listed = ins.listed_contracts("GC", dt.date(2026, 12, 30))
    assert listed[0]["label"] == "G27" and listed[0]["expiry"].startswith("2027-02")
    assert ins.listed_contracts("ES", dt.date(2026, 12, 19))[0]["label"] == "H27"


@pytest.mark.parametrize("rule, year, month, expected", [
    ("third_friday", 2026, 12, "2026-12-18"),
    ("crude", 2026, 12, "2026-11-20"),         # 3 jours ouvrés avant le 25 novembre
    ("crude", 2027, 1, "2026-12-22"),           # janvier : le décembre précédent, 25 = vendredi
    ("natgas", 2026, 12, "2026-11-26"),         # 3 jours ouvrés avant le 1er décembre
    ("third_last_bd", 2026, 12, "2026-12-29"),
    ("grain", 2026, 12, "2026-12-14"),
    ("treasury", 2026, 12, "2026-12-22"),       # 7 jours ouvrés avant le 31 décembre (Noël ignoré)
    ("fx", 2026, 12, "2026-12-14"),             # 2 jours ouvrés avant le 3e mercredi (16)
])
def test_expiry_rules(rule, year, month, expected):
    assert ins.EXPIRY_RULES[rule](year, month).isoformat() == expected


@pytest.mark.parametrize("symbol, quote_type, expected", [
    ("EURUSD=X", None, "fx_major"), ("USDJPY=X", None, "fx_major"), ("EURSEK=X", None, "fx_other"),
    ("XAUUSD=X", None, "gold"), ("GC=F", None, "gold"), ("CL=F", None, "commodity"),
    ("^GSPC", None, "index_major"), ("^STOXX50E", "INDEX", "index_major"), ("^VIX", "INDEX", "index_other"),
    ("BTC-EUR", None, "crypto"), ("DOGE", "CRYPTOCURRENCY", "crypto"),
    ("AAPL", None, "equity"), ("MC.PA", "EQUITY", "equity"), ("URTH", "ETF", "equity"),
    ("XYZ", "MUTUALFUND", "other"),
])
def test_cfd_underlying_classification(symbol, quote_type, expected):
    assert ins.classify_cfd_underlying(symbol, quote_type) == expected


def test_leverage_caps_follow_the_esma_classes():
    caps = {s: ins.cfd_leverage_cap(s) for s in ("EURUSD=X", "EURSEK=X", "GC=F", "^GSPC", "CL=F", "^VIX", "AAPL",
                                                  "BTC-USD")}
    assert caps == {"EURUSD=X": 30.0, "EURSEK=X": 20.0, "GC=F": 20.0, "^GSPC": 20.0, "CL=F": 10.0, "^VIX": 10.0,
                    "AAPL": 5.0, "BTC-USD": 2.0}
    assert set(ins.CFD_FEE_CLASS) == set(ins.CFD_LEVERAGE_CAPS)
