"""Bonds in the patrimoine (`wealth/bonds.py`, the ledger, the valuation and
the CSV import), the TWR around a deposit invested the same day, the
fresher of the last close and the trade price, the near-duplicate of a
re-imported statement and the conversion of a foreign quote. Every figure
is invented (round numbers, no connection with any real account)."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.wealth import bonds, importer, ledger, performance, prices, symbols

MATURITY = "2031-05-25"
COUPON = 0.015


# ------------------------------------------------------------------ bond arithmetic

def test_accrued_interest_follows_the_coupon_calendar():
    assert bonds.coupon_period(MATURITY, "2026-11-27") == (pd.Timestamp("2026-05-25"), pd.Timestamp("2027-05-25"))
    days = (pd.Timestamp("2026-11-27") - pd.Timestamp("2026-05-25")).days
    assert bonds.accrued_interest(10_000, COUPON, MATURITY, "2026-11-27") == pytest.approx(10_000 * COUPON * days / 365)
    assert bonds.accrued_interest(10_000, COUPON, MATURITY, "2027-05-25") == 0.0   # coupon day: paid, nothing accrued
    assert bonds.accrued_interest(10_000, COUPON, MATURITY, "2031-06-01") == 0.0   # matured
    assert bonds.accrued_interest(10_000, None, MATURITY, "2026-11-27") == 0.0


def test_yield_and_price_are_inverse_and_pull_to_par():
    y = bonds.yield_to_maturity(COUPON, MATURITY, "2026-11-27", 0.95)
    assert 0.02 < y < 0.03
    assert bonds.clean_price(COUPON, MATURITY, "2026-11-27", y) == pytest.approx(0.95, abs=1e-12)
    later = bonds.clean_price(COUPON, MATURITY, "2029-11-27", y)
    assert 0.95 < later < 1.0                                                  # a discount bond accretes to par
    assert bonds.yield_to_maturity(COUPON, MATURITY, "2026-11-27", 1.0) == pytest.approx(COUPON, abs=2e-4)


def test_coupon_is_inferred_from_the_accrued_interest_paid():
    trade = "2026-11-27"
    accrued = bonds.accrued_interest(10_000, COUPON, MATURITY, bonds.settlement_day(trade))
    assert bonds.infer_coupon(round(accrued, 2), 10_000, MATURITY, trade) == COUPON
    assert bonds.infer_coupon(0.01, 0.03, MATURITY, trade) is None             # too small to say
    assert bonds.infer_coupon(round(accrued, 2) * 1.09, 10_000, MATURITY, trade) is None   # off the grid


def test_maturity_and_coupon_are_read_from_a_label_never_guessed():
    assert bonds.maturity_from_text("Nov. 2032", "Buy trade FR0000000000 FRANKREICH 22/32 O.A.T.") == "2032-11-25"
    assert bonds.maturity_from_text("OAT 2,75% 25/10/2027") == "2027-10-25"
    assert bonds.maturity_from_text("Nov. 2032", "ACME CORP 22/32") is None    # not an OAT: no maturity day to assume
    assert bonds.coupon_from_text("OAT 2,75% 25/10/2027") == pytest.approx(0.0275)
    assert bonds.looks_like_bond("BOND") and bonds.looks_like_bond(None, "FRANKREICH O.A.T.")
    assert not bonds.looks_like_bond("STOCK", "Thales", "Buy trade FR0000121329 THALES")


# ------------------------------------------------------------------ ledger and valuation

def _bond_buy(**kw):
    raw = {"kind": "buy", "ts": "2026-11-27", "symbol": "FR0000000001", "quantity": 10_000, "price": 0.95,
           "fees": 1, "amount": 9_500 + 25 + 1, "rate": COUPON, "maturity": MATURITY, **kw}
    return ledger.normalize_movement(raw)


def test_a_bond_buy_keeps_the_broker_amount_with_its_accrued_interest():
    mv = _bond_buy()
    assert mv["amount"] == pytest.approx(-9_526) and mv["price"] == 0.95
    assert _bond_buy(price=95)["price"] == pytest.approx(0.95)                 # a quote in % of nominal
    assert ledger.normalize_movement({**_bond_buy(), "amount": None})["amount"] == pytest.approx(-9_501)
    with pytest.raises(ledger.LedgerError, match="incohérent"):
        _bond_buy(amount=9_000)                                                # less than nominal x price
    with pytest.raises(ledger.LedgerError, match="incohérent"):
        _bond_buy(amount=11_000)                                               # more than a year of coupon


def test_a_bond_without_quote_is_valued_at_constant_yield_plus_accrued_interest():
    mvs = [ledger.normalize_movement({"kind": "deposit", "ts": "2026-11-27", "amount": 10_000}), _bond_buy()]
    none = performance.dict_price_provider({})
    h = performance.holdings_table(mvs, none, as_of="2026-11-27")
    (row,) = h["rows"]
    accrued = bonds.accrued_interest(10_000, COUPON, MATURITY, "2026-11-27")
    assert row["is_bond"] and row["price_source"] == "rendement constant"
    assert row["price"] == pytest.approx(0.95) and row["accrued"] == pytest.approx(accrued)
    assert row["value"] == pytest.approx(9_500 + accrued)
    assert row["latent_pnl"] == pytest.approx(9_500 + accrued - 9_526)        # cost = the cash paid
    assert row["ytm"] == pytest.approx(bonds.yield_to_maturity(COUPON, MATURITY, "2026-11-27", 0.95))
    a_year_on = performance.holdings_table(mvs, none, as_of="2027-11-26")["rows"][0]
    assert 0.95 < a_year_on["price"] < 1.0
    matured = performance.holdings_table(mvs, none, as_of="2031-06-02")["rows"][0]
    assert matured["price"] == 1.0 and matured["value"] == pytest.approx(10_000)
    val = performance.valuation_series(mvs, none, end="2026-12-04")
    assert val["value"].iloc[0] == pytest.approx(h["total"])


# ------------------------------------------------------------------ TWR and marking

def test_fees_of_a_deposit_invested_the_same_day_weigh_on_the_capital_invested():
    days = pd.bdate_range("2026-11-02", periods=6)
    px = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0, 10.0], index=days)
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": days[0], "amount": 400},
        {"kind": "buy", "ts": days[0], "symbol": "X", "quantity": 40, "price": 10},
        {"kind": "deposit", "ts": days[3], "amount": 5_000},
        {"kind": "buy", "ts": days[3], "symbol": "X", "quantity": 497.5, "price": 10, "fees": 25},
    )]
    rets = performance.time_weighted_returns(performance.valuation_series(mvs, performance.dict_price_provider({"X": px}),
                                                                          end=days[-1]))
    assert rets[days[3]] == pytest.approx(-25 / 5_400)                        # not -25 / 400


def test_a_close_older_than_the_last_trade_gives_way_to_the_trade_price():
    days = pd.bdate_range("2026-11-23", periods=4)
    px = pd.Series([5.9, 5.95], index=days[:2])                               # no close on the trade day yet
    mvs = [ledger.normalize_movement(m) for m in (
        {"kind": "deposit", "ts": days[2], "amount": 6_200},
        {"kind": "buy", "ts": days[2], "symbol": "X", "quantity": 1_000, "price": 6.1},
    )]
    row = performance.holdings_table(mvs, performance.dict_price_provider({"X": px}), as_of=days[2])["rows"][0]
    assert row["price"] == 6.1 and row["price_source"] == "prix de transaction"


# ------------------------------------------------------------------ import

TR_BONDS = """\
"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency","description"
"2026-11-15T18:38:00Z","2026-11-15","DEFAULT","CASH","TRANSFER_INSTANT_INBOUND","","Jane Doe","","","","3000.000000","","","EUR","Incoming transfer"
"2026-11-15T18:40:00Z","2026-11-15","DEFAULT","CASH","IPO_SUBSCRIPTION","STOCK","Acme","US0000000002","","","-2999.000000","-1.00","","EUR","IPO access pre-payment for subscription: x"
"2026-11-19T11:09:00Z","2026-11-19","DEFAULT","TRADING","BUY","STOCK","Acme","US0000000002","10.0000000000","50.0000000000","","","","EUR","BUY US0000000002"
"2026-11-19T11:09:01Z","2026-11-19","DEFAULT","CASH","IPO_SUBSCRIPTION","STOCK","Acme","US0000000002","","","2499.000000","","","EUR","(partial reimbursement) IPO access pre-payment"
"2026-11-27T08:00:00Z","2026-11-27","DEFAULT","CASH","TRANSFER_INBOUND","","Jane Doe","","","","10000.000000","","","EUR","Incoming transfer"
"2026-11-27T08:17:00Z","2026-11-27","DEFAULT","TRADING","BUY","BOND","May 2031","FR0000000001","10000.0000000000","0.9500000000","-{cash:.2f}","-1.00","","EUR","Buy trade FR0000000001 FRANKREICH 21/31 O.A.T., quantity: 10000.0"
"2026-11-27T08:17:00Z","2026-11-27","DEFAULT","TRADING","BUY","BOND","May 2031","FR0000000001","0.0300000000","0.9500000000","-0.03","","","EUR","Buy trade FR0000000001 FRANKREICH 21/31 O.A.T., quantity: 0.03"
"""


def test_trade_republic_bond_and_ipo_lines_are_booked_like_the_broker_cash():
    accrued = round(bonds.accrued_interest(10_000, COUPON, MATURITY, bonds.settlement_day("2026-11-27")), 2)
    csv = TR_BONDS.replace("{cash:.2f}", f"{9_500 + accrued:.2f}")
    queries = []

    def search(q):
        queries.append(q)
        return [{"symbol": "ACME", "quoteType": "EQUITY"}] if q in ("US0000000002", "Acme") else []

    out = importer.parse_csv(csv.encode(), resolve=symbols.make_resolver("EUR", search=search))
    assert out["errors"] == []
    assert "May 2031" not in queries                                           # a bond's name is never searched
    kinds = [(r["line"], r["kind"]) for r in out["rows"]]
    assert (3, "fee") in kinds and not any(line in (3, 5) and k != "fee" for line, k in kinds)
    bond, rest = [r for r in out["rows"] if r["symbol"] == "FR0000000001"]
    assert (bond["maturity"], bond["rate"], bond["price"]) == (MATURITY, COUPON, 0.95)
    assert bond["amount"] == pytest.approx(-(9_500 + accrued + 1))
    assert rest["rate"] == COUPON                                              # shared from the main line
    assert not any(w["line"] == 8 and "coupon inconnu" in w["warning"] for w in out["warnings"])
    assert any(w["line"] == 7 and "coupon 1.500%" in w["warning"] for w in out["warnings"])
    broker_cash = 3_000 - 2_999 - 1 + 2_499 + 10_000 - (9_500 + accrued) - 1 - 0.03
    assert ledger.replay(out["rows"]).cash == pytest.approx(broker_cash)


LCL = """Historique des opérations
Edition du 27/11/2026
Contrat numéro : 00000 - 000000X;;;M DOE JANE (PEA)
Du 27/11/2024 au 27/11/2026
"Opération";"Valeur";"ISIN";"Quantité";"Montant Net";"Frais";"Date";""
"VERSEMENT";"";"";"0";"1000,00 €";"0,00 ";"2026-11-26";""
"ACHAT COMPTANT";"ETF MONDE";"FR0000000003";"100";"-1010,00 €";"-10,00 €";"2026-11-26";""
"REMBT BOURSE FRAIS PEA";"";"";"0";"0,10 €";"0,00 ";"2026-09-29";""
"VERSEMENT";"";"";"0";"200,00 €";"0,00 ";"2026-09-18";""
"""


def test_a_net_amount_includes_the_fees_and_a_value_date_shift_is_a_probable_duplicate():
    resolve = symbols.make_resolver("EUR", search=lambda q: [{"symbol": "ETFM.PA", "quoteType": "ETF"}]
                                    if q == "FR0000000003" else [])
    out = importer.parse_csv(LCL.encode("cp1252"), resolve=resolve)
    assert out["errors"] == [] and out["columns"]["Valeur"] == "name"
    buy = next(r for r in out["rows"] if r["kind"] == "buy")
    assert (buy["symbol"], buy["price"], buy["fees"], buy["amount"]) == ("ETFM.PA", pytest.approx(10.0), 10.0,
                                                                         pytest.approx(-1010.0))
    typed_by_hand = [ledger.normalize_movement({"kind": "deposit", "ts": "2026-09-21", "amount": 200})]
    plan = importer.plan_import(out["rows"], {}, "acc", {"acc": typed_by_hand})
    status = {(p["ts"], p["kind"]): p["status"] for p in plan}
    assert status[("2026-09-18", "deposit")] == "doublon probable"
    assert status[("2026-11-26", "deposit")] == "" and status[("2026-09-29", "interest")] == ""


# ------------------------------------------------------------------ currency

def test_a_foreign_quote_is_converted_into_the_account_currency(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    days = pd.bdate_range("2026-11-16", periods=3)
    answers = {"ACME": pd.Series([110.0, 121.0, 99.0], index=days),
               "EURUSD=X": pd.Series([1.10, 1.10, 1.10], index=days)}
    asked = []

    def download(symbol, start, auto_adjust, progress):
        asked.append(symbol)
        return pd.DataFrame({"Close": answers.get(symbol, pd.Series(dtype=float))})

    monkeypatch.setattr(prices.yf, "download", download)
    get = prices.make_provider(store=_NoLake())
    assert get("ACME").tolist() == pytest.approx([100.0, 110.0, 90.0])
    assert get("FR0000000001") is None and "FR0000000001" not in asked        # a bare ISIN is not a Yahoo symbol
    assert [prices.quote_currency(s) for s in ("ACME", "AIR.PA", "AXS-EUR", "BTC-USD", "^STOXX50E", "EURUSD=X",
                                                "NESN.SW", "BRK-B", "VUSA.L")] == \
        ["USD", "EUR", "EUR", "USD", None, None, "CHF", "USD", None]


class _NoLake:
    def exists(self, key):
        return False
