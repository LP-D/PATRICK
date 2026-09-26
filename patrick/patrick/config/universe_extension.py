"""Roadmap bloc 4 -- univers ETENDU de cibles, verifie en direct.

Cibles SEULEMENT, comme `config/equity_universe.py` : ces groupes
alimentent le selecteur de cible (`webapp/forms.py::TARGET_GROUPS`) et la
page Univers, JAMAIS `config.defaults.DEFAULT_UNIVERSE_YF_TICKERS` (le
pool de features de chaque run). Les ajouter aux features multiplierait le
cout de construction de CHAQUE run (audit de vitesse du 2026-09-25 :
~1000 s pour 42 series) sans validation de leur apport -- c'est une
decision separee, a prendre sur ablation.

Chaque ticker a ete verifie le 2026-09-25 par `patrick audit tickers`
(`data/ticker_check.py`) : historique Yahoo non vide, derniere cotation a
moins de 7 seances, au moins 750 seances. `first` = premiere date servie
par Yahoo (pas la date historique de cotation). Ecarte a la verification :
^EVZ (aucune cotation servie). Les actions ci-dessous ne sont PAS dans
`EQUITY_UNIVERSE` : pas de features fondamentales ni de momentum
cross-sectionnel pour elles (decisions prises pour cet univers-la, voir
`features/guida.py`), seulement le pipeline standard.

Noms de groupes : ceux de l'ancien univers quand ils existent (traductions
deja presentes, `webapp/i18n.py::TARGET_GROUP_LABEL_KEYS`), sinon nouveaux ;
jamais un nom deja utilise par `DEFAULT_TARGET_GROUPS` (une fusion de dict
ecraserait le groupe existant).
"""
from __future__ import annotations

VERIFIED_ON = "2026-09-25"

# {groupe: [(symbole, libelle, premiere date servie par Yahoo), ...]}
EXTENDED_TARGET_GROUPS: dict[str, list[tuple[str, str, str]]] = {
    "ETFs sectoriels & thématiques": [
        ("XLK", "Tech_Select_Sector", "1998-12-22"),
        ("XLF", "Financials_Select_Sector", "1998-12-22"),
        ("XLE", "Energy_Select_Sector", "1998-12-22"),
        ("XLV", "HealthCare_Select_Sector", "1998-12-22"),
        ("XLI", "Industrials_Select_Sector", "1998-12-22"),
        ("XLY", "ConsDiscretionary_Select_Sector", "1998-12-22"),
        ("XLP", "ConsStaples_Select_Sector", "1998-12-22"),
        ("XLU", "Utilities_Select_Sector", "1998-12-22"),
        ("XLB", "Materials_Select_Sector", "1998-12-22"),
        ("XLRE", "RealEstate_Select_Sector", "2015-10-08"),
        ("XLC", "CommServices_Select_Sector", "2018-06-19"),
        ("SMH", "Semiconductors_ETF", "2000-06-05"),
        ("KRE", "RegionalBanks_ETF", "2006-06-22"),
        ("XBI", "Biotech_ETF", "2006-02-06"),
        ("ITB", "HomeBuilders_ETF", "2006-05-05"),
    ],
    "Obligataire & taux (ETFs)": [
        ("TLT", "UST_20Y_plus_ETF", "2002-07-30"),
        ("IEF", "UST_7_10Y_ETF", "2002-07-30"),
        ("SHY", "UST_1_3Y_ETF", "2002-07-30"),
        ("LQD", "IG_Corporate_ETF", "2002-07-30"),
        ("HYG", "HighYield_Corporate_ETF", "2007-04-11"),
        ("TIP", "TIPS_ETF", "2003-12-05"),
        ("EMB", "EM_USD_Bonds_ETF", "2007-12-19"),
        ("AGG", "US_Aggregate_ETF", "2003-09-29"),
        ("BND", "US_TotalBond_ETF", "2007-04-10"),
        ("MUB", "Municipal_Bonds_ETF", "2007-09-10"),
        ("BNDX", "Intl_Bonds_Hedged_ETF", "2013-06-04"),
        ("IGOV", "Intl_Treasury_ETF", "2009-01-30"),
    ],
    "International (ETFs pays)": [
        ("EWJ", "Japan_ETF", "1996-03-18"),
        ("EWG", "Germany_ETF", "1996-03-18"),
        ("EWU", "UK_ETF", "1996-03-18"),
        ("EWQ", "France_ETF", "1996-03-18"),
        ("EWZ", "Brazil_ETF", "2000-07-14"),
        ("EWC", "Canada_ETF", "1996-03-18"),
        ("EWA", "Australia_ETF", "1996-03-18"),
        ("FXI", "China_LargeCap_ETF", "2004-10-08"),
        ("INDA", "India_ETF", "2012-02-03"),
        ("EEM", "EmergingMarkets_ETF", "2003-04-14"),
        ("VGK", "Europe_ETF", "2005-03-10"),
        ("EWY", "SouthKorea_ETF", "2000-05-12"),
        ("EWT", "Taiwan_ETF", "2000-06-23"),
        ("EWW", "Mexico_ETF", "1996-03-18"),
        ("EWL", "Switzerland_ETF", "1996-03-18"),
        ("EWP", "Spain_ETF", "1996-03-18"),
        ("EWI", "Italy_ETF", "1996-03-18"),
        ("EWN", "Netherlands_ETF", "1996-03-18"),
        ("EWD", "Sweden_ETF", "1996-03-18"),
        ("MCHI", "China_MSCI_ETF", "2011-03-31"),
    ],
    "Indices mondiaux": [
        ("^FCHI", "CAC40", "1990-03-01"),
        ("^STOXX50E", "EuroStoxx50", "2007-03-30"),
        ("^GDAXI", "DAX", "1987-12-30"),
        ("^FTSE", "FTSE100", "1984-01-03"),
        ("^N225", "Nikkei225", "1965-01-05"),
        ("^HSI", "HangSeng", "1986-12-31"),
        ("^NDX", "Nasdaq100", "1985-10-01"),
        ("^RUT", "Russell2000", "1987-09-10"),
        ("^DJI", "DowJones", "1992-01-02"),
        ("^IBEX", "IBEX35", "1993-07-12"),
        ("^AXJO", "ASX200", "1992-11-23"),
        ("^BVSP", "Bovespa", "1993-04-27"),
        ("^GSPTSE", "TSX", "1979-06-29"),
        ("^KS11", "KOSPI", "1996-12-11"),
        ("^NSEI", "Nifty50", "2007-09-17"),
    ],
    "Actions US (méga-capitalisations)": [
        ("AAPL", "Apple", "1980-12-12"),
        ("MSFT", "Microsoft", "1986-03-13"),
        ("NVDA", "Nvidia", "1999-01-22"),
        ("GOOGL", "Alphabet", "2004-08-19"),
        ("META", "Meta", "2012-05-18"),
        ("JPM", "JPMorgan", "1980-03-17"),
        ("XOM", "ExxonMobil", "1962-01-02"),
        ("JNJ", "Johnson_Johnson", "1962-01-02"),
        ("V", "Visa", "2008-03-19"),
        ("UNH", "UnitedHealth", "1984-10-17"),
        ("BRK-B", "Berkshire_B", "1996-05-09"),
        ("LLY", "EliLilly", "1972-06-01"),
        ("WMT", "Walmart", "1972-08-25"),
        ("PG", "Procter_Gamble", "1962-01-02"),
        ("KO", "CocaCola", "1962-01-02"),
    ],
    "Actions France (CAC 40)": [
        ("MC.PA", "LVMH", "2000-01-03"),
        ("OR.PA", "LOreal", "2000-01-03"),
        ("SAN.PA", "Sanofi", "2000-01-03"),
        ("AIR.PA", "Airbus", "2001-09-03"),
        ("BNP.PA", "BNP_Paribas", "1993-10-18"),
        ("SU.PA", "Schneider", "2000-01-03"),
        ("AI.PA", "AirLiquide", "2000-01-03"),
        ("DG.PA", "Vinci", "2000-01-03"),
        ("RMS.PA", "Hermes", "2000-01-03"),
        ("SAF.PA", "Safran", "2000-01-03"),
        ("CS.PA", "AXA", "1990-08-24"),
        ("BN.PA", "Danone", "1989-01-16"),
        ("KER.PA", "Kering", "2000-01-03"),
        ("EL.PA", "EssilorLuxottica", "2000-01-03"),
        ("CAP.PA", "Capgemini", "2000-01-03"),
    ],
    "Devises (majeures)": [
        ("GBPUSD=X", "GBP_USD", "2003-12-01"),
        ("USDJPY=X", "USD_JPY", "1996-10-30"),
        ("USDCHF=X", "USD_CHF", "2003-09-17"),
        ("AUDUSD=X", "AUD_USD", "2006-05-16"),
        ("USDCAD=X", "USD_CAD", "2003-09-17"),
        ("NZDUSD=X", "NZD_USD", "2003-12-01"),
        ("EURGBP=X", "EUR_GBP", "1999-01-04"),
        ("EURJPY=X", "EUR_JPY", "2003-01-23"),
        ("EURCHF=X", "EUR_CHF", "2003-01-23"),
    ],
    "Crypto (majeures)": [
        ("ETH-USD", "Ethereum", "2017-11-09"),
        ("SOL-USD", "Solana", "2020-04-10"),
        ("XRP-USD", "XRP", "2017-11-09"),
        ("BNB-USD", "BNB", "2017-11-09"),
        ("ADA-USD", "Cardano", "2017-11-09"),
    ],
    "Volatilité": [
        ("^VIX3M", "VIX_3M", "2006-07-17"),
        ("^VVIX", "VVIX", "2007-01-03"),
        ("^VXN", "Nasdaq_Vol", "2001-01-23"),
        ("^OVX", "Oil_Vol", "2007-05-10"),
        ("^GVZ", "Gold_Vol", "2008-06-03"),
    ],
}

EXCLUDED_AT_VERIFICATION = ('^EVZ',)



def extended_target_choices() -> list[tuple[str, str, str]]:
    """(symbole, libelle, source) -- meme forme que DEFAULT_TARGET_CHOICES."""
    return [(sym, label, "yfinance") for items in EXTENDED_TARGET_GROUPS.values() for sym, label, _ in items]


def extended_target_groups() -> dict[str, list[tuple[str, str]]]:
    return {g: [(sym, label) for sym, label, _ in items] for g, items in EXTENDED_TARGET_GROUPS.items()}


def all_target_groups() -> dict[str, list[tuple[str, str]]]:
    """Every selectable target, grouped: the reduced default universe (also
    the default feature pool), the individual equities
    (`equity_universe`), then the verified extension -- the same list the
    launch form and /universe show. Targets only: the default feature pool
    stays `defaults.DEFAULT_UNIVERSE_YF_TICKERS`."""
    from patrick.config import defaults as D
    from patrick.config import equity_universe as EQ

    return {
        **D.DEFAULT_TARGET_GROUPS,
        EQ.EQUITY_TARGET_GROUP: [(sym, meta["label"]) for sym, meta in EQ.EQUITY_UNIVERSE.items()],
        **extended_target_groups(),
    }
