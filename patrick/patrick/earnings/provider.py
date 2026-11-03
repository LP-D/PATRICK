"""Accès aux données gratuites : Yahoo Finance (via yfinance) et la bibliothèque de facteurs de Kenneth French.

Une seule classe, `YahooProvider`, que tout le reste reçoit en argument : les tests passent un faux fournisseur, le réseau
n'est jamais touché hors de ce fichier. Une défaillance réseau ne lève jamais : la méthode renvoie `None` / liste vide et
l'erreur est gardée dans `self.errors` (une série qui manque ne doit pas faire perdre les autres, même règle que
`data/sources/yfinance_source`). Les prix passent par `LocalCache` (écriture atomique, 1 jour de fraîcheur) pour qu'un second
clic ne retélécharge rien.

Ce que Yahoo donne gratuitement, vérifié le 2026-11-03 : dates d'annonce horodatées (heure de New York) avec EPS estimé, publié
et surprise ; estimations et révisions du consensus (instantané du jour seulement) ; historique DATÉ des changements de
recommandation ; cibles de cours (instantané) ; chaîne d'options (instantané) ; part vendue à découvert (instantané).
Ce qu'il ne donne pas : options historiques, transcriptions, consensus daté, guidance, chiffre d'affaires publié vs estimé.
"""
from __future__ import annotations

import io
import time
import urllib.request
import zipfile
from datetime import date

import numpy as np
import pandas as pd

from patrick.cache_manager import LocalCache

FRENCH_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{name}"
FRENCH_FILES = {
    "US": ("F-F_Research_Data_Factors_daily_CSV.zip", "F-F_Momentum_Factor_daily_CSV.zip"),
    "EU": ("Europe_3_Factors_Daily_CSV.zip", "Europe_MOM_Factor_Daily_CSV.zip"),
    "JP": ("Japan_3_Factors_Daily_CSV.zip", "Japan_MOM_Factor_Daily_CSV.zip"),
}
INFO_FIELDS = ("longName", "shortName", "sector", "industry", "country", "exchange", "currency", "quoteType", "marketCap", "beta",
               "sharesOutstanding", "floatShares", "lastFiscalYearEnd", "mostRecentQuarter", "firstTradeDateMilliseconds",
               "shortPercentOfFloat", "sharesShort", "sharesShortPriorMonth", "dateShortInterest", "priceToBook", "trailingPE",
               "forwardPE", "returnOnEquity", "averageVolume", "heldPercentInstitutions")


def _clean(symbol: str) -> str:
    return symbol.replace("^", "IDX_").replace("-", "_").replace("=", "_").replace(".", "_")


def parse_french_csv(text: str) -> pd.DataFrame:
    """CSV de la bibliothèque French : lignes `AAAAMMJJ, a, b, c, rf` en POURCENT, entourées d'en-têtes et de pieds de page.
    Renvoie un DataFrame en décimales (1 % = 0.01) indexé par date, colonnes nettoyées (`Mkt-RF` -> `Mkt_RF`)."""
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if cells and len(cells[0]) == 8 and cells[0].isdigit() and len(cells) > 1:
            rows.append(cells)
        elif rows:
            break                                   # fin du bloc quotidien (le fichier enchaîne parfois d'autres tableaux)
        elif len(cells) > 1 and not cells[0].isdigit():
            header = [c.replace("-", "_").replace(" ", "") or f"c{i}" for i, c in enumerate(cells)]
    if not rows:
        return pd.DataFrame()
    width = len(rows[0])
    names = (header or [])[:]
    if len(names) == width - 1:
        names = ["date", *names]
    elif len(names) != width:
        names = ["date", *[f"c{i}" for i in range(1, width)]]
    names[0] = "date"
    frame = pd.DataFrame(rows, columns=names)
    frame.index = pd.to_datetime(frame.pop("date"), format="%Y%m%d")
    out = frame.apply(pd.to_numeric, errors="coerce") / 100.0
    return out.replace([-0.9999, -0.99], np.nan)    # valeurs manquantes codées -99.99 / -999 dans les fichiers


class YahooProvider:
    def __init__(self, cache: LocalCache | None = None):
        self.cache = cache or LocalCache()
        self.errors: list[str] = []

    # -------------------------------------------------------------------------------------------------------- utilitaires
    def _note(self, what: str, exc: Exception) -> None:
        self.errors.append(f"{what} : {type(exc).__name__}: {str(exc)[:120]}")

    def _try(self, what: str, fn, retries: int = 2):
        for attempt in range(retries):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 -- frontière fournisseur : yfinance lève des erreurs de toute nature
                if attempt == retries - 1:
                    self._note(what, exc)
                else:
                    time.sleep(0.8 * (attempt + 1))
        return None

    # ------------------------------------------------------------------------------------------------------------- prix
    def ohlcv(self, symbol: str, start: str = "2005-01-01", max_age_days: int = 1) -> pd.DataFrame | None:
        """Open, High, Low, Close (ajustés des splits ET dividendes), Volume, Dividends, Stock Splits ; index = jours, sans fuseau."""
        key = f"earn_ohlcv_{_clean(symbol)}_{start}"
        cached = self.cache.load_dataframe(key, max_age_days=max_age_days)
        if cached is not None and len(cached):
            return cached

        def fetch():
            import yfinance as yf
            df = yf.Ticker(symbol).history(start=start, auto_adjust=True, actions=True)
            if df is None or df.empty:
                return None
            idx = pd.DatetimeIndex(df.index)
            df.index = (idx.tz_localize(None) if idx.tz is None else idx.tz_convert(idx.tz).tz_localize(None)).normalize()
            df = df[~df.index.duplicated(keep="last")]
            keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits") if c in df.columns]
            return df[keep].astype(float)

        df = self._try(f"prix {symbol}", fetch)
        if df is None or df.empty:
            return cached
        try:
            self.cache.save_dataframe(key, df, max_age_days=max_age_days)
        except Exception as exc:  # noqa: BLE001 -- le cache est un confort : sans lui, on sert quand même les prix
            self._note(f"cache {symbol}", exc)
        return df

    # ------------------------------------------------------------------------------------------------------- annonces
    def calendar(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """Annonces passées et à venir : colonnes `ts` (horodatage tz-aware, New York), `eps_estimate`, `eps_actual`, `surprise_pct`."""
        def fetch():
            import yfinance as yf
            return yf.Ticker(symbol).get_earnings_dates(limit=limit)

        raw = self._try(f"annonces {symbol}", fetch)
        if raw is None or len(raw) == 0:
            return pd.DataFrame(columns=["ts", "eps_estimate", "eps_actual", "surprise_pct"])
        out = pd.DataFrame({
            "ts": pd.DatetimeIndex(raw.index),
            "eps_estimate": pd.to_numeric(raw.get("EPS Estimate"), errors="coerce").to_numpy(),
            "eps_actual": pd.to_numeric(raw.get("Reported EPS"), errors="coerce").to_numpy(),
            "surprise_pct": pd.to_numeric(raw.get("Surprise(%)"), errors="coerce").to_numpy(),
        })
        return out.sort_values("ts").reset_index(drop=True)

    def info(self, symbol: str) -> dict:
        def fetch():
            import yfinance as yf
            raw = yf.Ticker(symbol).info
            return {k: raw.get(k) for k in INFO_FIELDS if raw.get(k) is not None}

        return self._try(f"fiche {symbol}", fetch) or {}

    def search(self, query: str, n: int = 8) -> list[dict]:
        def fetch():
            import yfinance as yf
            return yf.Search(query, max_results=n).quotes

        raw = self._try(f"recherche {query}", fetch) or []
        return [{"symbol": q.get("symbol"), "name": q.get("longname") or q.get("shortname") or "",
                 "exchange": q.get("exchDisp") or q.get("exchange") or "", "type": q.get("quoteType") or "",
                 "sector": q.get("sector") or ""} for q in raw if q.get("symbol")]

    # --------------------------------------------------------------------------------------------- analystes (instantanés)
    def consensus(self, symbol: str) -> dict:
        """Consensus du jour : estimations BPA/CA, révisions (7/30/60/90 j), recommandations, cibles de cours. Sans historique."""
        def frame(name):
            def fetch():
                import yfinance as yf
                df = getattr(yf.Ticker(symbol), name)
                if df is None or (hasattr(df, "empty") and df.empty):
                    return None
                return df.reset_index().to_dict("records") if hasattr(df, "reset_index") else df
            return self._try(f"{name} {symbol}", fetch, retries=1)

        return {name: frame(name) for name in
                ("earnings_estimate", "eps_revisions", "eps_trend", "revenue_estimate", "recommendations", "analyst_price_targets")}

    def upgrades(self, symbol: str) -> pd.DataFrame:
        """Changements de recommandation DATÉS (la seule série analyste historique et gratuite), du plus ancien au plus récent."""
        key = f"earn_upg_{_clean(symbol)}"
        cached = self.cache.load_dataframe(key, max_age_days=1)
        if cached is not None:
            return cached

        def fetch():
            import yfinance as yf
            df = yf.Ticker(symbol).upgrades_downgrades
            if df is None or df.empty:
                return None
            df = df.copy()
            idx = pd.DatetimeIndex(df.index)
            df.index = idx.tz_localize(None) if idx.tz is None else idx.tz_convert("UTC").tz_localize(None)
            return df.sort_index()

        df = self._try(f"recommandations {symbol}", fetch, retries=1)
        if df is None:
            return pd.DataFrame()
        try:
            self.cache.save_dataframe(key, df, max_age_days=1)
        except Exception as exc:  # noqa: BLE001
            self._note(f"cache {symbol}", exc)
        return df

    def straddle(self, symbol: str, on_or_after: date | str) -> dict | None:
        """Straddle ATM (call + put au strike le plus proche du cours) de la première échéance à partir de `on_or_after`,
        rapporté au cours. Instantané : il INCLUT les jours entre l'annonce et l'échéance, donc surestime le mouvement attendu."""
        def fetch():
            import yfinance as yf
            t = yf.Ticker(symbol)
            target = pd.Timestamp(on_or_after)
            expiries = [e for e in (t.options or ()) if pd.Timestamp(e) >= target]
            if not expiries:
                return None
            hist = t.history(period="5d")
            spot = float(hist["Close"].iloc[-1])
            chain = t.option_chain(expiries[0])
            calls, puts = chain.calls, chain.puts
            strike = float(calls.iloc[(calls["strike"] - spot).abs().argmin()]["strike"])

            def price(df):
                row = df[df["strike"] == strike]
                if row.empty:
                    return np.nan
                row = row.iloc[0]
                bid, ask = float(row.get("bid", 0) or 0), float(row.get("ask", 0) or 0)
                return (bid + ask) / 2 if bid > 0 and ask > 0 else float(row.get("lastPrice", np.nan))

            call, put = price(calls), price(puts)
            if not np.isfinite(call + put):
                return None
            return {"expiry": expiries[0], "strike": strike, "spot": spot, "call": call, "put": put,
                    "straddle_pct": (call + put) / spot, "days_to_expiry": int((pd.Timestamp(expiries[0]) - pd.Timestamp.today().normalize()).days)}

        return self._try(f"options {symbol}", fetch, retries=1)

    # ----------------------------------------------------------------------------------------------------------- facteurs
    def factors(self, region: str, max_age_days: int = 7) -> pd.DataFrame | None:
        """Facteurs journaliers (Mkt_RF, SMB, HML, RF, MOM) en décimales pour US / EU / JP. Publiés avec 1 à 2 mois de retard."""
        if region not in FRENCH_FILES:
            return None
        key = f"earn_ff_{region}"
        cached = self.cache.load_dataframe(key, max_age_days=max_age_days)
        if cached is not None and len(cached):
            return cached

        def get(name: str) -> pd.DataFrame:
            req = urllib.request.Request(FRENCH_URL.format(name=name), headers={"User-Agent": "Mozilla/5.0 PATRICK"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                payload = resp.read()
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                return parse_french_csv(zf.read(zf.namelist()[0]).decode("latin-1"))

        def fetch():
            base_name, mom_name = FRENCH_FILES[region]
            base = get(base_name)
            try:
                mom = get(mom_name)
                mom.columns = ["MOM"] + list(mom.columns[1:])
                base = base.join(mom[["MOM"]], how="left")
            except Exception as exc:  # noqa: BLE001 -- sans momentum, le modèle à facteurs se réduit à 3 facteurs
                self._note(f"facteur momentum {region}", exc)
            return base

        df = self._try(f"facteurs {region}", fetch, retries=1)
        if df is None or df.empty:
            return cached
        try:
            self.cache.save_dataframe(key, df, max_age_days=max_age_days)
        except Exception as exc:  # noqa: BLE001
            self._note(f"cache facteurs {region}", exc)
        return df
