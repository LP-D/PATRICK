"""Fragments et téléchargements de la fiche d'un actif (B6 : sortis de `webapp/app.py`, sans changement de comportement).

Export Excel (A25), volatilité prévue (A1, D8), valorisation (A8), carte de chaleur de l'AUC regroupée (D10), frise des champions (D26).
Les signaux d'un actif et des classes restent dans `app.py` : ils partagent ses vues de prédictions.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from patrick.core.clock import utc_today
from patrick.tracking import db as trackdb
from patrick.webapp import forms, market_data

_VALUATION_CACHE: dict[str, tuple[float, dict]] = {}
_VALUATION_TTL_S = 6 * 3600


def register(app: FastAPI, templates, i18n_context) -> None:
    @app.get("/api/export/patrick.xlsx")
    def export_xlsx():
        """Classeur Excel (A25) : dernières prédictions des champions, champions, fonds. Lecture seule."""
        from patrick.fund import service
        from patrick.webapp import excel_export
        conn = trackdb.connect()
        try:
            data = excel_export.workbook_bytes(conn, service.current_date())
        finally:
            conn.close()
        name = f"patrick-{utc_today().isoformat()}.xlsx"
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


    @app.get("/fragments/vol-forecast/{symbol}")
    def vol_forecast_fragment(request: Request, symbol: str):
        """Volatilité prévue d'un actif (A1, D8) : HAR-RV du lendemain contre la volatilité glissante, jugés en QLIKE. Une TAILLE de position,
        jamais une direction : affichée à part des signaux."""
        import pandas as pd

        from patrick.fund import vol_forecast
        source = forms.TARGET_SOURCE_BY_SYMBOL.get(symbol)
        if source is None:
            raise HTTPException(status_code=404, detail="Cible inconnue")
        hist = market_data.price_history(symbol, source, "5y")
        out = None
        if hist.get("closes"):
            df = pd.DataFrame({"close": hist["closes"]}, index=pd.to_datetime(hist["dates"]))
            for key, col in (("opens", "open"), ("highs", "high"), ("lows", "low")):
                if hist.get(key) and len(hist[key]) == len(df):
                    df[col] = pd.to_numeric(pd.Series(hist[key], index=df.index), errors="coerce")
            forecast = vol_forecast.har_sigma(df)
            if forecast:
                out = {**forecast, "eval": vol_forecast.evaluate(df), "ohlc": {"open", "high", "low"}.issubset(df.columns)}
                index = vol_forecast.IMPLIED_INDEX.get(symbol)
                if index:                                   # FO24 : la volatilité implicite du marché d'options à côté de la prévision
                    implied_hist = market_data.price_history(index, "yfinance", "1mo")
                    closes = implied_hist.get("closes") or []
                    out["implied"] = vol_forecast.implied_vs_forecast(symbol, forecast.get("sigma"), closes[-1] if closes else None)
        return templates.TemplateResponse(request, "_vol_forecast.html", {**i18n_context(request), "vf": out})




    @app.get("/fragments/valuation/{symbol}")
    def valuation_fragment(request: Request, symbol: str, g: float = 0.05):
        """Valorisation d'une action (A8) : multiples, DCF inversé (croissance que le prix suppose) et DCF à hypothèse explicite `g`
        (croissance annuelle du FCF sur 10 ans, bornée à [-20 % ; 30 %]) avec sa table de sensibilité. Données yfinance gardées 6 h."""
        import time as _time

        from patrick.analysis import valuation
        if forms.TARGET_SOURCE_BY_SYMBOL.get(symbol) != "yfinance":
            raise HTTPException(status_code=404, detail="Cible inconnue")
        g = min(max(g, -0.20), 0.30)
        now = _time.monotonic()
        cached = _VALUATION_CACHE.get(symbol)
        if cached is None or now - cached[0] > _VALUATION_TTL_S:
            info = valuation.load_info(symbol)
            try:
                rf = valuation.risk_free(info.get("currency"))
            except Exception:  # noqa: BLE001 -- frontière fournisseur : le taux sans risque par défaut prend le relais
                rf = None
            cached = (now, {"info": info, "rf": rf})
            _VALUATION_CACHE[symbol] = cached
        data = cached[1]
        out = valuation.analyse(data["info"], rf=data["rf"], growth=g) if data["info"] else None
        return templates.TemplateResponse(request, "_valuation.html", {**i18n_context(request), "val": out, "symbol": symbol, "g": g})


    @app.get("/fragments/pooled-heatmap")
    def pooled_heatmap_fragment(request: Request):
        """Carte de chaleur cible x horizon de l'AUC regroupée (D10), sur la Synthèse : où est le signal, en un coup d'oeil."""
        from patrick.tracking import pooled_signal
        conn = trackdb.connect()
        try:
            grid = pooled_signal.heatmap(pooled_signal.load(conn))
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_pooled_heatmap.html", {**i18n_context(request), "grid": grid})


    @app.get("/fragments/model-set/{symbol}")
    def model_set_fragment(request: Request, symbol: str):
        """FO1/FO2 (25/11) : ensemble de confiance de modèles (MCS) et test SPA de chaque horizon à champion de l'actif."""
        from patrick.validation import model_set
        if symbol not in forms.TARGET_SOURCE_BY_SYMBOL:
            raise HTTPException(status_code=404, detail="Cible inconnue")
        conn = trackdb.connect()
        try:
            horizons = [h for (h,) in conn.execute("SELECT horizon FROM champion WHERE target = ? ORDER BY horizon", (symbol,))]
            results = [model_set.evaluate(conn, symbol, h, reps=500) for h in horizons]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_model_set.html", {**i18n_context(request), "results": results})

    @app.get("/fragments/champion-history/{symbol}")
    def champion_history_fragment(request: Request, symbol: str):
        """Frise des champions d'un actif (D26) : qui a tenu le titre à chaque horizon, de quand à quand. Chargé après l'affichage."""
        from patrick.tracking import champion_history
        if symbol not in forms.TARGET_SOURCE_BY_SYMBOL:
            raise HTTPException(status_code=404, detail="Cible inconnue")
        conn = trackdb.connect()
        try:
            by_horizon = champion_history.history(conn, symbol)
            from patrick.tracking import retrain_diff
            diffs = {h: retrain_diff.diff(conn, symbol, int(h)) for h in by_horizon}
        finally:
            conn.close()
        longest = max((r["days"] or 0 for reigns in by_horizon.values() for r in reigns), default=0)
        return templates.TemplateResponse(request, "_champion_history.html",
                                          {**i18n_context(request), "by_horizon": by_horizon, "longest": max(longest, 1), "diffs": diffs})
