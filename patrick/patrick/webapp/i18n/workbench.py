"""Chaînes FR/EN des outils de travail ajoutés le 2026-11-19 : vue « Par horizon » de /predictions (avantage live), recherche d'actifs
dans la palette de commandes, page « Écrans côte à côte ». Fusionnées dans `i18n.STRINGS` ; `WORKBENCH_JS_KEYS` complète `i18n.js_strings`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


WORKBENCH_STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ /predictions : vue « Par horizon »
    "pv_tabs_label": _s("Vue du tableau", "Table view"),
    "pv_tab_asset": _s("Un actif par ligne", "One asset per row"),
    "pv_tab_horizon": _s("Par horizon · avantage live", "By horizon · live edge"),
    "pv_horizon_hint": _s("Mêmes signaux, regroupés par horizon puis par classe, avec l'avantage mesuré sur les signaux déjà jugés.",
                          "Same signals, grouped by horizon then by class, with the edge measured on signals already judged."),
    "eh_scope": _s("Signaux live jugés", "Live signals judged"),
    "eh_scope_value": _s("{n} signaux · du {a} au {b}", "{n} signals · {a} to {b}"),
    "eh_excluded": _s("{n} barres reconstituées écartées : recalculées après coup, elles ne sont pas de vrais signaux live.",
                      "{n} reconstructed bars excluded: recomputed after the fact, they are not real live signals."),
    "eh_matrix_h": _s("Où les signaux live battent-ils le hasard ?", "Where do live signals beat chance?"),
    "eh_rules": _s(
        "Chaque case = le taux de réussite directionnel des signaux déjà jugés d'une classe à un horizon. Trois précautions : "
        "(1) seuls les vrais signaux live comptent, pas les barres reconstituées ; (2) les actifs d'une classe bougent ensemble le même jour, "
        "donc les réussites sont d'abord moyennées par date ; (3) deux signaux à h séances d'écart se recouvrent, donc le nombre "
        "d'observations indépendantes vaut environ jours ÷ horizon. « Avantage probable » exige : test unilatéral meilleur que 50 % "
        "après correction de Benjamini-Hochberg (10 %) sur toutes les cases, et une réussite au-dessus de la règle naïve « toujours le côté "
        "majoritaire ». Un actif isolé n'est jamais testé : sur plusieurs centaines, quelques-uns gagneraient au hasard.",
        "Each cell = the directional hit rate of the signals already judged for a class at a horizon. Three safeguards: "
        "(1) only real live signals count, not reconstructed bars; (2) assets of a class move together on the same day, "
        "so hits are averaged by date first; (3) two signals h sessions apart overlap, so independent observations are about "
        "days ÷ horizon. \"Probable edge\" requires: a one-sided test better than 50% after Benjamini-Hochberg correction (10%) "
        "across all cells, and a hit rate above the naive rule \"always the majority side\". A single asset is never tested: "
        "among several hundred, a few would win by chance."),
    "eh_matrix_foot": _s("Moins de {m} observations indépendantes : « Trop tôt », aucune conclusion. Les horizons longs mûrissent lentement.",
                         "Fewer than {m} independent observations: \"Too early\", no conclusion. Long horizons mature slowly."),
    "eh_col_class": _s("Classe d'actifs", "Asset class"),
    "eh_all": _s("Toutes classes", "All classes"),
    "eh_other": _s("Autres actifs", "Other assets"),
    "eh_v_edge": _s("Avantage probable", "Probable edge"),
    "eh_v_lean": _s("À confirmer", "To confirm"),
    "eh_v_none": _s("Pas d'avantage", "No edge"),
    "eh_v_below": _s("Sous le hasard", "Below chance"),
    "eh_v_early": _s("Trop tôt", "Too early"),
    "eh_pop_hit": _s("Réussite directionnelle", "Directional hit rate"),
    "eh_pop_ci": _s("intervalle à 95 %", "95% interval"),
    "eh_pop_naive": _s("Règle naïve (toujours le côté majoritaire)", "Naive rule (always the majority side)"),
    "eh_pop_sample": _s("Échantillon", "Sample"),
    "eh_pop_sample_v": _s("{n} signaux · {d} jours · ≈ {e} observations indépendantes",
                          "{n} signals · {d} days · ≈ {e} independent observations"),
    "eh_pop_p": _s("p (mieux que le hasard)", "p (better than chance)"),
    "eh_pop_need": _s("Il faut au moins {m} observations indépendantes pour conclure.", "At least {m} independent observations are needed to conclude."),
    "eh_horizon_title": _s("Horizon {h}", "Horizon {h}"),
    "eh_horizon_sub": _s("{n} signaux aujourd'hui", "{n} signals today"),
    "eh_class_line": _s("{p} % de réussite · ≈ {e} observations indépendantes", "{p}% hit rate · ≈ {e} independent observations"),
    "eh_col_signal": _s("Signal du jour", "Today's signal"),
    "eh_col_hit": _s("Réussite jugée", "Judged hit rate"),
    "eh_col_vs": _s("Face au hasard", "Versus chance"),
    "eh_above": _s("au-dessus", "above"),
    "eh_below": _s("en dessous", "below"),
    "eh_within": _s("indistinct", "indistinct"),
    "eh_not_judged": _s("pas encore jugé", "not judged yet"),
    "eh_empty": _s("Aucun signal live jugé pour l'instant.", "No live signal judged yet."),
    "eh_empty_hint": _s("Les signaux sont jugés une fois leur horizon écoulé ; ils apparaissent après la première actualisation des prédictions.",
                        "Signals are judged once their horizon has elapsed; they appear after the first predictions refresh."),

    # ------------------------------------------------------------------ Écrans côte à côte (/split)
    "nav_split": _s("Côte à côte", "Side by side"),
    "sp_title": _s("Écrans côte à côte", "Side-by-side screens"),
    "sp_layouts": _s("Disposition des volets", "Pane layout"),
    "sp_layout_s1": _s("Un seul volet", "Single pane"),
    "sp_layout_c2": _s("Deux colonnes", "Two columns"),
    "sp_layout_c3": _s("Trois colonnes", "Three columns"),
    "sp_layout_r2": _s("Deux lignes", "Two rows"),
    "sp_layout_g4": _s("Grille 2 × 2", "2 × 2 grid"),
    "sp_layout_l12": _s("Grand volet à gauche, deux à droite", "Large pane left, two on the right"),
    "sp_layout_t12": _s("Grand volet en haut, deux en bas", "Large pane on top, two below"),
    "sp_hint": _s("Glissez un séparateur pour redimensionner (double-clic : remise à zéro).",
                  "Drag a divider to resize (double-click: reset)."),
    "sp_copy": _s("Copier le lien de cette vue", "Copy this view's link"),
    "sp_copied": _s("Lien copié", "Link copied"),
    "sp_reset": _s("Réinitialiser", "Reset"),
    "sp_nested": _s("Cette page ne peut pas s'afficher dans un volet.", "This page cannot be shown inside a pane."),
    "sp_search_ph": _s("Page ou actif…", "Page or asset…"),
    "sp_open_path": _s("Ouvrir cette adresse", "Open this address"),
    "sp_empty": _s("Choisissez une page ou un actif à afficher ici.", "Choose a page or an asset to show here."),
    "sp_untitled": _s("Volet vide", "Empty pane"),
    "sp_reload": _s("Recharger", "Reload"),
    "sp_maximize": _s("Agrandir", "Maximise"),
    "sp_open_tab": _s("Ouvrir en pleine page", "Open full page"),
    "sp_close": _s("Vider ce volet", "Empty this pane"),
}

WORKBENCH_JS_KEYS: tuple[str, ...] = (
    "sp_copied", "sp_nested", "sp_search_ph", "sp_open_path", "sp_empty", "sp_untitled", "sp_reload", "sp_maximize", "sp_open_tab", "sp_close",
)
