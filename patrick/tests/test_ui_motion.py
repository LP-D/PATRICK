"""Mouvement de l'interface (ADR 0023) : les 18 règles tiennent dans des jetons de patrick.css, un script (motion.js) et deux repères
partagés d'une page à l'autre (barre latérale, onglets d'un run). Ces tests figent les valeurs et les contrats, pas l'aspect."""
from __future__ import annotations

import json
import re

import pytest
from page_support import FullPageClient as TestClient

from patrick.tracking import db
from patrick.webapp.app import BASE_DIR, app

STATIC = BASE_DIR / "static"
CSS = (STATIC / "patrick.css").read_text(encoding="utf-8")
MOTION_JS = (STATIC / "motion.js").read_text(encoding="utf-8")


def _token(name: str) -> str:
    match = re.search(r"\n\s*" + re.escape(name) + r":\s*([^;]+);", CSS)
    assert match, name
    return match.group(1).strip()


def _ms(name: str) -> float:
    value = _token(name)
    assert value.endswith("ms"), (name, value)
    return float(value[:-2])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps({"name": "demo", "validation": {"scheme": "walkforward"}}), "cfg", "sha", 42)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    return TestClient(app)


def test_the_motion_tokens_carry_the_eighteen_rules_values():
    assert _token("--press-scale") == "0.97"            # boutons à 0,97 à l'appui
    assert _token("--pop-scale") == "0.95"              # popovers à 0,95
    assert _token("--stretch") == "1.12"                # étire de 12 % ce qui bouge
    assert _token("--stagger") == "30ms"                # lignes décalées de 30 ms
    assert 150 <= _ms("--dur-menu") <= 250              # menus déroulants : 150-250 ms


@pytest.mark.parametrize("enter,leave", [("--dur-menu", "--dur-menu-out"), ("--dur-pop", "--dur-pop-out"),
                                         ("--dur-icon", "--dur-icon-out"), ("--dur-page", "--dur-page-out")])
def test_exits_are_twenty_percent_shorter_than_entries(enter, leave):
    assert _ms(leave) == pytest.approx(_ms(enter) * 0.8)


@pytest.mark.parametrize("name", ["--ease-enter", "--ease-exit", "--ease-move", "--ease-out"])
def test_no_curve_overshoots_its_target(name):
    """Pas de ressort aux transitions : les ordonnées des points de contrôle restent dans [0, 1]."""
    _x1, y1, _x2, y2 = (float(v) for v in re.fullmatch(r"cubic-bezier\(([^)]*)\)", _token(name)).group(1).split(","))
    assert 0 <= y1 <= 1 and 0 <= y2 <= 1, name


def test_entries_ease_out_and_moves_ease_in_out():
    x1, y1, x2, y2 = (float(v) for v in re.search(r"cubic-bezier\(([^)]*)\)", _token("--ease-enter")).group(1).split(","))
    assert y1 > x1                                      # départ vif : ease-out
    x1, y1, x2, y2 = (float(v) for v in re.search(r"cubic-bezier\(([^)]*)\)", _token("--ease-move")).group(1).split(","))
    assert y1 < x1 and y2 > x2                          # lent, vif, lent : ease-in-out


def test_popovers_menus_and_dialogs_grow_from_their_trigger():
    for selector in (".glossary-popover", ".help-pop", ".pred-pop", ".mega-panel", ".cmdk-panel", "dialog.modal"):
        start = CSS.index("\n" + selector + " {") if ("\n" + selector + " {") in CSS else CSS.index(selector)
        block = CSS[start:start + 2500]
        assert "var(--origin-x" in block and "var(--pop-scale)" in block, selector
    assert "--origin-x" in MOTION_JS and "getBoundingClientRect" in MOTION_JS


def test_every_animation_has_a_reduced_motion_path():
    assert "@media (prefers-reduced-motion: no-preference) {\n  @view-transition { navigation: auto; }" in CSS
    reduced = CSS[CSS.rindex("@media (prefers-reduced-motion: reduce)"):]
    assert "::view-transition-group(*)" in reduced and ".is-revealing" in reduced and "[data-elastic]" in reduced
    assert "prefers-reduced-motion: reduce" in MOTION_JS


def test_keyboard_gestures_never_animate():
    assert ':root[data-input="keyboard"]' in CSS and 'setAttribute("data-input"' in MOTION_JS


def test_the_sidebar_marks_the_current_page_with_one_shared_ink(client):
    html = client.get("/universe").text
    sidebar = html[html.index('id="sidebar-tree"'):html.index("sidebar-footer")]
    assert sidebar.count('class="nav-ink"') == 1
    assert re.search(r'<a href="/universe"[^>]*aria-current="page"><span class="nav-ink" aria-hidden="true"></span>', sidebar)
    assert "view-transition-name: nav-ink" in CSS


def test_run_tabs_share_one_ink_across_their_pages(client):
    for path, label in (("/runs/run1/detail", "/detail"), ("/runs/run1/analyse", "/analyse")):
        html = client.get(path).text
        tabs = re.search(r'<nav class="run-tabs".*?</nav>', html, re.DOTALL).group(0)
        assert tabs.count('class="tab-ink"') == 1, path
        assert re.search(r'href="/runs/run1' + label + r'" aria-current="page"><span class="tab-ink"', tabs), path
    assert ".run-tabs .tab-ink { view-transition-name: run-tab-ink; }" in CSS


def test_every_page_loads_the_motion_script(client):
    assert re.search(r'<script src="/static/motion\.js\?v=[0-9a-f]{8}" defer></script>', client.get("/").text)
