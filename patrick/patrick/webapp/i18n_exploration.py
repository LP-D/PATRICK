"""Chaînes FR/EN des analyses de dépendance de la page Exploration (corrélation croisée préblanchie, Granger robuste et matrice « qui mène
qui », dépendance non linéaire, ratio de variance, corrélation partielle). Fusionné dans `i18n_models.MODELS_STRINGS` ; les clés `exp_*` qui
ne finissent pas par `_hint` partent au navigateur (`PAGE_JS_KEYS`). Les textes explicatifs sont écrits une fois ici et affichés derrière
un « ? » (`static/help.js`)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


EXPLORATION_STRINGS: dict[str, dict[str, str]] = {
    # --- onglet et corrélation partielle
    "exp_tab_dep": _s("Dépendance", "Dependence"),
    "exp_m_partial": _s("Partielle (sachant les autres)", "Partial (given the others)"),

    # --- ratio de variance (onglet Mémoire)
    "exp_vr_title": _s("Ratio de variance", "Variance ratio"),
    "exp_vr_hint": _s(
        "Si les rendements sont imprévisibles, la variance sur q périodes vaut q fois celle d'une période : le ratio vaut 1. Au-dessus de "
        "1, les mouvements se prolongent (momentum) ; en dessous, ils se corrigent (retour à la moyenne). Le z robuste (Lo-MacKinlay) tient "
        "compte d'une variance qui change dans le temps ; le test d'ensemble (Chow-Denning) évite de compter plusieurs fois la même chance "
        "d'un horizon à l'autre.",
        "If returns are unpredictable, the variance over q periods is q times that of one period: the ratio is 1. Above 1, moves tend to "
        "continue (momentum); below, they correct (mean reversion). The robust z (Lo-MacKinlay) allows for variance that changes over time; "
        "the joint test (Chow-Denning) avoids counting the same chance several times across horizons."),
    "exp_vr_horizon": _s("Horizon (périodes)", "Horizon (periods)"),
    "exp_vr_ratio": _s("Ratio", "Ratio"),
    "exp_vr_z": _s("z robuste", "Robust z"),
    "exp_vr_joint": _s("Test d'ensemble (p)", "Joint test (p)"),
    "exp_vr_v_random_walk": _s("marche aléatoire", "random walk"),
    "exp_vr_v_momentum": _s("les mouvements se prolongent", "moves tend to continue"),
    "exp_vr_v_mean_reversion": _s("les mouvements se corrigent", "moves tend to correct"),

    # --- corrélation croisée (onglet Lien)
    "exp_ccf_basis": _s("Série croisée", "Crossed series"),
    "exp_basis_returns": _s("Rendements", "Returns"),
    "exp_basis_diff": _s("Différences de niveau", "Level differences"),
    "exp_basis_abs": _s("Volatilité (|rendement|)", "Volatility (|return|)"),
    "exp_prewhiten": _s("Préblanchir", "Prewhiten"),
    "exp_rank": _s("Rangs (Spearman)", "Ranks (Spearman)"),
    "exp_ccf_b_leads": _s("{b} mène {a} (p {p})", "{b} leads {a} (p {p})"),
    "exp_ccf_a_leads": _s("{a} mène {b} (p {p})", "{a} leads {b} (p {p})"),
    "exp_ccf_ar": _s("Blanchiment AR : {a} p = {pa}, {b} p = {pb}", "AR prewhitening: {a} p = {pa}, {b} p = {pb}"),
    "exp_ccf_raw_warn": _s("Sans blanchiment, des séries persistantes affichent de fausses corrélations croisées.",
                           "Without prewhitening, persistent series show spurious cross-correlations."),

    # --- Granger sur un couple
    "exp_gr_order": _s("Ordre", "Order"),
    "exp_gr_p": _s("p robuste", "Robust p"),
    "exp_gr_gain": _s("Gain de variance", "Variance gain"),
    "exp_gr_bonf": _s("p Bonferroni", "Bonferroni p"),
    "exp_gr_nonstat": _s("Série non stationnaire : {s}. Granger suppose des séries stationnaires.",
                         "Non-stationary series: {s}. Granger assumes stationary series."),
    "exp_gr_on_abs": _s("Test sur la volatilité (|rendement|)", "Test on volatility (|return|)"),

    # --- dépendance non linéaire d'un couple (onglet Lien)
    "exp_depp_title": _s("Dépendance non linéaire par décalage", "Nonlinear dependence by lag"),
    "exp_depp_hint": _s(
        "Corrélation de distance et information mutuelle entre A(t) et B(t−k). Contrairement à la corrélation croisée, elles voient aussi "
        "les liens en U, les liens de volatilité et les effets de seuil. Ligne pointillée : seuil à 95 % d'une loi nulle obtenue en "
        "décalant circulairement une série (chaque série garde sa dynamique propre, grappes de volatilité comprises). Barres pleines : "
        "significatives après correction de Benjamini-Hochberg sur les décalages. Calculé sur les 1 500 dernières observations au plus.",
        "Distance correlation and mutual information between A(t) and B(t−k). Unlike cross-correlation they also see U-shaped links, "
        "volatility links and threshold effects. Dotted line: 95% threshold of a null law built by circularly shifting one series (each "
        "series keeps its own dynamics, volatility clustering included). Solid bars: significant after Benjamini-Hochberg correction "
        "across the lags. Computed on the last 1,500 observations at most."),
    "exp_dcor_title": _s("Corrélation de distance", "Distance correlation"),
    "exp_mi_title": _s("Information mutuelle (échelle de corrélation)", "Mutual information (correlation scale)"),
    "exp_depp_threshold": _s("Seuil à 95 %", "95% threshold"),
    "exp_depp_pearson": _s("|ρ| de Pearson, maximum sur ces décalages", "Pearson |ρ|, maximum over these lags"),
    "exp_depp_window": _s("Calculé sur les {n} dernières observations (sur {total})", "Computed on the last {n} observations (of {total})"),
    "exp_v_nonlinear_only": _s("lien non linéaire : Pearson ne le voit pas", "nonlinear link: Pearson misses it"),
    "exp_v_linear_too": _s("lien aussi visible en linéaire", "link also visible linearly"),
    "exp_v_no_link": _s("pas de lien simultané détecté par cette mesure", "no same-day link detected by this measure"),

    # --- dépendance non linéaire, matrice (onglet Dépendance)
    "exp_dep_title": _s("Dépendance non linéaire", "Nonlinear dependence"),
    "exp_dep_hint": _s(
        "Corrélation de distance : vaut 0 seulement si les séries sont indépendantes, quelle que soit la forme du lien (version corrigée "
        "du biais). Information mutuelle : information partagée, ramenée à l'échelle d'une corrélation (Linfoot) et calculée sur les rangs. "
        "Cases pleines : significatives après correction de Benjamini-Hochberg ; ce test suppose des séries sans mémoire et les grappes de "
        "volatilité le rendent un peu optimiste : confirmer un couple dans l'onglet « Lien entre deux actifs ». « Ce que Pearson ne voit pas » "
        "classe les couples par dépendance moins |ρ|.",
        "Distance correlation: 0 only if the series are independent, whatever the shape of the link (bias-corrected version). Mutual "
        "information: shared information, brought back to a correlation scale (Linfoot) and computed on ranks. Solid cells: significant "
        "after Benjamini-Hochberg correction; the test assumes memoryless series and volatility clustering makes it a little optimistic: "
        "confirm a pair in the \"Link between two assets\" tab. \"What Pearson misses\" ranks pairs by dependence minus |ρ|."),
    "exp_measure": _s("Mesure", "Measure"),
    "exp_m_dcor": _s("Corrélation de distance", "Distance correlation"),
    "exp_m_mi": _s("Information mutuelle", "Mutual information"),
    "exp_dep_strongest": _s("Les plus dépendants", "Most dependent"),
    "exp_dep_hidden": _s("Ce que Pearson ne voit pas", "What Pearson misses"),
    "exp_dep_col_pair": _s("Couple", "Pair"),
    "exp_dep_col_value": _s("Mesure", "Measure"),
    "exp_dep_col_pearson": _s("|ρ| Pearson", "Pearson |ρ|"),
    "exp_dep_col_gap": _s("Écart", "Gap"),
    "exp_dep_mean": _s("Dépendance moyenne", "Mean dependence"),
    "exp_dep_mean_pearson": _s("contre |ρ| moyen", "versus mean |ρ|"),
    "exp_dep_window": _s("Calculé sur les {n} dernières observations (sur {total})", "Computed on the last {n} observations (of {total})"),
    "exp_dep_no_hidden": _s("Aucun couple où la dépendance dépasse nettement la corrélation.",
                            "No pair where dependence clearly exceeds correlation."),

    # --- qui mène qui (onglet Dépendance)
    "exp_gm_title": _s("Qui mène qui", "Who leads whom"),
    "exp_gm_hint": _s(
        "Test de Granger de chaque couple (cause en ligne, effet en colonne), corrigé de Benjamini-Hochberg sur tous les sens testés. "
        "Conditionnelle : chaque actif est expliqué par le passé de TOUS les autres, ce qui écarte les chaînes (A → B → C n'affiche pas "
        "A → C). Par couple : un couple à la fois, chaînes comprises. Un marché qui clôture plus tôt (Tokyo avant New York) « mène » "
        "mécaniquement d'un jour sans que ce soit exploitable. C'est un pouvoir prédictif linéaire, jamais une cause économique.",
        "Granger test of every pair (cause in rows, effect in columns), Benjamini-Hochberg corrected across all directions tested. "
        "Conditional: each asset is explained by the past of ALL the others, which rules out chains (A → B → C does not show A → C). "
        "Pairwise: one pair at a time, chains included. A market that closes earlier (Tokyo before New York) mechanically \"leads\" by "
        "a day without being exploitable. This is linear predictive power, never an economic cause."),
    "exp_gm_on": _s("Série", "Series"),
    "exp_gm_on_returns": _s("Rendements", "Returns"),
    "exp_gm_on_abs": _s("Volatilité (|rendement|)", "Volatility (|return|)"),
    "exp_gm_scope": _s("Portée", "Scope"),
    "exp_gm_conditional": _s("Conditionnelle (liens directs)", "Conditional (direct links)"),
    "exp_gm_pairwise": _s("Par couple", "Pairwise"),
    "exp_gm_leaders": _s("Meneurs", "Leaders"),
    "exp_gm_out": _s("Mène", "Leads"),
    "exp_gm_in": _s("Suit", "Follows"),
    "exp_gm_net": _s("Solde", "Net"),
    "exp_gm_edges": _s("Liens significatifs", "Significant links"),
    "exp_gm_col_link": _s("Cause → effet", "Cause → effect"),
    "exp_gm_col_order": _s("Ordre", "Order"),
    "exp_gm_col_q": _s("p corrigée", "Adjusted p"),
    "exp_gm_col_gain": _s("Gain de variance", "Variance gain"),
    "exp_gm_none": _s("Aucun lien significatif après correction.", "No significant link after correction."),
    "exp_gm_summary": _s("{e} liens sur {t} sens testés", "{e} links out of {t} directions tested"),
    "exp_gm_cell": _s("{a} → {b} · p corrigée {q} · gain {g}", "{a} → {b} · adjusted p {q} · gain {g}"),
    "exp_gm_legend": _s("lien significatif (couleur plus franche = lien plus net)", "significant link (stronger color = clearer link)"),
}

