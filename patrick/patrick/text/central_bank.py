"""Ton « hawkish / dovish » d'un communiqué, d'un procès-verbal ou d'un discours de banque centrale.

Méthode par expressions (pas par mots isolés : « rate » seul ne dit rien). `tone = (faucon − colombe) / (faucon + colombe)`
dans [−1, 1] : > 0 = resserrement (hausse de taux, inflation jugée élevée, politique restrictive), < 0 = assouplissement.
`None` quand aucune expression n'a été trouvée.

Version 3 (lecture du texte complet de la page, `fulltext.py`) :
- expressions du vocabulaire réel de la Fed et de la BoE (« raise the target range », « voted to increase Bank Rate », « risks to
  the inflation outlook are tilted to the upside ») ;
- « tightening », « easing » et « further increases » ne comptent plus seuls (« regulatory tightening », « easing of capital rules » n'ont rien de
  monétaire) : il faut « monetary / policy / quantitative » devant ;
- **filtre de pertinence** : un texte long qui parle à peine d'inflation, de taux ou de politique monétaire (discours sur la
  supervision bancaire, procès-verbal d'un comité technique) n'a pas de ton (`None`), même s'il contient une expression. Un texte
  court (titre et phrase du flux) est pris tel quel : il n'a pas la place d'être hors sujet. Un long texte avec une seule
  expression n'a pas de ton non plus (±1 sur une preuve mince).

Limites : pas de négation (« no longer restrictive » compte comme restrictif) ; le jargon change d'une banque et d'une époque à
l'autre. C'est un indicateur de lecture rapide, à valider contre les décisions de taux réelles avant tout usage comme variable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RATE = r"(?:the\s+)?(?:target\s+range(?:\s+for\s+the\s+federal\s+funds\s+rate)?|Bank\s+Rate|(?:policy|interest|official)\s+rates?|rates?(?!\s+of\b))"
_HAWKISH = [
    r"rate hikes?", rf"(?:raise[sd]?|rais(?:ing)|increas(?:e|es|ed|ing)|hik(?:e|es|ed|ing))\s+{_RATE}",
    r"(?:monetary\s+|policy\s+|quantitative\s+)tightening",
    r"tighten(?:ed|ing)?\s+(?:the\s+)?(?:monetary\s+)?polic(?:y|ies)",
    r"restrictiv(?:e|es|if|ifs)", r"inflation\s+(?:remains|remain|is|stays?|has\s+remained)\s+(?:somewhat\s+|still\s+)?(?:elevated|high|too high|persistent)",
    r"inflation\s+is\s+too\s+high", r"upside\s+risks?\s+to\s+(?:the\s+)?inflation(?:\s+outlook)?",
    r"risks\s+to\s+(?:the\s+)?inflation(?:\s+outlook)?\s+(?:are|were|remain|remained)\s+tilted\s+(?:to|towards)\s+the\s+upside",
    r"further\s+(?:(?:policy|monetary|rate)\s+(?:increases?|firming|tightening)|firming)", r"higher for longer", r"balance sheet\s+(?:reduction|runoff)",
    r"vigilan(?:t|ce)", r"persistent inflation", r"inflation(?:ary)?\s+pressures?\s+(?:remain|remains|persist|persists|are\s+building)",
    r"strong labou?r market", r"hausse des taux", r"resserrement", r"inflation\s+(?:reste|demeure)\s+(?:élevée|forte)",
]
_DOVISH = [
    r"rate cuts?", rf"(?:cut(?:ting|s)?|lower(?:ing|s|ed)?|reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing))\s+{_RATE}",
    r"(?:monetary\s+|policy\s+|quantitative\s+)easing", r"easing\s+(?:of\s+)?(?:monetary\s+)?polic(?:y|ies)",
    r"accommodati(?:ve|on)", r"downside\s+risks?\s+to\s+(?:the\s+)?(?:inflation|growth|activity|employment|economic)",
    r"(?:has|have)\s+(?:softened|eased|cooled|weakened)", r"inflation\s+(?:is\s+)?(?:easing|cooling|moderating)",
    r"asset purchases", r"patien(?:t|ce)", r"disinflation(?:ary)?", r"policy support",
    r"(?:soft|softer|softening|slack)\s+labou?r\s+market", r"labou?r\s+market\s+(?:slack|softness)",
    r"baisse des taux", r"assouplissement", r"accommodant(?:e|es)?", r"ralentissement de l'inflation",
]
_HAWK_RX = [re.compile(r"\b" + p + r"\b", re.IGNORECASE) for p in _HAWKISH]
_DOVE_RX = [re.compile(r"\b" + p + r"\b", re.IGNORECASE) for p in _DOVISH]

# Sujets monétaires : un texte long qui n'en parle presque pas n'a pas de ton.
_MONETARY = re.compile(r"\b(?:inflation|monetary\s+policy|policy\s+rates?|interest\s+rates?|federal\s+funds|bank\s+rate|target\s+range"
                       r"|price\s+stability|politique\s+monétaire|taux\s+directeurs?)\b", re.IGNORECASE)
MIN_MONETARY_MENTIONS = 3
MIN_PHRASES_LONG = 2                    # une seule expression dans un long texte donnerait ±1 sur une preuve mince
SHORT_TEXT_CHARS = 1500


@dataclass(frozen=True)
class ToneScore:
    tone: float | None
    n_hawkish: int
    n_dovish: int
    n_monetary: int = 0


def score_tone(text: str) -> ToneScore:
    text = (text or "").replace("’", "'")
    hawk = sum(len(rx.findall(text)) for rx in _HAWK_RX)
    dove = sum(len(rx.findall(text)) for rx in _DOVE_RX)
    monetary = len(_MONETARY.findall(text))
    total = hawk + dove
    long_text = len(text) >= SHORT_TEXT_CHARS
    if total == 0 or (long_text and (monetary < MIN_MONETARY_MENTIONS or total < MIN_PHRASES_LONG)):
        return ToneScore(None, hawk, dove, monetary)
    return ToneScore((hawk - dove) / total, hawk, dove, monetary)
