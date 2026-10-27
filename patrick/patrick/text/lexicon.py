"""Sentiment par dictionnaire, au format Loughran-McDonald (LM).

Le dictionnaire LM complet (Loughran & McDonald, 2011) est un fichier CSV distribué par ses auteurs pour la recherche :
PATRICK ne le redistribue pas. `load_loughran_mcdonald(chemin)` le lit tel quel (colonnes `Word`, `Negative`, `Positive`,
`Uncertainty`, `Litigious` ; une valeur non nulle = le mot appartient à la liste). Sans fichier, `default_lexicon()` donne un
lexique RÉDUIT, écrit pour ce projet (anglais et français), nettement plus court : il sert de repli et de test, pas de
référence de recherche.

Méthode : mots comptés après mise en minuscules. Convention LM pour la négation : un mot positif précédé d'une négation
dans les 3 mots qui précèdent compte comme négatif ; un mot négatif nié est ignoré (« no loss » n'est pas une mauvaise
nouvelle, mais n'en est pas une bonne non plus).
`polarity = (positifs − négatifs) / (positifs + négatifs)` dans [−1, 1] ; **`None` quand aucun mot de sentiment n'a été
trouvé** : « aucune information » n'est pas « neutre ».

Limite assumée : la polarité d'un mot ne dépend pas de l'actif (une hausse du pétrole est une bonne nouvelle pour un
producteur, une mauvaise pour une compagnie aérienne). Le signal est une information, pas un jugement sur l'actif.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

NEGATION_WINDOW = 3
_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_ELISION = re.compile(r"^(?:[ldsnjmtc]|qu)['’](.+)$")

_NEGATORS = frozenset({
    "no", "not", "none", "neither", "nor", "never", "cannot", "without", "hardly", "nothing",
    "pas", "jamais", "sans", "aucun", "aucune", "ni", "nul",
})

_POSITIVE = frozenset(["gain", "gains", "rise", "rises", "rose", "rising", "rally", "rallies", "rallied", "surge", "surges", "surged", "soar", "soars", "soared", "jump", "jumps", "jumped", "climb", "climbs", "climbed", "advance", "advances", "advanced", "beat", "beats", "outperform", "outperforms", "outperformed", "upgrade", "upgrades", "upgraded", "growth", "grow", "grows", "grew", "strong", "stronger", "strength", "record", "profit", "profits", "profitable", "improve", "improves", "improved", "improvement", "recover", "recovers", "recovery", "rebound", "rebounds", "rebounded", "boost", "boosts", "boosted", "optimistic", "optimism", "upbeat", "bullish", "expand", "expands", "expansion", "expanded", "success", "successful", "win", "wins", "won", "approval", "approved", "dividend", "dividends", "buyback", "exceed", "exceeds", "exceeded", "robust", "resilient", "favorable", "favourable", "positive", "accelerate", "accelerates", "accelerated", "breakthrough", "good", "better", "best", "great", "gagne", "gagnent", "hausse", "hausses", "bondit", "bondissent", "grimpe", "grimpent", "progresse", "progressent", "progression", "bénéfice", "bénéfices", "record", "rebond", "amélioration", "améliore", "améliorent", "solide", "solides", "robuste", "dynamique", "favorable", "favorables", "positif", "positive", "positifs", "succès", "relèvement", "relève", "croissance", "bon", "bons", "bonne", "bonnes", "excellent", "excellente"])

_NEGATIVE = frozenset(["loss", "losses", "fall", "falls", "fell", "falling", "drop", "drops", "dropped", "plunge", "plunges", "plunged", "slump", "slumps", "slumped", "tumble", "tumbles", "tumbled", "crash", "crashes", "crashed", "miss", "misses", "missed", "downgrade", "downgrades", "downgraded", "decline", "declines", "declined", "weak", "weaker", "weakness", "cut", "cuts", "layoff", "layoffs", "bankruptcy", "default", "defaults", "fraud", "probe", "investigation", "lawsuit", "lawsuits", "recall", "recalls", "shortfall", "warning", "warnings", "warn", "warns", "warned", "crisis", "recession", "sanction", "sanctions", "strike", "strikes", "shutdown", "plummet", "plummets", "plummeted", "selloff", "bearish", "pessimistic", "concern", "concerns", "fear", "fears", "worry", "worries", "slowdown", "deteriorate", "deteriorates", "deteriorated", "bankrupt", "scandal", "bad", "worse", "worst", "poor", "penalty", "fine", "fined", "disappoint", "disappoints", "disappointing", "disappointed", "outage", "shortage", "shortages", "halt", "halted", "suspend", "suspended", "chute", "chutent", "recule", "reculent", "plonge", "plongent", "s'effondre", "effondre", "effondrement", "perte", "pertes", "baisse", "baisses", "avertissement", "faillite", "fraude", "enquête", "crise", "récession", "sanction", "sanctions", "grève", "mauvais", "mauvaise", "mauvaises", "faible", "faibles", "négatif", "négative", "négatifs", "dégradation", "dégrade", "déception", "décevant", "pénurie"])

_UNCERTAINTY = frozenset(["uncertain", "uncertainty", "uncertainties", "unclear", "unknown", "unpredictable", "volatile", "volatility", "risk", "risks", "risky", "may", "might", "perhaps", "possibly", "possible", "approximately", "depend", "depends", "depending", "fluctuate", "fluctuates", "fluctuation", "doubt", "doubts", "incertain", "incertaine", "incertitude", "incertitudes", "volatil", "volatile", "volatilité", "peut-être", "éventuel", "éventuelle", "risque", "risques"])

_LITIGIOUS = frozenset(["lawsuit", "lawsuits", "litigation", "court", "courts", "plaintiff", "plaintiffs", "defendant", "defendants", "sue", "sued", "sues", "indictment", "attorney", "attorneys", "settlement", "settlements", "verdict", "subpoena", "allegation", "allegations", "tribunal", "procès", "plainte", "plaintes", "poursuite", "poursuites", "jugement"])


# Ajouts de la version 2 (2026-10-27) : verbes de titres boursiers que la version 1 ne notait pas (« shares slip », « bank cutting
# jobs », « bid for liquidators »). Mots d'emploi général seulement ; les mots ambigus (« hit », « raises », « tariffs ») restent
# dehors : mieux vaut « aucune information » qu'un signe faux.
_POSITIVE_V2 = frozenset(["boom", "booms", "booming", "tops", "topped", "surpass", "surpasses", "surpassed", "outpace", "outpaces",
                          "outpaced", "lifts", "lifted", "gagnent", "flambe", "flambent", "reprise"])
_NEGATIVE_V2 = frozenset(["slip", "slips", "slipped", "slide", "slides", "slid", "sink", "sinks", "sank", "tank", "tanks", "tanked",
                          "dip", "dips", "dipped", "retreat", "retreats", "retreated", "cutting", "cutback", "cutbacks", "slash",
                          "slashes", "slashed", "axe", "axes", "axed", "layoff", "turmoil", "tensions", "hostilities", "conflict",
                          "war", "attack", "attacks", "cyberattack", "hack", "hacked", "breach", "ban", "bans", "banned",
                          "liquidation", "liquidator", "liquidators", "insolvency", "insolvent", "bailout", "downturn", "struggle",
                          "struggles", "struggling", "trouble", "troubles", "tumbling", "glisse", "glissent", "dégringole",
                          "tensions", "guerre", "licenciements", "licenciement", "interdiction"])

# Expressions à plusieurs mots ramenées à un mot du lexique avant le découpage (le découpage coupe « sell-off » en deux).
_PHRASES = (
    (re.compile(r"\bsell[- ]offs?\b", re.IGNORECASE), "selloff"),
    (re.compile(r"\b(?:lay|lays|laying|laid)[- ]off\b", re.IGNORECASE), "layoff"),
    (re.compile(r"\bflare[- ]ups?\b", re.IGNORECASE), "conflict"),
)


@dataclass(frozen=True)
class Lexicon:
    name: str
    positive: frozenset | set
    negative: frozenset | set
    uncertainty: frozenset | set
    litigious: frozenset | set


@dataclass(frozen=True)
class SentimentScore:
    polarity: float | None
    n_positive: int
    n_negative: int
    n_uncertainty: int
    n_litigious: int
    n_tokens: int


def default_lexicon() -> Lexicon:
    return Lexicon("builtin-fr-en-reduced-2", _POSITIVE | _POSITIVE_V2, _NEGATIVE | _NEGATIVE_V2, _UNCERTAINTY, _LITIGIOUS)


def load_loughran_mcdonald(path) -> Lexicon:
    """Lit le « Master Dictionary » LM (CSV). Les mots sont mis en minuscules."""
    lists = {"Negative": set(), "Positive": set(), "Uncertainty": set(), "Litigious": set()}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"Word", *lists} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"colonnes absentes du dictionnaire LM : {sorted(missing)}")
        for row in reader:
            word = (row["Word"] or "").strip().lower()
            if not word:
                continue
            for col, bucket in lists.items():
                try:
                    if int(float(row[col] or 0)) != 0:
                        bucket.add(word)
                except ValueError:
                    continue
    return Lexicon(f"lm:{Path(path).name}", lists["Positive"], lists["Negative"], lists["Uncertainty"],
                   lists["Litigious"])


def tokenize(text: str) -> list[str]:
    tokens = []
    text = text or ""
    for rx, word in _PHRASES:
        text = rx.sub(word, text)
    for raw in _TOKEN.findall(text.lower().replace("’", "'")):
        m = _ELISION.match(raw)
        tokens.append(m.group(1) if m else raw)
    return tokens


def _is_negator(token: str) -> bool:
    return token in _NEGATORS or token.endswith("n't")


def score_text(text: str, lex: Lexicon | None = None) -> SentimentScore:
    lex = lex or default_lexicon()
    tokens = tokenize(text)
    pos = neg = unc = lit = 0
    for i, tok in enumerate(tokens):
        if tok in lex.uncertainty:
            unc += 1
        if tok in lex.litigious:
            lit += 1
        is_pos, is_neg = tok in lex.positive, tok in lex.negative
        if not (is_pos or is_neg):
            continue
        negated = any(_is_negator(t) for t in tokens[max(0, i - NEGATION_WINDOW):i])
        if is_pos and not negated:
            pos += 1
        elif is_pos and negated or is_neg and not negated:
            neg += 1
    total = pos + neg
    return SentimentScore(None if total == 0 else (pos - neg) / total, pos, neg, unc, lit, len(tokens))
