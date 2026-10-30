"""Noms d'affichage des instruments : ce que l'interface montre à la place du symbole (ticker).

Le symbole (`^GSPC`, `AAPL`, `GC=F`, `DGS10`) reste l'identifiant partout dans les données, les URL et les runs ; seul l'affichage
change. Les libellés techniques de `config/defaults.py` (`SP500_Price`, `Gold_Futures`) NE SONT PAS des noms : ce sont des noms de
colonnes du pipeline, jamais renommés.

Chaque entrée : `symbole -> (genre, nom français, nom anglais)`. Genres :
  stock (société), etf (fonds coté)           -> affichés par leur seul nom (« Apple », « SPDR Gold Shares »)
  future, index, vol, fx, crypto, rate, macro -> le genre d'abord (« Future · Or », « Indice · S&P 500 », « Devise · EUR/USD »)
Un symbole absent est déduit de sa forme (`=F` future, `=X` devise, `-USD` crypto, `^` indice) par `webapp/instruments.py`.
"""
from __future__ import annotations

KIND_ORDER = ("stock", "etf", "index", "vol", "future", "fx", "crypto", "rate", "macro")
NAME_ONLY_KINDS = frozenset({"stock", "etf"})          # le nom suffit : une société ou un fonds se reconnaît à son nom

INSTRUMENTS: dict[str, tuple[str, str, str]] = {}


def _add(kind: str, rows: list[tuple[str, ...]]) -> None:
    for row in rows:
        symbol, fr = row[0], row[1]
        INSTRUMENTS[symbol] = (kind, fr, row[2] if len(row) > 2 else fr)


# ------------------------------------------------------------------------------------------------------------ indices
_add("index", [
    ("^GSPC", "S&P 500"), ("^FCHI", "CAC 40"), ("^STOXX50E", "Euro Stoxx 50"), ("^GDAXI", "DAX 40"), ("^FTSE", "FTSE 100"),
    ("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("^NDX", "Nasdaq 100"), ("^RUT", "Russell 2000"), ("^DJI", "Dow Jones"),
    ("^IBEX", "IBEX 35"), ("^AXJO", "ASX 200"), ("^BVSP", "Bovespa"), ("^GSPTSE", "S&P/TSX Composite"), ("^KS11", "KOSPI"),
    ("^NSEI", "Nifty 50"), ("^IXIC", "Nasdaq Composite"), ("^SOX", "PHLX Semiconductor (SOX)"), ("^NYA", "NYSE Composite"),
    ("^DJT", "Dow Jones Transports"), ("^AEX", "AEX (Pays-Bas)", "AEX (Netherlands)"), ("^SSMI", "SMI (Suisse)", "SMI (Switzerland)"),
    ("FTSEMIB.MI", "FTSE MIB (Italie)", "FTSE MIB (Italy)"), ("^BFX", "BEL 20 (Belgique)", "BEL 20 (Belgium)"),
    ("^TWII", "Taiwan Weighted (TAIEX)"), ("^BSESN", "BSE Sensex (Inde)", "BSE Sensex (India)"), ("000001.SS", "Shanghai Composite"),
    ("^MXX", "IPC (Mexique)", "IPC (Mexico)"), ("^STI", "Straits Times (Singapour)", "Straits Times (Singapore)"),
    ("DX-Y.NYB", "Dollar US (DXY)", "US Dollar (DXY)"),
])
_add("vol", [
    ("^VIX", "VIX (S&P 500)"), ("^VIX3M", "VIX 3 mois", "VIX 3-month"), ("^VVIX", "VVIX (volatilité du VIX)", "VVIX (volatility of the VIX)"),
    ("^VXN", "VXN (Nasdaq 100)"), ("^OVX", "OVX (pétrole)", "OVX (crude oil)"), ("^GVZ", "GVZ (or)", "GVZ (gold)"),
    ("^MOVE", "MOVE (obligations)", "MOVE (bonds)"), ("^SKEW", "SKEW (risque de queue)", "SKEW (tail risk)"),
    ("^VIX9D", "VIX 9 jours", "VIX 9-day"), ("^VXD", "VXD (Dow Jones)"),
])
_add("rate", [
    ("^IRX", "Trésor US 13 semaines", "US Treasury 13-week"), ("^FVX", "Trésor US 5 ans", "US Treasury 5-year"),
    ("^TNX", "Trésor US 10 ans", "US Treasury 10-year"), ("^TYX", "Trésor US 30 ans", "US Treasury 30-year"),
])

# ----------------------------------------------------------------------------------------------------------- futures
_add("future", [
    ("GC=F", "Or", "Gold"), ("SI=F", "Argent", "Silver"), ("HG=F", "Cuivre", "Copper"), ("CL=F", "Pétrole WTI", "WTI crude oil"),
    ("BZ=F", "Pétrole Brent", "Brent crude oil"), ("NG=F", "Gaz naturel", "Natural gas"), ("ZC=F", "Maïs", "Corn"),
    ("ZO=F", "Avoine", "Oats"), ("KE=F", "Blé (Kansas City)", "Wheat (Kansas City)"), ("ZR=F", "Riz", "Rough rice"),
    ("ZS=F", "Soja", "Soybeans"), ("GF=F", "Bovins d'engraissement", "Feeder cattle"), ("HE=F", "Porcs maigres", "Lean hogs"),
    ("LE=F", "Bovins vivants", "Live cattle"), ("CC=F", "Cacao", "Cocoa"), ("KC=F", "Café", "Coffee"), ("CT=F", "Coton", "Cotton"),
    ("OJ=F", "Jus d'orange", "Orange juice"), ("SB=F", "Sucre", "Sugar"), ("PL=F", "Platine", "Platinum"), ("PA=F", "Palladium"),
    ("HO=F", "Fioul domestique", "Heating oil"), ("RB=F", "Essence RBOB", "RBOB gasoline"), ("ZW=F", "Blé (Chicago)", "Wheat (Chicago)"),
    ("ZL=F", "Huile de soja", "Soybean oil"), ("ZM=F", "Tourteau de soja", "Soybean meal"), ("HRC=F", "Acier laminé à chaud", "Hot-rolled steel"),
    ("MTF=F", "Charbon", "Coal"), ("ALI=F", "Aluminium", "Aluminum"), ("TTF=F", "Gaz TTF (Pays-Bas)", "Dutch TTF gas"),
    ("ZT=F", "Trésor US 2 ans", "US Treasury 2-year"), ("ZF=F", "Trésor US 5 ans", "US Treasury 5-year"),
    ("ZN=F", "Trésor US 10 ans", "US Treasury 10-year"), ("ZB=F", "Trésor US 30 ans", "US Treasury 30-year"),
])

# ------------------------------------------------------------------------------------------------------------- devises
_add("fx", [(f"{a}{b}=X", f"{a}/{b}") for a, b in (
    ("EUR", "USD"), ("GBP", "USD"), ("USD", "JPY"), ("USD", "CHF"), ("AUD", "USD"), ("USD", "CAD"), ("NZD", "USD"), ("EUR", "GBP"),
    ("EUR", "JPY"), ("EUR", "CHF"), ("GBP", "JPY"), ("AUD", "JPY"))])
_add("fx", [(f"{b}=X", f"USD/{b}") for b in ("CNY", "INR", "MXN", "BRL", "ZAR", "KRW", "SGD")])

# -------------------------------------------------------------------------------------------------------------- crypto
_add("crypto", [
    ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"), ("XRP-USD", "XRP"), ("BNB-USD", "BNB"),
    ("ADA-USD", "Cardano"), ("LTC-USD", "Litecoin"), ("DOGE-USD", "Dogecoin"), ("LINK-USD", "Chainlink"), ("TRX-USD", "Tron"),
    ("XLM-USD", "Stellar"), ("BCH-USD", "Bitcoin Cash"), ("AVAX-USD", "Avalanche"), ("DOT-USD", "Polkadot"),
])

# ---------------------------------------------------------------------------------------------------------------- ETF
_add("etf", [
    ("XLK", "Technology Select Sector SPDR Fund"), ("XLF", "Financial Select Sector SPDR Fund"), ("XLE", "Energy Select Sector SPDR Fund"),
    ("XLV", "Health Care Select Sector SPDR Fund"), ("XLI", "Industrial Select Sector SPDR Fund"),
    ("XLY", "Consumer Discretionary Select Sector SPDR Fund"), ("XLP", "Consumer Staples Select Sector SPDR Fund"),
    ("XLU", "Utilities Select Sector SPDR Fund"), ("XLB", "Materials Select Sector SPDR Fund"),
    ("XLRE", "Real Estate Select Sector SPDR Fund"), ("XLC", "Communication Services Select Sector SPDR Fund"),
    ("SMH", "VanEck Semiconductor ETF"), ("KRE", "SPDR S&P Regional Banking ETF"), ("XBI", "SPDR S&P Biotech ETF"),
    ("ITB", "iShares U.S. Home Construction ETF"),
    # ETF courants des comptes titres et PEA français (module Patrimoine)
    ("CW8.PA", "Amundi MSCI World UCITS ETF"), ("ESE.PA", "BNP Paribas Easy S&P 500 UCITS ETF"),
    ("PE500.PA", "Amundi PEA S&P 500 UCITS ETF"), ("PAEEM.PA", "Amundi PEA MSCI Emerging Markets UCITS ETF"),
    ("IWDA.AS", "iShares Core MSCI World UCITS ETF"), ("EUNL.DE", "iShares Core MSCI World UCITS ETF"),
    ("VWCE.DE", "Vanguard FTSE All-World UCITS ETF"), ("SXR8.DE", "iShares Core S&P 500 UCITS ETF"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF"), ("IEF", "iShares 7-10 Year Treasury Bond ETF"),
    ("SHY", "iShares 1-3 Year Treasury Bond ETF"), ("LQD", "iShares iBoxx $ Investment Grade Corporate Bond ETF"),
    ("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF"), ("TIP", "iShares TIPS Bond ETF"),
    ("EMB", "iShares J.P. Morgan USD Emerging Markets Bond ETF"), ("AGG", "iShares Core U.S. Aggregate Bond ETF"),
    ("BND", "Vanguard Total Bond Market ETF"), ("MUB", "iShares National Muni Bond ETF"),
    ("BNDX", "Vanguard Total International Bond ETF"), ("IGOV", "iShares International Treasury Bond ETF"),
    ("EWJ", "iShares MSCI Japan ETF"), ("EWG", "iShares MSCI Germany ETF"), ("EWU", "iShares MSCI United Kingdom ETF"),
    ("EWQ", "iShares MSCI France ETF"), ("EWZ", "iShares MSCI Brazil ETF"), ("EWC", "iShares MSCI Canada ETF"),
    ("EWA", "iShares MSCI Australia ETF"), ("FXI", "iShares China Large-Cap ETF"), ("INDA", "iShares MSCI India ETF"),
    ("EEM", "iShares MSCI Emerging Markets ETF"), ("VGK", "Vanguard FTSE Europe ETF"), ("EWY", "iShares MSCI South Korea ETF"),
    ("EWT", "iShares MSCI Taiwan ETF"), ("EWW", "iShares MSCI Mexico ETF"), ("EWL", "iShares MSCI Switzerland ETF"),
    ("EWP", "iShares MSCI Spain ETF"), ("EWI", "iShares MSCI Italy ETF"), ("EWN", "iShares MSCI Netherlands ETF"),
    ("EWD", "iShares MSCI Sweden ETF"), ("MCHI", "iShares MSCI China ETF"),
    ("GLD", "SPDR Gold Shares"), ("SLV", "iShares Silver Trust"), ("USO", "United States Oil Fund"),
    ("UNG", "United States Natural Gas Fund"), ("DBC", "Invesco DB Commodity Index Tracking Fund"),
    ("DBA", "Invesco DB Agriculture Fund"), ("GDX", "VanEck Gold Miners ETF"), ("URA", "Global X Uranium ETF"),
    ("UUP", "Invesco DB US Dollar Index Bullish Fund"), ("FXE", "Invesco CurrencyShares Euro Trust"),
    ("FXY", "Invesco CurrencyShares Japanese Yen Trust"), ("VNQ", "Vanguard Real Estate ETF"),
])

# ---------------------------------------------------------------------------------------------------------- sociétés
_add("stock", [
    # États-Unis, méga-capitalisations
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"), ("GOOGL", "Alphabet (Google)"), ("META", "Meta Platforms"),
    ("JPM", "JPMorgan Chase"), ("XOM", "ExxonMobil"), ("JNJ", "Johnson & Johnson"), ("V", "Visa"), ("UNH", "UnitedHealth Group"),
    ("BRK-B", "Berkshire Hathaway (B)"), ("LLY", "Eli Lilly"), ("WMT", "Walmart"), ("PG", "Procter & Gamble"), ("KO", "Coca-Cola"),
    ("AMZN", "Amazon"),
    # États-Unis, grandes capitalisations
    ("TSLA", "Tesla"), ("AVGO", "Broadcom"), ("ORCL", "Oracle"), ("COST", "Costco"), ("HD", "Home Depot"), ("MA", "Mastercard"),
    ("ABBV", "AbbVie"), ("MRK", "Merck"), ("PEP", "PepsiCo"), ("CVX", "Chevron"), ("BAC", "Bank of America"), ("ADBE", "Adobe"),
    ("CRM", "Salesforce"), ("NFLX", "Netflix"), ("AMD", "AMD"), ("TMO", "Thermo Fisher Scientific"), ("CSCO", "Cisco"),
    ("ACN", "Accenture"), ("MCD", "McDonald's"), ("ABT", "Abbott"), ("WFC", "Wells Fargo"), ("DIS", "Disney"), ("INTC", "Intel"),
    ("QCOM", "Qualcomm"), ("TXN", "Texas Instruments"), ("IBM", "IBM"), ("GE", "GE Aerospace"), ("CAT", "Caterpillar"),
    ("GS", "Goldman Sachs"), ("MS", "Morgan Stanley"), ("BA", "Boeing"), ("NKE", "Nike"), ("PFE", "Pfizer"), ("T", "AT&T"),
    ("VZ", "Verizon"), ("CMCSA", "Comcast"), ("LOW", "Lowe's"), ("HON", "Honeywell"), ("UPS", "UPS"), ("AMGN", "Amgen"),
    ("SBUX", "Starbucks"), ("LMT", "Lockheed Martin"), ("DE", "Deere & Company"), ("BKNG", "Booking Holdings"), ("UBER", "Uber"),
    ("PYPL", "PayPal"), ("COP", "ConocoPhillips"), ("SLB", "SLB (Schlumberger)"), ("MMM", "3M"), ("C", "Citigroup"),
    ("AXP", "American Express"), ("BLK", "BlackRock"), ("SCHW", "Charles Schwab"), ("NEE", "NextEra Energy"), ("DUK", "Duke Energy"),
    ("SO", "Southern Company"), ("LIN", "Linde"), ("MDLZ", "Mondelez"), ("CL", "Colgate-Palmolive"), ("MO", "Altria"),
    ("PM", "Philip Morris International"), ("F", "Ford"), ("GM", "General Motors"), ("NOC", "Northrop Grumman"), ("RTX", "RTX"),
    ("GILD", "Gilead Sciences"), ("BMY", "Bristol-Myers Squibb"), ("CVS", "CVS Health"), ("TGT", "Target"),
    ("MU", "Micron Technology"), ("AMAT", "Applied Materials"), ("LRCX", "Lam Research"), ("KLAC", "KLA"),
    ("ISRG", "Intuitive Surgical"), ("VRTX", "Vertex Pharmaceuticals"), ("REGN", "Regeneron"), ("INTU", "Intuit"),
    ("NOW", "ServiceNow"), ("PANW", "Palo Alto Networks"), ("SHOP", "Shopify"), ("SPGI", "S&P Global"), ("CME", "CME Group"),
    ("ICE", "Intercontinental Exchange"), ("MCO", "Moody's"), ("USB", "U.S. Bancorp"), ("PNC", "PNC Financial Services"),
    ("TFC", "Truist Financial"), ("MET", "MetLife"), ("PRU", "Prudential Financial"), ("AIG", "AIG"), ("TRV", "Travelers"),
    ("CB", "Chubb"), ("AON", "Aon"), ("ADP", "ADP (Automatic Data Processing)"), ("FDX", "FedEx"), ("CSX", "CSX"),
    ("UNP", "Union Pacific"), ("NSC", "Norfolk Southern"), ("EMR", "Emerson Electric"), ("ETN", "Eaton"),
    ("ITW", "Illinois Tool Works"), ("PH", "Parker-Hannifin"), ("ROK", "Rockwell Automation"), ("DOW", "Dow"),
    ("LYB", "LyondellBasell"), ("NEM", "Newmont"), ("FCX", "Freeport-McMoRan"), ("MOS", "Mosaic"), ("ADM", "Archer-Daniels-Midland"),
    ("KR", "Kroger"), ("DG", "Dollar General"), ("DLTR", "Dollar Tree"), ("ROST", "Ross Stores"), ("TJX", "TJX Companies"),
    ("YUM", "Yum! Brands"), ("CMG", "Chipotle"), ("MAR", "Marriott"), ("HLT", "Hilton"), ("EBAY", "eBay"),
    ("TTWO", "Take-Two Interactive"), ("ZTS", "Zoetis"), ("BDX", "Becton Dickinson"), ("SYK", "Stryker"), ("MDT", "Medtronic"),
    ("BSX", "Boston Scientific"), ("EW", "Edwards Lifesciences"), ("DHR", "Danaher"), ("A", "Agilent Technologies"),
    ("WAT", "Waters"), ("IQV", "IQVIA"), ("LHX", "L3Harris"), ("GD", "General Dynamics"), ("TDG", "TransDigm"),
    ("HWM", "Howmet Aerospace"),
    # France, CAC 40
    ("TTE.PA", "TotalEnergies"), ("HO.PA", "Thales"), ("MC.PA", "LVMH"), ("OR.PA", "L'Oréal"), ("SAN.PA", "Sanofi"),
    ("AIR.PA", "Airbus"), ("BNP.PA", "BNP Paribas"), ("SU.PA", "Schneider Electric"), ("AI.PA", "Air Liquide"), ("DG.PA", "Vinci"),
    ("RMS.PA", "Hermès"), ("SAF.PA", "Safran"), ("CS.PA", "AXA"), ("BN.PA", "Danone"), ("KER.PA", "Kering"),
    ("EL.PA", "EssilorLuxottica"), ("CAP.PA", "Capgemini"),
    # France, autres valeurs
    ("ALDAT.PA", "D.A.T.E"), ("ACA.PA", "Crédit Agricole"), ("GLE.PA", "Société Générale"), ("ORA.PA", "Orange"),
    ("ENGI.PA", "Engie"), ("VIE.PA", "Veolia"), ("SGO.PA", "Saint-Gobain"), ("ML.PA", "Michelin"), ("STLAP.PA", "Stellantis"),
    ("RNO.PA", "Renault"), ("CA.PA", "Carrefour"), ("PUB.PA", "Publicis"), ("EN.PA", "Bouygues"), ("LR.PA", "Legrand"),
    ("URW.PA", "Unibail-Rodamco-Westfield"), ("WLN.PA", "Worldline"), ("DSY.PA", "Dassault Systèmes"),
    ("STMPA.PA", "STMicroelectronics"), ("TEP.PA", "Teleperformance"), ("ERF.PA", "Eurofins Scientific"), ("SW.PA", "Sodexo"),
    ("BVI.PA", "Bureau Veritas"), ("EDEN.PA", "Edenred"), ("AC.PA", "Accor"), ("ALO.PA", "Alstom"), ("VIV.PA", "Vivendi"),
    ("ATO.PA", "Atos"), ("SOP.PA", "Sopra Steria"), ("IPS.PA", "Ipsos"), ("NEX.PA", "Nexans"), ("RCO.PA", "Rémy Cointreau"),
    ("MMT.PA", "Métropole Télévision (M6)"), ("AM.PA", "Dassault Aviation"), ("RI.PA", "Pernod Ricard"), ("SK.PA", "SEB"),
    ("FGR.PA", "Eiffage"), ("COFA.PA", "Coface"), ("CDI.PA", "Christian Dior"), ("DIM.PA", "Sartorius Stedim Biotech"),
    ("ELIS.PA", "Elis"), ("GFC.PA", "Gecina"), ("ICAD.PA", "Icade"), ("LI.PA", "Klépierre"), ("NK.PA", "Imerys"),
    ("RUI.PA", "Rubis"), ("RXL.PA", "Rexel"), ("TFI.PA", "TF1"), ("VK.PA", "Vallourec"), ("VLA.PA", "Valneva"),
    ("ADP.PA", "Aéroports de Paris (ADP)"), ("AF.PA", "Air France-KLM"), ("AKE.PA", "Arkema"), ("BIM.PA", "bioMérieux"),
    ("BOL.PA", "Bolloré"), ("CO.PA", "Casino Guichard-Perrachon"),
    # Allemagne
    ("SAP.DE", "SAP"), ("SIE.DE", "Siemens"), ("ALV.DE", "Allianz"), ("DTE.DE", "Deutsche Telekom"), ("BAS.DE", "BASF"),
    ("BAYN.DE", "Bayer"), ("BMW.DE", "BMW"), ("MBG.DE", "Mercedes-Benz Group"), ("VOW3.DE", "Volkswagen"), ("ADS.DE", "Adidas"),
    ("IFX.DE", "Infineon"), ("MUV2.DE", "Munich Re"), ("DBK.DE", "Deutsche Bank"), ("EOAN.DE", "E.ON"), ("RWE.DE", "RWE"),
    ("HEN3.DE", "Henkel"), ("DHL.DE", "DHL Group"), ("CBK.DE", "Commerzbank"),
    # Royaume-Uni
    ("SHEL.L", "Shell"), ("AZN.L", "AstraZeneca"), ("HSBA.L", "HSBC"), ("ULVR.L", "Unilever"), ("BP.L", "BP"), ("GSK.L", "GSK"),
    ("RIO.L", "Rio Tinto"), ("BATS.L", "British American Tobacco"), ("DGE.L", "Diageo"), ("LSEG.L", "London Stock Exchange Group"),
    ("REL.L", "RELX"), ("BARC.L", "Barclays"), ("LLOY.L", "Lloyds Banking Group"), ("VOD.L", "Vodafone"), ("NG.L", "National Grid"),
    ("TSCO.L", "Tesco"), ("AAL.L", "Anglo American"), ("GLEN.L", "Glencore"),
    # Europe, autres pays
    ("ASML.AS", "ASML"), ("INGA.AS", "ING"), ("PHIA.AS", "Philips"), ("AD.AS", "Ahold Delhaize"), ("HEIA.AS", "Heineken"),
    ("WKL.AS", "Wolters Kluwer"), ("ADYEN.AS", "Adyen"), ("PRX.AS", "Prosus"), ("NESN.SW", "Nestlé"), ("NOVN.SW", "Novartis"),
    ("UBSG.SW", "UBS"), ("ZURN.SW", "Zurich Insurance"), ("ABBN.SW", "ABB"), ("CFR.SW", "Richemont"), ("SREN.SW", "Swiss Re"),
    ("LONN.SW", "Lonza"), ("SAN.MC", "Banco Santander"), ("ITX.MC", "Inditex"), ("IBE.MC", "Iberdrola"), ("BBVA.MC", "BBVA"),
    ("TEF.MC", "Telefónica"), ("REP.MC", "Repsol"), ("ENEL.MI", "Enel"), ("ISP.MI", "Intesa Sanpaolo"), ("UCG.MI", "UniCredit"),
    ("ENI.MI", "Eni"), ("RACE.MI", "Ferrari"), ("G.MI", "Generali"), ("NOKIA.HE", "Nokia"), ("NDA-FI.HE", "Nordea"),
    ("VOLV-B.ST", "Volvo (B)"), ("ERIC-B.ST", "Ericsson (B)"), ("ATCO-A.ST", "Atlas Copco (A)"), ("NOVO-B.CO", "Novo Nordisk (B)"),
    ("DSV.CO", "DSV"), ("ORSTED.CO", "Ørsted"), ("EQNR.OL", "Equinor"), ("DNB.OL", "DNB Bank"),
    # Asie (locales et ADR)
    ("7203.T", "Toyota"), ("6758.T", "Sony"), ("9984.T", "SoftBank Group"), ("8306.T", "Mitsubishi UFJ Financial"),
    ("6861.T", "Keyence"), ("7974.T", "Nintendo"), ("9432.T", "NTT"), ("005930.KS", "Samsung Electronics"),
    ("000660.KS", "SK Hynix"), ("0700.HK", "Tencent"), ("1299.HK", "AIA Group"), ("0941.HK", "China Mobile"),
    ("3690.HK", "Meituan"), ("RELIANCE.NS", "Reliance Industries"), ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"), ("TSM", "TSMC (ADR)"), ("BABA", "Alibaba (ADR)"), ("PDD", "PDD Holdings"), ("JD", "JD.com"),
    ("BIDU", "Baidu (ADR)"), ("NIO", "NIO"), ("HMC", "Honda (ADR)"), ("INFY", "Infosys (ADR)"),
])

# ---------------------------------------------------------------------------------------------- séries macro (FRED)
_add("macro", [
    ("BAMLC0A0CM", "Spread de crédit « investment grade » (OAS)", "Investment-grade credit spread (OAS)"),
    ("BAMLC0A4CBBB", "Spread de crédit notation BBB (OAS)", "BBB credit spread (OAS)"),
    ("BAMLH0A0HYM2", "Spread de crédit haut rendement (OAS)", "High-yield credit spread (OAS)"),
    ("CPIAUCSL", "Inflation, prix à la consommation (CPI)", "Consumer price index (CPI)"),
    ("CPILFESL", "Inflation sous-jacente (CPI hors énergie et alimentation)", "Core CPI (ex food and energy)"),
    ("DCOILBRENTEU", "Pétrole Brent, prix au comptant (FRED)", "Brent crude oil spot price (FRED)"),
    ("DCOILWTICO", "Pétrole WTI, prix au comptant (FRED)", "WTI crude oil spot price (FRED)"),
    ("DFF", "Taux des fonds fédéraux (quotidien)", "Federal funds effective rate (daily)"),
    ("DGS1", "Rendement du Trésor US 1 an", "US Treasury 1-year yield"),
    ("DGS2", "Rendement du Trésor US 2 ans", "US Treasury 2-year yield"),
    ("DGS3", "Rendement du Trésor US 3 ans", "US Treasury 3-year yield"),
    ("DGS5", "Rendement du Trésor US 5 ans", "US Treasury 5-year yield"),
    ("DGS7", "Rendement du Trésor US 7 ans", "US Treasury 7-year yield"),
    ("DGS10", "Rendement du Trésor US 10 ans", "US Treasury 10-year yield"),
    ("DGS20", "Rendement du Trésor US 20 ans", "US Treasury 20-year yield"),
    ("DGS30", "Rendement du Trésor US 30 ans", "US Treasury 30-year yield"),
    ("DTB4WK", "Bons du Trésor US 4 semaines", "US Treasury bill 4-week"),
    ("DTB3", "Bons du Trésor US 3 mois", "US Treasury bill 3-month"),
    ("DTB6", "Bons du Trésor US 6 mois", "US Treasury bill 6-month"),
    ("EFFR", "Taux effectif des fonds fédéraux (EFFR)", "Effective federal funds rate (EFFR)"),
    ("FEDFUNDS", "Taux des fonds fédéraux (mensuel)", "Federal funds rate (monthly)"),
    ("GDP", "PIB américain (nominal)", "US GDP (nominal)"),
    ("INDPRO", "Production industrielle US", "US industrial production"),
    ("NFCI", "Conditions financières (Chicago Fed, NFCI)", "Financial conditions (Chicago Fed, NFCI)"),
    ("PAYEMS", "Emplois non agricoles (Nonfarm payrolls)", "Nonfarm payrolls"),
    ("PCE", "Dépenses de consommation (PCE)", "Personal consumption expenditures (PCE)"),
    ("PCEPILFE", "Inflation sous-jacente (PCE)", "Core PCE inflation"),
    ("RSAFS", "Ventes au détail US", "US retail sales"),
    ("SOFR", "SOFR (taux au jour le jour garanti)", "SOFR (secured overnight financing rate)"),
    ("SP500", "Niveau du S&P 500 (FRED)", "S&P 500 level (FRED)"),
    ("STLFSI4", "Stress financier (Saint-Louis Fed)", "Financial stress (St. Louis Fed)"),
    ("T10Y2Y", "Pente des taux 10 ans – 2 ans", "Yield curve slope 10-year – 2-year"),
    ("T10Y3M", "Pente des taux 10 ans – 3 mois", "Yield curve slope 10-year – 3-month"),
    ("T10YIE", "Inflation anticipée à 10 ans (point mort)", "10-year breakeven inflation"),
    ("T5YIE", "Inflation anticipée à 5 ans (point mort)", "5-year breakeven inflation"),
    ("T5YIFR", "Inflation anticipée 5 ans dans 5 ans", "5-year, 5-year forward inflation expectation"),
    ("TEDRATE", "Écart TED (stress interbancaire)", "TED spread (interbank stress)"),
    ("UMCSENT", "Confiance des consommateurs (Michigan)", "Consumer sentiment (Michigan)"),
    ("UNRATE", "Taux de chômage US", "US unemployment rate"),
    ("VIXCLS", "VIX, clôture (FRED)", "VIX close (FRED)"),
    # séries d'entraînement seulement (jamais des cibles)
    ("ECBDFR", "Taux de dépôt de la BCE", "ECB deposit facility rate"),
    ("CIVPART", "Taux de participation au marché du travail", "Labor force participation rate"),
    ("EMRATIO", "Ratio emploi / population", "Employment-population ratio"),
    ("U6RATE", "Chômage au sens large (U6)", "Underemployment rate (U6)"),
    ("AHETPI", "Salaire horaire moyen", "Average hourly earnings"),
    ("AWHMAN", "Heures hebdomadaires moyennes (industrie)", "Average weekly hours (manufacturing)"),
    ("UEMPMEAN", "Durée moyenne du chômage", "Average duration of unemployment"),
    ("JTSJOL", "Offres d'emploi (JOLTS)", "Job openings (JOLTS)"),
    ("ICSA", "Inscriptions initiales au chômage", "Initial jobless claims"),
    ("CCSA", "Inscriptions continues au chômage", "Continued jobless claims"),
    ("CPIENGSL", "Inflation, énergie (CPI)", "CPI energy"), ("CPIUFDSL", "Inflation, alimentation (CPI)", "CPI food"),
    ("CPIMEDSL", "Inflation, santé (CPI)", "CPI medical care"), ("CUSR0000SAH1", "Inflation, logement (CPI)", "CPI shelter"),
    ("STICKCPIM159SFRBATL", "Inflation « sticky » (Atlanta Fed)", "Sticky-price CPI (Atlanta Fed)"),
    ("PPIACO", "Prix à la production, toutes matières", "Producer price index, all commodities"),
    ("PCEPI", "Indice des prix PCE", "PCE price index"),
    ("MICH", "Inflation anticipée des ménages (Michigan)", "Household inflation expectations (Michigan)"),
    ("GASREGW", "Prix de l'essence aux États-Unis", "US regular gasoline price"),
    ("PSAVERT", "Taux d'épargne des ménages", "Personal saving rate"),
    ("DSPIC96", "Revenu disponible réel", "Real disposable personal income"),
    ("GDPC1", "PIB réel US", "US real GDP"), ("A191RL1Q225SBEA", "Croissance du PIB réel (trimestrielle)", "Real GDP growth (quarterly)"),
    ("HOUST", "Mises en chantier de logements", "Housing starts"), ("PERMIT", "Permis de construire", "Building permits"),
    ("DGORDER", "Commandes de biens durables", "Durable goods orders"), ("AMTMNO", "Nouvelles commandes industrielles", "Manufacturers' new orders"),
    ("TCU", "Taux d'utilisation des capacités", "Capacity utilization"), ("IPMAN", "Production industrielle manufacturière", "Manufacturing industrial production"),
    ("TOTALSA", "Ventes de véhicules", "Total vehicle sales"), ("CSUSHPINSA", "Prix de l'immobilier (Case-Shiller)", "Home prices (Case-Shiller)"),
    ("CFNAI", "Activité nationale (Chicago Fed)", "National activity (Chicago Fed)"), ("M2SL", "Masse monétaire M2", "M2 money supply"),
    ("WALCL", "Total des actifs de la Fed", "Fed total assets"), ("WTREGEN", "Compte général du Trésor", "Treasury general account"),
    ("WRESBAL", "Réserves bancaires", "Bank reserves"), ("TOTCI", "Prêts commerciaux et industriels", "Commercial and industrial loans"),
    ("DFII10", "Taux réel 10 ans (TIPS)", "10-year real yield (TIPS)"), ("DFII5", "Taux réel 5 ans (TIPS)", "5-year real yield (TIPS)"),
    ("DAAA", "Rendement obligataire Aaa (Moody's)", "Moody's Aaa corporate yield"), ("DBAA", "Rendement obligataire Baa (Moody's)", "Moody's Baa corporate yield"),
    ("AAA10Y", "Écart Aaa – Trésor 10 ans", "Aaa – 10-year Treasury spread"), ("BAA10Y", "Écart Baa – Trésor 10 ans", "Baa – 10-year Treasury spread"),
    ("T10YFF", "Écart Trésor 10 ans – fonds fédéraux", "10-year Treasury – fed funds spread"),
    ("T5YFF", "Écart Trésor 5 ans – fonds fédéraux", "5-year Treasury – fed funds spread"),
    ("DPRIME", "Taux préférentiel (prime rate)", "Bank prime loan rate"),
    ("MORTGAGE30US", "Taux hypothécaire à 30 ans", "30-year mortgage rate"), ("MORTGAGE15US", "Taux hypothécaire à 15 ans", "15-year mortgage rate"),
    ("IRLTLT01DEM156N", "Rendement allemand à 10 ans (Bund)", "German 10-year yield (Bund)"),
    ("IRLTLT01JPM156N", "Rendement japonais à 10 ans (JGB)", "Japanese 10-year yield (JGB)"),
    ("IRLTLT01GBM156N", "Rendement britannique à 10 ans (Gilt)", "UK 10-year yield (Gilt)"),
    ("IRLTLT01FRM156N", "Rendement français à 10 ans (OAT)", "French 10-year yield (OAT)"),
    ("IRLTLT01ITM156N", "Rendement italien à 10 ans (BTP)", "Italian 10-year yield (BTP)"),
    ("CP0000EZ19M086NEST", "Inflation de la zone euro (HICP)", "Euro-area inflation (HICP)"),
    ("CLVMNACSCAB1GQEA19", "PIB réel de la zone euro", "Euro-area real GDP"),
    ("LRHUTTTTDEM156S", "Taux de chômage allemand", "German unemployment rate"),
    ("ECBMRRFR", "Taux de refinancement de la BCE", "ECB main refinancing rate"),
    ("IRLTLT01FRM156N", "Rendement français à 10 ans (OAT)", "French 10-year yield (OAT)"),
    ("IRLTLT01ITM156N", "Rendement italien à 10 ans (BTP)", "Italian 10-year yield (BTP)"),
    ("CP0000EZ19M086NEST", "Inflation de la zone euro (HICP)", "Euro-area inflation (HICP)"),
    ("CLVMNACSCAB1GQEA19", "PIB réel de la zone euro", "Euro-area real GDP"),
    ("LRHUTTTTDEM156S", "Taux de chômage allemand", "German unemployment rate"),
    ("ECBMRRFR", "Taux de refinancement de la BCE", "ECB main refinancing rate"),
    ("NFCIRISK", "Conditions financières, risque (NFCI)", "Financial conditions, risk (NFCI)"),
    ("NFCICREDIT", "Conditions financières, crédit (NFCI)", "Financial conditions, credit (NFCI)"),
    ("NFCILEVERAGE", "Conditions financières, levier (NFCI)", "Financial conditions, leverage (NFCI)"),
    ("VXNCLS", "VXN, clôture (FRED)", "VXN close (FRED)"), ("RVXCLS", "RVX (Russell 2000), clôture (FRED)", "RVX (Russell 2000) close (FRED)"),
    ("OVXCLS", "OVX, clôture (FRED)", "OVX close (FRED)"), ("GVZCLS", "GVZ, clôture (FRED)", "GVZ close (FRED)"),
    ("DEXJPUS", "USD/JPY (FRED)"), ("DEXUSUK", "GBP/USD (FRED)"), ("DEXCHUS", "USD/CNY (FRED)"), ("DEXSZUS", "USD/CHF (FRED)"),
    ("DEXCAUS", "USD/CAD (FRED)"),
])
