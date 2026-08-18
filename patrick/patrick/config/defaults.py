"""Defaults encoding the lessons learned from the VIX project (README) — can be
switched on differently, never removed from the code: SHAP beats RFE/LASSO in
direct testing, stacking loses on 93% of the (horizon, fold) pairs tested in
walk-forward, DL never beat classical ML, purge has a negligible effect,
calibration only helps outside STRESS regimes.
"""

DEFAULT_ML_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "CatBoost"]
ALL_ML_ALGOS = ["XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost"]
DEFAULT_SAMPLERS_ALL = ["SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN"]
DEFAULT_SAMPLER = ["SMOTE"]
DEFAULT_SELECTION_METHOD = "shap"
DEFAULT_N_FEATURES_GRID = list(range(5, 16))
DEFAULT_REGIMES = ["GLOBAL"]
DEFAULT_HORIZONS = [1, 2, 3, 5, 7, 10]
DEFAULT_FEATURE_FAMILIES = ["technical", "interactions", "spike", "vol_models", "macro"]
DEFAULT_POOL_PREFILTER = 450
DEFAULT_SHAP_SAMPLE = 500
DEFAULT_N_WF_FOLDS = 5
DEFAULT_MIN_TRAIN_FRAC = 0.40
DEFAULT_FLAT_THR = 0.003
DEFAULT_SEED = 42

# Phase 2.1 (statistical validity): last months reserved as terminal holdout,
# never seen by feature selection/tuning/leaderboard ranking. The original plan
# leaves a range (12-24 months); 15 = reasonable midpoint. Configurable via
# validation.holdout_months in the YAML (range: 12-24, default: 15).
DEFAULT_HOLDOUT_MONTHS = 15

# Phase X5 -- mapping from asset class (`data/session_calendar.classify_asset_class`)
# -> "class-specific" baseline candidates for the Diebold-Mariano test (Phase 2.5).
# When several candidates are listed, the best one (highest F1_dir on the
# evaluated fold) is kept -- see `pipeline/engine.py::_evaluate_diebold_mariano`.
# Class-agnostic persistence is ALWAYS computed in addition, as a fixed common
# reference across classes (never part of this mapping). Not exhaustive: any
# class absent here falls back to ["persistence"] (historical, conservative
# behavior).
DEFAULT_BASELINE_BY_ASSET_CLASS: dict[str, list[str]] = {
    "volatility_index": ["har_rv"],
    "equities_us": ["persistence", "majority_by_regime"],
    "equities_americas_other": ["persistence", "majority_by_regime"],
    "equities_europe": ["persistence", "majority_by_regime"],
    "equities_asia_pacific": ["persistence", "majority_by_regime"],
    "fx": ["random_walk_no_drift"],
    "futures": ["momentum_20"],
    "crypto": ["persistence", "momentum_5"],
    "macro": ["random_walk_drift"],
    "other": ["persistence"],
}

# Optuna is part of the loop by default (explicit requirement): selecting the
# best model without tuning it does not fulfill "return the best model".
DEFAULT_TUNING_ENABLED = True
DEFAULT_TUNING_TOP_K = 5
DEFAULT_TUNING_N_TRIALS = 100
DEFAULT_TUNING_CV_SPLITS = 3
# Audit report, C3: `top_k` used to be selected GLOBALLY across all horizons --
# a multi-horizon run could see 100% of the Optuna budget concentrated on a
# single horizon (whichever had the dominant best SCAN trial), the others
# getting none. True = each horizon receives its own top_k/n_trials,
# independently of the others (fixed behavior, default).
DEFAULT_TUNING_OPTUNA_SELECT_TOP_K_PER_HORIZON = True

# Phase 6.5 (P6.5) -- data quality gates at ingestion: thresholds MEASURED by
# simulation, not chosen by convention -- see detailed justification in
# `data/quality.py` (module docstring).
DEFAULT_QUALITY_MAX_FROZEN_RUN = 4
DEFAULT_QUALITY_MAX_GAP_BDAYS = 10
DEFAULT_QUALITY_MAX_ROBUST_Z = 40.0
DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30

# Phase 6.1 (P6.1) -- CPCV: minimal (N, k=2) pair that makes PBO satisfiable
# (guard C5, MIN_BLOCKS=6) without superfluous combinatorial computation --
# see detailed justification in `validation/cpcv.py`.
DEFAULT_CPCV_N_GROUPS = 7
DEFAULT_CPCV_K_TEST_GROUPS = 2

# Options disabled by default but wired into the pipeline (not an appendix):
# purge (VIX_PURGED_CV: negligible F1_dir delta), calibration (VIX_CALIBRATED_THRESHOLD:
# regime-conditional gain, hurts in STRESS), stacking (VIX_STACKING_WF: loses 28/30).
DEFAULT_PURGE_ENABLED = False
DEFAULT_CALIBRATION_ENABLED = False
DEFAULT_STACKING_ENABLED = False

# Embargo (Phase 0 correctness, distinct from the purge above): removes from the
# TEST set the first `embargo_bars` bars following the train/test cut, against
# rolling windows (rolling mean/std...) computed right after the cut that are
# still correlated with train. Unlike purge (measured negligible effect in the
# original VIX project), there is not yet an empirical measurement for embargo
# on this generalized framework -- enabled by default out of caution (low cost:
# a few fewer test bars per fold), unlike purge.
DEFAULT_EMBARGO_ENABLED = True
DEFAULT_EMBARGO_BARS = None  # None -> derived from the current horizon (e = horizon)

# Models in the "vol_models" family (patrick/features/vol_models.py), individually
# selectable from the web interface. The first 5 are the ones from the original VIX
# pipeline (always computed together until now) — kept enabled by default so as not
# to change the already-validated F1_dir≈0.610 reference. AR/MA/ARMA/ARIMA are new,
# never tested in walk-forward: disabled by default.
ALL_VOL_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy", "ar", "ma", "arma", "arima"]
DEFAULT_VOL_MODELS = ["egarch", "kalman", "hmm", "heston_proxy", "vrp_proxy"]

# Open list of targets proposed by the web form ("what to predict?"), grouped
# by category for a browsable dropdown despite their number — no more free-text
# field. Each entry also fixes its source (yfinance except for the
# "Macro (FRED)" group), so there is no separate source choice to make anymore.
# Manually maintained blocklist: tickers already known to be delisted, malformed
# for yfinance, or renamed since — to exclude if ever reinjected into
# YF_TICKERS_RAW/MANUAL_YF_NAMES above during a future extension.
BAD_TICKERS = {
    "XXIV", "TVIX", "ZIV", "^MIB", "CELG", "AET", "HES", "GPS", "JWN", "DFS",
    "SPX", "EON", "EDF", "RWE", "SZR", "ICN", "CEIX", "MXEA", "SQ", "SHELL", "K",
}

FRED_TARGET_GROUP = "Macro (FRED)"

DEFAULT_TARGET_GROUPS = {
    "Indices": [
        ("^AORD", "AORD_AUS"),
        ("^AXJO", "ASX_Australia"),
        ("^BVSP", "BOVESPA_Brazil"),
        ("^DJI", "DOW_Price"),
        ("^EVZ", "EVZ_EUR_Vol"),
        ("^FCHI", "CAC40_France"),
        ("^FTSE", "FTSE_UK"),
        ("^GDAXI", "DAX_Germany"),
        ("^GSPC", "SP500_Price"),
        ("^GVZ", "GVZ_Gold_Vol"),
        ("^HSI", "HangSeng_HK"),
        ("^IBEX", "IBEX_Spain"),
        ("^IXIC", "NASDAQ_Price"),
        ("^N225", "Nikkei_Japan"),
        ("^OVX", "OVX_Oil_Vol"),
        ("^RUT", "Russell_Price"),
        ("^STOXX50E", "STOXX50E_EU"),
        ("^VIX", "VIX_Price"),
        ("^VXN", "VXN_NASDAQ_Vol"),
        # Additions (yfinance list provided by the user, 2026-07-27): world
        # indices absent above, manually filtered/validated against the source
        # file (no duplicate with symbols already present).
        ("000001.SS", "SSE_Shanghai"),
        ("^BFX", "BEL20_Belgium"),
        ("^BSESN", "Sensex_India"),
        ("^CASE30", "EGX30_Egypt"),
        ("DX-Y.NYB", "DXY_DollarIndex"),
        ("^GSPTSE", "TSX_Canada"),
        ("^JKSE", "JCI_Indonesia"),
        ("^JN0U.JO", "JSE_SouthAfrica"),
        ("^KLSE", "KLCI_Malaysia"),
        ("^KS11", "KOSPI_Korea"),
        ("^MERV", "Merval_Argentina"),
        ("^MXX", "IPC_Mexico"),
        ("^N100", "Euronext100"),
        ("^NSEI", "Nifty50_India"),
        ("^NZ50", "NZX50_NewZealand"),
        ("^STI", "STI_Singapore"),
        ("^TA125.TA", "TA125_Israel"),
        ("^TWII", "Taiwan_Weighted"),
    ],
    "Devises": [
        ("EURUSD=X", "EUR_USD"),
        ("EURGBP=X", "EUR_GBP"),
        ("EURCHF=X", "EUR_CHF"),
        ("EURCAD=X", "EUR_CAD"),
        ("EURCNY=X", "EUR_CNY"),
        ("EURJPY=X", "EUR_JPY"),
        ("EURSEK=X", "EUR_SEK"),
        ("EURHUF=X", "EUR_HUF"),
        ("GBPUSD=X", "GBP_USD"),
        ("GBPCNY=X", "GBP_CNY"),
        ("GBPJPY=X", "GBP_JPY"),
        ("CHF=X", "USD_CHF"),
        ("CAD=X", "USD_CAD"),
        ("CNY=X", "USD_CNY"),
        ("USDHKD=X", "USD_HKD"),
        ("USDSGD=X", "USD_SGD"),
        ("USDINR=X", "USD_INR"),
        ("USDMXN=X", "USD_MXN"),
        ("USDPHP=X", "USD_PHP"),
        ("USDIDR=X", "USD_IDR"),
        ("USDTHB=X", "USD_THB"),
        ("USDMYR=X", "USD_MYR"),
        ("USDZAR=X", "USD_ZAR"),
        ("USDRUB=X", "USD_RUB"),
        ("JPY=X", "USD_JPY"),
        ("AUDUSD=X", "AUD_USD"),
        ("AUDJPY=X", "AUD_JPY"),
        ("NZDUSD=X", "NZD_USD"),
    ],
    "Matières premières (futures)": [
        ("GC=F", "Gold_Futures"),
        ("SI=F", "Silver_Futures"),
        ("HG=F", "Copper_Futures"),
        ("CL=F", "WTI_Futures"),
        ("BZ=F", "Brent_Futures"),
        ("NG=F", "NatGas_Futures"),
        ("ZC=F", "Corn_Futures"),
        ("ZO=F", "Oats_Futures"),
        ("KE=F", "Wheat_KC_Futures"),
        ("ZR=F", "Rice_Futures"),
        ("ZS=F", "Soybeans_Futures"),
        ("GF=F", "FeederCattle_Futures"),
        ("HE=F", "LeanHogs_Futures"),
        ("LE=F", "LiveCattle_Futures"),
        ("CC=F", "Cocoa_Futures"),
        ("KC=F", "Coffee_Futures"),
        ("CT=F", "Cotton_Futures"),
        ("LBS=F", "Lumber_Futures"),
        ("OJ=F", "OrangeJuice_Futures"),
        ("SB=F", "Sugar_Futures"),
    ],
    "Actions France & Europe": [
        # High-confidence subset of the raw list (18922 tickers): the vast
        # majority of the ~7966 "Actions" codes were Euronext warrants/turbos
        # (.NX suffix, ~7074) or certificate series on the same underlying
        # (e.g. ACAxx/ETAxx/MLxxx, identified by a repeated common prefix)
        # rather than distinct stocks — filtered out. Keeps only listed
        # companies identified with confidence (CAC 40 + recognizable
        # mid-caps), each verified present in the source file. TTE
        # (TotalEnergies) already present under "Actions individuelles" (US
        # row) — no TTE.PA duplicate here.
        ("AI.PA", "AirLiquide"),
        ("AIR.PA", "Airbus"),
        ("MC.PA", "LVMH"),
        ("OR.PA", "LOreal"),
        ("RMS.PA", "Hermes"),
        ("SAN.PA", "Sanofi"),
        ("BNP.PA", "BNPParibas"),
        ("GLE.PA", "SocieteGenerale"),
        ("ACA.PA", "CreditAgricole"),
        ("SU.PA", "SchneiderElectric"),
        ("SGO.PA", "SaintGobain"),
        ("DG.PA", "Vinci"),
        ("CS.PA", "AXA"),
        ("KER.PA", "Kering"),
        ("RI.PA", "PernodRicard"),
        ("BN.PA", "Danone"),
        ("EL.PA", "EssilorLuxottica"),
        ("CAP.PA", "Capgemini"),
        ("SAF.PA", "Safran"),
        ("VIE.PA", "Veolia"),
        ("ENGI.PA", "Engie"),
        ("ORA.PA", "Orange"),
        ("CA.PA", "Carrefour"),
        ("WLN.PA", "Worldline"),
        ("STLAP.PA", "Stellantis"),
        ("LR.PA", "Legrand"),
        ("VIV.PA", "Vivendi"),
        ("PUB.PA", "PublicisGroupe"),
        ("URW.PA", "UnibailRodamcoWestfield"),
        ("UBI.PA", "Ubisoft"),
        ("ADP.PA", "AeroportsDeParis"),
        ("EN.PA", "Bouygues"),
        ("HO.PA", "Thales"),
        ("FR.PA", "Valeo"),
        ("TE.PA", "TechnipEnergies"),
        ("SW.PA", "Sodexo"),
        ("ATO.PA", "Atos"),
        ("FGR.PA", "Eiffage"),
        ("GTT.PA", "GazTransportTechnigaz"),
        ("BVI.PA", "BureauVeritas"),
        ("ML.PA", "Michelin"),
        ("AKE.PA", "Arkema"),
        ("AMUN.PA", "Amundi"),
        ("DSY.PA", "DassaultSystemes"),
        ("EDEN.PA", "Edenred"),
        ("ELIOR.PA", "EliorGroup"),
        ("ELIS.PA", "Elis"),
        ("ERF.PA", "EurofinsScientific"),
        ("FNAC.PA", "FnacDarty"),
        ("GET.PA", "Getlink"),
        ("GFC.PA", "Gecina"),
        ("ICAD.PA", "Icade"),
        ("IPN.PA", "Ipsen"),
        ("IPS.PA", "Ipsos"),
        ("LI.PA", "Klepierre"),
        ("NANO.PA", "Nanobiotix"),
        ("NEX.PA", "Nexans"),
        ("NK.PA", "Imerys"),
        ("OSE.PA", "OSEImmunotherapeutics"),
        ("PRC.PA", "Precia"),
        ("RCO.PA", "RemyCointreau"),
        ("SCR.PA", "SCOR"),
        ("SK.PA", "SEB"),
        ("SMCP.PA", "SMCPGroup"),
        ("SOP.PA", "SopraSteria"),
        ("SPIE.PA", "Spie"),
        ("STMPA.PA", "STMicroelectronics"),
        ("TEP.PA", "Teleperformance"),
        ("TFI.PA", "TF1"),
        ("VLA.PA", "Valneva"),
        ("XFAB.PA", "XFabSiliconFoundries"),
        ("BIM.PA", "BioMerieux"),
        ("COFA.PA", "Coface"),
        ("COV.PA", "Covivio"),
        ("MRN.PA", "Mersen"),
        ("DBG.PA", "Derichebourg"),
        ("DEC.PA", "JCDecaux"),
        ("VK.PA", "Vallourec"),
        ("BOL.PA", "Bollore"),
        ("CARM.PA", "Carmila"),
    ],
    "ETFs larges & style": [
        ("ARKK", "ARKK_Innovation"),
        ("DGRO", "DGRO_DividendGrowth"),
        ("DIA", "DIA_Dow"),
        ("EEMV", "EEMV_EMMinVol"),
        ("EFA", "EFA_MSCI_EAFE"),
        ("EUSA", "EUSA_EuropeMomentum"),
        ("HDV", "HDV_HighDiv"),
        ("IVV", "IVV_SP500"),
        ("IWM", "IWM_SmallCap"),
        ("JEPI", "JEPI_EquityPremiumIncome"),
        ("MTUM", "MTUM_Momentum"),
        ("NOBL", "NOBL_Aristocrat"),
        ("QQQ", "QQQ"),
        ("QUAL", "QUAL_Quality"),
        ("QYLD", "QYLD_NasdaqYield"),
        ("RSP", "RSP_EqualWeight_SP500"),
        ("RYLD", "RYLD_Russell2000Yield"),
        ("SCHD", "SCHD_Div"),
        ("SPLV", "SPLV_LowVol_SP500"),
        ("SPY", "SPY"),
        ("USMV", "USMV_MinVol"),
        ("VB", "VB_SmallCap2"),
        ("VIG", "VIG_DivGrowth"),
        ("VLUE", "VLUE_Value"),
        ("VOO", "VOO_SP500_2"),
        ("VTI", "VTI_Total"),
        ("VTV", "VTV_Value"),
        ("VUG", "VUG_Growth"),
        ("VV", "VV_LargeCap"),
        ("VYMI", "VYMI_HighDivYield"),
        ("XYLD", "XYLD_XYieldETF"),
    ],
    "ETFs sectoriels & thématiques": [
        ("IBB", "IBB_Biotech2"),
        ("ICLN", "ICLN_CleanEnergy"),
        ("ITA", "ITA_Defense"),
        ("IYM", "IYM_BasicMaterials"),
        ("IYR", "IYR_US_REIT2"),
        ("IYT", "IYT_Transport"),
        ("KBE", "KBE_Banks"),
        ("KRE", "KRE_RegionalBanks"),
        ("OIH", "OIH_OilServices"),
        ("REM", "REM_Mortgage_REIT"),
        ("SOXX", "SOXX_Semis"),
        ("TAN", "TAN_SolarEnergy"),
        ("VNQ", "VNQ_US_REIT"),
        ("XBI", "XBI_Biotech"),
        ("XHB", "XHB_Homebuilders"),
        ("XLB", "XLB_Materials"),
        ("XLC", "XLC_CommServ"),
        ("XLE", "XLE_Energy"),
        ("XLF", "XLF_Fin"),
        ("XLI", "XLI_Indust"),
        ("XLK", "XLK_Tech"),
        ("XLP", "XLP_Staples"),
        ("XLRE", "XLRE_RE"),
        ("XLU", "XLU_Util"),
        ("XLV", "XLV_Health"),
        ("XLY", "XLY_Disc"),
        ("XOP", "XOP_OilExploration"),
    ],
    "Obligataire & taux (ETFs)": [
        ("AGG", "AGG_Aggregate"),
        ("BIL", "BIL_TBill3M"),
        ("BND", "BND_TotalBond"),
        ("BNDX", "BNDX_IntlBond"),
        ("EMB", "EMB_EM"),
        ("HYG", "HYG_HighYield"),
        ("HYLD", "HYLD_HYieldETF"),
        ("IEF", "IEF_MidBond"),
        ("JNK", "JNK_HY2"),
        ("LQD", "LQD_InvGrade"),
        ("MBB", "MBB_Mortgage"),
        ("PFFA", "PFFA_PreferredA"),
        ("SHV", "SHV_TBill"),
        ("SHY", "SHY_ShortBond"),
        ("TIP", "TIP_TIPS"),
        ("TLT", "TLT_LongBond"),
        ("VCIT", "VCIT_CorpIG"),
        ("VCSH", "VCSH_CorpST"),
    ],
    "Matières premières & devises (ETFs)": [
        ("BZF", "BZF_BrazilReal"),
        ("WEAT", "WEAT_Wheat"),
        ("CEW", "CEW_EM_FX"),
        ("CORN", "CORN_Corn"),
        ("CYB", "CYB_ChineseYuan"),
        ("DBA", "DBA_Agri"),
        ("DBC", "DBC_Commodity"),
        ("FXA", "FXA_AUD"),
        ("FXB", "FXB_GBP"),
        ("FXC", "FXC_CAD"),
        ("FXD", "FXD_SwedishKrona"),
        ("FXE", "FXE_Euro"),
        ("FXF", "FXF_CHF"),
        ("FXN", "FXN_NorwegianKrone"),
        ("FXY", "FXY_Yen"),
        ("GDX", "GDX_GoldMiners"),
        ("GDXJ", "GDXJ_JrMiners"),
        ("GLD", "GLD_Gold"),
        ("PDBC", "PDBC_Commodity2"),
        ("SLV", "SLV_Silver"),
        ("SOYB", "SOYB_Soybean"),
        ("UNG", "UNG_Gas"),
        ("USO", "USO_Oil"),
        ("UUP", "UUP_Dollar"),
    ],
    "Volatilité": [
        ("SVXY", "SVXY"),
        ("UVXY", "UVXY"),
        ("VIXM", "VIXM"),
        ("VIXY", "VIXY"),
        ("VXX", "VXX"),
        ("VXZ", "VXZ"),
    ],
    "Crypto": [
        ("BITO", "BITO_BitcoinETF"),
        ("CIFR", "CIFR_Cipher"),
        ("CLSK", "CLSK_CleanSpark"),
        ("COIN", "COIN_Crypto"),
        ("CORZ", "CORZ_Core_Sci"),
        ("ETHA", "ETHA_EthereumETF"),
        ("GBTC", "GBTC_Bitcoin"),
        ("IBIT", "IBIT_Bitcoin2"),
        ("MARA", "MARA_Marathon"),
        ("MSTR", "MSTR_Bitcoin3"),
        ("RIOT", "RIOT_Riot"),
        # Spot (absent above, which only covered stock/ETF proxies) — only major
        # cryptos, non-stablecoin, non-wrapped (excludes
        # USDT/USDC/STETH/WBTC/WETH... redundant with their underlying).
        ("BTC-USD", "Bitcoin_Spot"),
        ("ETH-USD", "Ethereum_Spot"),
        ("BNB-USD", "BNB_Spot"),
        ("XRP-USD", "XRP_Spot"),
        ("SOL-USD", "Solana_Spot"),
        ("DOGE-USD", "Dogecoin_Spot"),
        ("ADA-USD", "Cardano_Spot"),
        ("AVAX-USD", "Avalanche_Spot"),
        ("LINK-USD", "Chainlink_Spot"),
        ("DOT-USD", "Polkadot_Spot"),
        ("LTC-USD", "Litecoin_Spot"),
        ("BCH-USD", "BitcoinCash_Spot"),
        ("XLM-USD", "Stellar_Spot"),
        ("TRX-USD", "Tron_Spot"),
    ],
    "International (ETFs pays)": [
        ("ASHR", "ASHR_China_A"),
        ("EEM", "EEM_EM2"),
        ("EGRX", "EGRX_Greece"),
        ("EIDO", "EIDO_Indonesia"),
        ("EPI", "EPI_India2"),
        ("EPOL", "EPOL_Poland"),
        ("EWA", "EWA_Australia"),
        ("EWC", "EWC_Canada"),
        ("EWG", "EWG_Germany"),
        ("EWH", "EWH_HongKong"),
        ("EWI", "EWI_Italy"),
        ("EWJ", "EWJ_Japan"),
        ("EWL", "EWL_Switzerland"),
        ("EWM", "EWM_Malaysia"),
        ("EWP", "EWP_Spain"),
        ("EWQ", "EWQ_France"),
        ("EWS", "EWS_Singapore"),
        ("EWT", "EWT_Taiwan"),
        ("EWU", "EWU_UK"),
        ("EWY", "EWY_Korea"),
        ("EWZ", "EWZ_Brazil"),
        ("EZA", "EZA_SouthAfrica"),
        ("FXI", "FXI_China"),
        ("GXG", "GXG_Germany2"),
        ("IEMG", "IEMG_EM"),
        ("INDA", "INDA_India"),
        ("MCHI", "MCHI_China2"),
        ("TUR", "TUR_Turkey"),
        ("VEA", "VEA_DM"),
    ],
    "Actions individuelles": [
        ("AAL", "AAL_AmericanAir"),
        ("AAPL", "AAPL"),
        ("ABBV", "ABBV_AbbVie"),
        ("ABT", "ABT"),
        ("ACN", "ACN"),
        ("ADBE", "ADBE"),
        ("ADM", "ADM_ArcherDaniels"),
        ("AEP", "AEP_AmericanElectric"),
        ("AMD", "AMD"),
        ("AMGN", "AMGN_Amgen"),
        ("AMT", "AMT_AmericanTower"),
        ("AMZN", "AMZN"),
        ("ASML", "ASML_ASML"),
        ("AVB", "AVB_AvalonBay"),
        ("AVGO", "AVGO_Broadcom"),
        ("AXP", "AXP_Amex"),
        ("BA", "BA"),
        ("BABA", "BABA"),
        ("BAC", "BAC"),
        ("BAX", "BAX_BankBoston"),
        ("BBY", "BBY_BestBuy"),
        ("BDX", "BDX_Becton_Dickinson"),
        ("BLK", "BLK_BlackRock"),
        ("BLMN", "BLMN_BloombergME"),
        ("BMY", "BMY_BristolMyers"),
        ("BNTX", "BNTX_BioNTech"),
        ("BP", "BP_BritishPetroleum"),
        ("BTI", "BTI_BritishAmerican"),
        ("CAT", "CAT_Caterpillar"),
        ("CCI", "CCI_CrownCastle"),
        ("CHTR", "CHTR_Charter"),
        ("CI", "CI_Cigna"),
        ("CL", "CL_Colgate"),
        ("CLX", "CLX_Clorox"),
        ("CMCSA", "CMCSA"),
        ("CMG", "CMG"),
        ("COF", "COF_CapitalOne"),
        ("COLD", "COLD_ColdStorage"),
        ("COP", "COP_ConocoPhillips"),
        ("COST", "COST"),
        ("CPB", "CPB_CampbellSoup"),
        ("CRM", "CRM"),
        ("CRSP", "CRSP_CrisprTherapy"),
        ("CRWD", "CRWD_CrowdStrike"),
        ("CSCO", "CSCO"),
        ("CTAS", "CTAS_Cintas"),
        ("CVX", "CVX"),
        ("DAL", "DAL_Delta"),
        ("DASH", "DASH_DoorDash"),
        ("DDOG", "DDOG_Datadog"),
        ("DE", "DE_Deere"),
        ("DHR", "DHR"),
        ("DIS", "DIS"),
        ("DLR", "DLR_Digital_Realty"),
        ("DPZ", "DPZ_Dominos"),
        ("DUK", "DUK_Duke"),
        ("DXCM", "DXCM_Dexcom"),
        ("EBAY", "EBAY_eBay"),
        ("EMR", "EMR_Emerson"),
        ("ENB", "ENB_EnbridgeInc"),
        ("EOG", "EOG_EOGResources"),
        ("EQIX", "EQIX_Equinix"),
        ("EQR", "EQR_Equity"),
        ("ES", "ES_Evergy"),
        ("ETN", "ETN_Eaton"),
        ("EXC", "EXC_Exelon"),
        ("GD", "GD_GeneralDynamics"),
        ("GE", "GE"),
        ("GILD", "GILD_Gilead"),
        ("GIS", "GIS_GeneralMills"),
        ("GOOG", "GOOG"),
        ("GOOGL", "GOOGL_Google"),
        ("GS", "GS_GoldmanSachs"),
        ("HD", "HD"),
        ("HII", "HII_HuntingtonIngalls"),
        ("HON", "HON_Honeywell"),
        ("HUM", "HUM_Humana"),
        ("ILMN", "ILMN_Illumina"),
        ("INTC", "INTC"),
        ("ITT", "ITT_ITTInc"),
        ("JCI", "JCI_JohnsonControls"),
        ("JD", "JD_JD.com"),
        ("JNJ", "JNJ"),
        ("JPM", "JPM"),
        ("KO", "KO"),
        ("LHX", "LHX_L3Harris"),
        ("LDOS", "LDOS_LeadosSecurity"),
        ("LLY", "LLY"),
        ("LMT", "LMT_LockheedMartin"),
        ("LOGI", "LOGI_Logitech"),
        ("LOW", "LOW_Lowes"),
        ("LUV", "LUV_SouthwestAir"),
        ("LVRK", "LVRK_Lavazza"),
        ("LYFT", "LYFT_Lyft"),
        ("M", "M_Macys"),
        ("MA", "MA"),
        ("MCD", "MCD"),
        ("MDLZ", "MDLZ_Mondelez"),
        ("MELI", "MELI_MercadoLibre"),
        ("MET", "MET_MetalexEnergy"),
        ("META", "META_Meta"),
        ("MKC", "MKC_McCormick"),
        ("MMM", "3M"),
        ("MO", "MO_AltriaMG"),
        ("MPC", "MPC_MarathonPetroleum"),
        ("MRK", "MRK_Merck"),
        ("MRNA", "MRNA_Moderna"),
        ("MS", "MS_MorganStanley"),
        ("MSFT", "MSFT"),
        ("NEE", "NEE_NextEra"),
        ("NET", "NET_Cloudflare"),
        ("NFLX", "NFLX"),
        ("NOC", "NOC_Northrop"),
        ("NSRGY", "NSRGY_Nestle"),
        ("NVDA", "NVDA"),
        ("NWL", "NWL_Newell"),
        ("ORCL", "ORCL"),
        ("OTIS", "OTIS_Otis"),
        ("PAYX", "PAYX_Paychex"),
        ("PCAR", "PCAR_PaccarInc"),
        ("PDD", "PDD_PinDuoDuo"),
        ("PEP", "PEP"),
        ("PFE", "PFE"),
        ("PG", "PG"),
        ("PINS", "PINS_Pinterest"),
        ("PLD", "PLD_Prologis"),
        ("PM", "PM_PhilipMorris"),
        ("PPL", "PPL_PPL"),
        ("PSA", "PSA_PublicStorage"),
        ("PSX", "PSX_PhillipsLiquids"),
        ("PTC", "PTC_PTC"),
        ("PYPL", "PYPL"),
        ("QCOM", "QCOM"),
        ("QSR", "QSR_RestaurantBrands"),
        ("RBLX", "RBLX_Roblox"),
        ("REXR", "REXR_Rexford"),
        ("ROKU", "ROKU_Roku"),
        ("ROST", "ROST_RossStores"),
        ("RRR", "RRR_RareMedica"),
        ("RTX", "RTX_Raytheon"),
        ("SBUX", "SBUX"),
        ("SCHW", "SCHW_Schwab"),
        ("SE", "SE_SeaLimited"),
        ("SHOP", "SHOP_Shopify"),
        ("SJM", "SJM_JM_Smucker"),
        ("SLB", "SLB_Schlumberger"),
        ("SMCI", "SMCI_SuperMicroComputer"),
        ("SMFG", "SMFG"),
        ("SNAP", "SNAP_Snapchat"),
        ("SNOW", "SNOW_Snowflake"),
        ("SO", "SO_SouthernCo"),
        ("SPCE", "SPCE_VirginGalactic"),
        ("SPG", "SPG_SimonProperty"),
        ("SRE", "SRE_Sempra"),
        ("T", "T"),
        ("TAP", "TAP_MolsonCoors"),
        ("TBP", "TBP_Tata"),
        ("TDOC", "TDOC_Teladoc"),
        ("TERM", "TERM_Terminal"),
        ("TGT", "TGT_Target"),
        ("TM", "TM_Telephone"),
        ("TMUS", "TMUS_TMobileUS"),
        ("TSLA", "TSLA"),
        ("TTE", "TTE_TotalEnergies"),
        ("TXN", "TXN"),
        ("UAL", "UAL_UnitedAir"),
        ("UBER", "UBER_Uber"),
        ("UL", "UL_Unilever"),
        ("UNH", "UNH"),
        ("UPST", "UPST_Upstart"),
        ("V", "V"),
        ("VIPS", "VIPS_Vipshop"),
        ("VLO", "VLO_Valero"),
        ("VOD", "VOD_Vodafone"),
        ("VRTX", "VRTX_VertexPharm"),
        ("VZ", "VZ"),
        ("WFC", "WFC_WellsFargo"),
        ("WMT", "WMT"),
        ("XEL", "XEL_Xcel"),
        ("XOM", "XOM"),
        ("YUM", "YUM_YumBrands"),
        ("ZM", "ZM_Zoom"),
    ],
    "Macro (FRED)": [
        ("BAMLC0A0CM", "IG_OAS"),
        ("BAMLC0A4CBBB", "BBB_OAS"),
        ("BAMLH0A0HYM2", "HY_OAS"),
        ("CPIAUCSL", "CPI"),
        ("CPILFESL", "Core_CPI"),
        ("DCOILBRENTEU", "Brent_Oil_FRED"),
        ("DCOILWTICO", "WTI_Oil_FRED"),
        ("DFF", "DFF"),
        ("DGS1", "US1Y_Rate"),
        ("DGS10", "US10Y_Rate"),
        ("DGS2", "US2Y_Rate"),
        ("DGS20", "US20Y_Rate"),
        ("DGS3", "US3Y_Rate"),
        ("DGS30", "US30Y_Rate"),
        ("DGS5", "US5Y_Rate"),
        ("DGS7", "US7Y_Rate"),
        ("DTB1", "US1M_Rate"),
        ("DTB3", "US3M_Rate"),
        ("DTB6", "US6M_Rate"),
        ("EFFR", "EFFR"),
        ("FEDFUNDS", "FedFunds"),
        ("GDP", "GDP"),
        ("INDPRO", "Industrial_Production"),
        ("NFCI", "NFCI"),
        ("OILPRICE", "Oil_Price"),
        ("PAYEMS", "NonfarmPayrolls"),
        ("PCE", "PCE"),
        ("PCEPILFE", "Core_PCE"),
        ("RSAFS", "Retail_Sales"),
        ("SOFR", "SOFR_SecuredOIS"),
        ("SP500", "SP500_Level"),
        ("STLFSI4", "STLFSI4"),
        ("T10Y2Y", "T10Y2Y_Spread"),
        ("T10Y3M", "T10Y3M_Spread"),
        ("T10YIE", "T10Y_Inflation_Expectation"),
        ("T5YIE", "T5Y_Inflation_Expectation"),
        ("T5YIFR", "T5Y5Y_Inflation_Forward"),
        ("TEDRATE", "TED_Spread"),
        ("UMCSENT", "Michigan_Sentiment"),
        ("UNRATE", "Unemployment"),
        ("VIXCLS", "VIX"),
        ("VIXDVOL", "VIX_DrawVol"),
        ("WILL5000IND", "Wilshire5000"),
    ],
}

def _flatten_target_choices():
    out = []
    for group, items in DEFAULT_TARGET_GROUPS.items():
        src = "fred" if group == FRED_TARGET_GROUP else "yfinance"
        for sym, label in items:
            out.append((sym, label, src))
    return out


# (symbol, label, source) — "flattened" view of DEFAULT_TARGET_GROUPS, for any
# code that doesn't need the grouping (resolving a symbol's source, etc.)
DEFAULT_TARGET_CHOICES = _flatten_target_choices()

# "Large" universe automatically used to build features (no more manual ticker
# selection): union of everything available above, both yfinance and FRED side.
# The chosen target is removed from it when building the config (see
# webapp/forms.py) to avoid a ticker predicting itself.
DEFAULT_UNIVERSE_YF_TICKERS = [s for s, _, src in DEFAULT_TARGET_CHOICES if src == "yfinance"]
DEFAULT_UNIVERSE_FRED_SERIES = {label: s for s, label, src in DEFAULT_TARGET_CHOICES if src == "fred"}
