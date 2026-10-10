"""Chaînes FR/EN des pages Modèles (ML, DL, RL) et de la page Exploration. Fusionnées dans `i18n.STRINGS` ;
`MODELS_JS_KEYS` et `PAGE_JS_KEYS` complètent `i18n.js_strings` (clés lues côté navigateur via `window.I18N`).

Convention : un texte explicatif est écrit une seule fois ici et affiché derrière un « ? » (`static/help.js`) ; seuls les titres,
libellés, valeurs et boutons restent visibles à l'écran."""
from __future__ import annotations

from patrick.webapp.glossary_models import LABEL_STRINGS
from patrick.webapp.i18n_dl import DL_STRINGS
from patrick.webapp.i18n_rl import RL_STRINGS


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


MODELS_STRINGS: dict[str, dict[str, str]] = {
    # --- navigation
    "nav_cat_models": _s("MODÈLES", "MODELS"),
    "nav_ml": _s("Machine learning", "Machine learning"),
    "nav_dl": _s("Deep learning", "Deep learning"),
    "nav_rl": _s("Reinforcement learning", "Reinforcement learning"),
    "nav_exploration": _s("Exploration", "Exploration"),

    # --- aide « ? » (help.js)
    "help_aria": _s("Aide", "Help"),

    # --- page ML
    "ml_title": _s("Machine learning", "Machine learning"),
    "ml_subtitle": _s(
        "Arbres, forêts et boosting : cadre un run, lance-le, suis-le. Les blocs repliés portent des valeurs par défaut issues de "
        "résultats mesurés ; chaque brique de rigueur affiche son état, ON comme OFF, sans qu'il faille l'ouvrir.",
        "Trees, forests and boosting: frame a run, launch it, follow it. Collapsed blocks carry defaults derived from measured "
        "results; every rigor gate shows its state, ON or OFF, without opening it."),

    # ------------------------------------------------------------------ Exploration : cadre
    "exp_title": _s("Exploration", "Exploration"),
    "exp_subtitle": _s(
        "Études statistiques entre actifs : corrélations, distribution, mémoire, liens de causalité, structure, saisonnalité. "
        "Les séries sont alignées sur leurs dates communes AVANT de calculer les rendements. Quand plusieurs tests sont lancés d'un "
        "coup, seule la p-value corrigée (Benjamini-Hochberg) permet de conclure. Ce qui existe déjà ailleurs n'est pas refait : "
        "statistiques par actif sur les pages de classes d'actifs, covariance et HRP sur Portefeuille, régime de marché, qualité des "
        "données.",
        "Statistical studies between assets: correlations, distribution, memory, causal links, structure, seasonality. Series are "
        "aligned on their common dates BEFORE returns are computed. When several tests run at once, only the corrected p-value "
        "(Benjamini-Hochberg) allows a conclusion. What exists elsewhere is not redone: per-asset statistics on the asset-class pages, "
        "covariance and HRP on Portfolio, market regime, data quality."),
    "exp_sel_title": _s("Actifs", "Assets"),
    "exp_sel_hint": _s(
        "Choisis 2 à 40 actifs (Ctrl/Cmd + clic pour en ajouter). Les séries macro mensuelles ou trimestrielles exigent la fréquence "
        "« Mois » ; en jour ou en semaine elles sont exclues plutôt que recopiées, ce qui fabriquerait des corrélations.",
        "Pick 2 to 40 assets (Ctrl/Cmd + click to add). Monthly or quarterly macro series require the \"Month\" frequency; at day or "
        "week frequency they are excluded rather than forward-filled, which would fabricate correlations."),
    "exp_filter": _s("Filtrer la liste", "Filter the list"),
    "exp_selected": _s("{n} sélectionné(s)", "{n} selected"),
    "exp_none_selected": _s("Aucun actif choisi", "No asset selected"),
    "exp_clear": _s("Vider", "Clear"),
    "exp_remove": _s("Retirer {s}", "Remove {s}"),
    "exp_preset_indices": _s("Grands indices", "Major indices"),
    "exp_preset_risk": _s("Risque", "Risk"),
    "exp_preset_sectors": _s("Secteurs US", "US sectors"),
    "exp_preset_commodities": _s("Matières premières", "Commodities"),
    "exp_preset_rates": _s("Taux US", "US rates"),
    "exp_period": _s("Début", "Start"),
    "exp_p_1y": _s("1 an", "1 yr"),
    "exp_p_3y": _s("3 ans", "3 yrs"),
    "exp_p_5y": _s("5 ans", "5 yrs"),
    "exp_p_10y": _s("10 ans", "10 yrs"),
    "exp_p_max": _s("Tout", "All"),
    "exp_freq": _s("Fréquence", "Frequency"),
    "exp_freq_D": _s("Jour", "Day"),
    "exp_freq_W": _s("Semaine", "Week"),
    "exp_freq_M": _s("Mois", "Month"),
    "exp_transform": _s("Rendements", "Returns"),
    "exp_transform_hint": _s(
        "Automatique : rendement logarithmique pour un prix (toujours positif), différence pour un taux ou un écart de crédit "
        "(peut changer de signe). « Logarithmique » ou « Simple » retombent sur la différence si un niveau est ≤ 0.",
        "Automatic: log return for a price (always positive), difference for a rate or credit spread (can change sign). "
        "\"Log\" or \"Simple\" fall back to the difference when a level is ≤ 0."),
    "exp_tr_auto": _s("Automatique", "Automatic"),
    "exp_tr_log": _s("Logarithmique", "Log"),
    "exp_tr_simple": _s("Simple", "Simple"),
    "exp_tr_diff": _s("Différence", "Difference"),
    "exp_run": _s("Analyser", "Analyze"),
    "exp_running": _s("Calcul en cours…", "Computing…"),
    "exp_status": _s("{n} observations · {start} → {end} · {k} actifs", "{n} observations · {start} → {end} · {k} assets"),
    "exp_pick_two": _s("Choisis au moins deux actifs.", "Pick at least two assets."),
    "exp_pick_one": _s("Choisis au moins un actif.", "Pick at least one asset."),
    "exp_error": _s("Analyse impossible : {e}", "Analysis failed: {e}"),
    "exp_load_error": _s("Erreur de chargement.", "Loading error."),
    "exp_not_run": _s("Choisis des actifs puis lance l'analyse.", "Pick assets, then run the analysis."),

    # --- onglets
    "exp_tab_corr": _s("Corrélations", "Correlations"),
    "exp_tab_dist": _s("Distribution", "Distribution"),
    "exp_tab_memory": _s("Mémoire", "Memory"),
    "exp_tab_link": _s("Lien entre deux actifs", "Link between two assets"),
    "exp_tab_struct": _s("Structure", "Structure"),
    "exp_tab_season": _s("Saisonnalité", "Seasonality"),
    "exp_asset": _s("Actif", "Asset"),
    "exp_asset_a": _s("Actif A", "Asset A"),
    "exp_asset_b": _s("Actif B", "Asset B"),
    "exp_bench": _s("Référence", "Benchmark"),
    "exp_window": _s("Fenêtre", "Window"),
    "exp_lags": _s("Décalages", "Lags"),
    "exp_apply": _s("Appliquer", "Apply"),
    "exp_pair_needs_two": _s("Choisis deux actifs différents.", "Pick two different assets."),

    # --- corrélations
    "exp_method": _s("Méthode", "Method"),
    "exp_m_pearson": _s("Pearson", "Pearson"),
    "exp_m_spearman": _s("Spearman (rangs)", "Spearman (ranks)"),
    "exp_m_kendall": _s("Kendall (rangs)", "Kendall (ranks)"),
    "exp_corr_hint": _s(
        "Cases pleines : corrélation significative après correction de Benjamini-Hochberg sur l'ensemble des paires ; cases pâles : "
        "non significative. Bleu : les deux actifs bougent ensemble ; rouge : ils bougent en sens opposé. Les actifs sont rangés par "
        "classification hiérarchique : les blocs corrélés apparaissent côte à côte. Spearman et Kendall résistent aux valeurs aberrantes.",
        "Solid cells: significant correlation after Benjamini-Hochberg correction across all pairs; faded cells: not significant. "
        "Blue: both assets move together; red: they move in opposite directions. Assets are ordered by hierarchical clustering: "
        "correlated blocks appear side by side. Spearman and Kendall resist outliers."),
    "exp_corr_most_pos": _s("Les plus liés", "Most linked"),
    "exp_corr_most_neg": _s("Les plus opposés", "Most opposed"),
    "exp_corr_mean_abs": _s("Corrélation absolue moyenne", "Mean absolute correlation"),
    "exp_corr_tests": _s("{n} paires testées", "{n} pairs tested"),
    "exp_corr_no_sig": _s("Trop de paires pour tester la significativité.", "Too many pairs to test significance."),
    "exp_roll_title": _s("Corrélation glissante", "Rolling correlation"),
    "exp_roll_hint": _s(
        "Une corrélation mesurée sur une fenêtre fluctue d'environ ±1/√fenêtre même si le vrai lien est constant : la bande grisée "
        "montre ce bruit. Seule une variation qui en sort mérite d'être lue comme un changement de régime.",
        "A correlation measured over a window fluctuates by about ±1/√window even when the true link is constant: the shaded band "
        "shows that noise. Only a move outside it deserves to be read as a regime change."),
    "exp_roll_full": _s("Période entière", "Full sample"),
    "exp_roll_last": _s("Dernière", "Latest"),
    "exp_roll_min": _s("Min", "Min"),
    "exp_roll_max": _s("Max", "Max"),
    "exp_roll_halves": _s("1re moitié → 2e moitié", "1st half → 2nd half"),

    # --- distribution
    "exp_col_asset": _s("Actif", "Asset"),
    "exp_col_mean": _s("Rendement ann.", "Ann. return"),
    "exp_col_vol": _s("Volatilité ann.", "Ann. volatility"),
    "exp_col_skew": _s("Asymétrie", "Skew"),
    "exp_col_kurt": _s("Kurtosis", "Kurtosis"),
    "exp_col_normal": _s("Normalité", "Normality"),
    "exp_col_var": _s("VaR 95 %", "VaR 95%"),
    "exp_col_es": _s("ES 95 %", "ES 95%"),
    "exp_col_worst": _s("Pire", "Worst"),
    "exp_col_best": _s("Meilleur", "Best"),
    "exp_col_dd": _s("Perte max.", "Max drawdown"),
    "exp_col_pos": _s("% positifs", "% positive"),
    "exp_col_ac1": _s("Autocorr. 1", "Autocorr. 1"),
    "exp_col_transform": _s("Transformation", "Transform"),
    "exp_normal_rejected": _s("rejetée", "rejected"),
    "exp_normal_kept": _s("non rejetée", "not rejected"),
    "exp_dist_hint": _s(
        "Rendement et volatilité annualisés (périodes par an : 252 en jour, 52 en semaine, 12 en mois). La VaR est la perte seuil "
        "dépassée dans 5 % des périodes, l'ES (perte moyenne au-delà de ce seuil) mesure la gravité de la queue. Un kurtosis excédentaire "
        "positif signale des queues plus épaisses qu'une loi normale ; le test de Jarque-Bera rejette la normalité dans ce cas. "
        "La perte maximale n'est pas calculée pour un taux ou un écart (transformation « différence »).",
        "Return and volatility are annualized (periods per year: 252 daily, 52 weekly, 12 monthly). VaR is the threshold loss exceeded "
        "in 5% of periods; ES (the average loss beyond it) measures tail severity. A positive excess kurtosis signals fatter tails than "
        "a normal law; the Jarque-Bera test rejects normality in that case. Max drawdown is not computed for a rate or spread "
        "(\"difference\" transform)."),

    # --- mémoire et stationnarité
    "exp_stat_title": _s("Stationnarité", "Stationarity"),
    "exp_stat_hint": _s(
        "Une série stationnaire a une moyenne et une variance stables : les modèles y sont fiables. Un prix est presque toujours non "
        "stationnaire (racine unitaire), son rendement l'est presque toujours. ADF et KPSS testent des hypothèses OPPOSÉES : on conclut "
        "« stationnaire » seulement si ADF rejette la racine unitaire ET KPSS ne rejette pas la stationnarité. L'exposant de Hurst "
        "(sur le log-niveau) vaut ≈ 0,5 pour une marche aléatoire, moins pour un retour à la moyenne, plus pour une tendance persistante.",
        "A stationary series has a stable mean and variance: models are reliable on it. A price is almost always non-stationary (unit "
        "root), its return almost always stationary. ADF and KPSS test OPPOSITE hypotheses: conclude \"stationary\" only if ADF rejects "
        "the unit root AND KPSS does not reject stationarity. The Hurst exponent (on the log level) is ≈ 0.5 for a random walk, lower "
        "for mean reversion, higher for persistent trending."),
    "exp_col_adf": _s("ADF niveau (p)", "ADF level (p)"),
    "exp_col_kpss": _s("KPSS niveau (p)", "KPSS level (p)"),
    "exp_col_level": _s("Niveau", "Level"),
    "exp_col_ret_stat": _s("Rendement", "Return"),
    "exp_col_hurst": _s("Hurst", "Hurst"),
    "exp_v_stationary": _s("stationnaire", "stationary"),
    "exp_v_unit_root": _s("racine unitaire", "unit root"),
    "exp_v_ambiguous": _s("ambigu", "ambiguous"),
    "exp_h_random_walk": _s("marche aléatoire", "random walk"),
    "exp_h_mean_reverting": _s("retour à la moyenne", "mean-reverting"),
    "exp_h_trending": _s("tendance", "trending"),
    "exp_mem_title": _s("Autocorrélation", "Autocorrelation"),
    "exp_mem_hint": _s(
        "Autocorrélation (ACF) : lien entre le rendement d'aujourd'hui et celui d'il y a k périodes ; hors de la bande ±1,96/√n, "
        "le décalage est significatif isolément. La PACF isole l'effet direct de chaque décalage. L'ACF des rendements au carré révèle "
        "les grappes de volatilité (les gros mouvements se suivent). Ljung-Box teste l'ensemble des décalages ; ARCH-LM teste "
        "directement les grappes de volatilité.",
        "Autocorrelation (ACF): link between today's return and the return k periods ago; outside the ±1.96/√n band the lag is "
        "individually significant. PACF isolates the direct effect of each lag. The ACF of squared returns reveals volatility clustering "
        "(big moves follow each other). Ljung-Box tests all lags together; ARCH-LM tests volatility clustering directly."),
    "exp_acf_returns": _s("ACF des rendements", "Return ACF"),
    "exp_pacf_returns": _s("PACF des rendements", "Return PACF"),
    "exp_acf_squared": _s("ACF des rendements au carré", "Squared-return ACF"),
    "exp_lb_returns": _s("Ljung-Box rendements (p)", "Ljung-Box returns (p)"),
    "exp_lb_squared": _s("Ljung-Box carrés (p)", "Ljung-Box squared (p)"),
    "exp_arch_lm": _s("ARCH-LM (p)", "ARCH-LM (p)"),
    "exp_v_autocorr": _s("rendements autocorrélés", "returns autocorrelated"),
    "exp_v_no_autocorr": _s("pas d'autocorrélation", "no autocorrelation"),
    "exp_v_clustering": _s("grappes de volatilité", "volatility clustering"),
    "exp_v_no_clustering": _s("pas de grappes", "no clustering"),
    "exp_lag": _s("décalage", "lag"),

    # --- lien entre deux actifs
    "exp_link_hint": _s(
        "Quatre regards sur le même couple : la corrélation croisée (qui précède qui), la causalité de Granger (le passé de l'un aide-t-il "
        "à prédire l'autre ; un pouvoir prédictif, jamais une cause économique), la cointégration (les deux prix reviennent-ils l'un vers "
        "l'autre à long terme) et la dépendance de queue (chutent-ils ensemble plus souvent que la corrélation ne le laisse croire).",
        "Four views of the same pair: cross-correlation (who leads whom), Granger causality (does one's past help predict the other; "
        "predictive power, never an economic cause), cointegration (do the two prices revert toward each other in the long run) and tail "
        "dependence (do they fall together more often than correlation suggests)."),
    "exp_xcorr_title": _s("Corrélation croisée", "Cross-correlation"),
    "exp_xcorr_hint": _s(
        "Corrélation entre A aujourd'hui et B décalé de k périodes. k > 0 : B mène (le passé de B éclaire A) ; k < 0 : A mène. "
        "La bande ±1,96/√n est valable pour un décalage isolé, sans correction des décalages testés.",
        "Correlation between A today and B shifted by k periods. k > 0: B leads (B's past informs A); k < 0: A leads. The "
        "±1.96/√n band holds for a single lag, without correction for the lags tested."),
    "exp_xcorr_best": _s("Meilleur décalage", "Best lag"),
    "exp_xcorr_zero": _s("Simultanée", "Contemporaneous"),
    "exp_granger_title": _s("Causalité de Granger", "Granger causality"),
    "exp_granger_hint": _s(
        "p-value corrigée de Bonferroni sur les décalages essayés (on ne retient pas le meilleur décalage sans le payer). "
        "p < 5 % : le passé de la cause apporte de l'information sur l'effet au-delà du passé de l'effet lui-même.",
        "Bonferroni-corrected p-value over the lags tried (the best lag is not kept without paying for it). p < 5%: the cause's past "
        "adds information about the effect beyond the effect's own past."),
    "exp_granger_dir": _s("{a} → {b}", "{a} → {b}"),
    "exp_granger_lag": _s("meilleur décalage", "best lag"),
    "exp_v_predictive": _s("pouvoir prédictif", "predictive"),
    "exp_v_not_predictive": _s("aucun pouvoir prédictif", "not predictive"),
    "exp_coint_title": _s("Cointégration", "Cointegration"),
    "exp_coint_hint": _s(
        "Test d'Engle-Granger sur les log-prix. p < 5 % : l'écart entre les deux log-prix (corrigé du ratio de couverture) revient vers "
        "sa moyenne. La demi-vie est le temps moyen pour combler la moitié de l'écart. Le z-score situe l'écart actuel parmi ses "
        "valeurs récentes. Un lien trouvé en balayant de nombreux couples n'a pas la même valeur qu'un couple choisi d'avance.",
        "Engle-Granger test on log prices. p < 5%: the gap between the two log prices (adjusted by the hedge ratio) reverts to its mean. "
        "The half-life is the average time to close half of the gap. The z-score places the current gap within its recent values. A link "
        "found by scanning many pairs is not worth the same as a pair chosen in advance."),
    "exp_coint_p": _s("p-value", "p-value"),
    "exp_coint_hedge": _s("Ratio de couverture", "Hedge ratio"),
    "exp_coint_half": _s("Demi-vie (périodes)", "Half-life (periods)"),
    "exp_coint_z": _s("Z-score actuel", "Current z-score"),
    "exp_v_cointegrated": _s("cointégrés", "cointegrated"),
    "exp_v_not_cointegrated": _s("non cointégrés", "not cointegrated"),
    "exp_zscore": _s("Z-score de l'écart", "Spread z-score"),
    "exp_tail_title": _s("Dépendance de queue", "Tail dependence"),
    "exp_tail_hint": _s(
        "Probabilité que B soit dans sa queue sachant que A est dans la sienne. Sous indépendance elle vaut q ; un rapport nettement "
        "supérieur à 1 signifie que les deux actifs chutent (ou montent) ensemble bien plus que ne le dit la corrélation moyenne. Peu "
        "d'observations dans la queue : résultat très bruité.",
        "Probability that B is in its tail given that A is in its own. Under independence it equals q; a ratio well above 1 means both "
        "assets fall (or rise) together far more than average correlation suggests. Few tail observations: very noisy result."),
    "exp_tail_q": _s("Seuil de queue", "Tail threshold"),
    "exp_tail_lower": _s("Baisse commune", "Joint decline"),
    "exp_tail_upper": _s("Hausse commune", "Joint rise"),
    "exp_tail_ratio": _s("× l'indépendance", "× independence"),
    "exp_tail_corr": _s("Corrélation moyenne", "Average correlation"),

    # --- structure
    "exp_pca_title": _s("Composantes principales", "Principal components"),
    "exp_pca_hint": _s(
        "Décompose les mouvements communs : la composante 1 est le facteur qui explique le plus de variance (souvent « le marché »). "
        "Si elle domine, la diversification apparente est faible. Les charges disent quels actifs portent chaque facteur.",
        "Decomposes common movements: component 1 is the factor explaining the most variance (often \"the market\"). If it dominates, "
        "apparent diversification is low. Loadings show which assets carry each factor."),
    "exp_pca_explained": _s("Variance expliquée", "Explained variance"),
    "exp_pca_cum": _s("Cumulée", "Cumulative"),
    "exp_pca_n80": _s("Facteurs pour 80 %", "Factors for 80%"),
    "exp_pca_first": _s("Part du facteur 1", "Factor 1 share"),
    "exp_pca_loadings": _s("Charges", "Loadings"),
    "exp_pca_comp": _s("Composante {k}", "Component {k}"),
    "exp_beta_title": _s("Bêta et alpha", "Beta and alpha"),
    "exp_beta_hint": _s(
        "Régression de l'actif sur la référence : le bêta est la sensibilité (bêta 1,5 : l'actif bouge 1,5 fois la référence), l'alpha "
        "le rendement moyen non expliqué par la référence, annualisé. Un alpha n'est crédible que si sa p-value l'est ; le bêta glissant "
        "montre s'il est stable.",
        "Regression of the asset on the benchmark: beta is the sensitivity (beta 1.5: the asset moves 1.5 times the benchmark), alpha is "
        "the average return not explained by the benchmark, annualized. An alpha is credible only if its p-value is; rolling beta shows "
        "whether it is stable."),
    "exp_beta": _s("Bêta", "Beta"),
    "exp_alpha_ann": _s("Alpha annualisé", "Annualized alpha"),
    "exp_r2": _s("R²", "R²"),
    "exp_rolling_beta": _s("Bêta glissant", "Rolling beta"),

    # --- saisonnalité
    "exp_season_hint": _s(
        "Rendement moyen de chaque jour de semaine et de chaque mois, comparé à tout le reste de l'échantillon, avec correction de "
        "Benjamini-Hochberg sur l'ensemble des groupes testés. Un jour très atypique tire la moyenne du reste et fait paraître les autres "
        "plus faibles : lire d'abord le test d'ensemble et le groupe le plus extrême. Les effets de calendrier publiés se dissipent vite "
        "une fois connus.",
        "Average return of each weekday and month compared with the rest of the sample, with Benjamini-Hochberg correction over all groups "
        "tested. A very atypical day pulls the mean of the rest and makes the others look weaker: read the omnibus test and the most "
        "extreme group first. Published calendar effects tend to fade once known."),
    "exp_season_weekday": _s("Jour de semaine", "Weekday"),
    "exp_season_month": _s("Mois", "Month"),
    "exp_season_excess": _s("Écart vs reste", "Excess vs rest"),
    "exp_season_omnibus": _s("Test d'ensemble (p)", "Omnibus test (p)"),
    "exp_season_tom": _s("Fin / début de mois", "Turn of month"),
    "exp_season_tom_cmp": _s("{a} contre {b} le reste", "{a} vs {b} the rest"),
    "exp_col_group": _s("Groupe", "Group"),
    "exp_col_n": _s("N", "N"),
    "exp_col_t": _s("t", "t"),
    "exp_col_p": _s("p", "p"),
    "exp_col_padj": _s("p corrigée", "adj. p"),
    "exp_col_hit": _s("% hausse", "% up"),
    "exp_sig": _s("significatif", "significant"),
    "exp_nonsig": _s("non significatif", "not significant"),
    "exp_obs": _s("{n} observations", "{n} observations"),
    "exp_chart_aria": _s("Graphique : {t}", "Chart: {t}"),
    "exp_legend_pos": _s("lien positif", "positive link"),
    "exp_legend_neg": _s("lien négatif", "negative link"),
    "exp_legend_faded": _s("non significatif", "not significant"),
}

MODELS_STRINGS.update(LABEL_STRINGS)
MODELS_STRINGS.update(DL_STRINGS)
MODELS_STRINGS.update(RL_STRINGS)

# Clés lues par le navigateur (`window.I18N`) : `help_aria` partout ; les libellés des pages à graphiques seulement sur leur page (la charge
# utile de chaque page reste petite). Les textes réservés au gabarit (`*_hint`, `*_subtitle`) ne sont jamais envoyés.
MODELS_JS_KEYS: tuple[str, ...] = ("help_aria",)


def _browser_keys(*prefixes: str) -> tuple[str, ...]:
    return tuple(k for k in MODELS_STRINGS if k.startswith(prefixes) and not k.endswith(("_hint", "_subtitle")))


PAGE_JS_KEYS: dict[str, tuple[str, ...]] = {
    "/exploration": _browser_keys("exp_"),
    "/rl": _browser_keys("rlp_"),
}
