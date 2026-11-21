"""Lecteur universel de tableaux (`patrick/tabular/`) : nombres et dates de toutes les écritures, mises en page variées, types de valeurs,
conversion en niveaux, cours OHLC. Chaque fichier est construit dans le test (aucun fichier externe)."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from patrick.tabular import detect, parse, reader


# ------------------------------------------------------------------ nombres et dates
@pytest.mark.parametrize("cells, expected, dec", [
    (["1 234,56 €", "12,5", "(3,2)", "−0,4"], [1234.56, 12.5, -3.2, -0.4], ","),
    (["1,234.56", "12.5", "1,000"], [1234.56, 12.5, 1000.0], "."),
    (["1.234,5", "2.000,25"], [1234.5, 2000.25], ","),
    (["1'234.5", "n.d.", "-", "#N/A"], [1234.5, None, None, None], "."),
])
def test_numbers_any_notation(cells, expected, dec):
    values, info = parse.to_numbers(cells)
    assert info["decimal"] == dec
    for v, e in zip(values, expected):
        assert (np.isnan(v) and e is None) or v == pytest.approx(e)


def test_percent_share_is_reported():
    _, info = parse.to_numbers(["1,5 %", "2 %", "-0,3 %"])
    assert info["percent_share"] == 1.0


def test_dates_every_writing():
    cells = ["31/12/2023", "2024-01-31", "29.02.24", "20240331", "avr. 2024", "31 mai 2024", "Jun 28, 2024", "T3 2024", 45657, pd.Timestamp("2025-01-02").to_pydatetime()]
    dates, info = parse.to_dates(cells)
    got = [d.date().isoformat() for d in dates]
    assert got == ["2023-12-31", "2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31", "2024-06-28", "2024-09-30", "2024-12-31", "2025-01-02"]
    assert info["parsed_share"] == 1.0


def test_month_first_is_detected_from_the_column():
    dates, info = parse.to_dates(["12/31/2023", "01/15/2024", "02/01/2024"])
    assert not info["dayfirst"] and dates.iloc[2].date().isoformat() == "2024-02-01"
    years, info = parse.to_dates([2019, 2020, 2021], year_cells=True)
    assert info["granularity"] == "year" and years.iloc[0].date().isoformat() == "2019-12-31"


def test_isin_check_digit():
    assert parse.isin_valid("FR0010135103") and parse.isin_valid("LU1681043599") and not parse.isin_valid("FR0010135104")
    assert parse.find_isin("Carmignac Patrimoine (FR0010135103) part A") == "FR0010135103"


# ------------------------------------------------------------------ lecture des fichiers
def test_csv_separator_and_encoding():
    text = "Historique;;\nDate;VL;Volume\n02/01/2024;101,5;10\n03/01/2024;102,0;12\n".encode("cp1252")
    grid = reader.read_text(text)
    assert grid.shape[1] == 3 and grid.iat[2, 1] == "101,5"
    assert reader.sniff_separator(["a,b;c", "1,2;3", "4,5;6"]) == ";" or reader.sniff_separator(["a,b;c", "1,2;3", "4,5;6"]) == ","
    with pytest.raises(reader.TabularError):
        reader.read_tables("x.pdf", b"%PDF")


def _monthly(n=40, start="2020-01-31", seed=0, drift=0.005):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="ME")
    return idx, 100 * np.cumprod(1 + rng.normal(drift, 0.03, n))


def test_pee_style_excel_with_title_rows():
    idx, nav = _monthly()
    rows = [["Liste des valeurs liquidatives du fonds Groupama Avenir Euro en date du 30/09/2026", None], [None, None], ["Date", "Valeur liquidative"]]
    rows += [[d.strftime("%d/%m/%Y"), f"{v:.2f}".replace(".", ",")] for d, v in zip(idx, nav)]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    found, _ = detect.detect("export.xlsx", buf.getvalue())
    assert len(found) == 1 and found[0].name == "Groupama Avenir Euro" and found[0].kind == "price"
    assert found[0].frequency == "monthly" and found[0].levels().iloc[-1] == pytest.approx(round(nav[-1], 2))


def test_wide_table_with_isin_headers_and_newest_first():
    idx, a = _monthly(seed=1)
    _, b = _monthly(seed=2)
    frame = pd.DataFrame({"Date": idx[::-1].strftime("%Y-%m-%d"), "FR0010135103": a[::-1], "Amundi World": b[::-1]})
    found, _ = detect.detect("tableau.csv", frame.to_csv(index=False).encode())
    names = {f.name for f in found}
    assert names == {"FR0010135103", "Amundi World"}
    isin = next(f for f in found if f.name == "FR0010135103")
    assert isin.isin == "FR0010135103" and any("plus récent" in n for n in isin.notes)
    assert isin.raw.index.is_monotonic_increasing


def test_side_by_side_blocks_and_long_format():
    idx, a = _monthly(seed=3)
    _, b = _monthly(seed=4, n=30)
    width = max(len(a), len(b))
    grid = [["Fonds A", None, None, "Fonds B", None], ["Date", "VL", None, "Date", "VL"]]
    for i in range(width):
        left = [idx[i].strftime("%d/%m/%Y"), a[i]] if i < len(a) else [None, None]
        right = [idx[i].strftime("%d/%m/%Y"), b[i]] if i < len(b) else [None, None]
        grid.append(left + [None] + right)
    found, _ = detect.detect_grid(pd.DataFrame(grid, dtype=object), "Feuil1", "comparateur.xlsx")
    assert {f.name for f in found} == {"Fonds A", "Fonds B"} and {len(f.raw) for f in found} == {40, 30}
    long = pd.DataFrame([(d.strftime("%Y-%m-%d"), name, v) for name, series in (("Alpha", a), ("Beta", b)) for d, v in zip(idx, series)],
                        columns=["date", "fonds", "vl"])
    found2, _ = detect.detect("long.csv", long.to_csv(index=False).encode())
    assert {f.name for f in found2} == {"Alpha", "Beta"} and any("format long" in n for n in found2[0].notes)


def test_transposed_table():
    idx, a = _monthly(seed=5, n=12)
    grid = pd.DataFrame([["Support"] + [d.strftime("%d/%m/%Y") for d in idx], ["Fonds T"] + list(a)], dtype=object)
    found, _ = detect.detect_grid(grid, "Feuil1", "t.xlsx")
    assert len(found) == 1 and found[0].name == "Fonds T" and "tableau transposé (dates en ligne)" in found[0].notes


def test_value_kinds_and_their_levels():
    idx, _ = _monthly(n=24)
    perf = pd.DataFrame({"Mois": [d.strftime("%b %Y") for d in idx], "Performance mensuelle (%)": [1.0] * 24})
    found, _ = detect.detect("perf.csv", perf.to_csv(index=False, sep=";").encode())
    f = found[0]
    assert f.kind == "return_pct" and f.levels().iloc[-1] == pytest.approx(100 * 1.01 ** 24)
    cum = pd.DataFrame({"Date": idx.strftime("%Y-%m-%d"), "Perf. cumulée (%)": np.linspace(0.5, 30, 24)})
    f2 = detect.detect("cum.csv", cum.to_csv(index=False).encode())[0][0]
    assert f2.kind == "cum_pct" and f2.levels().iloc[-1] == pytest.approx(130.0)
    rates = pd.DataFrame({"Année": [2019, 2020, 2021], "Taux servi net": ["1,5 %", "1,2 %", "1,1 %"]})
    f3 = detect.detect("euros.csv", rates.to_csv(index=False, sep=";").encode())[0][0]
    assert f3.kind == "annual_rate"
    lv = f3.levels()
    assert lv.iloc[0] == 100.0 and lv.loc["2019-12-31"] == pytest.approx(101.5) and lv.is_monotonic_increasing
    assert detect.levels(pd.Series([10.0, -5.0], index=pd.to_datetime(["2020-01-31", "2020-02-29"])), "return_pct").iloc[-1] == pytest.approx(104.5)


def test_annual_rates_never_reach_the_future():
    next_year = pd.Timestamp.today().year + 1
    lv = detect.levels(pd.Series([2.0, 2.0], index=[pd.Timestamp(year=next_year - 1, month=12, day=31), pd.Timestamp(year=next_year, month=12, day=31)]),
                       "annual_rate")
    assert lv.index[-1] <= pd.Timestamp.today() + pd.offsets.MonthEnd(0)


def test_nothing_usable_raises_a_clear_error():
    with pytest.raises(detect.DetectError, match="aucune série datée"):
        detect.detect("notes.csv", b"nom;age\nalice;31\nbob;40\n")


def test_ohlc_prices_long_format_and_close_only_fallback():
    idx = pd.bdate_range("2023-01-02", periods=20)
    rows = [(s, d.strftime("%Y-%m-%d"), 10 + i, 11 + i, 9 + i, 10.5 + i, 1000) for s in ("AAA", "BBB") for i, d in enumerate(idx)]
    csv = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"]).to_csv(index=False).encode()
    prices, notes = detect.detect_prices("cours.csv", csv)
    assert set(prices) == {"AAA", "BBB"} and prices["AAA"]["close"].iloc[-1] == pytest.approx(29.5) and "OHLC" in notes[0]
    wide = pd.DataFrame({"Date": idx.strftime("%d/%m/%Y"), "SPY": np.linspace(400, 420, 20), "QQQ": np.linspace(300, 330, 20)})
    prices2, _notes2 = detect.detect_prices("wide.csv", wide.to_csv(index=False, sep=";").encode())
    assert set(prices2) == {"SPY", "QQQ"} and (prices2["SPY"]["open"] == prices2["SPY"]["close"]).all()


def test_html_disguised_as_xls():
    pytest.importorskip("lxml")
    idx, a = _monthly(n=10)
    html = "<html><body><table><tr><td>Date</td><td>VL</td></tr>" + "".join(f"<tr><td>{d:%d/%m/%Y}</td><td>{v:.2f}</td></tr>" for d, v in zip(idx, a)) + "</table></body></html>"
    found, _ = detect.detect("export_banque.xls", html.encode())
    assert len(found) == 1 and len(found[0].raw) == 10


def test_ods_spreadsheet():
    pytest.importorskip("odf")
    idx, a = _monthly(n=10)
    buf = io.BytesIO()
    pd.DataFrame({"Date": idx, "Fonds ODS": a}).to_excel(buf, engine="odf", index=False)
    found, _ = detect.detect("libre.ods", buf.getvalue())
    assert found[0].name == "Fonds ODS" and len(found[0].raw) == 10
