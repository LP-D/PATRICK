"""Section Connaissances : parcours (`/connaissances`), cours (`/connaissances/cours[/{slug}]`), dictionnaire (`/connaissances/dictionnaire`) et sa recherche
JSON (`/api/dictionary/search`). Tout le contenu est statique (fichiers `docs/cours/`, modules `patrick/knowledge/`) : aucun appel base ni réseau.

Le dictionnaire est construit une fois par langue (750 notions, formules en MathML) puis servi tel quel ; un cours est rendu une fois puis gardé tant que son fichier
ne change pas."""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request
from markupsafe import Markup

from patrick.knowledge import courses as C
from patrick.knowledge import dictionary as D
from patrick.knowledge import latex_lite

DICTIONARY_URL = "/connaissances/dictionnaire"
TOC_MAX_ENTRIES_FOR_DEEP_PLAN = 80


def _initial(label: str) -> str:
    ch = D.normalize(label.strip())[:1].upper()
    return ch if ch.isalpha() else "#"


@lru_cache(maxsize=4)
def dictionary_view(lang: str) -> dict:
    """Notions triées par libellé dans la langue, avec renvois (dans les deux sens), cours et formule rendue ; thèmes et niveaux avec leurs effectifs."""
    terms = D.sorted_terms(lang)
    items = []
    for t in terms:
        course = None
        if t.course:
            slug, _, anchor = t.course.partition("#")
            c = C.get(slug)
            if c is not None and C.available(slug):
                course = {"slug": slug, "anchor": anchor, "title": c.title(lang)}
        other = t.label_fr if lang == "en" else t.label_en
        items.append({
            "key": t.key, "label": t.label(lang), "other": other if D.normalize(other) != D.normalize(t.label(lang)) else "",
            "alias": " ; ".join(t.alias), "theme": t.theme, "theme_label": D.theme_label(t.theme, lang), "level": t.level, "level_label": D.level_label(t.level, lang),
            "text": t.text(lang), "formula": Markup(latex_lite.math_element(t.formula, display=True)) if t.formula else "",
            "see": [{"key": r.key, "label": r.label(lang)} for r in D.related(t)], "course": course, "legacy": t.legacy, "initial": _initial(t.label(lang)),
        })
    counts_theme: dict[str, int] = {}
    counts_level: dict[int, int] = {}
    for t in terms:
        counts_theme[t.theme] = counts_theme.get(t.theme, 0) + 1
        counts_level[t.level] = counts_level.get(t.level, 0) + 1
    letters = sorted({i["initial"] for i in items}, key=lambda x: (x == "#", x))
    groups = [{"letter": ch, "items": [i for i in items if i["initial"] == ch]} for ch in letters]
    return {
        "items": items, "groups": groups, "letters": letters, "total": len(items),
        "themes": [{"key": k, "label": en if lang == "en" else fr, "count": counts_theme.get(k, 0)} for k, fr, en in D.THEMES],
        "levels": [{"key": k, "label": en if lang == "en" else fr, "desc": den if lang == "en" else dfr, "count": counts_level.get(k, 0)} for k, fr, en, dfr, den in D.LEVELS],
    }


def _course_cards(lang: str) -> list[dict]:
    out = []
    for c in C.COURSES:
        ok = C.available(c.slug)
        rendered = C.load(c.slug) if ok else None
        out.append({"slug": c.slug, "title": c.title(lang), "summary": c.summary(lang), "level": c.level, "level_label": D.level_label(c.level, lang), "available": ok,
                    "minutes": rendered.minutes if rendered else 0, "n_terms": len(D.terms_of_course(c.slug)),
                    "themes": [D.theme_label(k, lang) for k in c.themes]})
    return out


def _plan(toc: tuple[dict, ...]) -> list[dict]:
    """Plan affiché : sans le titre du document, jusqu'aux sous-sections si le cours est court, aux chapitres sinon."""
    body = list(toc[1:]) if toc and toc[0]["level"] == 1 else list(toc)
    deep = sum(1 for h in body if h["level"] <= 3) <= TOC_MAX_ENTRIES_FOR_DEEP_PLAN
    depth = 3 if deep else 2
    base = min((h["level"] for h in body), default=1)
    return [{"id": h["id"], "text": h["text"], "indent": h["level"] - base} for h in body if h["level"] <= depth]


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    @app.get("/connaissances")
    def knowledge_hub(request: Request):
        ctx = context(request)
        view = dictionary_view(ctx["lang"])
        matrix = D.matrix()
        rows = [{"key": k, "label": en if ctx["lang"] == "en" else fr, "cells": [matrix.get((k, lvl), 0) for lvl in D.LEVEL_KEYS]} for k, fr, en in D.THEMES]
        return templates.TemplateResponse(request, "knowledge_hub.html", {**ctx, "levels": view["levels"], "total": view["total"], "rows": rows, "courses": _course_cards(ctx["lang"]),
                                                                          "dictionary_url": DICTIONARY_URL})

    @app.get("/connaissances/cours")
    def knowledge_courses(request: Request):
        ctx = context(request)
        return templates.TemplateResponse(request, "knowledge_courses.html", {**ctx, "courses": _course_cards(ctx["lang"])})

    @app.get("/connaissances/cours/{slug}")
    def knowledge_course(request: Request, slug: str):
        course = C.get(slug)
        if course is None:
            raise HTTPException(status_code=404, detail="Cours inconnu")
        ctx = context(request)
        lang = ctx["lang"]
        rendered = C.load(slug) if C.available(slug) else None
        terms = [{"key": t.key, "label": t.label(lang)} for t in D.sorted_terms(lang, tuple(D.terms_of_course(slug)))]
        return templates.TemplateResponse(request, "knowledge_course.html", {
            **ctx, "course": course, "title": course.title(lang), "summary": course.summary(lang), "available": rendered is not None,
            "body": Markup(rendered.html) if rendered else "", "plan": _plan(rendered.toc) if rendered else [], "minutes": rendered.minutes if rendered else 0,
            "terms": terms, "dictionary_url": DICTIONARY_URL})

    @app.get(DICTIONARY_URL)
    def knowledge_dictionary(request: Request):
        ctx = context(request)
        return templates.TemplateResponse(request, "knowledge_dictionary.html", {**ctx, **dictionary_view(ctx["lang"]), "dictionary_url": DICTIONARY_URL})

    @app.get("/api/dictionary/search")
    def dictionary_search(request: Request, q: str = "", limit: int = 12):
        lang = context(request)["lang"]
        hits = D.search(q, lang, max(1, min(limit, 50)))
        return {"query": q, "results": [{"key": t.key, "label": t.label(lang), "theme": D.theme_label(t.theme, lang), "level": t.level, "level_label": D.level_label(t.level, lang),
                                         "text": t.text(lang)[:220], "url": f"{DICTIONARY_URL}#term-{t.key}"} for t in hits]}
