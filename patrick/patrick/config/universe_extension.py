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
^EVZ (aucune cotation servie). Ajoutes le 2026-09-27 (`ADDED_ON_2026_09_27`,
meme controle, sur le PC A et dans le conteneur) : les 9 tickers de la
branche feature/replay-cache-universe absents de cette liste.

`EXTENDED_FEATURE_CANDIDATES` : la liste de candidats FEATURES de cette
branche (39 tickers), fusionnee ici -- une seule source de verite, chaque
candidat est un symbole verifie de `EXTENDED_TARGET_GROUPS`. Opt-in par run
(formulaire, « Univers candidat » = etendu), a coupler avec la reduction
par clustering de correlation (`UniverseConfig.reduction_corr_threshold`). Les actions ci-dessous ne sont PAS dans
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
        ("^IXIC", "NasdaqComposite", "1971-02-05"),
    ],
    "Taux US (indices CBOE)": [
        ("^IRX", "UST_13W_Yield", "1960-01-04"),
        ("^FVX", "UST_5Y_Yield", "1962-01-02"),
        ("^TNX", "UST_10Y_Yield", "1962-01-02"),
        ("^TYX", "UST_30Y_Yield", "1977-02-15"),
    ],
    "Matières premières (compléments)": [
        ("PL=F", "Platinum", "1997-10-29"),
        ("PA=F", "Palladium", "1998-09-28"),
        ("HO=F", "HeatingOil", "2000-09-01"),
        ("RB=F", "RBOB_Gasoline", "2000-11-01"),
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
    # Ajoutes le 2026-10-07 (`ADDED_ON_2026_10_07`) : actions individuelles,
    # verifiees en direct par `patrick audit tickers` (>= 750 seances, derniere
    # cotation < 7 seances). Cotations doubles ecartees (Unilever, Stellantis
    # Milan, TSMC Taipei, Alibaba HK, Infosys Inde, Sony/Toyota/HDFC ADR) :
    # une seule ligne par societe, pour ne pas fausser un classement.
    "Actions US (grandes capitalisations)": [
        ("TSLA", "Tesla", "2010-06-29"),
        ("AVGO", "Broadcom", "2009-08-06"),
        ("ORCL", "Oracle", "1986-03-12"),
        ("COST", "Costco", "1986-07-09"),
        ("HD", "HomeDepot", "1981-09-22"),
        ("MA", "Mastercard", "2006-05-25"),
        ("ABBV", "AbbVie", "2013-01-02"),
        ("MRK", "Merck", "1962-01-02"),
        ("PEP", "PepsiCo", "1972-06-01"),
        ("CVX", "Chevron", "1962-01-02"),
        ("BAC", "BankOfAmerica", "1973-02-21"),
        ("ADBE", "Adobe", "1986-08-13"),
        ("CRM", "Salesforce", "2004-06-23"),
        ("NFLX", "Netflix", "2002-05-23"),
        ("AMD", "AMD", "1980-03-17"),
        ("TMO", "ThermoFisher", "1980-03-17"),
        ("CSCO", "Cisco", "1990-02-16"),
        ("ACN", "Accenture", "2001-07-19"),
        ("MCD", "McDonalds", "1966-07-05"),
        ("ABT", "Abbott", "1980-03-17"),
        ("WFC", "WellsFargo", "1972-06-01"),
        ("DIS", "Disney", "1962-01-02"),
        ("INTC", "Intel", "1980-03-17"),
        ("QCOM", "Qualcomm", "1991-12-13"),
        ("TXN", "TexasInstruments", "1972-06-01"),
        ("IBM", "IBM", "1962-01-02"),
        ("GE", "GE_Aerospace", "1962-01-02"),
        ("CAT", "Caterpillar", "1962-01-02"),
        ("GS", "GoldmanSachs", "1999-05-04"),
        ("MS", "MorganStanley", "1993-02-23"),
        ("BA", "Boeing", "1962-01-02"),
        ("NKE", "Nike", "1980-12-02"),
        ("PFE", "Pfizer", "1972-06-01"),
        ("T", "ATT", "1983-11-21"),
        ("VZ", "Verizon", "1983-11-21"),
        ("CMCSA", "Comcast", "1980-03-17"),
        ("LOW", "Lowes", "1980-03-17"),
        ("HON", "Honeywell", "1962-01-02"),
        ("UPS", "UPS", "1999-11-10"),
        ("AMGN", "Amgen", "1983-06-17"),
        ("SBUX", "Starbucks", "1992-06-26"),
        ("LMT", "LockheedMartin", "1962-01-02"),
        ("DE", "Deere", "1972-06-01"),
        ("BKNG", "BookingHoldings", "1999-03-31"),
        ("UBER", "Uber", "2019-05-10"),
        ("PYPL", "PayPal", "2015-07-06"),
        ("COP", "ConocoPhillips", "1981-12-31"),
        ("SLB", "SLB", "1981-12-31"),
        ("MMM", "3M", "1962-01-02"),
        ("C", "Citigroup", "1977-01-03"),
        ("AXP", "AmericanExpress", "1972-06-01"),
        ("BLK", "BlackRock", "1999-10-01"),
        ("SCHW", "CharlesSchwab", "1987-09-22"),
        ("NEE", "NextEraEnergy", "1973-02-21"),
        ("DUK", "DukeEnergy", "1980-03-17"),
        ("SO", "SouthernCompany", "1981-12-31"),
        ("LIN", "Linde", "1992-06-17"),
        ("MDLZ", "Mondelez", "2001-06-13"),
        ("CL", "ColgatePalmolive", "1973-05-02"),
        ("MO", "Altria", "1962-01-02"),
        ("PM", "PhilipMorris", "2008-03-17"),
        ("F", "Ford", "1972-06-01"),
        ("GM", "GeneralMotors", "2010-11-18"),
        ("NOC", "NorthropGrumman", "1981-12-31"),
        ("RTX", "RTX", "1962-04-02"),
        ("GILD", "Gilead", "1992-01-22"),
        ("BMY", "BristolMyersSquibb", "1972-06-01"),
        ("CVS", "CVSHealth", "1973-02-21"),
        ("TGT", "Target", "1973-02-21"),
        ("MU", "Micron", "1984-06-01"),
        ("AMAT", "AppliedMaterials", "1980-03-17"),
        ("LRCX", "LamResearch", "1984-05-04"),
        ("KLAC", "KLA", "1980-10-08"),
        ("ISRG", "IntuitiveSurgical", "2000-06-16"),
        ("VRTX", "Vertex", "1991-07-24"),
        ("REGN", "Regeneron", "1991-04-02"),
        ("INTU", "Intuit", "1993-03-12"),
        ("NOW", "ServiceNow", "2012-06-29"),
        ("PANW", "PaloAltoNetworks", "2012-07-20"),
        ("SHOP", "Shopify", "2015-05-20"),
        ("SPGI", "SP_Global", "1973-02-21"),
        ("CME", "CME_Group", "2002-12-06"),
        ("ICE", "IntercontinentalExchange", "2005-11-16"),
        ("MCO", "Moodys", "1994-10-31"),
        ("USB", "USBancorp", "1973-05-03"),
        ("PNC", "PNC_Financial", "1975-11-17"),
        ("TFC", "Truist", "1980-03-18"),
        ("MET", "MetLife", "2000-04-05"),
        ("PRU", "Prudential", "2001-12-13"),
        ("AIG", "AIG", "1973-01-02"),
        ("TRV", "Travelers", "1975-11-17"),
        ("CB", "Chubb", "1993-03-25"),
        ("AON", "Aon", "1980-06-02"),
        ("ADP", "ADP_Payroll", "1980-03-17"),
        ("FDX", "FedEx", "1978-04-12"),
        ("CSX", "CSX", "1980-11-03"),
        ("UNP", "UnionPacific", "1980-01-02"),
        ("NSC", "NorfolkSouthern", "1982-06-02"),
        ("EMR", "Emerson", "1972-06-01"),
        ("ETN", "Eaton", "1972-06-01"),
        ("ITW", "IllinoisToolWorks", "1973-03-13"),
        ("PH", "ParkerHannifin", "1980-03-17"),
        ("ROK", "RockwellAutomation", "1981-12-31"),
        ("DOW", "Dow", "2019-03-20"),
        ("LYB", "LyondellBasell", "2010-04-28"),
        ("NEM", "Newmont", "1980-03-17"),
        ("FCX", "FreeportMcMoRan", "1995-07-10"),
        ("MOS", "Mosaic", "1988-01-26"),
        ("ADM", "ArcherDanielsMidland", "1980-03-17"),
        ("KR", "Kroger", "1962-01-02"),
        ("DG", "DollarGeneral", "2009-11-13"),
        ("DLTR", "DollarTree", "1995-03-07"),
        ("ROST", "RossStores", "1985-08-08"),
        ("TJX", "TJX", "1987-06-26"),
        ("YUM", "YumBrands", "1997-09-17"),
        ("CMG", "Chipotle", "2006-01-26"),
        ("MAR", "Marriott", "1998-03-23"),
        ("HLT", "Hilton", "2013-12-12"),
        ("EBAY", "eBay", "1998-09-24"),
        ("TTWO", "TakeTwo", "1997-04-15"),
        ("ZTS", "Zoetis", "2013-02-01"),
        ("BDX", "BectonDickinson", "1973-02-21"),
        ("SYK", "Stryker", "1980-03-17"),
        ("MDT", "Medtronic", "1973-05-02"),
        ("BSX", "BostonScientific", "1992-05-19"),
        ("EW", "EdwardsLifesciences", "2000-03-27"),
        ("DHR", "Danaher", "1978-12-29"),
        ("A", "Agilent", "1999-11-18"),
        ("WAT", "Waters", "1995-11-17"),
        ("IQV", "IQVIA", "2013-05-09"),
        ("LHX", "L3Harris", "1981-12-31"),
        ("GD", "GeneralDynamics", "1962-01-02"),
        ("TDG", "TransDigm", "2006-03-15"),
        ("HWM", "Howmet", "2016-11-01"),
    ],
    "Actions France (autres valeurs)": [
        ("ACA.PA", "CreditAgricole", "2001-12-14"),
        ("GLE.PA", "SocieteGenerale", "2000-01-03"),
        ("ORA.PA", "Orange", "2000-01-03"),
        ("ENGI.PA", "Engie", "2000-01-03"),
        ("VIE.PA", "Veolia", "2000-07-20"),
        ("SGO.PA", "SaintGobain", "2000-01-03"),
        ("ML.PA", "Michelin", "2000-01-03"),
        ("STLAP.PA", "Stellantis", "2001-09-03"),
        ("RNO.PA", "Renault", "2000-01-03"),
        ("CA.PA", "Carrefour", "2000-01-03"),
        ("PUB.PA", "Publicis", "2000-09-19"),
        ("EN.PA", "Bouygues", "1991-01-07"),
        ("LR.PA", "Legrand", "2006-04-07"),
        ("URW.PA", "UnibailRodamco", "2023-04-14"),
        ("WLN.PA", "Worldline", "2014-06-27"),
        ("DSY.PA", "DassaultSystemes", "2000-01-03"),
        ("STMPA.PA", "STMicroelectronics", "2001-09-03"),
        ("TEP.PA", "Teleperformance", "1992-06-01"),
        ("ERF.PA", "Eurofins", "1997-10-27"),
        ("SW.PA", "Sodexo", "2000-01-03"),
        ("BVI.PA", "BureauVeritas", "2007-10-24"),
        ("EDEN.PA", "Edenred", "2010-07-01"),
        ("AC.PA", "Accor", "2000-01-03"),
        ("ALO.PA", "Alstom", "2005-08-03"),
        ("VIV.PA", "Vivendi", "2000-01-03"),
        ("ATO.PA", "Atos", "2000-01-03"),
        ("SOP.PA", "SopraSteria", "2000-01-03"),
        ("IPS.PA", "Ipsos", "2001-01-01"),
        ("NEX.PA", "Nexans", "2001-06-13"),
        ("RCO.PA", "RemyCointreau", "2000-01-03"),
        ("MMT.PA", "M6_Metropole", "2000-01-03"),
        ("AM.PA", "DassaultAviation", "2000-01-03"),
        ("RI.PA", "PernodRicard", "2000-01-03"),
        ("SK.PA", "SEB", "2000-01-03"),
        ("FGR.PA", "Eiffage", "2000-01-03"),
        ("COFA.PA", "Coface", "2014-06-27"),
        ("CDI.PA", "ChristianDior", "1992-01-27"),
        ("DIM.PA", "SartoriusStedim", "2000-01-03"),
        ("ELIS.PA", "Elis", "2015-02-11"),
        ("GFC.PA", "Gecina", "1992-07-08"),
        ("ICAD.PA", "Icade", "2000-01-03"),
        ("LI.PA", "Klepierre", "1992-07-09"),
        ("NK.PA", "Imerys", "2000-01-03"),
        ("RUI.PA", "Rubis", "2000-01-03"),
        ("RXL.PA", "Rexel", "2007-04-05"),
        ("TFI.PA", "TF1", "1992-07-17"),
        ("VK.PA", "Vallourec", "2000-01-03"),
        ("VLA.PA", "Valneva", "2007-06-29"),
        ("ADP.PA", "AeroportsDeParis", "2006-06-19"),
        ("AF.PA", "AirFranceKLM", "2000-01-03"),
        ("AKE.PA", "Arkema", "2006-05-18"),
        ("BIM.PA", "BioMerieux", "2004-07-07"),
        ("BOL.PA", "Bollore", "2000-01-03"),
        ("CO.PA", "Casino", "2000-01-03"),
    ],
    "Actions Allemagne": [
        ("SAP.DE", "SAP", "1998-04-09"),
        ("SIE.DE", "Siemens", "1996-11-08"),
        ("ALV.DE", "Allianz", "1996-12-16"),
        ("DTE.DE", "DeutscheTelekom", "1996-11-18"),
        ("BAS.DE", "BASF", "1996-12-16"),
        ("BAYN.DE", "Bayer", "1996-12-16"),
        ("BMW.DE", "BMW", "1996-11-08"),
        ("MBG.DE", "MercedesBenz", "1996-10-30"),
        ("VOW3.DE", "Volkswagen", "1998-07-22"),
        ("ADS.DE", "Adidas", "1998-06-24"),
        ("IFX.DE", "Infineon", "2000-03-13"),
        ("MUV2.DE", "MunichRe", "1998-06-24"),
        ("DBK.DE", "DeutscheBank", "1996-11-18"),
        ("EOAN.DE", "EON", "2000-01-03"),
        ("RWE.DE", "RWE", "1996-12-16"),
        ("HEN3.DE", "Henkel", "1998-06-24"),
        ("DHL.DE", "DHL_Group", "2000-11-20"),
        ("CBK.DE", "Commerzbank", "1996-12-16"),
    ],
    "Actions Royaume-Uni": [
        ("SHEL.L", "Shell", "1996-08-29"),
        ("AZN.L", "AstraZeneca", "1993-05-21"),
        ("HSBA.L", "HSBC", "1988-07-05"),
        ("ULVR.L", "Unilever", "1988-07-01"),
        ("BP.L", "BP", "1988-07-01"),
        ("GSK.L", "GSK", "1988-07-01"),
        ("RIO.L", "RioTinto", "1988-07-01"),
        ("BATS.L", "BritishAmericanTobacco", "1995-01-03"),
        ("DGE.L", "Diageo", "1988-05-03"),
        ("LSEG.L", "LondonStockExchange", "2001-07-20"),
        ("REL.L", "RELX", "1988-07-01"),
        ("BARC.L", "Barclays", "1988-07-01"),
        ("LLOY.L", "Lloyds", "1995-12-28"),
        ("VOD.L", "Vodafone", "1988-10-25"),
        ("NG.L", "NationalGrid", "1995-12-11"),
        ("TSCO.L", "Tesco", "1988-07-01"),
        ("AAL.L", "AngloAmerican", "1999-05-24"),
        ("GLEN.L", "Glencore", "2011-05-19"),
    ],
    "Actions Europe (autres pays)": [
        ("ASML.AS", "ASML", "1998-07-20"),
        ("INGA.AS", "ING", "1995-03-27"),
        ("PHIA.AS", "Philips", "1995-03-27"),
        ("AD.AS", "AholdDelhaize", "2008-10-24"),
        ("HEIA.AS", "Heineken", "1995-03-27"),
        ("WKL.AS", "WoltersKluwer", "1995-03-27"),
        ("ADYEN.AS", "Adyen", "2018-06-13"),
        ("PRX.AS", "Prosus", "2019-09-11"),
        ("NESN.SW", "Nestle", "1990-01-03"),
        ("NOVN.SW", "Novartis", "1995-04-03"),
        ("UBSG.SW", "UBS", "1995-08-03"),
        ("ZURN.SW", "ZurichInsurance", "1998-10-06"),
        ("ABBN.SW", "ABB", "1999-06-25"),
        ("CFR.SW", "Richemont", "1995-04-03"),
        ("SREN.SW", "SwissRe", "1995-04-03"),
        ("LONN.SW", "Lonza", "1999-11-01"),
        ("SAN.MC", "BancoSantander", "2000-01-03"),
        ("ITX.MC", "Inditex", "2001-05-24"),
        ("IBE.MC", "Iberdrola", "2000-01-03"),
        ("BBVA.MC", "BBVA", "2000-01-03"),
        ("TEF.MC", "Telefonica", "2000-01-03"),
        ("REP.MC", "Repsol", "2000-01-03"),
        ("ENEL.MI", "Enel", "1999-11-02"),
        ("ISP.MI", "IntesaSanpaolo", "1995-03-24"),
        ("UCG.MI", "UniCredit", "2000-01-03"),
        ("ENI.MI", "ENI", "1995-11-29"),
        ("RACE.MI", "Ferrari", "2016-01-04"),
        ("G.MI", "Generali", "1986-07-25"),
        ("NOKIA.HE", "Nokia", "2000-01-03"),
        ("NDA-FI.HE", "Nordea", "2000-01-25"),
        ("VOLV-B.ST", "Volvo", "2000-01-03"),
        ("ERIC-B.ST", "Ericsson", "2000-01-03"),
        ("ATCO-A.ST", "AtlasCopco", "2000-01-03"),
        ("NOVO-B.CO", "NovoNordisk", "2001-01-08"),
        ("DSV.CO", "DSV", "2000-01-21"),
        ("ORSTED.CO", "Orsted", "2016-06-09"),
        ("EQNR.OL", "Equinor", "2000-01-03"),
        ("DNB.OL", "DNB", "2000-01-03"),
    ],
    "Actions Asie (locales & ADR)": [
        ("7203.T", "Toyota", "1999-05-06"),
        ("6758.T", "Sony", "2000-01-04"),
        ("9984.T", "SoftBank", "2000-01-04"),
        ("8306.T", "MitsubishiUFJ", "2005-09-29"),
        ("6861.T", "Keyence", "2001-01-01"),
        ("7974.T", "Nintendo", "2001-01-04"),
        ("9432.T", "NTT", "2000-01-04"),
        ("005930.KS", "Samsung", "2000-01-04"),
        ("000660.KS", "SKHynix", "2000-01-04"),
        ("0700.HK", "Tencent", "2004-06-16"),
        ("1299.HK", "AIA", "2010-10-29"),
        ("0941.HK", "ChinaMobile", "2000-01-04"),
        ("3690.HK", "Meituan", "2018-09-20"),
        ("RELIANCE.NS", "Reliance", "1996-01-01"),
        ("TCS.NS", "TataConsultancy", "2002-08-12"),
        ("HDFCBANK.NS", "HDFC_Bank", "1996-01-01"),
        ("TSM", "TSMC_ADR", "1997-10-09"),
        ("BABA", "Alibaba_ADR", "2014-09-19"),
        ("PDD", "PDD_Holdings", "2018-07-26"),
        ("JD", "JD_com", "2014-05-22"),
        ("BIDU", "Baidu_ADR", "2005-08-05"),
        ("NIO", "NIO", "2018-09-12"),
        ("HMC", "Honda_ADR", "1980-03-17"),
        ("INFY", "Infosys_ADR", "1999-03-11"),
    ],
}

EXCLUDED_AT_VERIFICATION = ('^EVZ',)

ADDED_ON_2026_09_27 = ("^IXIC", "^IRX", "^FVX", "^TNX", "^TYX", "PL=F", "PA=F", "HO=F", "RB=F")

# Groupes d'actions individuelles ajoutes le 2026-10-07 (voir le commentaire
# dans `EXTENDED_TARGET_GROUPS`) -- tous les symboles de ces groupes.
ADDED_ON_2026_10_07_GROUPS = (
    "Actions US (grandes capitalisations)", "Actions France (autres valeurs)",
    "Actions Allemagne", "Actions Royaume-Uni", "Actions Europe (autres pays)",
    "Actions Asie (locales & ADR)",
)

# Candidats FEATURES de feature/replay-cache-universe (Phase 3), tous dans
# `EXTENDED_TARGET_GROUPS` ci-dessus (verifie par tests/test_universe_reduction.py).
EXTENDED_FEATURE_CANDIDATES: tuple[str, ...] = (
    # Indices actions
    "^DJI", "^IXIC", "^RUT", "^FTSE", "^GDAXI", "^FCHI", "^N225", "^HSI", "^STOXX50E",
    # Taux / volatilite implicite
    "^TNX", "^IRX", "^FVX", "^TYX", "^VXN",
    # Devises majeures
    "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X",
    # ETFs sectoriels US
    "XLE", "XLF", "XLK", "XLU", "XLV", "XLI", "XLP", "XLY", "XLB",
    # ETFs obligataires / credit
    "TLT", "IEF", "SHY", "LQD", "HYG",
    # Autres futures / crypto
    "PL=F", "PA=F", "HO=F", "RB=F", "ETH-USD",
)


def extended_target_choices() -> list[tuple[str, str, str]]:
    """(symbole, libelle, source) -- meme forme que DEFAULT_TARGET_CHOICES."""
    return [(sym, label, "yfinance") for items in EXTENDED_TARGET_GROUPS.values() for sym, label, _ in items]


def extended_candidate_yf_tickers() -> list[str]:
    """Univers de features « etendu » : l'univers par defaut
    (`defaults.DEFAULT_UNIVERSE_YF_TICKERS`) puis les candidats ci-dessus
    qui n'y sont pas deja (ni dans `BAD_TICKERS`)."""
    from patrick.config import defaults as D

    base = list(D.DEFAULT_UNIVERSE_YF_TICKERS)
    return base + [t for t in EXTENDED_FEATURE_CANDIDATES if t not in base and t not in D.BAD_TICKERS]


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
