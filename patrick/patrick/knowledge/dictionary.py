"""Le dictionnaire du quant : des bases de la finance aux méthodes les plus avancées.

Chaque notion (`Term`) a une clé stable, un thème, un niveau (1 bases, 2 intermédiaire, 3 avancé), un libellé et une définition en français ET en anglais, des
renvois (`see`), éventuellement une formule LaTeX, des synonymes et un lien vers un chapitre de cours (`slug#ancre`).

Il réunit deux sources :
- le lexique déjà présent (`webapp/glossary*.py` : bulles « ? » et page /vocabulary), repris tel quel et classé par thème et niveau ;
- les notions ajoutées, écrites dans les modules `dict_*.py` (un par thème), via `d(...)`.

Aucun accès base ni réseau. `check()` valide l'ensemble (clés uniques, renvois existants, anciennes et nouvelles notions dans les deux langues) ; un test l'exécute.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

LEVELS: tuple[tuple[int, str, str, str, str], ...] = (
    (1, "Bases", "Basics", "Comprendre les marchés et le vocabulaire courant.", "Understand markets and everyday vocabulary."),
    (2, "Intermédiaire", "Intermediate", "Mesurer, comparer, construire : risque, taux, portefeuille, statistiques.", "Measure, compare, build: risk, rates, portfolios, statistics."),
    (3, "Avancé", "Advanced", "Modéliser, valider, prévoir : économétrie, backtests, apprentissage automatique.", "Model, validate, forecast: econometrics, backtests, machine learning."),
)

# (clé, libellé FR, libellé EN) dans l'ordre d'apprentissage conseillé.
THEMES: tuple[tuple[str, str, str], ...] = (
    ("bases", "Bases de la finance", "Finance basics"),
    ("marches", "Marchés et instruments", "Markets and instruments"),
    ("donnees", "Données de marché et qualité", "Market data and quality"),
    ("macro", "Macroéconomie et banques centrales", "Macroeconomics and central banks"),
    ("taux", "Taux, obligations et crédit", "Rates, bonds and credit"),
    ("fondamental", "Analyse fondamentale et comptabilité", "Fundamental analysis and accounting"),
    ("derives", "Dérivés et volatilité implicite", "Derivatives and implied volatility"),
    ("micro", "Microstructure et exécution", "Microstructure and execution"),
    ("risque", "Risque et performance", "Risk and performance"),
    ("portefeuille", "Portefeuille et allocation", "Portfolio and allocation"),
    ("strategies", "Stratégies quantitatives", "Quantitative strategies"),
    ("probas", "Probabilités et statistiques", "Probability and statistics"),
    ("series", "Séries temporelles et économétrie", "Time series and econometrics"),
    ("ml", "Apprentissage automatique", "Machine learning"),
    ("backtest", "Backtest, validation et biais", "Backtesting, validation and biases"),
    ("evenements", "Événements et résultats d'entreprises", "Events and corporate earnings"),
    ("patrick", "Dans PATRICK : cibles, suivi, application", "In PATRICK: targets, tracking, application"),
)
THEME_KEYS = tuple(k for k, _, _ in THEMES)
LEVEL_KEYS = tuple(k for k, *_ in LEVELS)

# Rubriques du lexique existant -> thème du dictionnaire, et niveau par défaut d'une rubrique.
LEGACY_THEME = {"targets": "patrick", "metrics": "risque", "stats": "probas", "validation": "backtest", "data": "donnees", "assets": "marches",
                "models": "ml", "portfolio": "portefeuille", "text": "patrick", "app": "patrick"}
LEGACY_LEVEL = {"targets": 2, "metrics": 2, "stats": 3, "validation": 3, "data": 2, "assets": 1, "models": 3, "portfolio": 2, "text": 2, "app": 1}
# Termes du lexique existant à placer ailleurs que dans le thème de leur rubrique : clé -> (thème, niveau).
LEGACY_OVERRIDES: dict[str, tuple[str, int]] = {
    "horizon": ("bases", 1), "benchmark": ("risque", 2), "beta": ("risque", 2), "pea": ("bases", 1), "cto": ("bases", 1), "dat": ("marches", 2),
    "twr": ("portefeuille", 2), "xirr": ("portefeuille", 2), "hrp": ("portefeuille", 3), "ledoit_wolf": ("portefeuille", 3),
    "p_value": ("probas", 2), "alpha_level": ("probas", 2), "autocorrelation": ("series", 3), "alfred": ("macro", 3), "vintage": ("macro", 3),
    "publication_lag": ("macro", 3), "regime": ("series", 3), "kalman": ("series", 3), "hmm": ("series", 3), "egarch": ("series", 3),
    "ar": ("series", 3), "ma": ("series", 3), "arma": ("series", 3), "arima": ("series", 3), "vol_models": ("series", 3),
    "diebold_mariano": ("series", 3), "p_value_dm": ("series", 3), "n_trials": ("backtest", 3), "deflated_sharpe": ("backtest", 3), "pbo": ("backtest", 3),
    "holdout": ("backtest", 2), "walk_forward": ("backtest", 2), "fold": ("backtest", 2), "data_leak": ("backtest", 2),
}
# Synonymes et sigles des notions du lexique existant (elles n'en portaient pas) : séparés par « ; », utilisés par la recherche.
LEGACY_ALIASES: dict[str, str] = {
    "exp_var_es": "value at risk; valeur à risque; expected shortfall; CVaR; VaR; ES", "exp_adf": "ADF; Dickey-Fuller; racine unitaire", "exp_kpss": "KPSS; stationnarité",
    "exp_acf": "ACF; PACF; autocorrélation; corrélogramme", "exp_stationarity": "stationnarité; stationary", "exp_hurst": "Hurst; mémoire longue; persistance",
    "exp_coint": "cointégration; Engle-Granger; Johansen", "exp_granger": "Granger; causalité", "exp_pca": "ACP; PCA; composantes principales",
    "exp_vr": "ratio de variance; variance ratio; Lo-MacKinlay", "exp_dcor": "dCor; distance correlation", "exp_mi": "information mutuelle; mutual information",
    "exp_tail": "dépendance de queue; tail dependence; copule", "exp_xcorr": "corrélation croisée; CCF; cross-correlation", "exp_partial": "corrélation partielle; partial correlation",
    "bh_fdr": "Benjamini-Hochberg; FDR; fausses découvertes", "deflated_sharpe": "DSR; Sharpe déflaté", "pbo": "PBO; probabilité de surapprentissage du backtest",
    "diebold_mariano": "DM; test de Diebold-Mariano", "walk_forward": "walk-forward; validation avancée", "hrp": "HRP; hierarchical risk parity; parité de risque hiérarchique",
    "ledoit_wolf": "Ledoit-Wolf; shrinkage; rétrécissement", "black_litterman": "Black-Litterman; BL", "twr": "TWR; rendement pondéré par le temps", "xirr": "XIRR; TRI; IRR",
    "auc": "AUC; ROC", "brier": "score de Brier; Brier score", "p_value": "p-value; valeur p; niveau de signification", "beta": "bêta; beta", "benchmark": "indice de référence",
    "regime": "régime; regime", "hmm": "HMM; chaîne de Markov cachée; hidden Markov model", "kalman": "filtre de Kalman; Kalman filter", "egarch": "EGARCH; GARCH exponentiel",
    "shap": "SHAP; Shapley", "lasso": "LASSO; L1", "conformal": "prédiction conforme; conformal prediction", "purge": "purge; purging", "data_leak": "fuite d'information; leakage; look-ahead",
}
_KEY = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class Term:
    key: str
    theme: str
    level: int
    label_fr: str
    label_en: str
    text_fr: str
    text_en: str
    see: tuple[str, ...] = ()
    course: str = ""              # « slug#ancre » d'un chapitre de cours qui détaille la notion
    formula: str = ""             # LaTeX (rendu en MathML)
    alias: tuple[str, ...] = ()   # synonymes et sigles (recherche)
    legacy: bool = False          # vient du lexique existant (bulles « ? »)

    def label(self, lang: str) -> str:
        return self.label_en if lang == "en" else self.label_fr

    def text(self, lang: str) -> str:
        return self.text_en if lang == "en" else self.text_fr


def d(theme: str, key: str, label_fr: str, label_en: str, level: int, text_fr: str, text_en: str, *, see: str = "", course: str = "", formula: str = "",
      alias: str = "") -> Term:
    """Une notion ajoutée. `see` : clés séparées par des espaces ; `alias` : synonymes séparés par « ; »."""
    return Term(key, theme, level, label_fr, label_en, text_fr.strip(), text_en.strip(), tuple(see.split()), course, formula.strip(),
                tuple(a.strip() for a in alias.split(";") if a.strip()))


def normalize(text: str) -> str:
    """Minuscules sans accents."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def squash(text: str) -> str:
    """Pour la recherche : minuscules, sans accents, ponctuation et tirets remplacés par des espaces (« écart-type » = « ecart type »)."""
    return re.sub(r"[^a-z0-9]+", " ", normalize(text)).strip()


# ---------------------------------------------------------------- chargement
def _new_terms() -> list[Term]:
    from patrick.knowledge import (
        dict_backtest,
        dict_bases,
        dict_bases_epargne,
        dict_derives,
        dict_donnees,
        dict_evenements,
        dict_fondamental,
        dict_macro,
        dict_marches,
        dict_micro,
        dict_ml,
        dict_portefeuille,
        dict_probas,
        dict_risque,
        dict_series,
        dict_strategies,
        dict_taux,
    )
    modules = (dict_bases, dict_bases_epargne, dict_marches, dict_donnees, dict_macro, dict_taux, dict_fondamental, dict_derives, dict_micro, dict_risque, dict_portefeuille,
               dict_strategies, dict_probas, dict_series, dict_ml, dict_backtest, dict_evenements)
    out: list[Term] = []
    for m in modules:
        out.extend(m.TERMS)
    return out


def _legacy_terms() -> list[Term]:
    """Le lexique existant (`GLOSSARY`), libellés résolus dans les deux langues, classé par thème et niveau."""
    from patrick.webapp import i18n
    from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS
    from patrick.webapp.glossary_extra import TERM_CATEGORY

    tr = {"fr": i18n.translator("fr"), "en": i18n.translator("en")}
    out = []
    for key, entry in GLOSSARY.items():
        label_key = TERM_LABEL_KEYS.get(key)
        category = TERM_CATEGORY.get(key, "app")
        theme, level = LEGACY_THEME.get(category, "patrick"), LEGACY_LEVEL.get(category, 2)
        if label_key and label_key.startswith(("field_", "section_")):
            theme, level = "patrick", 3                      # réglage d'un formulaire de lancement : spécifique à l'application
        theme, level = LEGACY_OVERRIDES.get(key, (theme, level))
        fr, en = entry.get("fr", ""), entry.get("en", "") or entry.get("fr", "")
        alias = tuple(a.strip() for a in LEGACY_ALIASES.get(key, "").split(";") if a.strip())
        out.append(Term(key=key, theme=theme, level=level, label_fr=tr["fr"](label_key) if label_key else key, label_en=tr["en"](label_key) if label_key else key,
                        text_fr=fr, text_en=en, alias=alias, legacy=True))
    return out


@lru_cache(maxsize=1)
def all_terms() -> tuple[Term, ...]:
    """Toutes les notions : le lexique existant puis les notions ajoutées, dans cet ordre (l'ordre d'affichage est alphabétique)."""
    return tuple(_legacy_terms() + _new_terms())


@lru_cache(maxsize=1)
def by_key() -> dict[str, Term]:
    return {t.key: t for t in all_terms()}


def theme_label(key: str, lang: str) -> str:
    return next((en if lang == "en" else fr for k, fr, en in THEMES if k == key), key)


def level_label(level: int, lang: str) -> str:
    return next((en if lang == "en" else fr for k, fr, en, _, _ in LEVELS if k == level), str(level))


def sorted_terms(lang: str, terms: tuple[Term, ...] | None = None) -> list[Term]:
    return sorted(terms if terms is not None else all_terms(), key=lambda t: normalize(t.label(lang)))


def related(term: Term) -> list[Term]:
    """Les renvois d'une notion, plus les notions qui la citent (réciprocité), sans doublon."""
    index = by_key()
    keys = [k for k in term.see if k in index]
    keys += [t.key for t in all_terms() if term.key in t.see and t.key not in keys]
    return [index[k] for k in dict.fromkeys(keys) if k != term.key]


def terms_of_course(slug: str) -> list[Term]:
    return [t for t in all_terms() if t.course.split("#")[0] == slug]


def matrix() -> dict[tuple[str, int], int]:
    """Nombre de notions par (thème, niveau)."""
    out: dict[tuple[str, int], int] = {}
    for t in all_terms():
        out[(t.theme, t.level)] = out.get((t.theme, t.level), 0) + 1
    return out


def search(query: str, lang: str = "fr", limit: int = 30) -> list[Term]:
    """Recherche sans accents ni casse : libellé exact, début de libellé, synonyme, libellé contenant, texte contenant (dans cet ordre)."""
    q = squash(query)
    if not q:
        return []
    scored: list[tuple[int, int, str, Term]] = []
    for t in all_terms():
        labels = [squash(t.label_fr), squash(t.label_en)]
        aliases = [squash(a) for a in t.alias]
        if q in (squash(t.key), *labels, *aliases):
            score = 0
        elif any(x.startswith(q) for x in labels):
            score = 1
        elif any(x.startswith(q) for x in aliases):
            score = 2
        elif any(q in x for x in labels):
            score = 3
        elif any(q in x for x in aliases):
            score = 4
        elif q in squash(t.text(lang)):
            score = 5
        else:
            continue
        shown = squash(t.label(lang))
        scored.append((score, len(shown), shown, t))
    scored.sort(key=lambda x: x[:3])
    return [t for *_, t in scored[:limit]]


# ---------------------------------------------------------------- validation
def check() -> list[str]:
    """Liste des problèmes du dictionnaire (vide = cohérent). Utilisée par les tests."""
    from patrick.knowledge import courses, latex_lite

    problems: list[str] = []
    seen: set[str] = set()
    index = by_key()
    anchors = {c.slug: {h["id"] for h in courses.load(c.slug).toc} for c in courses.COURSES if courses.available(c.slug)}
    for t in all_terms():
        if not _KEY.match(t.key):
            problems.append(f"{t.key}: clé invalide")
        if t.key in seen:
            problems.append(f"{t.key}: clé en double")
        seen.add(t.key)
        if t.theme not in THEME_KEYS:
            problems.append(f"{t.key}: thème inconnu {t.theme}")
        if t.level not in LEVEL_KEYS:
            problems.append(f"{t.key}: niveau inconnu {t.level}")
        for lang in ("fr", "en"):
            if not t.label(lang).strip() or not t.text(lang).strip():
                problems.append(f"{t.key}: libellé ou texte {lang} vide")
        for ref in t.see:
            if ref not in index:
                problems.append(f"{t.key}: renvoi inconnu {ref}")
            elif ref == t.key:
                problems.append(f"{t.key}: renvoi à soi-même")
        if len(set(t.see)) != len(t.see):
            problems.append(f"{t.key}: renvoi en double")
        if t.course:
            slug, _, anchor = t.course.partition("#")
            if slug not in anchors:
                problems.append(f"{t.key}: cours inconnu ou absent {slug}")
            elif anchor and anchor not in anchors[slug]:
                problems.append(f"{t.key}: ancre de cours inconnue {t.course}")
        if t.formula:
            _, unknown = latex_lite.to_mathml(t.formula, display=True)
            if unknown:
                problems.append(f"{t.key}: formule avec commandes inconnues {unknown}")
    return problems
