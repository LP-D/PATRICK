"""Registre des cours (`docs/cours/`) : titres, niveau, résumé, rendu HTML avec plan et temps de lecture.

Les cours restent des fichiers Markdown du dépôt (source unique, lisibles hors de l'application) ; ce module les lit, les rend (`markdown_lite`, formules en MathML)
et garde le résultat en mémoire tant que le fichier ne change pas. Si le dossier `docs/cours/` est absent (installation sans le dépôt), la liste le dit au lieu de planter.
Ajouter un cours = déposer le fichier dans `docs/cours/` et ajouter une ligne à `COURSES`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from patrick.knowledge import markdown_lite

COURSES_DIR = Path(__file__).resolve().parents[3] / "docs" / "cours"
WORDS_PER_MINUTE = 200       # lecture attentive d'un texte technique


@dataclass(frozen=True)
class Course:
    slug: str
    file: str                         # chemin relatif à `docs/cours/`
    title_fr: str
    title_en: str
    summary_fr: str
    summary_en: str
    level: int                        # niveau d'entrée conseillé (1 à 3)
    themes: tuple[str, ...]           # thèmes du dictionnaire couverts
    prerequisites: tuple[str, ...] = ()   # slugs de cours à lire avant

    def title(self, lang: str) -> str:
        return self.title_en if lang == "en" else self.title_fr

    def summary(self, lang: str) -> str:
        return self.summary_en if lang == "en" else self.summary_fr


COURSES: tuple[Course, ...] = (
    Course(
        "econometrie", "econometrie/cours-econometrie.md",
        "L'économétrie d'une série financière",
        "The econometrics of a financial series",
        "Stationnarité, dépendance, moyenne et variance conditionnelles (ARMA, GARCH et famille, HAR), régimes, prévision hors échantillon, VAR et cointégration : "
        "chaque test et chaque modèle de la page Économétrie, avec ses formules, sa lecture et des exemples chiffrés.",
        "Stationarity, dependence, conditional mean and variance (ARMA, GARCH family, HAR), regimes, out-of-sample forecasting, VAR and cointegration: every test and "
        "model of the Econometrics page, with formulas, how to read them and worked numbers. (Course text in French.)",
        3, ("series", "probas", "risque", "backtest")),
    Course(
        "evenements-de-resultats", "evenements-de-resultats.md",
        "Les événements de résultats : la méthode et les maths",
        "Earnings events: the method and the maths",
        "Mesurer la réaction d'un titre à une annonce de résultats (rendements anormaux, CAR, BHAR), savoir si elle est significative (BMP, Patell, Corrado, "
        "corrections multiples), les 54 études de la page et comment lire un résultat.",
        "Measuring a stock's reaction to an earnings announcement (abnormal returns, CAR, BHAR), telling whether it is significant (BMP, Patell, Corrado, multiple-"
        "testing corrections), the 54 studies of the page and how to read a result. (Course text in French.)",
        3, ("evenements", "probas", "backtest")),
)


def get(slug: str) -> Course | None:
    return next((c for c in COURSES if c.slug == slug), None)


def available(slug: str) -> bool:
    c = get(slug)
    return bool(c) and (COURSES_DIR / c.file).is_file()


@dataclass(frozen=True)
class Rendered:
    html: str
    toc: tuple[dict, ...]
    words: int
    minutes: int


_CACHE: dict[str, tuple[float, Rendered]] = {}


def load(slug: str) -> Rendered:
    """Le cours rendu. Relu si le fichier a changé. `KeyError` si le cours n'est pas au registre, `FileNotFoundError` si le fichier manque."""
    course = get(slug)
    if course is None:
        raise KeyError(slug)
    path = COURSES_DIR / course.file
    mtime = path.stat().st_mtime
    hit = _CACHE.get(slug)
    if hit and hit[0] == mtime:
        return hit[1]
    text = path.read_text(encoding="utf-8")
    html, toc = markdown_lite.render(text)
    words = len(re.findall(r"\w+", re.sub(r"```.*?```|\$\$.*?\$\$|\$[^$\n]+\$", " ", text, flags=re.DOTALL)))
    rendered = Rendered(html, tuple(toc), words, max(1, round(words / WORDS_PER_MINUTE)))
    _CACHE[slug] = (mtime, rendered)
    return rendered
