"""Roadmap bloc 4 -- patrimoine: ledger (accounts, movements, PRU), real vs
fictive rules, PEA checks, valuation/TWR/XIRR, benchmark replica, term
deposits, ex-ante risk. Every number checked here is computable by hand."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.wealth import ledger, performance

DAYS = pd.bdate_range("2024-01-01", periods=300)


def _prices(path, start=100.0):
    return pd.Series(start * np.cumprod(np.r_[1.0, 1.0 + np.asarray(path)]), index=DAYS[: len(path) + 1])


# ------------------------------------------------------------------ ledger

def test_buy_and_sell_amounts_are_derived_from_quantity_price_and_fees():
    buy = ledger.normalize_movement({"kind": "buy", "ts": "2024-01-02", "symbol": "air.pa",
                                     "quantity": "10", "price": "150,5", "fees": 2})
    assert buy["symbol"] == "AIR.PA" and buy["amount"] == pytest.approx(-(1505 + 2))
    sell = ledger.normalize_movement({"kind": "sell", "ts": "2024-02-02", "symbol": "AIR.PA",
                                      "quantity": 4, "price": 160, "fees": 1})
    assert sell["amount"] == pytest.approx(640 - 1)
    dep = ledger.normalize_movement({"kind": "withdrawal", "ts": "2024-01-02", "amount": 500})
    assert dep["amount"] == -500


@pytest.mark.parametrize("raw", [
    {"kind": "buy", "ts": "2024-01-02", "symbol": "X", "quantity": 0, "price": 10},
    {"kind": "buy", "ts": "2024-01-02", "quantity": 1, "price": 10},
    {"kind": "teleport", "ts": "2024-01-02", "amount": 1},
    {"kind": "deposit", "ts": "not a date", "amount": 1},
    {"kind": "deposit", "ts": "2024-01-02", "amount": "nan"},
    {"kind": "term_deposit", "ts": "2024-01-02", "amount": 1000, "rate": 0.03, "maturity": "2023-01-01"},
])
def test_invalid_movements_are_rejected(raw):
    with pytest.raises(ledger.LedgerError):
        ledger.normalize_movement(raw)


def test_pru_includes_purchase_fees_and_a_sale_realises_against_it():
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": "2024-01-02", "amount": 10_000},
        {"kind": "buy", "ts": "2024-01-03", "symbol": "A.PA", "quantity": 10, "price": 100, "fees": 10},
        {"kind": "buy", "ts": "2024-01-04", "symbol": "A.PA", "quantity": 10, "price": 120, "fees": 10},
        {"kind": "sell", "ts": "2024-01-05", "symbol": "A.PA", "quantity": 5, "price": 130, "fees": 5},
    )]
    st = ledger.replay(mvs)
    pos = st.positions["A.PA"]
    pru = (1010 + 1210) / 20
    assert pos.quantity == 15 and pos.pru == pytest.approx(pru)
    assert pos.realized == pytest.approx(5 * 130 - 5 - 5 * pru)
    assert st.cash == pytest.approx(10_000 - 1010 - 1210 + 645)


def test_overselling_is_warned_not_raised():
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "buy", "ts": "2024-01-03", "symbol": "A.PA", "quantity": 1, "price": 10},
        {"kind": "sell", "ts": "2024-01-04", "symbol": "A.PA", "quantity": 3, "price": 10},
    )]
    st = ledger.replay(mvs)
    assert any("vente de 3" in w for w in st.warnings)
    assert "A.PA" not in st.positions


def test_pea_checks_cap_early_withdrawal_and_likely_ineligible_security():
    account = {"kind": "PEA", "opened_on": "2022-01-01"}
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": "2022-01-03", "amount": 100_000},
        {"kind": "deposit", "ts": "2023-01-03", "amount": 60_000},
        {"kind": "buy", "ts": "2023-01-04", "symbol": "AAPL", "quantity": 1, "price": 150},
        {"kind": "buy", "ts": "2023-01-04", "symbol": "MC.PA", "quantity": 1, "price": 700},
        {"kind": "withdrawal", "ts": "2024-06-03", "amount": 1_000},
    )]
    warnings = ledger.regulatory_warnings(account, mvs)
    assert any("plafond" in w for w in warnings)
    assert any("5e anniversaire" in w and "2027-01-01" in w for w in warnings)
    assert any("AAPL" in w and "MC.PA" not in w for w in warnings)
    assert ledger.regulatory_warnings({"kind": "CTO"}, mvs) == []


def test_real_and_fictive_transfer_rules(conn):
    real_a = ledger.create_account(conn, "PEA Boursorama", "PEA", "real")
    real_b = ledger.create_account(conn, "CTO", "CTO", "real")
    fictive = ledger.create_account(conn, "Bac à sable", "CTO", "fictive")
    mid = ledger.add_movement(conn, real_a, {"kind": "deposit", "ts": "2024-01-02", "amount": 1000})

    assert ledger.transfer_movement(conn, mid, fictive)["action"] == "copied"
    assert len(ledger.list_movements(conn, real_a)) == 1 and len(ledger.list_movements(conn, fictive)) == 1

    assert ledger.transfer_movement(conn, mid, real_b)["action"] == "moved"
    assert ledger.list_movements(conn, real_a) == [] and len(ledger.list_movements(conn, real_b)) == 1

    fictive_mid = ledger.list_movements(conn, fictive)[0]["movement_id"]
    with pytest.raises(ledger.LedgerError):
        ledger.transfer_movement(conn, fictive_mid, real_a)


def test_clone_as_fictive_copies_every_movement(conn):
    src = ledger.create_account(conn, "PEA", "PEA", "real", opened_on="2020-05-04")
    ledger.add_movement(conn, src, {"kind": "deposit", "ts": "2024-01-02", "amount": 1000})
    ledger.add_movement(conn, src, {"kind": "buy", "ts": "2024-01-03", "symbol": "MC.PA", "quantity": 1,
                                    "price": 700})
    clone = ledger.clone_as_fictive(conn, src)
    acc = ledger.get_account(conn, clone)
    assert acc["mode"] == "fictive" and acc["source_account_id"] == src and acc["opened_on"] == "2020-05-04"
    strip = lambda ms: [{k: v for k, v in m.items() if k not in ("movement_id", "account_id")} for m in ms]
    assert strip(ledger.list_movements(conn, clone)) == strip(ledger.list_movements(conn, src))


def test_default_benchmark_follows_the_wrapper(conn):
    pea = ledger.create_account(conn, "PEA", "PEA", "real")
    livret = ledger.create_account(conn, "Livret A", "LIVRET", "real")
    assert ledger.get_account(conn, pea)["benchmark"] == "^STOXX50E"
    assert ledger.get_account(conn, livret)["benchmark"] is None


# ------------------------------------------------------------- performance

def test_twr_is_neutral_to_flows_while_xirr_is_not():
    """Deposit 1000 and buy; later deposit 9000 more and buy at a higher
    price; the asset then falls back. TWR = the asset's own return; XIRR is
    dragged down by the badly timed second deposit."""
    path = [0.01] * 50 + [-0.01] * 60
    px = _prices(path)
    d0, d1 = DAYS[0], DAYS[50]
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": d0, "amount": 1000},
        {"kind": "buy", "ts": d0, "symbol": "X", "quantity": 1000 / px[d0], "price": px[d0]},
        {"kind": "deposit", "ts": d1, "amount": 9000},
        {"kind": "buy", "ts": d1, "symbol": "X", "quantity": 9000 / px[d1], "price": px[d1]},
    )]
    end = DAYS[len(path)]
    summary = performance.performance_summary(mvs, performance.dict_price_provider({"X": px}), end=end)
    assert summary["twr"] == pytest.approx(px[end] / px[d0] - 1.0, rel=1e-9)
    assert summary["value"] == pytest.approx((1000 / px[d0] + 9000 / px[d1]) * px[end])
    assert summary["xirr"] < summary["twr_annualized"]


def test_xirr_of_a_simple_one_year_investment():
    assert performance.xirr([("2023-01-01", -100.0), ("2024-01-01", 110.0)]) == pytest.approx(0.10, abs=1e-6)
    assert performance.xirr([("2023-01-01", -100.0)]) is None
    assert performance.xirr([("2023-01-01", 100.0), ("2024-01-01", 110.0)]) is None


def test_benchmark_replica_equals_a_portfolio_that_holds_the_benchmark():
    rng = np.random.default_rng(3)
    px = _prices(rng.normal(0, 0.01, 120))
    flows = {DAYS[0]: 5000, DAYS[40]: 2000, DAYS[80]: -1500}
    mvs = []
    for d, f in flows.items():
        kind = "deposit" if f > 0 else "withdrawal"
        mvs.append(ledger.normalize_movement({"kind": kind, "ts": d, "amount": abs(f)}))
        trade = "buy" if f > 0 else "sell"
        mvs.append(ledger.normalize_movement({"kind": trade, "ts": d, "symbol": "IDX",
                                              "quantity": abs(f) / px[d], "price": px[d]}))
    end = DAYS[120]
    s = performance.performance_summary(mvs, performance.dict_price_provider({"IDX": px}), benchmark="IDX", end=end)
    assert s["benchmark_replica_value"] == pytest.approx(s["value"], rel=1e-9)
    assert s["excess_vs_benchmark"] == pytest.approx(0.0, abs=1e-9)


def test_term_deposit_accrues_simple_interest_and_freezes_at_maturity():
    v = performance.term_deposit_value(10_000, 0.03, "2024-01-01", "2024-07-01", "2024-04-01")
    assert v == pytest.approx(10_000 * (1 + 0.03 * 91 / 365))
    frozen = performance.term_deposit_value(10_000, 0.03, "2024-01-01", "2024-07-01", "2025-01-01")
    assert frozen == pytest.approx(10_000 * (1 + 0.03 * 182 / 365))


def test_term_deposit_dilutes_ex_ante_risk_with_zero_variance():
    rng = np.random.default_rng(5)
    px = _prices(rng.normal(0, 0.01, 290))
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": DAYS[0], "amount": 20_000},
        {"kind": "buy", "ts": DAYS[0], "symbol": "EQ", "quantity": 10_000 / px[DAYS[0]], "price": px[DAYS[0]]},
        {"kind": "term_deposit", "ts": DAYS[0], "amount": 10_000, "rate": 0.0, "maturity": "2030-01-01"},
    )]
    prices = performance.dict_price_provider({"EQ": px})
    holdings = performance.holdings_table(mvs, prices, as_of=DAYS[0])
    risk = performance.ex_ante_risk(holdings, prices)
    eq_vol = px.pct_change().dropna().iloc[-252:].std(ddof=1) * np.sqrt(252)
    assert risk["volatility"] == pytest.approx(0.5 * eq_vol, rel=1e-9)
    assert risk["covered_weight"] == pytest.approx(1.0)


def test_a_symbol_without_quotes_is_valued_at_its_last_trade_price_and_says_so():
    mvs = [ledger.normalize_movement({"kind": "buy", "ts": "2024-01-02", "symbol": "FONDS-X", "quantity": 3,
                                      "price": 42})]
    h = performance.holdings_table(mvs, performance.dict_price_provider({}), as_of="2024-02-01")
    row = h["rows"][0]
    assert row["value"] == pytest.approx(126) and row["price_source"] == "prix de transaction"


# ---------------------------------------------------------------- importer

def test_french_broker_csv_is_parsed_day_first_with_decimal_commas():
    from patrick.wealth import importer
    csv_text = ("Date;Opération;Valeur;Quantité;Cours;Montant;Frais;Libellé\n"
                "03/01/2024;Versement;;;;5 000,00;;virement\n"
                "04/01/2024;Achat;MC.PA;2;712,40;;1,99;\n"
                "15/03/2024;Dividende;MC.PA;;;26,00;;\n"
                "\n"
                "16/03/2024;Téléportation;MC.PA;;;1;;\n"
                "31/02/2024;Retrait;;;;10;;\n")
    out = importer.parse_csv(csv_text.encode("utf-8-sig"))
    assert out["delimiter"] == ";"
    assert [r["kind"] for r in out["rows"]] == ["deposit", "buy", "dividend"]
    assert out["rows"][0]["ts"] == "2024-01-03" and out["rows"][0]["amount"] == 5000.0
    assert out["rows"][1]["amount"] == pytest.approx(-(2 * 712.40 + 1.99))
    assert [e["line"] for e in out["errors"]] == [6, 7]


def test_english_comma_csv_and_unreadable_files():
    from patrick.wealth import importer
    out = importer.parse_csv("date,type,symbol,quantity,price,fees\n2024-02-01,buy,AAPL,3,180.5,1\n")
    assert out["rows"][0]["symbol"] == "AAPL" and out["delimiter"] == ","
    with pytest.raises(ledger.LedgerError):
        importer.parse_csv("foo;bar\n1;2\n")
    with pytest.raises(ledger.LedgerError):
        importer.parse_csv(b"x" * (importer.MAX_BYTES + 1))


def test_a_position_without_history_is_risked_through_its_proxy_and_says_so():
    """D.A.T.E (ALDAT.PA) has no quote yet: its risk comes from ^FCHI x the
    declared prior; without a proxy the position would be excluded."""
    rng = np.random.default_rng(21)
    fchi = _prices(rng.normal(0, 0.01, 290))
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": DAYS[0], "amount": 1000},
        {"kind": "buy", "ts": DAYS[0], "symbol": "ALDAT.PA", "quantity": 100, "price": 10},
    )]
    prices = performance.dict_price_provider({"^FCHI": fchi})
    holdings = performance.holdings_table(mvs, prices, as_of=DAYS[0])
    risk = performance.ex_ante_risk(holdings, prices)
    fchi_vol = fchi.pct_change().dropna().iloc[-252:].std(ddof=1) * np.sqrt(252)
    assert risk["excluded"] == []
    assert risk["proxied"][0]["proxy"] == "^FCHI" and risk["proxied"][0]["scale_source"] == "prior"
    assert risk["volatility"] == pytest.approx(2.0 * fchi_vol, rel=0.02)
    without = performance.ex_ante_risk(holdings, prices, proxies={})
    assert without["excluded"] == ["ALDAT.PA"] and without["volatility"] is None
