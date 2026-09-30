"""CSV import of movements (`wealth/importer.py`) and symbol resolution
(`wealth/symbols.py`): a broker export goes in as it is, every position
gets a Yahoo symbol that prices it -- never a homonym (AXS the crypto is
not AXS the NYSE insurer)."""
from __future__ import annotations

import pytest

from patrick.wealth import importer, ledger, symbols

# Shape of a Trade Republic "Exportation de transactions" (made-up values).
TR_CSV = """\
"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency","description"
"2026-09-18T08:26:04Z","2026-09-18","DEFAULT","CASH","TRANSFER_INSTANT_INBOUND","","Jane Doe","","","","110.000000","","","EUR","Incoming transfer from Jane Doe (FR7630006000011234567890189)"
"2026-09-18T08:28:07Z","2026-09-18","DEFAULT","TRADING","BUY","STOCK","Thales","FR0000121329","0.4212290000","237.4000000000","-100.00","-1.00","-0.40","EUR","Buy trade FR0000121329 THALES"
"2026-09-18T08:29:13Z","2026-09-18","PEA","CASH","PEA_MARKETING","","","","","","1.000000","","","EUR","PEA activation"
"2026-09-18T08:36:41Z","2026-09-18","DEFAULT","CASH","CUSTOMER_INPAYMENT","","Jane Doe","","","","10.100000","-0.10","","EUR","Apple Pay Top up"
"2026-09-18T08:36:46Z","2026-09-18","DEFAULT","TRADING","BUY","CRYPTO","Axie Infinity","AXS","11.3246430000","0.8830300000","-10.00","-1.00","","EUR","Buy trade XF000AXS0014 Axie Infinity"
"2026-09-18T08:51:26Z","2026-09-18","DEFAULT","TRADING","BUY","STOCK","Amazon.com","US0231351067","0.0454750000","219.8500000000","-10.00","","","EUR","Buy trade US0231351067 AMAZON.COM INC."
"2026-09-18T08:51:27Z","2026-09-18","DEFAULT","CASH","REFERRAL","","","","","","10.000000","","","EUR","Onboarding cash reward"
"2026-09-18T08:51:29Z","2026-09-18","DEFAULT","CASH","TRANSFER_OUT","","","","","","-78.690000","","","EUR","Versement PEA"
"2026-09-18T08:51:29Z","2026-09-18","PEA","CASH","TRANSFER_IN","","","","","","78.690000","","","EUR","Versement PEA"
"2026-09-18T08:51:26Z","2026-09-18","PEA","TRADING","BUY","STOCK","TotalEnergies","FR0000120271","1.0000000000","78.9800000000","-78.98","-0.39","-0.32","EUR","Buy trade FR0000120271"
"2026-09-22T15:29:10Z","2026-09-22","PEA","TRADING","SELL","STOCK","TotalEnergies","FR0000120271","-1.0000000000","78.3200000000","78.32","-0.39","","EUR","Sell trade FR0000120271"
"2026-09-22T15:40:18Z","2026-09-22","DEFAULT","CASH","TRANSFER_IN","","","","","","77.930000","","","EUR","Retrait PEA"
"2026-09-22T15:40:18Z","2026-09-22","PEA","CASH","TRANSFER_OUT","","","","","","-77.930000","","","EUR","Retrait PEA"
"""

# What Yahoo's search answers (checked 2026-09-30): the ISIN of Amazon only
# finds the Nasdaq listing, its name also finds Xetra.
YAHOO = {
    "FR0000121329": [{"symbol": "HO.PA", "quoteType": "EQUITY"}],
    "FR0000120271": [{"symbol": "TTE.PA", "quoteType": "EQUITY"}],
    "US0231351067": [{"symbol": "AMZN", "quoteType": "EQUITY"}],
    "Amazon.com": [{"symbol": "AMZN", "quoteType": "EQUITY"}, {"symbol": "SAMZN=F", "quoteType": "FUTURE"},
                   {"symbol": "AMZ.DE", "quoteType": "EQUITY"}],
}


def _search(calls=None):
    def search(query):
        if calls is not None:
            calls.append(query)
        return YAHOO.get(query, [])
    return search


def test_trade_republic_export_is_imported_whole_with_priced_symbols():
    out = importer.parse_csv(TR_CSV.encode(), resolve=symbols.make_resolver("EUR", search=_search()))
    assert out["errors"] == [] and out["sources"] == {"DEFAULT": 8, "PEA": 5}
    by_line = {}
    for r in out["rows"]:
        by_line.setdefault(r["line"], []).append(r)

    # `date` wins over `datetime`, `type` over `category`.
    assert out["columns"]["date"] == "ts" and out["columns"]["type"] == "kind" and "category" not in out["columns"]
    thales = by_line[3][0]
    assert (thales["kind"], thales["symbol"], thales["fees"]) == ("buy", "HO.PA", pytest.approx(1.40))
    axs = by_line[6][0]
    assert axs["symbol"] == "AXS-EUR" and axs["amount"] == pytest.approx(-11.0, abs=1e-4)
    assert by_line[7][0]["symbol"] == "AMZ.DE"                            # EUR listing found by name
    assert by_line[12][0]["kind"] == "sell" and by_line[12][0]["quantity"] == 1.0   # -1 shares
    assert [r["kind"] for r in by_line[5]] == ["deposit", "fee"]           # top-up fee booked apart
    assert by_line[4][0]["kind"] == by_line[8][0]["kind"] == "interest"    # broker bonuses = income
    assert [by_line[i][0]["kind"] for i in (9, 10, 13, 14)] == ["withdrawal", "deposit", "deposit", "withdrawal"]
    assert "FR76" in by_line[2][0]["note"] and "1234567890189" not in by_line[2][0]["note"]  # IBAN masked

    plan = importer.plan_import(out["rows"], {}, "acc", {})
    assert [p["line"] for p in plan if p["status"] == "virement interne"] == [9, 10, 13, 14]
    # Same cash as the broker: 110 - 101.40 + 10.10 - 0.10 - 11 - 10 + 10 + 1 - 79.69 + 77.93.
    cash = sum(p["amount"] for p in plan if not p["status"])
    assert cash == pytest.approx(110 - 101.40 + 10.10 - 0.10 - 11 - 10 + 10 + 1 - 79.69 + 77.93, abs=0.01)


def test_crypto_is_never_its_stock_homonym():
    resolve = symbols.make_resolver("EUR", search=None)
    assert resolve("AXS", "Axie Infinity", "CRYPTO") == ("AXS-EUR", None)
    assert resolve("", "Bitcoin", None, "Buy trade XF000BTC0017 Bitcoin")[0] == "BTC-EUR"
    assert resolve("BTC-USD", None, "CRYPTO")[0] == "BTC-USD"
    assert resolve("AXS", None, "STOCK") == ("AXS", None)     # a stock ticker is trusted as given
    assert symbols.make_resolver("USD", search=None)("ETH", None, "crypto")[0] == "ETH-USD"


def test_isin_resolution_prefers_the_account_currency_and_says_when_it_cannot():
    calls = []
    resolve = symbols.make_resolver("EUR", search=_search(calls))
    assert resolve("US0231351067", "Amazon.com") == ("AMZ.DE", None)
    assert resolve("US0231351067", "Amazon.com") == ("AMZ.DE", None)
    assert calls == ["US0231351067", "Amazon.com"]              # memoised
    sym, warning = resolve("US0231351067", None)
    assert sym == "AMZN" and "hors EUR" in warning
    sym, warning = resolve("XS0000000009", "Inconnu SA")
    assert sym == "XS0000000009" and "introuvable" in warning
    sym, warning = symbols.make_resolver("EUR", search=None)("FR0000121329")
    assert sym == "FR0000121329" and "hors ligne" in warning
    assert resolve("", None, None, "Achat FR0000121329 THALES") == ("HO.PA", None)


def test_any_reasonable_format_is_read():
    csv_text = ("Relevé de compte\nPériode : septembre 2026\n\n"
                "Date;Libellé;Débit;Crédit\n"
                "18 sept. 2026;VIR SEPA RECU DE MOI;;1 234,56 €\n"
                "19/09/26;PRLV FRAIS TENUE;(2,50);\n"
                "20.09.2026;Opération mystère;;3,00\n"
                "21/09/2026;Rien;;\n").encode("cp1252")
    out = importer.parse_csv(csv_text)
    assert [(r["ts"], r["kind"], r["amount"]) for r in out["rows"]] == [
        ("2026-09-18", "deposit", 1234.56), ("2026-09-19", "fee", -2.5), ("2026-09-20", "deposit", 3.0)]
    assert [w["line"] for w in out["warnings"]] == [7] and [e["line"] for e in out["errors"]] == [8]


@pytest.mark.parametrize("raw, expected", [
    ("1 234,56", "1234.56"), ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("(12,50)", "-12.50"),
    ("12,50-", "-12.50"), ("-78.690000", "-78.690000"), ("€ 3", "3"), ("1e-3", "1e-3"), ("", ""),
])
def test_numbers_in_every_local_format(raw, expected):
    assert importer._clean_number(raw) == expected


def test_quantity_or_price_is_derived_from_the_amount_when_missing():
    out = importer.parse_csv("date;type;symbole;quantité;prix;montant\n"
                             "02/01/2024;achat;MC.PA;2;;-1400\n"
                             "03/01/2024;achat;MC.PA;;700;1400\n"
                             "04/01/2024;;MC.PA;-1;700;\n")
    assert [(r["kind"], r["quantity"], r["price"]) for r in out["rows"]] == [
        ("buy", 2, 700), ("buy", 2, 700), ("sell", 1, 700)]


def test_reimporting_a_file_skips_what_is_already_there():
    rows = importer.parse_csv("date;type;montant\n02/01/2024;versement;100\n02/01/2024;versement;100\n")["rows"]
    existing = {"acc": [{**ledger.normalize_movement({"kind": "deposit", "ts": "2024-01-02", "amount": 100})}]}
    plan = importer.plan_import(rows, {}, "acc", existing)
    assert [p["status"] for p in plan] == ["doublon", ""]    # two identical deposits, one already booked
