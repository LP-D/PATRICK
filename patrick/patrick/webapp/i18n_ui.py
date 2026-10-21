"""Chaînes FR/EN de l'audit d'interface du 2026-10-21 : libellés qui étaient écrits en français dans les gabarits, les scripts ou les
tables Python (modèles de volatilité, fenêtres, statuts de fraîcheur, libellés de glossaire…). Fusionnées dans `i18n.STRINGS` ;
`UI_JS_KEYS` complète `i18n.js_strings` (lues par les scripts via `window.I18N`)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


UI_STRINGS: dict[str, dict[str, str]] = {
    # --- gabarits
    "day_suffix": _s("j", "d"),
    "dt_empty": _s("Aucune donnée.", "No data."),
    "sparkline_aria": _s("tendance", "trend"),
    "pred_live_reliability": _s("Fiabilité live", "Live reliability"),
    "fr_days_late": _s("{n} j de retard", "{n} d late"),
    "fr_never_cached": _s("jamais mis en cache", "never cached"),
    "acct_kind_PEA": _s("PEA", "PEA"),
    "acct_kind_CTO": _s("CTO", "Taxable brokerage (CTO)"),
    "acct_kind_AV": _s("Assurance-vie", "Life insurance"),
    "acct_kind_LIVRET": _s("Livret", "Savings account"),
    "acct_kind_DAT": _s("Dépôt à terme", "Term deposit"),
    "acct_kind_AUTRE": _s("Autre", "Other"),
    "gl_label_regime": _s("Régime de marché", "Market regime"),
    "gl_label_universe": _s("Univers de données", "Data universe"),
    "tg_ci90": _s("IC 90 %", "90% CI"),
    "tg_not_computable": _s("non calculable", "not computable"),
    # --- modèles de volatilité et fenêtres du formulaire de lancement (anciennes tables Python en français)
    "volm_egarch": _s("EGARCH (vol. conditionnelle)", "EGARCH (conditional vol.)"),
    "volm_kalman": _s("Filtre de Kalman (niveau filtré)", "Kalman filter (filtered level)"),
    "volm_hmm": _s("HMM (proba. de régime stress)", "HMM (stress-regime probability)"),
    "volm_heston_proxy": _s("Proxy Heston (mean-reversion vol.)", "Heston proxy (vol. mean reversion)"),
    "volm_vrp_proxy": _s("Proxy VRP (prime de risque de variance)", "VRP proxy (variance risk premium)"),
    "volm_ar": _s("AR (autorégressif)", "AR (autoregressive)"),
    "volm_ma": _s("MA (moyenne mobile)", "MA (moving average)"),
    "volm_arma": _s("ARMA", "ARMA"),
    "volm_arima": _s("ARIMA", "ARIMA"),
    "tl_returns_windows": _s("Fenêtres de rendements", "Returns lookbacks"),
    "tl_zscore_windows": _s("Fenêtres de z-score", "Z-score lookbacks"),
    "tl_ma_ratio_windows": _s("Fenêtres de moyenne mobile", "Moving-average lookbacks"),
    "tl_rolling_vol_windows": _s("Fenêtres de volatilité (glissante)", "Rolling volatility lookbacks"),
    "tl_ohlc_vol_windows": _s("Fenêtres de volatilité OHLC", "OHLC volatility lookbacks"),
    # --- scripts : messages de la page Patrimoine, de l'état du marché et de la dérive des variables
    "js_summary_unavailable": _s("Résumé indisponible.", "Summary unavailable."),
    "js_drift_stable": _s("stable", "stable"),
    "js_drift_attention": _s("attention", "watch"),
    "js_drift_significant": _s("dérive", "drift"),
    "js_drift_footer": _s(
        "PSI < 0,10 stable · 0,10–0,25 attention · > 0,25 dérive significative. Mesure enregistrée : le badge de la page Prédictions est à jour.",
        "PSI < 0.10 stable · 0.10–0.25 watch · > 0.25 significant drift. Measurement saved: the Predictions page badge is up to date."),
    "js_ms_market": _s("Marché", "Market"),
    "js_ms_regime": _s("Régime", "Regime"),
    "js_ms_pstress": _s("P(stress)", "P(stress)"),
    "js_ms_calm": _s("calme", "calm"),
    "js_ms_stressed": _s("stress", "stress"),
    "js_ms_insufficient": _s("historique insuffisant", "insufficient history"),
    "js_ms_row_unavailable": _s("indisponible : {error}", "unavailable: {error}"),
    "js_ms_sess": _s("s.", "sess."),
    "js_ms_since": _s("Depuis", "Since"),
    "js_ms_stress": _s("Stress (63 s.)", "Stress (63 sess.)"),
    "js_ms_vol21": _s("Vol. 21 s.", "Vol. 21 sess."),
    "js_ms_vol_long": _s("Vol. long terme", "Long-term vol."),
    "js_ms_vol_states": _s("Vol. état calme / stress", "Vol. calm / stress state"),
    "js_ms_updated": _s("Mis à jour : {at} · dernière séance par marché : {sessions}", "Updated: {at} · last session per market: {sessions}"),
    "js_ms_computing": _s("Calcul de l'état du marché (HMM) en cours…", "Computing the market state (HMM)…"),
    "js_ms_unavailable": _s("État du marché indisponible : {error}", "Market state unavailable: {error}"),
    "js_w_kind_buy": _s("Achat", "Buy"),
    "js_w_kind_sell": _s("Vente", "Sale"),
    "js_w_kind_dividend": _s("Dividende", "Dividend"),
    "js_w_kind_deposit": _s("Versement", "Deposit"),
    "js_w_kind_withdrawal": _s("Retrait", "Withdrawal"),
    "js_w_kind_fee": _s("Frais", "Fees"),
    "js_w_kind_interest": _s("Intérêts / bonus", "Interest / bonus"),
    "js_w_kind_term_deposit": _s("Dépôt à terme", "Term deposit"),
    "js_w_skipped": _s("{n} ligne(s) écartée(s) : virements internes, doublons déjà enregistrés ou lignes ignorées.",
                        "{n} row(s) skipped: internal transfers, duplicates already saved or ignored rows."),
    "js_w_col_date": _s("Date", "Date"),
    "js_w_col_type": _s("Type", "Type"),
    "js_w_col_asset": _s("Actif", "Asset"),
    "js_w_col_qty": _s("Qté", "Qty"),
    "js_w_col_amount": _s("Montant", "Amount"),
    "js_w_col_account": _s("Compte", "Account"),
    "js_w_col_status": _s("Statut", "Status"),
    "js_w_line": _s("ligne {n} : {msg}", "row {n}: {msg}"),
    "js_w_chart_aria": _s("Valeur du compte du {from} au {to} : de {a} à {b}.", "Account value from {from} to {to}: from {a} to {b}."),
    "js_w_to_save": _s("à enregistrer", "to save"),
}

UI_JS_KEYS: tuple[str, ...] = (*(k for k in UI_STRINGS if k.startswith("js_")), "day_suffix")
