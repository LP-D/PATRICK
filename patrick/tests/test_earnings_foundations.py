"""Événements de résultats : parseur de newsletter, places de cotation, BMO / AMC et jour de réaction J0 (aucun réseau)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from patrick.earnings import exchanges
from patrick.earnings.config import EarningsConfig
from patrick.earnings.parse import (
    default_anchor_monday,
    parse_newsletter,
    snap_to_monday,
)

NEWSLETTER = """
Résultats de la semaine à venir

📅 Lundi 3 novembre : Palantir, Arm, Novo Nordisk (Copenhague), Ryanair (ADR)
**Mardi** — AMD, Block, Interparfums (Paris), Air France-KLM
Mercredi
Apple (AAPL), Qualcomm, SAP (avant ouverture) ; et Figma
Jeudi : Leonardo, Diageo, SharkNinja,
AMC (Entertainment)
Samedi - Berkshire Hathaway
"""


def test_the_default_monday_is_the_one_of_the_current_week():
    assert default_anchor_monday(date(2026, 11, 3)) == date(2026, 11, 2)      # mardi : lundi de CETTE semaine
    assert default_anchor_monday(date(2026, 11, 2)) == date(2026, 11, 2)      # lundi
    assert default_anchor_monday(date(2026, 11, 8)) == date(2026, 11, 2)      # dimanche : ISO, même semaine
    assert snap_to_monday(date(2026, 11, 5)) == date(2026, 11, 2)


def test_days_names_and_dates_are_read():
    result = parse_newsletter(NEWSLETTER, anchor=date(2026, 11, 2))
    by_day: dict[str, list[str]] = {}
    for it in result.items:
        by_day.setdefault(it.day_label, []).append(it.name)
    assert by_day["Lundi"] == ["Palantir", "Arm", "Novo Nordisk", "Ryanair"]
    assert by_day["Mardi"] == ["AMD", "Block", "Interparfums", "Air France-KLM"]
    assert by_day["Mercredi"] == ["Apple", "Qualcomm", "SAP", "Figma"]
    assert by_day["Jeudi"] == ["Leonardo", "Diageo", "SharkNinja", "AMC"]
    assert by_day["Samedi"] == ["Berkshire Hathaway"]
    assert result.ignored == ["Résultats de la semaine à venir"]
    palantir = result.items[0]
    assert palantir.plan_date == date(2026, 11, 2)
    assert [i.plan_date for i in result.items if i.day_label == "Samedi"] == [date(2026, 11, 7)]


def test_parentheses_become_hints_not_part_of_the_name():
    items = {it.name: it for it in parse_newsletter(NEWSLETTER, anchor=date(2026, 11, 2)).items}
    assert items["Novo Nordisk"].listing_hint == "co" and items["Novo Nordisk"].hint == "Copenhague"
    assert items["Ryanair"].listing_hint == "adr"
    assert items["Apple"].symbol_hint == "AAPL"
    assert items["SAP"].timing_hint == "BMO"
    assert items["AMC"].hint == "Entertainment" and items["AMC"].symbol_hint == ""


def test_a_text_without_any_day_gives_a_warning():
    result = parse_newsletter("juste une phrase sans jour", anchor=date(2026, 11, 2))
    assert result.items == [] and result.warnings


def test_the_same_name_twice_in_a_day_is_kept_once():
    result = parse_newsletter("Lundi : Apple, apple, Meta", anchor=date(2026, 11, 2))
    assert [i.name for i in result.items] == ["Apple", "Meta"]


def test_a_company_starting_like_a_day_is_not_a_header():
    result = parse_newsletter("Lundi : Marvell, Mercedes-Benz", anchor=date(2026, 11, 2))
    assert [i.name for i in result.items] == ["Marvell", "Mercedes-Benz"]


# ------------------------------------------------------------------------------------------------------------- places

def test_venue_lookup_by_suffix():
    assert exchanges.venue_for("AAPL").region == "US"
    assert exchanges.venue_for("BRK-B").region == "US"
    assert exchanges.venue_for("BF.B").region == "US"          # classe d'actions, pas un suffixe de place
    assert exchanges.venue_for("NOVO-B.CO").tz == "Europe/Copenhagen"
    assert exchanges.venue_for("RYA.IR").currency == "EUR"
    assert exchanges.benchmark_candidates("MC.PA")[0] == "^FCHI"
    assert exchanges.benchmark_candidates("AAPL") == ("^GSPC", "^GSPC")


def _ny(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="America/New_York")


def test_yahoo_stamps_are_new_york_time_even_for_europe():
    # Novo Nordisk publie à 07:00 CET : Yahoo l'écrit 01:00 à New York. Lue telle quelle, l'heure semblerait « avant l'ouverture
    # américaine » pour tout le monde ; reconvertie, elle est avant l'ouverture de Copenhague (09:00) : BMO.
    out = exchanges.classify_timing(_ny("2026-08-06 01:00"), "NOVO-B.CO")
    assert out["timing"] == "BMO" and out["local_time"] == "07:00" and out["local_date"] == date(2026, 8, 6)
    # SAP à 22:00 CET (16:00 New York) : après la clôture de Xetra (17:30) -> AMC, même jour local
    sap = exchanges.classify_timing(_ny("2019-01-29 16:00"), "SAP.DE")
    assert sap["timing"] == "AMC" and sap["local_time"] == "22:00"


def test_us_timings():
    assert exchanges.classify_timing(_ny("2026-11-02 16:00"), "AAPL")["timing"] == "AMC"
    assert exchanges.classify_timing(_ny("2026-11-04 07:00"), "PLTR")["timing"] == "BMO"
    during = exchanges.classify_timing(_ny("2026-11-04 11:00"), "AAPL")
    assert during["timing"] == "DURING" and during["uncertain"]
    # la clôture exacte : 16:00:00 est une publication APRÈS la clôture (convention Yahoo des annonces après séance)
    assert exchanges.classify_timing(_ny("2026-11-02 16:00"), "MSFT")["uncertain"] is False


def test_a_midnight_stamp_means_no_time_is_known():
    out = exchanges.classify_timing(_ny("2026-11-03 00:00"), "AAPL")
    assert out["timing"] == "UNKNOWN" and out["uncertain"] and out["reason"] == "heure absente"
    assert exchanges.classify_timing(pd.Timestamp("2026-11-03"), "AAPL")["timing"] == "UNKNOWN"


def test_tokyo_close_moved_to_1530_in_november_2024():
    old = exchanges.classify_timing(_ny("2024-05-09 02:15"), "7203.T")       # 15:15 à Tokyo, clôture 15:00 : après
    new = exchanges.classify_timing(_ny("2025-05-08 02:15"), "7203.T")       # 15:15 à Tokyo, clôture 15:30 : pendant
    assert old["timing"] == "AMC" and new["timing"] == "DURING"


def test_heuristic_timing_by_venue():
    assert exchanges.heuristic_timing("MC.PA") == "BMO"
    assert exchanges.heuristic_timing("7203.T") == "AMC"
    assert exchanges.heuristic_timing("AAPL") == "UNKNOWN"


# ------------------------------------------------------------------------------------------------------------------- J0

SESSIONS = pd.bdate_range("2026-10-26", "2026-11-13")                   # pas de férié dans ce tronçon


@pytest.mark.parametrize("ann_date, timing, expected", [
    ("2026-11-02", "BMO", "2026-11-02"),             # avant l'ouverture : réaction le jour même
    ("2026-11-02", "AMC", "2026-11-03"),             # après la clôture : lendemain (Apple, Palantir)
    ("2026-11-06", "AMC", "2026-11-09"),             # vendredi soir : lundi
    ("2026-11-07", "BMO", "2026-11-09"),             # samedi (Berkshire) : lundi, quelle que soit l'étiquette
    ("2026-11-07", "AMC", "2026-11-09"),
    ("2026-11-03", "DURING", "2026-11-03"),
    ("2026-11-03", "UNKNOWN", "2026-11-03"),
])
def test_day_zero(ann_date, timing, expected):
    assert exchanges.day_zero(ann_date, timing, SESSIONS) == pd.Timestamp(expected)


def test_day_zero_beyond_the_calendar_is_none():
    assert exchanges.day_zero("2026-11-20", "BMO", SESSIONS) is None
    projected = exchanges.project_sessions(SESSIONS, "2026-11-20")
    assert exchanges.day_zero("2026-11-20", "BMO", projected) == pd.Timestamp("2026-11-20")


# --------------------------------------------------------------------------------------------------------------- config

def test_config_hash_ignores_display_only_fields():
    base = EarningsConfig()
    assert base.measure_hash() == EarningsConfig(test="patell", winsorize=0.05, run_up=(-5, -1)).measure_hash()
    assert base.measure_hash() != EarningsConfig(model="market_adjusted").measure_hash()
    assert base.measure_hash() != EarningsConfig(est_window=(-200, -30)).measure_hash()


def test_config_validation_and_roundtrip():
    cfg = EarningsConfig(est_window=(-200, -40), drift_windows=((2, 10),))
    assert EarningsConfig.from_dict(cfg.to_dict()) == cfg
    with pytest.raises(ValueError):
        EarningsConfig(est_window=(-250, -5)).validate()        # l'estimation doit finir avant la trajectoire stockée
    with pytest.raises(ValueError):
        EarningsConfig(model="magie").validate()
