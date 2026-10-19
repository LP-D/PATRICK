"""Ton « hawkish / dovish » d'un communiqué, d'un procès-verbal ou d'un discours de banque centrale.

Méthode par expressions (pas par mots isolés : « rate » seul ne dit rien). `tone = (faucon − colombe) / (faucon + colombe)`
dans [−1, 1] : > 0 = resserrement (hausse de taux, inflation jugée élevée, politique restrictive), < 0 = assouplissement.
`None` quand aucune expression n'a été trouvée.

Limites : pas de négation (« no longer restrictive » compte comme restrictif) ; le jargon change d'une banque et d'une
époque à l'autre. C'est un indicateur de lecture rapide, à valider contre les décisions de taux réelles avant tout
usage comme variable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HAWKISH = [
    r"rate hikes?", r"raise[sd]?\s+(?:the\s+)?(?:policy\s+|interest\s+)?rates?", r"(?:policy\s+)?tightening",
    r"restrictiv(?:e|es|if|ifs)", r"inflation\s+(?:remains|remain|is|stays?)\s+(?:elevated|high|too high|persistent)",
    r"upside risks? to inflation", r"further\s+(?:increases?|firming)", r"higher for longer", r"balance sheet\s+(?:reduction|runoff)",
    r"quantitative tightening", r"vigilan(?:t|ce)", r"persistent inflation", r"strong labou?r market",
    r"hausse des taux", r"resserrement", r"inflation\s+(?:reste|demeure)\s+(?:élevée|forte)",
]
_DOVISH = [
    r"rate cuts?", r"cut(?:ting|s)?\s+(?:the\s+)?(?:policy\s+|interest\s+)?rates?", r"easing", r"accommodati(?:ve|on)",
    r"downside risks?", r"(?:has|have)\s+(?:softened|eased|cooled|weakened)", r"inflation\s+(?:is\s+)?(?:easing|cooling|moderating)",
    r"lower(?:ing)?\s+(?:the\s+)?(?:policy\s+|interest\s+)?rates?", r"asset purchases", r"quantitative easing", r"patien(?:t|ce)",
    r"disinflation", r"policy support", r"baisse des taux", r"assouplissement", r"accommodant(?:e|es)?",
    r"ralentissement de l'inflation",
]
_HAWK_RX = [re.compile(r"\b" + p + r"\b", re.IGNORECASE) for p in _HAWKISH]
_DOVE_RX = [re.compile(r"\b" + p + r"\b", re.IGNORECASE) for p in _DOVISH]


@dataclass(frozen=True)
class ToneScore:
    tone: float | None
    n_hawkish: int
    n_dovish: int


def score_tone(text: str) -> ToneScore:
    text = (text or "").replace("’", "'")
    hawk = sum(len(rx.findall(text)) for rx in _HAWK_RX)
    dove = sum(len(rx.findall(text)) for rx in _DOVE_RX)
    total = hawk + dove
    return ToneScore(None if total == 0 else (hawk - dove) / total, hawk, dove)
