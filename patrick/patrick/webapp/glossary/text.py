"""Vocabulaire de Black-Litterman et de l'analyse textuelle des news (bulles « ? » et page /vocabulary).

Même forme que `glossary_models` : FR/EN pour chaque terme, une rubrique (`CATEGORY`), un libellé affiché (`LABELS` -> clés i18n de
`LABEL_STRINGS`). Fusionné dans `glossary.GLOSSARY` / `TERM_LABEL_KEYS` / `glossary_extra.TERM_CATEGORY`."""
from __future__ import annotations


def _g(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


GLOSSARY_TEXT: dict[str, dict[str, str]] = {
    "black_litterman": _g(
        "Black-Litterman : part d'un portefeuille de référence (ici HRP) dont on déduit les rendements « d'équilibre » (le prior, "
        "ce que le marché semble attendre), puis le déplace dans la direction des vues, chacune pesée par sa confiance. Les vues sont "
        "les probabilités de hausse calibrées des modèles. Sans vue nette, le résultat est le portefeuille de référence.",
        "Black-Litterman: starts from a reference portfolio (here HRP) from which it infers \"equilibrium\" returns (the prior, what "
        "the market seems to expect), then shifts them toward the views, each weighted by its confidence. The views are the models' "
        "calibrated probabilities of a rise. With no decisive view, the result is the reference portfolio."),
    "p_up": _g(
        "P(hausse) : probabilité que l'actif monte à l'horizon choisi (hausse faible + hausse forte). « Calibrée » veut dire que parmi "
        "les jours où le modèle annonce 70 %, environ 70 % ont réellement monté ; sans calibration, un 70 % n'est qu'un score.",
        "P(up): probability that the asset rises over the chosen horizon (slight up + strong up). \"Calibrated\" means that among the "
        "days where the model says 70%, about 70% actually rose; without calibration, a 70% is just a score."),
    "news_sentiment": _g(
        "Sentiment par dictionnaire : on compte les mots positifs et négatifs d'un titre (listes de type Loughran-McDonald, conçues "
        "pour la finance), avec négation (« not good » compte négatif). Note de -1 (tout négatif) à +1 ; vide si aucun mot de "
        "sentiment : « pas d'information » n'est pas « neutre ». La note ne dit pas ce que la nouvelle change pour l'actif (une hausse "
        "du pétrole est bonne pour un producteur, mauvaise pour une compagnie aérienne).",
        "Dictionary sentiment: counts the positive and negative words of a headline (Loughran-McDonald-style lists built for "
        "finance), with negation (\"not good\" counts negative). Score from -1 (all negative) to +1; empty when no sentiment word is "
        "found: \"no information\" is not \"neutral\". The score does not say what the news means for the asset (a rise in oil is good "
        "for a producer, bad for an airline)."),
    "news_tone": _g(
        "Ton d'une banque centrale : hawkish (« faucon ») = penche vers un resserrement (hausse de taux, inflation jugée élevée) ; "
        "dovish (« colombe ») = penche vers un assouplissement (baisse de taux, économie qui ralentit). Note de -1 (colombe) à +1 "
        "(faucon), calculée sur des expressions, sans gérer la négation : un repère de lecture, pas un fait.",
        "Central bank tone: hawkish = leans toward tightening (rate hikes, inflation judged high); dovish = leans toward easing "
        "(rate cuts, slowing economy). Score from -1 (dovish) to +1 (hawkish), computed on phrases, without handling negation: a "
        "reading aid, not a fact."),
    "news_novelty": _g(
        "Nouveauté : 1 moins la ressemblance maximale avec les nouvelles parues avant (7 jours). Proche de 0 = dépêche recopiée, proche "
        "de 1 = information nouvelle. Évite de prendre un communiqué repris dix fois pour dix événements.",
        "Novelty: 1 minus the maximum similarity with earlier stories (7 days). Near 0 = a reprinted wire, near 1 = new information. "
        "Avoids mistaking one press release repeated ten times for ten events."),
    "news_attention": _g(
        "Attention médiatique : le nombre de nouvelles sur l'actif comparé à son niveau habituel des 252 séances précédentes (z-score, "
        "en écarts-types). +3 = trois fois l'écart-type habituel, un pic de couverture.",
        "Media attention: the number of stories about the asset compared with its usual level over the previous 252 sessions "
        "(z-score, in standard deviations). +3 = three standard deviations above normal, a coverage spike."),
    "news_point_in_time": _g(
        "Point-in-time : une nouvelle n'est utilisable qu'à partir du moment où on pouvait la lire. Heure retenue = la plus tardive de "
        "la publication annoncée et de la première observation par PATRICK ; après la clôture, elle compte pour la séance suivante. "
        "Une date sans heure est lue en fin de journée. Évite de donner au modèle une nouvelle qui n'existait pas encore.",
        "Point-in-time: a story can be used only from the moment it could be read. The time kept is the later of the announced "
        "publication and PATRICK's first sighting; after the close it counts for the next session. A date without a time is read at "
        "the end of the day. Prevents giving the model news that did not exist yet."),
    "llm_leakage": _g(
        "Fuite temporelle d'un LLM : un modèle de langage qui note une dépêche ancienne connaît la suite des événements, donc sa note "
        "mélange lecture du texte et mémoire de l'avenir. Seules les dates postérieures à sa date limite de connaissance (plus une "
        "marge) sont propres pour un backtest ; un modèle sans date limite connue est refusé.",
        "LLM temporal leakage: a language model scoring an old headline knows what happened next, so its score mixes reading the text "
        "with memory of the future. Only dates after its knowledge cutoff (plus a margin) are clean for a backtest; a model with no "
        "known cutoff is refused."),
    "news_event_study": _g(
        "Étude d'événement textuelle : on repère les nouvelles fortes et nouvelles (|note| et nouveauté au-dessus d'un seuil) et on "
        "mesure le rendement anormal du titre autour de leur parution, après retrait de ce que le marché a fait. Le résultat n'est "
        "fiable qu'avec assez d'événements indépendants (30 ou plus) ; des nouvelles groupées dans le temps ne le sont pas.",
        "Textual event study: strong, new stories (|score| and novelty above a threshold) are picked, and the stock's abnormal "
        "return around their release is measured after removing what the market did. Only reliable with enough independent events "
        "(30 or more); stories bunched in time are not independent."),
}

CATEGORY: dict[str, str] = {**{k: "text" for k in GLOSSARY_TEXT}, "black_litterman": "portfolio", "p_up": "metrics"}

LABELS: dict[str, str] = {k: f"gl_t_{k}" for k in GLOSSARY_TEXT}

LABEL_STRINGS: dict[str, dict[str, str]] = {
    "gl_t_black_litterman": _g("Black-Litterman", "Black-Litterman"),
    "gl_t_p_up": _g("P(hausse) calibrée", "Calibrated P(up)"),
    "gl_t_news_sentiment": _g("Sentiment par dictionnaire", "Dictionary sentiment"),
    "gl_t_news_tone": _g("Ton hawkish / dovish", "Hawkish / dovish tone"),
    "gl_t_news_novelty": _g("Nouveauté d'une nouvelle", "Story novelty"),
    "gl_t_news_attention": _g("Attention médiatique", "Media attention"),
    "gl_t_news_point_in_time": _g("Nouvelle point-in-time", "Point-in-time news"),
    "gl_t_llm_leakage": _g("Fuite temporelle des LLM", "LLM temporal leakage"),
    "gl_t_news_event_study": _g("Étude d'événement textuelle", "Textual event study"),
}
