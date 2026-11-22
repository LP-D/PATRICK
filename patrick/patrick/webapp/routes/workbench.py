"""Outils de travail transverses : recherche d'actifs dans la palette de commandes (`/api/asset-index`) et page « Écrans côte à côte »
(`/split`). Lecture seule, aucun calcul : la palette ouvre la fiche d'un actif (`/targets/{symbole}`, déjà servie par `app.py`) et la page
d'écrans côte à côte n'est qu'un cadre qui affiche d'autres pages de l'application dans des volets."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from patrick.config import asset_classes
from patrick.webapp import forms, instruments, nav_registry
from patrick.webapp.i18n import core as i18n
from patrick.webapp.live_edge_view import OTHER_CLASS


def asset_index(lang: str) -> list[dict[str, str]]:
    """Tous les actifs qui ont une fiche : `[{s: symbole, n: nom affiché, c: clé de classe, g: libellé de la classe}]`, dans l'ordre du catalogue.

    Un symbole sert de clé (une seule entrée même s'il figure dans plusieurs groupes) ; les actifs sans groupe vont dans « autres »."""
    t = i18n.translator(lang)
    class_of: dict[str, str] = {}
    for group, items in forms.TARGET_GROUPS.items():
        cls = asset_classes.class_of_group(group) or OTHER_CLASS
        for symbol, *_ in items:
            class_of.setdefault(symbol, cls)
    out = []
    for symbol in forms.TARGET_SOURCE_BY_SYMBOL:
        cls = class_of.get(symbol, OTHER_CLASS)
        label = t(f"nav_{cls}") if cls != OTHER_CLASS else t("eh_other")
        out.append({"s": symbol, "n": instruments.display(symbol, lang), "c": cls, "g": label})
    return out


SPLIT_LAYOUTS: tuple[str, ...] = ("s1", "c2", "c3", "r2", "g4", "l12", "t12")


def split_pages(lang: str) -> list[dict[str, str]]:
    """Les pages proposées dans le sélecteur d'un volet : celles de la navigation (pas /split lui-même) et les pages d'usage."""
    t = i18n.translator(lang)
    pages = []
    for section in nav_registry.nav_sections("/split"):
        for entry in section["entries"]:
            if entry["url"] != "/split":
                pages.append({"url": entry["url"], "label": t(entry["label_key"]) if entry["label_key"] else entry["label"],
                              "group": t(section["label_key"])})
    for entry in nav_registry.utility_links("/split"):
        pages.append({"url": entry["url"], "label": t(entry["label_key"]) if entry["label_key"] else entry["label"], "group": "PATRICK"})
    return pages


def register(app: FastAPI, templates: Jinja2Templates, i18n_ctx: Callable[[Request], dict]) -> None:
    @app.get("/api/asset-index")
    def asset_index_api(request: Request):
        """Index de recherche de la palette (Ctrl K) : chargé une seule fois à la première ouverture, puis gardé par le navigateur."""
        return JSONResponse(asset_index(i18n.get_lang(request)), headers={"Cache-Control": "private, max-age=600"})

    @app.get("/split")
    def split_page(request: Request):
        """Écrans côte à côte : cadre seul (aucune lecture de la base), les volets chargent les autres pages dans des `<iframe>` (static/split.js)."""
        return templates.TemplateResponse(
            request, "split.html",
            {"layouts": SPLIT_LAYOUTS, "pages": split_pages(i18n.get_lang(request)), **i18n_ctx(request)},
        )
