"""Vocabulaire des pages Exploration, Deep learning et Reinforcement learning (bulles « ? » et page /vocabulary).

Même forme que `glossary_extra` : FR/EN pour chaque terme, une rubrique (`CATEGORY`), un libellé affiché (`LABELS`, chaînes FR/EN
fusionnées dans `i18n.STRINGS`). Fusionné dans `glossary.GLOSSARY` / `TERM_LABEL_KEYS` / `glossary_extra.TERM_CATEGORY`."""
from __future__ import annotations


def _g(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


GLOSSARY_MODELS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ Exploration
    "exp_rolling_corr": _g(
        "Corrélation glissante : corrélation recalculée sur une fenêtre qui avance. Elle montre si le lien entre deux actifs est "
        "stable ou change de régime. Une fenêtre de n observations fait fluctuer le résultat d'environ ±1/√n même si le vrai lien ne bouge pas.",
        "Rolling correlation: correlation recomputed on a moving window. It shows whether the link between two assets is stable or "
        "changes regime. A window of n observations makes the result fluctuate by about ±1/√n even when the true link is fixed."),
    "exp_stationarity": _g(
        "Stationnarité : une série est stationnaire quand sa moyenne et sa variance ne dérivent pas dans le temps. Un prix ne l'est "
        "presque jamais (il erre, c'est une racine unitaire) ; son rendement l'est presque toujours. La plupart des modèles statistiques "
        "supposent des variables stationnaires.",
        "Stationarity: a series is stationary when its mean and variance do not drift over time. A price almost never is (it wanders: "
        "a unit root); its return almost always is. Most statistical models assume stationary variables."),
    "exp_adf": _g(
        "ADF (Dickey-Fuller augmenté) : test dont l'hypothèse de départ est une racine unitaire (série non stationnaire). Une p-value "
        "inférieure à 5 % rejette cette hypothèse : la série est stationnaire.",
        "ADF (augmented Dickey-Fuller): a test whose starting hypothesis is a unit root (non-stationary series). A p-value below 5% "
        "rejects it: the series is stationary."),
    "exp_kpss": _g(
        "KPSS : test dont l'hypothèse de départ est la stationnarité, à l'inverse de l'ADF. Une p-value inférieure à 5 % la rejette : "
        "la série n'est pas stationnaire. On croise ADF et KPSS pour éviter de conclure sur un seul.",
        "KPSS: a test whose starting hypothesis is stationarity, the opposite of ADF. A p-value below 5% rejects it: the series is not "
        "stationary. ADF and KPSS are crossed so that no conclusion rests on one alone."),
    "exp_hurst": _g(
        "Exposant de Hurst : mesure la mémoire d'une série. Environ 0,5 : marche aléatoire (aucune mémoire exploitable). Moins de 0,45 : "
        "retour à la moyenne (les écarts se corrigent). Plus de 0,55 : tendance persistante (les mouvements se prolongent).",
        "Hurst exponent: measures a series' memory. About 0.5: random walk (no usable memory). Below 0.45: mean reversion (gaps "
        "correct themselves). Above 0.55: persistent trend (moves tend to continue)."),
    "exp_acf": _g(
        "Autocorrélation (ACF) : corrélation d'une série avec elle-même décalée de k périodes. Hors de la bande ±1,96/√n, le décalage "
        "est significatif isolément. La PACF retire l'effet des décalages intermédiaires. Test de Ljung-Box : teste tous les décalages "
        "d'un coup ; ARCH-LM : teste les grappes de volatilité (les gros mouvements se suivent).",
        "Autocorrelation (ACF): correlation of a series with itself shifted by k periods. Outside the ±1.96/√n band the lag is "
        "individually significant. PACF removes the effect of intermediate lags. Ljung-Box test: tests all lags at once; ARCH-LM: tests "
        "volatility clustering (big moves follow each other)."),
    "exp_xcorr": _g(
        "Corrélation croisée : corrélation entre un actif et un autre décalé de k périodes. Elle révèle qui précède qui : si B décalé de "
        "3 jours corrèle fortement avec A, le passé de B éclaire A trois jours plus tard.",
        "Cross-correlation: correlation between one asset and another shifted by k periods. It reveals who leads whom: if B shifted by "
        "3 days correlates strongly with A, B's past informs A three days later."),
    "exp_granger": _g(
        "Causalité de Granger : le passé de X aide-t-il à prédire Y au-delà du passé de Y lui-même ? Un pouvoir prédictif linéaire, "
        "jamais la preuve d'une cause économique : deux actifs réagissant à une même nouvelle à des vitesses différentes la déclenchent.",
        "Granger causality: does X's past help predict Y beyond Y's own past? Linear predictive power, never proof of an economic "
        "cause: two assets reacting to the same news at different speeds will trigger it."),
    "exp_coint": _g(
        "Cointégration : deux séries non stationnaires sont cointégrées si une combinaison linéaire de leurs log-prix est stationnaire : "
        "elles peuvent s'éloigner mais reviennent l'une vers l'autre. Base du trading de paires. Test d'Engle-Granger ; demi-vie = temps "
        "moyen pour combler la moitié de l'écart.",
        "Cointegration: two non-stationary series are cointegrated if a linear combination of their log prices is stationary: they can "
        "drift apart but revert toward each other. Basis of pairs trading. Engle-Granger test; half-life = average time to close half "
        "of the gap."),
    "exp_tail": _g(
        "Dépendance de queue : probabilité que deux actifs soient ensemble dans leurs pires (ou meilleurs) jours. La corrélation moyenne "
        "peut être modérée alors que les krachs sont communs ; c'est le risque que la diversification ne protège pas.",
        "Tail dependence: probability that two assets are together in their worst (or best) days. Average correlation can be moderate "
        "while crashes are shared; it is the risk that diversification does not cover."),
    "exp_pca": _g(
        "Analyse en composantes principales (ACP) : décompose les mouvements d'un ensemble d'actifs en facteurs indépendants classés par "
        "variance expliquée. Si le premier facteur domine (souvent « le marché »), les actifs bougent surtout ensemble.",
        "Principal component analysis (PCA): decomposes the movements of a set of assets into independent factors ranked by explained "
        "variance. If the first factor dominates (often \"the market\"), the assets mostly move together."),
    "exp_var_es": _g(
        "VaR (valeur à risque) et ES (perte moyenne au-delà) : la VaR à 95 % est la perte qui n'est dépassée que dans 5 % des périodes ; "
        "l'ES est la perte moyenne quand elle l'est. L'ES dit la gravité de la queue, que la VaR ignore.",
        "VaR (value at risk) and ES (expected shortfall): 95% VaR is the loss exceeded in only 5% of periods; ES is the average loss "
        "when it is exceeded. ES conveys the tail's severity, which VaR ignores."),
}

CATEGORY: dict[str, str] = {k: "stats" for k in GLOSSARY_MODELS}

# Libellé affiché (page /vocabulary, titre des bulles) : clé i18n -> FR/EN.
LABELS: dict[str, str] = {k: f"exp_gl_{k[4:]}" for k in GLOSSARY_MODELS}

LABEL_STRINGS: dict[str, dict[str, str]] = {
    "exp_gl_rolling_corr": _g("Corrélation glissante", "Rolling correlation"),
    "exp_gl_stationarity": _g("Stationnarité", "Stationarity"),
    "exp_gl_adf": _g("ADF (Dickey-Fuller augmenté)", "ADF (augmented Dickey-Fuller)"),
    "exp_gl_kpss": _g("KPSS", "KPSS"),
    "exp_gl_hurst": _g("Exposant de Hurst", "Hurst exponent"),
    "exp_gl_acf": _g("Autocorrélation (ACF, PACF)", "Autocorrelation (ACF, PACF)"),
    "exp_gl_xcorr": _g("Corrélation croisée", "Cross-correlation"),
    "exp_gl_granger": _g("Causalité de Granger", "Granger causality"),
    "exp_gl_coint": _g("Cointégration", "Cointegration"),
    "exp_gl_tail": _g("Dépendance de queue", "Tail dependence"),
    "exp_gl_pca": _g("Analyse en composantes principales", "Principal component analysis"),
    "exp_gl_var_es": _g("VaR et ES", "VaR and ES"),
}
