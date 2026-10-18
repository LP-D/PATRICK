"""Chaînes FR/EN de la section Black-Litterman de `/portfolio` et de la page `/news` (analyse textuelle). Fusionnées dans
`i18n.STRINGS` ; `TEXT_JS_KEYS` complète `i18n.js_strings` (lues côté navigateur par `static/news.js`)."""
from __future__ import annotations

from patrick.webapp.glossary_text import LABEL_STRINGS


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


TEXT_STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ /portfolio : Black-Litterman
    "pf_bl_title": _s("Black-Litterman (probabilités calibrées)", "Black-Litterman (calibrated probabilities)"),
    "pf_bl_term": _s("Black-Litterman", "Black-Litterman"),
    "pf_bl_sub": _s(
        "Déplace le portefeuille de référence HRP vers les actifs dont le modèle annonce une hausse (ou une baisse) nette ; "
        "seules les probabilités calibrées servent de vues.",
        "Shifts the HRP reference portfolio toward the assets the model clearly expects to rise (or fall); only calibrated "
        "probabilities are used as views."),
    "pf_bl_horizon": _s("Horizon", "Horizon"),
    "pf_bl_days": _s("{h} j", "{h} d"),
    "pf_bl_empty": _s("Aucune probabilité de hausse calibrée et récente à cet horizon.",
                      "No recent calibrated probability of a rise at this horizon."),
    "pf_bl_empty_hint": _s(
        "Lance un run avec la calibration activée puis la prédiction du jour. Une probabilité non calibrée n'est pas utilisée.",
        "Launch a run with calibration enabled, then the daily prediction. An uncalibrated probability is not used."),
    "pf_bl_no_prices": _s("Historique de prix insuffisant en cache local pour estimer la covariance.",
                          "Not enough price history in the local cache to estimate the covariance."),
    "pf_bl_col_ref": _s("Poids de référence", "Reference weight"),
    "pf_bl_col_bl": _s("Poids Black-Litterman", "Black-Litterman weight"),
    "pf_bl_col_tilt": _s("Écart (pts)", "Shift (pts)"),
    "pf_bl_col_p": _s("Probabilité de hausse", "Probability of a rise"),
    "pf_bl_col_view": _s("Rendement visé (an)", "Target return (yr)"),
    "pf_bl_col_conf": _s("Confiance", "Confidence"),
    "pf_bl_footer": _s(
        "{n} actif(s), {v} vue(s) nette(s) sur {p} probabilité(s) calibrée(s) ; covariance Ledoit-Wolf sur {o} rendements communs ; "
        "prix au {d}.",
        "{n} asset(s), {v} decisive view(s) out of {p} calibrated probabilit(ies); Ledoit-Wolf covariance over {o} common returns; "
        "prices as of {d}."),
    "pf_bl_caveat": _s(
        "Le portefeuille n'a pas été comparé à la référence hors échantillon : c'est une lecture, pas une preuve de supériorité.",
        "The portfolio has not been compared with the reference out of sample: it is a reading, not proof of superiority."),

    # ------------------------------------------------------------------ navigation et page /news
    "nav_news": _s("News", "News"),
    "news_title": _s("News et sentiment", "News and sentiment"),
    "news_sub": _s(
        "Flux de nouvelles horodaté point-in-time, noté par dictionnaire, rattaché aux actifs suivis.",
        "Point-in-time news feed, scored by dictionary, linked to the tracked assets."),
    "news_refresh": _s("Actualiser", "Refresh"),
    "news_refreshing": _s("Collecte en cours…", "Collecting…"),
    "news_refresh_done": _s("{added} nouvelle(s) ajoutée(s), {scored} notée(s).", "{added} new item(s) added, {scored} scored."),
    "news_refresh_errors": _s("Sources en échec : {names}", "Sources that failed: {names}"),
    "news_refresh_failed": _s("La collecte a échoué : {e}", "Collection failed: {e}"),
    "news_k_total": _s("Nouvelles en base", "Stored stories"),
    "news_k_total_rel": _s("{n} depuis 24 h ; {s} anciennes écartées", "{n} in the last 24 h; {s} stale ones set aside"),
    "news_k_linked": _s("Rattachées à un actif", "Linked to an asset"),
    "news_k_linked_rel": _s("{n} actif(s) concerné(s)", "{n} asset(s) concerned"),
    "news_k_sources": _s("Sources", "Sources"),
    "news_k_sources_rel": _s("{n} flux différent(s) en base", "{n} distinct feed(s) stored"),
    "news_k_last": _s("Dernière nouvelle connue", "Latest known story"),
    "news_k_last_none": _s("aucune", "none"),
    "news_window": _s("Fenêtre", "Window"),
    "news_win_1": _s("24 h", "24 h"),
    "news_win_7": _s("7 jours", "7 days"),
    "news_win_30": _s("30 jours", "30 days"),
    "news_assets_title": _s("Sentiment par actif", "Sentiment by asset"),
    "news_assets_empty": _s("Aucune nouvelle rattachée à un actif sur cette fenêtre.",
                            "No story linked to an asset in this window."),
    "news_assets_empty_hint": _s("Lance « Actualiser » pour collecter les flux.", "Press \"Refresh\" to collect the feeds."),
    "news_col_asset": _s("Actif", "Asset"),
    "news_col_n": _s("Nouvelles", "Stories"),
    "news_col_scored": _s("Notées", "Scored"),
    "news_col_mean": _s("Note moyenne", "Mean score"),
    "news_col_pos": _s("Part positive", "Positive share"),
    "news_col_nov": _s("Nouveauté moy.", "Mean novelty"),
    "news_col_last": _s("Dernière", "Latest"),
    "news_feed_title": _s("Flux", "Feed"),
    "news_feed_filter": _s("Actif : {s}", "Asset: {s}"),
    "news_feed_all": _s("Tout afficher", "Show all"),
    "news_feed_empty": _s("Aucune nouvelle.", "No story."),
    "news_col_time": _s("Connue à", "Known at"),
    "news_col_title": _s("Titre", "Headline"),
    "news_col_source": _s("Source", "Source"),
    "news_col_score": _s("Note", "Score"),
    "news_col_tone": _s("Ton", "Tone"),
    "news_col_novelty": _s("Nouveauté", "Novelty"),
    "news_col_events": _s("Événements", "Events"),
    "news_col_assets": _s("Actifs", "Assets"),
    "news_ev_supply_shock": _s("choc d'offre", "supply shock"),
    "news_ev_sanction": _s("sanction", "sanction"),
    "news_ev_strike": _s("grève", "strike"),
    "news_ev_weather": _s("météo", "weather"),
    "news_es_title": _s("Réaction des prix aux nouvelles fortes", "Price reaction to strong stories"),
    "news_es_button": _s("Mesurer la réaction", "Measure the reaction"),
    "news_es_need_symbol": _s("Choisis un actif dans le tableau pour mesurer la réaction de son prix.",
                              "Pick an asset in the table to measure its price reaction."),
    "news_es_no_prices": _s("Prix de {s} absents du cache local : l'étude ne télécharge rien.",
                            "No cached prices for {s}: the study downloads nothing."),
    "news_es_too_few": _s(
        "Seulement {n} nouvelle(s) forte(s) et nouvelle(s) pour {s} (minimum {m}). Le flux s'accumule au fil des collectes ; "
        "GDELT permet de remonter plus loin.",
        "Only {n} strong, new stor(ies) for {s} (minimum {m}). The feed accumulates with each collection; GDELT can go further back."),
    "news_es_group_positive": _s("Nouvelles positives", "Positive stories"),
    "news_es_group_negative": _s("Nouvelles négatives", "Negative stories"),
    "news_es_n": _s("{n} événement(s)", "{n} event(s)"),
    "news_es_caar": _s("Rendement anormal cumulé [0, +1]", "Cumulative abnormal return [0, +1]"),
    "news_es_p": _s("p (BMP)", "p (BMP)"),
    "news_es_warn_few": _s("Moins de 30 événements : lecture indicative seulement.", "Fewer than 30 events: indicative only."),
    "news_es_warn_overlap": _s("{n} paires d'événements se chevauchent : les tests surestiment la significativité.",
                               "{n} event pairs overlap: the tests overstate significance."),
    "news_central_title": _s("Banques centrales", "Central banks"),
    "news_central_empty": _s("Aucun communiqué ni discours de banque centrale collecté.",
                             "No central bank statement or speech collected."),
    "news_method_title": _s("Méthode et limites", "Method and limits"),
    "news_method": _s(
        "Une nouvelle compte à partir de la plus tardive de sa publication annoncée et de la première fois que PATRICK l'a vue ; "
        "après la clôture, elle compte pour la séance suivante. Les notes viennent d'un lexique réduit (anglais, français) : un "
        "fichier Loughran-McDonald complet se branche par le réglage news_lm_dictionary. Le rattachement aux actifs privilégie la "
        "précision (casse respectée) ; un lien manqué est préféré à un faux lien. Aucune variable de ce flux n'entre dans les "
        "entraînements tant qu'un historique suffisant n'est pas constitué.",
        "A story counts from the later of its announced publication and the first time PATRICK saw it; after the close it counts for "
        "the next session. Scores come from a reduced lexicon (English, French): a full Loughran-McDonald file plugs in through the "
        "news_lm_dictionary setting. Linking to assets favours precision (case respected); a missed link is preferred to a false "
        "one. No variable from this feed enters training until enough history has accumulated."),
}

TEXT_STRINGS.update(LABEL_STRINGS)

TEXT_JS_KEYS: list[str] = ["news_refreshing", "news_refresh_done", "news_refresh_errors", "news_refresh_failed", "news_refresh"]
