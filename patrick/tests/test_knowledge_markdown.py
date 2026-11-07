"""Rendu Markdown -> HTML du module Connaissances : le sous-ensemble utilisé par les cours (titres à ancres, paragraphes, gras/italique/code, listes, tableaux,
citations, blocs de code, formules `$..$` et `$$..$$`), avec tout le texte échappé. Les deux vrais cours doivent se rendre sans formule brute ni balise ouverte."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from patrick.knowledge import markdown_lite as M

ROOT = Path(__file__).resolve().parents[2] / "docs" / "cours"
VOID = {"br", "hr", "img", "mspace", "input"}


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> sans ouvrante ({self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


def _balanced(html: str) -> list[str]:
    p = _Balance()
    p.feed(html)
    p.close()
    return p.errors + [f"balise ouverte : {t}" for t in p.stack]


def test_headings_get_stable_unique_anchors_and_a_table_of_contents():
    html, toc = M.render("# Titre un\n\n## Partie é\n\n### Détail\n\n## Partie é\n")
    assert [(t["level"], t["id"]) for t in toc] == [(1, "titre-un"), (2, "partie-e"), (3, "detail"), (2, "partie-e-2")]
    assert '<h2 id="partie-e">' in html and 'href="#partie-e"' in html


def test_inline_emphasis_code_and_escaping():
    html, _ = M.render("Un **gras**, un *italique*, du `code <b>` et <script>alert(1)</script>.")
    assert "<strong>gras</strong>" in html and "<em>italique</em>" in html and "<code>code &lt;b&gt;</code>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_asterisks_in_arithmetic_are_not_italics():
    html, _ = M.render("Le produit 2 * 3 * 4 vaut 24.")
    assert "<em>" not in html


def test_only_web_and_anchor_links_are_clickable():
    html, _ = M.render("[site](https://example.org/a) [ancre](#partie) [engine.py](../../patrick/patrick/earnings/engine.py) [mal](javascript:alert(1))")
    assert 'href="https://example.org/a"' in html and 'rel="noopener' in html and 'href="#partie"' in html
    assert "engine.py" in html and "../../patrick" not in html and "javascript:" not in html


def test_lists_ordered_and_unordered_with_continuation_lines():
    html, _ = M.render("- un\n- deux\n  suite de deux\n\n1. premier\n2. second\n")
    assert html.count("<li>") == 4 and "<ul>" in html and "<ol>" in html and "deux suite de deux" in html.replace("\n", " ")


def test_tables_have_a_header_and_pipes_inside_formulas_do_not_split_cells():
    html, _ = M.render("| Test | Règle |\n|---|---|\n| ADF | $|x|<1$ |\n| KPSS | `a|b` |\n")
    assert html.count("<th ") == 2 and html.count("<td>") == 4 and "<math" in html
    assert 'class="table-scroll"' in html


def test_fenced_code_is_kept_verbatim_and_escaped():
    html, _ = M.render("```\nx = a < b\n  y = 1\n```\n")
    assert "<pre" in html and "x = a &lt; b\n  y = 1" in html


def test_blockquote_and_rule():
    html, _ = M.render("> note importante\n\n---\n\nsuite")
    assert "<blockquote>" in html and "<hr>" in html


def test_inline_and_display_math_become_mathml():
    html, _ = M.render("Soit $x_t$ la série.\n\n$$\n\\frac{a}{b}\n$$\n\net $$y = 1$$ seul.")
    assert html.count("<math") == 3 and 'display="block"' in html and "<mfrac>" in html


def test_sup_and_sub_are_the_only_html_tags_allowed():
    html, _ = M.render("le 24<sup>e</sup> écart, H<sub>2</sub>O, <img src=x onerror=alert(1)>")
    assert "<sup>e</sup>" in html and "<sub>2</sub>" in html and "<img" not in html


def test_an_escaped_dollar_is_a_dollar():
    html, _ = M.render(r"Ça coûte 5 \$ et $x$.")
    assert "5 $" in html and html.count("<math") == 1


def _render_course(path: Path):
    return M.render(path.read_text(encoding="utf-8"))


def test_the_econometrics_course_renders_cleanly():
    html, toc = _render_course(ROOT / "econometrie" / "cours-econometrie.md")
    assert _balanced(html) == []
    assert len({t["id"] for t in toc}) == len(toc) and len(toc) > 40
    assert "<table" in html and "<pre" in html and "<blockquote>" in html


def test_the_earnings_course_renders_cleanly_with_every_formula_typeset():
    html, toc = _render_course(ROOT / "evenements-de-resultats.md")
    assert _balanced(html) == []
    assert len({t["id"] for t in toc}) == len(toc) and any(t["text"].startswith("Partie I.") for t in toc)
    assert html.count("<math") > 600 and "tex-unknown" not in html
    visible = re.sub(r"<math.*?</math>|<pre.*?</pre>|<code>.*?</code>", "", html, flags=re.DOTALL)
    assert "$" not in visible, re.findall(r".{30}\$.{30}", visible)[:3]
