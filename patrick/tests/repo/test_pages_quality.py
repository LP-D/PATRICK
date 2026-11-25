"""Qualité des pages sur la base de démonstration (AM18 et AM19 du 25/11) : accessibilité de base et budget de temps.

Chaque page de la navigation est ouverte avec ses blocs différés (`page_support.FullPageClient`, comme le navigateur), puis :

- AM18, accessibilité sans navigateur : langue du document, texte de remplacement des images, nom accessible des boutons et des
  champs de formulaire, identifiants uniques. Le contraste est déjà vérifié par `webapp/test_contrast_tokens.py`.
- AM19, budget de temps : une page (cadre + blocs) au-delà de `PATRICK_PAGE_BUDGET_S` secondes (12 par défaut : un exécuteur de CI à deux cœurs partagés ; /sante = 3,4 s en local) échoue ;
  la règle « pages instantanées » ne dépend plus d'une mesure à la main.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from page_support import FullPageClient

from patrick.webapp import nav_registry
from patrick.webapp.app import app
from patrick.webapp.routes import analysis as analysis_routes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_demo_db.py"
TODAY = dt.date(2026, 11, 13)
BUDGET_S = float(os.environ.get("PATRICK_PAGE_BUDGET_S", "12"))
_CONTROLS = {"input", "select", "textarea"}
_NO_NAME_INPUTS = {"hidden", "submit", "button", "reset", "image"}


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("demo-quality") / "patrick.db")
    spec = importlib.util.spec_from_file_location("make_demo_db_quality", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.build(path, TODAY)
    # Les fixes autouse de `conftest.py` sont de portée fonction : ce fixe de portée module s'isole lui-même de la VRAIE machine
    # (caches, racine de données, réglages), sinon /sante mesurait le vrai cache de variables (16 s) et lisait les vrais réglages.
    root = tmp_path_factory.mktemp("demo-env")
    mp = pytest.MonkeyPatch()
    for name, value in {"PATRICK_DB_PATH": path, "PATRICK_LIVE_REFRESH": "0", "PATRICK_EXTRA_HOSTS": "testserver",
                        "PATRICK_FEATURE_CACHE_ROOT": str(root / "feature_cache"), "PATRICK_CACHE_ROOT": str(root / "local_cache"),
                        "PATRICK_DATA_ROOT": str(root / "data_root"), "PATRICK_SETTINGS_PATH": str(root / "settings.json"),
                        "PATRICK_NO_AUTO_WORKER": "1", "PATRICK_INSTRUMENT_LOOKUP": "0", "PATRICK_ADVICE_PREWARM": "0"}.items():
        mp.setenv(name, value)
    (root / "data_root").mkdir()
    analysis_routes._forget("live_board")
    client = FullPageClient(app)
    urls = sorted({e.url for e in (*nav_registry.NAV_ENTRIES, *nav_registry.UTILITY_ENTRIES)})
    out = {}
    for url in urls:
        client.get(url)                                   # premier passage : caches de vues et imports, comme au démarrage du serveur
        start = time.perf_counter()
        response = client.get(url)
        out[url] = (response, time.perf_counter() - start)
    yield out
    mp.undo()


class _A11y(HTMLParser):
    """Relève les manques d'accessibilité les plus courants dans un document HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.problems: list[str] = []
        self.ids: dict[str, int] = {}
        self.label_for: set[str] = set()
        self.controls: list[tuple[str, dict]] = []
        self._label_depth = 0
        self._button: dict | None = None
        self._button_text = ""

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html" and self.lang is None:
            self.lang = a.get("lang", "")
        if a.get("id"):
            self.ids[a["id"]] = self.ids.get(a["id"], 0) + 1
        if tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag == "img" and "alt" not in a:
            self.problems.append(f"image sans alt : {a.get('src', '?')[:60]}")
        if tag in _CONTROLS and not (tag == "input" and a.get("type", "text") in _NO_NAME_INPUTS):
            self.controls.append((tag, {**a, "_in_label": str(self._label_depth > 0)}))
        if tag == "button":
            self._button, self._button_text = a, ""

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
        if tag == "button" and self._button is not None:
            a = self._button
            if not (self._button_text.strip() or a.get("aria-label") or a.get("aria-labelledby") or a.get("title")):
                self.problems.append(f"bouton sans nom accessible : class={a.get('class', '')[:50]}")
            self._button = None

    def handle_data(self, data):
        if self._button is not None:
            self._button_text += data

    def report(self) -> list[str]:
        out = list(self.problems)
        if not self.lang:
            out.append("document sans attribut lang")
        for tag, a in self.controls:
            named = (a.get("aria-label") or a.get("aria-labelledby") or a.get("title") or a.get("_in_label") == "True"
                     or (a.get("id") and a["id"] in self.label_for))
            if not named:
                out.append(f"champ <{tag}> sans libellé : name={a.get('name', '')[:40]} id={a.get('id', '')[:40]}")
        return out


def _cadre(response) -> str:
    """Le document de la page seule (les blocs différés sont des fragments, sans <html>)."""
    text = response.text
    end = text.find("</html>")
    return text[: end + 7] if end != -1 else text


def test_every_page_opens_within_the_time_budget(pages):
    slow = {url: round(t, 2) for url, (r, t) in pages.items() if t > BUDGET_S}
    assert all(r.status_code == 200 for r, _ in pages.values())
    assert slow == {}, f"pages au-delà de {BUDGET_S} s (cadre + blocs, base de démonstration) : {slow}"


def test_every_page_has_a_language_named_controls_and_unique_ids(pages):
    problems: dict[str, list[str]] = {}                 # manque -> pages où il apparaît (un manque de la coque apparaît partout)
    for url, (response, _) in pages.items():
        parser = _A11y()
        parser.feed(_cadre(response))
        found = parser.report()
        dup = sorted(i for i, n in parser.ids.items() if n > 1)
        if dup:
            found.append(f"identifiants en double : {dup[:5]}")
        for problem in found:
            problems.setdefault(problem, []).append(url)
    summary = "\n".join(f"{p} ({len(u)} page(s) : {', '.join(u[:3])})" for p, u in sorted(problems.items()))
    assert not problems, "\n" + summary
